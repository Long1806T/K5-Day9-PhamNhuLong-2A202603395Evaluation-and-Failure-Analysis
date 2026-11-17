"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class
NEG = "PASS"


def _norm(labels: Sequence[str]) -> list[str]:
    out = [str(x).strip().upper() for x in labels]
    bad = sorted({x for x in out if x not in (POS, NEG)})
    if bad:
        raise ValueError(f"labels must be {POS}/{NEG}, got {bad}")
    return out


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive. human = ground truth, judge = prediction."""
    h, j = _norm(human), _norm(judge)
    if len(h) != len(j):
        raise ValueError(f"human has {len(h)} labels, judge has {len(j)}")
    cm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for hv, jv in zip(h, j):
        if jv == POS:
            cm["tp" if hv == POS else "fp"] += 1
        else:
            cm["fn" if hv == POS else "tn"] += 1
    return cm


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    """precision = tp/(tp+fp), recall = tp/(tp+fn); 0.0 when the denominator is 0."""
    cm = confusion(human, judge)
    p = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    r = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return p, r


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if n == 0:
        raise ValueError("kappa undefined on an empty sample")
    p_o = (cm["tp"] + cm["tn"]) / n
    judge_fail, human_fail = (cm["tp"] + cm["fp"]) / n, (cm["tp"] + cm["fn"]) / n
    p_e = judge_fail * human_fail + (1 - judge_fail) * (1 - human_fail)
    if 1.0 - p_e <= 1e-12:
        raise ValueError("kappa undefined: chance agreement p_e == 1 (both raters constant)")
    return (p_o - p_e) / (1.0 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1].
    (p_obs + spec - 1) / (sens + spec - 1). Undefined (nan) when sens + spec <= 1:
    a judge no better than a coin cannot be corrected, only replaced."""
    for name, v in (("observed_rate", observed_rate), ("sensitivity", sensitivity), ("specificity", specificity)):
        if not (isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0):
            raise ValueError(f"{name} must be a rate in [0, 1], got {v!r}")
    youden = sensitivity + specificity - 1.0
    if youden <= 0:
        return float("nan")
    return min(1.0, max(0.0, (observed_rate + specificity - 1.0) / youden))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError(f"paired samples need the same 1-D shape, got {x.shape} and {y.shape}")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError("paired_bootstrap got NaN/inf: refuse to compare broken per-item scores")
    if np.array_equal(x, y):          # also covers empty input: nothing differs, nothing to resample
        return (0.0, 0.0, 0.0)
    diff = float(x.mean() - y.mean())

    def stat(s1, s2, axis=-1):
        return np.mean(s1, axis=axis) - np.mean(s2, axis=axis)

    res = bootstrap((x, y), stat, paired=True, vectorized=True, n_resamples=n_resamples,
                    confidence_level=confidence, method="percentile", rng=np.random.default_rng(rng))
    lo, hi = res.confidence_interval
    return (diff, float(lo), float(hi))


def _check_nck(n: int, c: int, k: int) -> tuple[int, int, int]:
    vals = []
    for name, v in (("n", n), ("c", c), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not v.is_integer()):
            raise ValueError(f"{name} must be an integer, got {v!r}")
        vals.append(int(v))
    n, c, k = vals
    if n < 1:
        raise ValueError(f"need n >= 1 trials, got n={n}")
    if not 0 <= c <= n:
        raise ValueError(f"need 0 <= c <= n, got c={c}, n={n}")
    if not 1 <= k <= n:
        raise ValueError(f"need 1 <= k <= n, got k={k}, n={n}")
    return n, c, k


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    n, c, k = _check_nck(n, c, k)
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    n, c, k = _check_nck(n, c, k)
    return math.comb(c, k) / math.comb(n, k)
