"""Verify every number in an AI-written memo against the metric registry.

The rule: a number may appear in the memo only if it matches (after normal rounding) a
metric the claim explicitly cites. Anything else blocks the claim.

Failure reasons
  unknown_metric     the claim cites a metric id that does not exist
  wrong_value        a number matches no cited metric (and no metric at all)
  uncited_metric     a number matches a real metric the claim did not cite
  unit_mismatch      e.g. a percentage-point change written as "%", or £k vs £M
  wrong_direction    "grew" next to a negative number, "fell" next to a positive one

Numbers that are part of a cited metric's own label ("Top 10 products", "month 3",
"90-day") and the years covered by the data are allowed.
"""
from dataclasses import dataclass, field
import re

from .metrics import Registry, Metric

NUM_RE = re.compile(
    r"(?P<sign>[-−+])?\s?(?P<cur>£)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suffix>\s?(?:%|percentage points|pts|pp|points|bn|M|m\b|k|K|x\b|×))?"
)
UP = {"grew", "grow", "growth", "rose", "rise", "increased", "increase", "up", "gained", "higher", "expanded",
      "added", "adds", "boosted", "lifted", "improved", "gain"}
DOWN = {"fell", "fall", "declined", "decline", "dropped", "drop", "down", "decreased", "decrease",
        "lower", "shrank", "contracted", "lost", "negative", "reduced", "cut", "subtracted", "worsened", "loss"}


@dataclass
class NumberCheck:
    raw: str
    ok: bool
    reason: str = ""
    matched_metric: str | None = None


@dataclass
class ClaimResult:
    text: str
    metric_ids: list
    numbers: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    @property
    def qualitative(self):
        return not self.numbers


def _parse(m: re.Match):
    num = float(m.group("num").replace(",", ""))
    dec = len(m.group("num").split(".")[1]) if "." in m.group("num") else 0
    suffix = (m.group("suffix") or "").strip().lower()
    neg = m.group("sign") in ("-", "−")
    return num, dec, suffix, bool(m.group("cur")), neg


def _candidates(metric: Metric, suffix: str, has_cur: bool):
    """Values the metric could be written as, given how the text wrote the number.
    Returns list of (value, unit_ok)."""
    v, u = metric.value, metric.unit
    if suffix == "%":
        return [(v * 100, u == "pct"), (v * 100, False if u == "pp" else None)]
    if suffix in ("pts", "pp", "points", "percentage points"):
        return [(v * 100, u == "pp"), (v * 100, False if u == "pct" else None)]
    if suffix in ("m", "bn", "k"):
        scale = {"m": 1e6, "bn": 1e9, "k": 1e3}[suffix]
        out = [(v / scale, u in ("gbp", "count"))]
        # wrong-scale detection (wrote £k but metric is £M-sized, etc.)
        for alt in (1e3, 1e6, 1e9):
            if alt != scale:
                out.append((v / alt, False if u in ("gbp", "count") else None))
        return out
    if suffix in ("x", "×"):
        return [(v, u == "ratio")]
    if has_cur:
        return [(v, u == "gbp")]
    return [(v, u in ("count", "ratio", "days", "gbp"))]


def _rounds_to(value: float, num: float, dec: int) -> bool:
    return abs(abs(value) - num) <= 0.5 * 10 ** (-dec) + 1e-9


def _match(metric, num, dec, suffix, has_cur):
    """'ok' | 'unit' | None"""
    result = None
    for cand, unit_ok in _candidates(metric, suffix, has_cur):
        if unit_ok is None:
            continue
        if _rounds_to(cand, num, dec):
            if unit_ok:
                return "ok"
            result = "unit"
    return result


