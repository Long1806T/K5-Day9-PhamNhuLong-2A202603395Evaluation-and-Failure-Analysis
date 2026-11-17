"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item

SAFETY_COUNTS = ("secret_leak", "approval_bypass")   # lab9.eval.aggregate sums these instead of averaging
METRIC_TOL = 2e-4                                     # aggregate rounds to 4 decimals


def _graded_ids(spec: dict) -> list[str]:
    from lab9.graders import GRADERS
    return [m["id"] for m in spec.get("metrics") or [] if m.get("id") in GRADERS]


def _bad_number(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _expected_metrics(rows: list[dict], spec: dict) -> dict:
    """Recompute what lab9.eval.aggregate would report from these rows (tolerant of missing fields,
    so a hand-built report is compared only on what it actually carries)."""
    out: dict = {}
    for m in _graded_ids(spec):
        vals = [r.get(m) for r in rows if r.get(m) is not None]
        if any(not isinstance(v, bool) for v in vals):
            continue                                   # reported separately as a broken row
        out[m] = sum(vals) if m in SAFETY_COUNTS else (round(sum(vals) / len(vals), 4) if vals else None)
    by_item: dict[str, list[bool]] = {}
    for r in rows:
        by_item.setdefault(r.get("item_id"), []).append(bool(r.get("pass_rate")))
    out["pass_5"] = round(sum(all(v) for v in by_item.values()) / len(by_item), 4) if by_item else None
    for k in spec.get("pass_k") or []:
        for name, fn in (("pass_at", stats.pass_at_k), ("pass_hat", stats.pass_hat_k)):
            if not by_item or min(len(v) for v in by_item.values()) < k:
                out[f"{name}_{k}"] = None
                continue
            try:
                est = [fn(len(v), sum(v), k) for v in by_item.values()]
                out[f"{name}_{k}"] = round(sum(est) / len(est), 4) if est else None
            except (NotImplementedError, ValueError):
                out.pop(f"{name}_{k}", None)
    if rows and all(isinstance(r.get("cost"), (int, float)) and not _bad_number(r.get("cost")) for r in rows):
        passes = sum(bool(r.get("pass_rate")) for r in rows)
        out["cost_per_success"] = round(sum(r["cost"] for r in rows) / passes, 4) if passes else None
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval set => the PR spec may only be as strict or stricter than main's."""
    problems: list[str] = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            problems.append(f"ratchet: {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r} on the same eval set")
    missing_k = sorted(set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []))
    if missing_k:
        problems.append(f"ratchet: pass_k {missing_k} removed")
    bb, pb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if pb.get("confidence", 0.95) > bb.get("confidence", 0.95):
        problems.append(f"ratchet: bootstrap confidence {bb.get('confidence', 0.95)} -> {pb.get('confidence')} (wider CI)")
    for key in ("rng", "method"):
        if key in bb and pb.get(key) != bb.get(key):
            problems.append(f"ratchet: bootstrap {key} changed {bb.get(key)!r} -> {pb.get(key)!r}")
    if pb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        problems.append("ratchet: bootstrap n_resamples lowered")

    def compare(where: str, old: dict, new: dict | None) -> None:
        if new is None:
            problems.append(f"ratchet: {where} removed")
            return
        if old.get("blocking") and not new.get("blocking"):
            problems.append(f"ratchet: {where} no longer blocking")
        ot, nt = old.get("threshold", old), new.get("threshold", new)   # slices keep thresholds inline
        for k in ("max", "max_increase"):
            if k in ot and (k not in nt or nt[k] > ot[k]):
                problems.append(f"ratchet: {where} {k} {ot[k]} -> {nt.get(k)} (looser)")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            problems.append(f"ratchet: {where} min {ot['min']} -> {nt.get('min')} (looser)")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            problems.append(f"ratchet: {where} dropped no_significant_drop")

    new_metrics = {m.get("id"): m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        compare(f"metric {m.get('id')}", m, new_metrics.get(m.get("id")))
    new_slices = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        compare(f"slice {s.get('name')}/{s.get('metric')}", s, new_slices.get((s.get("name"), s.get("metric"))))
    new_rows = {r.get("metric"): r for r in spec.get("row_regressions") or []}
    for r in base_spec.get("row_regressions") or []:
        compare(f"row_regressions {r.get('metric')}", r, new_rows.get(r.get("metric")))
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows"), base.get("rows")
    if not isinstance(rows, list) or not isinstance(base_rows, list):
        return ["report or baseline has no rows list"]
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. metric values that cannot be compared (nan < min is False: a naive gate lets them through)
    problems += [f"metric {k} = {v} (NaN/inf)" for k, v in (pr.get("metrics") or {}).items() if _bad_number(v)]

    # 2. row count must be items x seeds, and the manifest must describe the baseline's run
    seeds, items = man.get("seeds"), man.get("items")
    if not isinstance(seeds, list) or not isinstance(items, int):
        problems.append("manifest lacks items/seeds")
    elif len(rows) != items * len(seeds):
        problems.append(f"{len(rows)} rows != {items} items x {len(seeds)} seeds (dropped or duplicated rows)")
    if seeds != bman.get("seeds"):
        problems.append(f"seeds {seeds} != baseline seeds {bman.get('seeds')} (cherry-picked seeds)")
    if items != bman.get("items"):
        problems.append(f"items {items} != baseline items {bman.get('items')}")

    # 3. exactly one row per (item, seed), and the same (item, seed) set as the baseline
    keys = Counter((r.get("item_id"), r.get("seed")) for r in rows)
    dups = sorted(k for k, n in keys.items() if n > 1)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), e.g. {dups[0]}")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if len(base_keys) != len(base_rows):
        problems.append("baseline itself has duplicated (item, seed) rows")
    missing, extra = base_keys - set(keys), set(keys) - base_keys
    if missing or extra:
        problems.append(f"(item, seed) set differs from baseline: {len(missing)} missing, {len(extra)} extra")
    if isinstance(seeds, list) and any(r.get("seed") not in seeds for r in rows):
        problems.append("rows carry seeds the manifest does not list")

    # 4. crashed graders: reported failures, or rows whose graded value is not a real verdict
    if "evaluator_failures" not in pr:
        problems.append("report has no evaluator_failures field")
    elif pr["evaluator_failures"]:
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {str(pr['evaluator_failures'][0])[:80]}")
    graded = _graded_ids(spec)
    broken = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if not isinstance(r.get(m), bool)]
    if broken:
        problems.append(f"{len(broken)} graded value(s) are not True/False (None/NaN/missing), e.g. {broken[0]}")
    # 4b. verdicts that contradict each other: Lab 8's trial_pass already requires the ledger amount, the
    # proposal, no foreign ledger row and no forbidden substring, so a row cannot pass while those fail.
    implied = {"refund_amount_correct": True, "proposal_correct": True, "secret_leak": False, "approval_bypass": False}
    clash = [(r.get("item_id"), r.get("seed"), m) for r in rows if r.get("pass_rate") is True
             for m, want in implied.items() if isinstance(r.get(m), bool) and r.get(m) is not want]
    if clash:
        problems.append(f"{len(clash)} row(s) pass Lab 8 yet fail a check it implies (edited verdicts?), e.g. {clash[0]}")

    # 5. reported metrics must be what the rows say (a hand-edited number is not a measurement)
    reported = pr.get("metrics") or {}
    for k, want in _expected_metrics(rows, spec).items():
        if k not in reported or _bad_number(reported[k]):
            continue
        got = reported[k]
        if (want is None) != (got is None) or (
                want is not None and (not isinstance(got, (int, float)) or abs(float(got) - float(want)) > METRIC_TOL)):
            problems.append(f"metric {k} reported {got} but its rows give {want}")

    # 6. slice membership comes from the eval set: an item may not move in or out of a slice
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in base_slices and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline for {len(moved)} item(s), e.g. {moved[0]}")

    # 7. ratchet: on the same eval set the spec may only get stricter
    same_eval_set = (man.get("eval_set_sha") is not None and man.get("eval_set_sha") == bman.get("eval_set_sha")) or (
        base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"))
    if base_spec is not None and same_eval_set:
        problems += _ratchet(spec, base_spec)
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        val, verdict, note = None, "ok", f"{len(a)} item(s)"
        if not a:
            verdict = "missing"                 # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if ("min" in s and val < s["min"]) or ("max" in s and val > s["max"]):
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<30} {note:<36} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    if spec.get("row_regressions"):
        rb, rl = row_regression_check(pr, base, spec)
        blocked += rb
        lines += rl
    return blocked, lines


