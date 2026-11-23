"""Test the generate → verify → retry loop with a fake Claude client (no API key needed)."""
from types import SimpleNamespace

from firstlook.memo import generate_memo
from memo_evals import eval_registry


class FakeClient:
    """Returns a memo with one wrong number first, then a corrected memo."""
    def __init__(self, memos):
        self.memos = list(memos)
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        memo = self.memos.pop(0)
        block = SimpleNamespace(type="tool_use", id=f"tu_{len(self.calls)}", input=memo)
        return SimpleNamespace(content=[block])


def _memo(growth_text):
    return {"title": "First look", "sections": [
        {"heading": "Headline", "claims": [{"text": growth_text, "metric_ids": ["rev_growth"]}]}]}


def test_retry_fixes_blocked_claim():
    client = FakeClient([_memo("Net product revenue grew 19%."), _memo("Net product revenue grew 1.9%.")])
    out = generate_memo(eval_registry(), [], client=client)
    assert len(out["attempts"]) == 2
    assert out["attempts"][0]["summary"]["blocked"] == 1
    assert out["final"]["summary"]["blocked"] == 0
    # the second call must include the verifier's error message
    feedback = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "19%" in feedback and "wrong_value" in feedback


def test_still_wrong_after_retry_is_removed():
    client = FakeClient([_memo("Revenue grew 19%."), _memo("Revenue grew 21%.")])
    out = generate_memo(eval_registry(), [], client=client)
    assert out["final"]["summary"]["blocked"] == 1
    assert out["final"]["memo"]["sections"][0]["claims"] == []


def test_clean_memo_needs_one_call():
    client = FakeClient([_memo("Net product revenue grew 1.9%.")])
    out = generate_memo(eval_registry(), [], client=client)
    assert len(client.calls) == 1 and out["final"]["summary"]["verified"] == 1
