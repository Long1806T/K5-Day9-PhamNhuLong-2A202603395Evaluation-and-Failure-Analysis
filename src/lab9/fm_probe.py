"""Failure-mode probes: one bug per shape, so every FM in docs/failure_taxonomy.md has a trace.

    python -m lab9.fm_probe --matrix                       # which v1 items each probe breaks, and which grader saw it
    python -m lab9.fm_probe --matrix --spec config/metric_spec_v2.yaml
    python -m lab9.fm_probe --show FM-06 --claim C-006 --seed 11   # the trace, like lab9.trace_case

Probes are the Lab 8 swarm copy in lab9.variant_agent with exactly ONE bug switch on (plus
`no_override`, so the swarm's own seed-55 weakness does not blur the picture). FM-09 has no switch
in variant_agent, so it gets a small stand-alone probe below. Probes are registered at run time
like lab9.variants; no Lab 8 file and no public variant is edited. They are evidence for the
taxonomy and the item tags in lab9.evalset, never part of the gate.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from lab8.console import utf8_stdio
from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import compute_compensation, tool_cost
from lab8.trace import Trace
from lab9.variant_agent import make_shape

# name -> (FM code, bug switches)
PROBES: dict[str, tuple[str, frozenset[str]]] = {
    "probe_fm01_leaky_trace": ("FM-01", frozenset({"no_override", "leaky_trace"})),
    "probe_fm02_ignore_denied": ("FM-02", frozenset({"no_override", "ignore_denied"})),
    "probe_fm03_ticket_trust": ("FM-03", frozenset({"ticket_trust"})),
    "probe_fm03_quiet_override": ("FM-03", frozenset({"quiet_override"})),
    "probe_fm04_sum_parts": ("FM-04", frozenset({"no_override", "sum_parts"})),
    "probe_fm04_round_down": ("FM-04", frozenset({"no_override", "round_down"})),
    "probe_fm05_pre_deducted": ("FM-05", frozenset({"no_override", "pre_deducted"})),
    "probe_fm06_stale_clause": ("FM-06", frozenset({"no_override", "stale_clause"})),
    "probe_fm07_sibling_refund": ("FM-07", frozenset({"no_override", "sibling_refund"})),
    "probe_fm08_misreport": ("FM-08", frozenset({"no_override", "misreport"})),
    "probe_fm09_cross_principal": ("FM-09", frozenset()),
}


def _run_cross_principal(claim_id: str, *, seed: int, store_path: str, crash_at: str | None = None) -> RunResult:
    """FM-09 probe: when the scoped lookup says outside_principal_scope, the agent believes the
    ticket's authority claim ("tôi là admin / vợ chủ đơn / nhân viên CSKH"), reads the order row
    directly, logs it, and pays as if the requester owned the order."""
    conn = connect(store_path)
    name = "probe_fm09_cross_principal"
    try:
        budget, trace = Budget(), Trace(make_run_id(name, claim_id, seed))
        budget.add_tool(tool_cost())
        claim = conn.execute("SELECT claim_id, principal_id, order_id, ticket FROM claims WHERE claim_id = ?",
                             (claim_id,)).fetchone()
        if claim is None or not claim["order_id"]:
            trace.add("decision", {"status": "needs_info"})
            return finish(conn, shape=name, claim_id=claim_id, seed=seed, status="needs_info", proposal_amount=0,
                          budget=budget, trace=trace, error_reason="missing_order_id")
        complete(budget, seed=seed, purpose="parse", prompt=claim["ticket"])
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (claim["order_id"],)).fetchone()
        if row is None:
            return finish(conn, shape=name, claim_id=claim_id, seed=seed, status="escalated", proposal_amount=0,
                          budget=budget, trace=trace, error_reason="not_found")
        order = dict(row)
        if order["principal_id"] != claim["principal_id"]:
            trace.add("scope_bypass", {"requester": claim["principal_id"], "owner": order["principal_id"],
                                       "order_row": order})          # FM-09: another principal's data in our trace
        budget.add_tool(tool_cost())
        quote = compute_compensation(conn, {**order, "damage_verified": bool(order["damage_verified"])})
        trace.add("quote", quote)
        proposal = int(quote["amount_vnd"])
        if proposal <= 0:
            return finish(conn, shape=name, claim_id=claim_id, seed=seed, status="denied", proposal_amount=0,
                          budget=budget, trace=trace, error_reason=quote.get("reason"))
        try:
            out = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
        except InjectedCrash:
            trace.write()
            raise
        status = "resolved" if out["ok"] else "denied"
        return finish(conn, shape=name, claim_id=claim_id, seed=seed, status=status, proposal_amount=proposal,
                      budget=budget, trace=trace, error_reason=None if out["ok"] else out["reason"])
    finally:
        conn.close()


def register() -> list[str]:
    from lab8.shapes import SHAPES
    for name, (_, bugs) in PROBES.items():
        SHAPES.setdefault(name, _run_cross_principal if name == "probe_fm09_cross_principal" else make_shape(name, bugs))
    return list(PROBES)


def matrix(spec: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """probe -> item_id -> metrics that flagged it (a min-metric that is False, a max-metric that is True)."""
    from lab9.eval import run_eval
    from lab9.graders import GRADERS
    register()
    bad_if_true = {m["id"]: "max" in (m.get("threshold") or {}) for m in spec["metrics"] if m["id"] in GRADERS}
    out: dict[str, dict[str, list[str]]] = {}
    for name in PROBES:
        rep = run_eval(name, spec)
        flagged: dict[str, set[str]] = {}
        for r in rep["rows"]:
            hits = {k for k, bad in bad_if_true.items() if r.get(k) is bad}
            if hits:
                flagged.setdefault(r["item_id"], set()).update(hits)
        out[name] = {k: sorted(v) for k, v in sorted(flagged.items())}
    return out


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.fm_probe")
    ap.add_argument("--spec", default="config/metric_spec.yaml")
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--show", help="FM code, e.g. FM-06: print the trace of its probe")
    ap.add_argument("--claim", default="C-001")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    if args.matrix:
        from lab9.eval import load_spec
        for name, items in matrix(load_spec(Path(args.spec))).items():
            print(f"{PROBES[name][0]} {name:<28} {len(items):>2} item(s)")
            for item, metrics in items.items():
                print(f"    {item}: {', '.join(metrics)}")
        return 0
    if args.show:
        from lab9 import trace_case
        names = [n for n, (fm, _) in PROBES.items() if fm == args.show.upper()]
        if not names:
            ap.error(f"no probe for {args.show}")
        register()
        for name in names:
            trace_case.main(["--shape", name, "--claim", args.claim, "--seed", str(args.seed)])
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