CHANGE_ID_RE = re.compile(r"(_growth|_change)$|^pvm_(volume|mix|price|new|lost)$")
DATE_RE = re.compile(r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b", re.I)
CLAUSE_BREAK = re.compile(r"[,;:]|\b(while|but|whereas|and|although|versus|vs)\b", re.I)


def is_change_metric(metric_id: str) -> bool:
    """Direction words only make sense for changes (growth, deltas, bridge effects), not levels."""
    return bool(CHANGE_ID_RE.search(metric_id))


def _direction(text: str, start: int):
    """Nearest direction word before the number, within the same clause."""
    before = text[:start]
    breaks = list(CLAUSE_BREAK.finditer(before))
    clause = before[breaks[-1].end():] if breaks else before
    words = re.findall(r"[a-z]+", clause.lower())[-6:]
    for w in reversed(words):
        if w in UP:
            return 1
        if w in DOWN:
            return -1
    return 0


def _allowed_literals(cited: list[Metric], years: set):
    """(number, suffix) pairs that are part of a cited metric's own name, plus data years."""
    allowed = {(float(y), "") for y in years}
    for m in cited:
        for t in NUM_RE.finditer(m.label):
            num, _, suffix, _, _ = _parse(t)
            allowed.add((num, suffix))
    return allowed


def verify_claim(text: str, metric_ids: list, reg: Registry, years=(2009, 2010, 2011)) -> ClaimResult:
    res = ClaimResult(text, list(metric_ids))
    cited = []
    for mid in metric_ids:
        if mid in reg:
            cited.append(reg[mid])
        else:
            res.errors.append(f"unknown_metric: '{mid}' is not a computed metric")
    allowed = _allowed_literals(cited, set(float(y) for y in years))

    # day numbers in dates ("09 Dec 2011") are not figures
    scan = DATE_RE.sub(lambda d: " " * len(d.group(0)), text)
    for m in NUM_RE.finditer(scan):
        raw = m.group(0).strip()
        num, dec, suffix, has_cur, neg = _parse(m)
        # skip label literals and years written without units
        if not has_cur and (num, suffix) in allowed:
            continue
        # skip hyphenated label words like "90-day", "month-3", "3-tier" handled as literals above
        status, hit = None, None
        for c in cited:
            s = _match(c, num, dec, suffix, has_cur)
            if s == "ok":
                status, hit = "ok", c
                break
            if s == "unit":
                status, hit = "unit", c
        nc = NumberCheck(raw, False)
        if status == "ok":
            sign_val = -1 if hit.value < 0 else (1 if hit.value > 0 else 0)
            d = _direction(text, m.start())
            written_neg = neg
            if written_neg and sign_val > 0:
                nc.reason = f"wrong_direction: '{raw}' written as negative but {hit.id} is {hit.display()}"
            elif written_neg and sign_val < 0:
                nc.ok, nc.matched_metric = True, hit.id      # explicit sign matches: trust it
            elif d and sign_val and d != sign_val and is_change_metric(hit.id):
                nc.reason = (f"wrong_direction: text says {'up' if d > 0 else 'down'} but "
                             f"{hit.id} is {hit.display()}")
            if not nc.reason and not nc.ok:
                nc.ok, nc.matched_metric = True, hit.id
        elif status == "unit":
            nc.reason = f"unit_mismatch: '{raw}' does not match the unit of {hit.id} ({hit.display()})"
        else:
            other = next((o for o in reg if o not in cited and _match(o, num, dec, suffix, has_cur) == "ok"), None)
            if other is not None:
                nc.reason = f"uncited_metric: '{raw}' matches {other.id} but the claim does not cite it"
            else:
                nc.reason = f"wrong_value: '{raw}' matches no computed metric"
        res.numbers.append(nc)
        if not nc.ok:
            res.errors.append(nc.reason)
    return res


def verify_memo(memo: dict, reg: Registry) -> dict:
    """Verify every claim in a structured memo. Returns a report and a filtered memo
    containing only verified claims."""
    report, clean = [], {k: v for k, v in memo.items() if k != "sections"}
    clean["sections"] = []
    for sec in memo.get("sections", []):
        kept = []
        for claim in sec.get("claims", []):
            r = verify_claim(claim["text"], claim.get("metric_ids", []), reg)
            report.append({"section": sec["heading"], "text": r.text, "metric_ids": r.metric_ids,
                           "status": "VERIFIED" if r.ok and not r.qualitative else
                           ("QUALITATIVE" if r.ok else "BLOCKED"),
                           "numbers_checked": len(r.numbers), "errors": r.errors})
            if r.ok:
                kept.append(claim)
        clean["sections"].append({"heading": sec["heading"], "claims": kept})
    n = len(report)
    blocked = sum(1 for x in report if x["status"] == "BLOCKED")
    nums = sum(x["numbers_checked"] for x in report)
    summary = {"claims": n, "blocked": blocked,
               "verified": sum(1 for x in report if x["status"] == "VERIFIED"),
               "qualitative": sum(1 for x in report if x["status"] == "QUALITATIVE"),
               "numbers_checked": nums}
    return {"summary": summary, "claims": report, "memo": clean}