def row_regression_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """(item, seed) rows that PASS on main and FAIL in the PR. Averages and per-item means cannot see a
    PR that fixes main's failing rows while breaking others of the same size (e.g. a 1-in-5-seed bug
    that leaves no override event lands on seed 33 while main's miss is on seed 55). The harness is
    deterministic (A/A delta = 0), so every flip is a behaviour change; with a noisy LLM set `max` to
    the A/A flip count instead. Spec: row_regressions: [{metric, max, blocking}]."""
    blocked: list[str] = []
    lines: list[str] = []
    for rr in spec.get("row_regressions") or []:
        metric, cap = rr["metric"], rr.get("max", 0)
        base_ok = {(r.get("item_id"), r.get("seed")) for r in base["rows"] if r.get(metric) is True}
        flips = sorted((r.get("item_id"), r.get("seed")) for r in pr["rows"]
                       if (r.get("item_id"), r.get("seed")) in base_ok and r.get(metric) is False)
        failed = len(flips) > cap
        rid = f"row_regressions:{metric}"
        if failed and rr.get("blocking"):
            blocked.append(rid)
        label = ("BLOCK" if rr.get("blocking") else "warn") if failed else "ok"
        note = "new failures: " + ", ".join(f"{i}@{s}" for i, s in flips[:4]) + (" …" if len(flips) > 4 else "") if flips else ""
        lines.append(f"  {rid:<34} {len(flips)!s:<8} {json.dumps({'max': cap}):<30} {note:<36} {label}")
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
