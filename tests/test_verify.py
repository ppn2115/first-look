import pytest

from firstlook.verify import verify_claim, verify_memo
from memo_evals import CASES, eval_registry

REG = eval_registry()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_eval_case(case):
    r = verify_claim(case["text"], case["metric_ids"], REG)
    got = "PASS" if r.ok else "BLOCK"
    assert got == case["expect"], f"{case['id']}: {r.errors}"


def test_eval_catches_every_planted_error():
    wrong = [c for c in CASES if c["expect"] == "BLOCK"]
    caught = [c for c in wrong if not verify_claim(c["text"], c["metric_ids"], REG).ok]
    assert len(caught) == len(wrong)


def test_error_reasons_are_specific():
    assert "unit_mismatch" in verify_claim("Month-3 retention fell 3.9% for newer cohorts.",
                                           ["m3_ret_change"], REG).errors[0]
    assert "wrong_direction" in verify_claim("Revenue from identified customers grew 2.0%.",
                                             ["revenue_growth"], REG).errors[0]
    assert "uncited_metric" in verify_claim("Repeat is 43.8% vs 43.1%.", ["repeat_90d"], REG).errors[0]


def test_verify_memo_removes_blocked_claims():
    memo = {"title": "t", "sections": [{"heading": "Growth", "claims": [
        {"text": "Net product revenue grew 1.9%.", "metric_ids": ["rev_growth"]},
        {"text": "Net product revenue grew 19%.", "metric_ids": ["rev_growth"]},
    ]}]}
    out = verify_memo(memo, REG)
    assert out["summary"]["blocked"] == 1
    assert len(out["memo"]["sections"][0]["claims"]) == 1
