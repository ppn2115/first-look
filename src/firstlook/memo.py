"""Generate the first-look memo with Claude, then verify every number with code.

    export ANTHROPIC_API_KEY=...        # never commit this
    python -m firstlook.memo            # writes outputs/memo.json

Design:
  * Claude only sees the computed metric registry and the integrity checks, never raw data.
  * Output is structured (forced tool call), and every claim must cite the metric ids it uses.
  * verify.py checks every number. If anything is blocked, Claude gets the exact errors and
    one chance to fix them. Whatever still fails is removed from the memo and shown in the
    audit tab. Nothing unverified reaches the reader.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from .metrics import Registry
from .verify import verify_memo

DEFAULT_MODEL = os.environ.get("FIRSTLOOK_MODEL", "claude-sonnet-5-5")

SECTIONS = ["Headline", "Data integrity", "Growth and its drivers", "Customer retention",
            "Concentration and product", "Questions for management", "Limitations of this analysis"]

MEMO_TOOL = {
    "name": "submit_memo",
    "description": "Submit the first-look diligence memo as structured claims.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "enum": SECTIONS},
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string", "description": "One sentence."},
                                    "metric_ids": {"type": "array", "items": {"type": "string"},
                                                   "description": "Every metric whose number appears in text."},
                                },
                                "required": ["text", "metric_ids"],
                            },
                        },
                    },
                    "required": ["heading", "claims"],
                },
            },
        },
        "required": ["title", "sections"],
    },
}

SYSTEM = """You are a data science analyst on a consumer private equity deal team. You write a
first-look memo on a company's transaction data for the investment team.

Rules, which are enforced by code that will block any claim that breaks them:
1. Use ONLY numbers from the METRICS table. Write them as shown in the 'display' column, or
   rounded from it. Do not calculate new numbers (no differences, ratios or sums of your own).
2. Every claim's metric_ids must list every metric whose number appears in that claim.
3. Percentage-point changes (displayed as 'pts') must be written as 'pts', never '%'.
4. Use direction words that match the sign: a negative change "fell", a positive one "grew".
5. No outside facts about the company, its industry or the market.
6. Do not claim a cause the data cannot show. Read each metric's definition for its caveats.
7. Do not write dates as numbers (say "December 2011", not "09 Dec 2011").

Style: one sentence per claim, plain English, decision-relevant. Lead with what an investor
must know. 2–4 claims per section. 'Questions for management' are the questions this data
raises that only management can answer. 'Limitations' states honestly what this data cannot
tell us, and must note that most buyers look like trade (wholesale) accounts rather than end
consumers, so consumer conclusions need care."""


def _metrics_table(reg: Registry) -> str:
    rows = ["id | label | display | definition"]
    for m in reg:
        rows.append(f"{m.id} | {m.label} | {m.display()} | {m.definition}")
    return "\n".join(rows)


def _checks_text(checks) -> str:
    return "\n".join(f"[{c['status']}] {c['name']}: {c['detail']}" for c in checks)


def build_prompt(reg: Registry, checks) -> str:
    return (f"METRICS\n{_metrics_table(reg)}\n\nINTEGRITY CHECKS\n{_checks_text(checks)}\n\n"
            f"Periods: P0 = Dec 2009–Nov 2010, P1 = Dec 2010–Nov 2011. 'Large accounts' and "
            f"'Small accounts' are a segmentation by median order value; most buyers are trade customers.\n\n"
            f"Write the memo with these sections in order: {', '.join(SECTIONS)}. "
            f"Submit it by calling the submit_memo tool.")


def _call(client, model, messages):
    # tool_choice "auto": some newer models do not accept a forced tool call
    resp = client.messages.create(model=model, max_tokens=8000, system=SYSTEM, messages=messages,
                                  tools=[MEMO_TOOL], tool_choice={"type": "auto"})
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("The model replied without calling submit_memo. Run the command again.")
    return block, resp


def generate_memo(reg: Registry, checks, client=None, model=DEFAULT_MODEL, max_retries=1) -> dict:
    if client is None:
        import anthropic
        # gzip only: avoids a brotli/zstd decoder version clash seen in some Anaconda installs
        client = anthropic.Anthropic(default_headers={"Accept-Encoding": "gzip, deflate"})
    prompt = build_prompt(reg, checks)
    messages = [{"role": "user", "content": prompt}]
    attempts = []
    for attempt in range(max_retries + 1):
        block, resp = _call(client, model, messages)
        memo = block.input
        report = verify_memo(memo, reg)
        attempts.append({"memo": memo, "summary": report["summary"], "claims": report["claims"]})
        if report["summary"]["blocked"] == 0 or attempt == max_retries:
            break
        errors = [f"- \"{c['text']}\": {'; '.join(c['errors'])}" for c in report["claims"] if c["status"] == "BLOCKED"]
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": "The verifier blocked these claims:\n" + "\n".join(errors) +
                           "\nResubmit the full memo with these fixed. Follow the rules exactly."}]},
        ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "metrics_sha256": hashlib.sha256(json.dumps(reg.to_records(), sort_keys=True).encode()).hexdigest()[:16],
        "attempts": attempts,
        "final": report,
    }


if __name__ == "__main__":
    out = Path("outputs")
    reg = Registry.from_json(out / "metrics.json")
    checks = json.load(open(out / "checks.json"))
    result = generate_memo(reg, checks)
    with open(out / "memo.json", "w") as f:
        json.dump(result, f, indent=2)
    s = result["final"]["summary"]
    print(f"Memo written: {s['claims']} claims, {s['verified']} verified, {s['qualitative']} qualitative, "
          f"{s['blocked']} blocked, {s['numbers_checked']} numbers checked, {len(result['attempts'])} attempt(s).")
