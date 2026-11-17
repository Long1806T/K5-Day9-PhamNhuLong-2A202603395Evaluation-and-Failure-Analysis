"""Regression test for docs/trace_case.md: seeded_regression C-014@11 (FM-05 pre_deducted -> FM-08).

The agent subtracts the earlier 30.000 refund itself (event 5, `proposal` 120.000), the host
subtracts it again, the ledger ends at 90.000 while the reply tells the customer 120.000.
The same claim@seed on `fixed` must stay clean. Runs the shapes on a temp store (no team DB).
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-014", 11


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


@pytest.fixture(scope="module")
def cases():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, CLAIM, SEED) for shape in ("seeded_regression", "fixed")}


def ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"], output=case["trial"],
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_first_wrong_step_is_the_pre_deducted_proposal(cases):
    trial = cases["seeded_regression"]["trial"]
    kinds = [e["kind"] for e in trial["events"]]
    assert kinds[:5] == ["handoff", "investigator", "quote", "refund_history", "proposal"]
    assert trial["events"][2]["payload"]["amount_vnd"] == 150000     # step 3 correct: max(30.000 ship, 150.000 damage)
    assert trial["events"][3]["payload"]["refunded_vnd"] == 30000    # step 4 correct: a read, nothing decided yet
    assert trial["events"][4]["payload"]["amount_vnd"] == 120000     # step 5 WRONG: agent deducts, host will deduct again
    assert trial["snapshot"]["refund_vnd"] == 90000 != cases["seeded_regression"]["label"]["refund_vnd"]


def test_graders_catch_the_case(cases, graders):
    c = ctx(cases["seeded_regression"])
    assert graders.TrialPass().evaluate(c).value is False
    assert graders.RefundAmountCorrect().evaluate(c).value is False   # ledger 90.000 != 120.000
    assert graders.ProposalCorrect().evaluate(c).value is False       # proposed 120.000 != 150.000
    assert graders.ReplyMatchesLedger().evaluate(c).value is False    # reply 120.000 != ledger 90.000 (FM-08)


def test_same_claim_seed_is_clean_on_fixed(cases, graders):
    c = ctx(cases["fixed"])
    assert "proposal" not in [e["kind"] for e in cases["fixed"]["trial"]["events"]]
    for g in (graders.TrialPass, graders.RefundAmountCorrect, graders.ProposalCorrect,
              graders.ReplyMatchesLedger, graders.StatusMatchesLedger, graders.DbFactKept):
        assert g().evaluate(c).value is True, g.__name__
    assert graders.ApprovalBypass().evaluate(c).value is False
    assert graders.SecretLeak().evaluate(c).value is False
