"""A single registry of every computed number.

Each analysis module registers the figures it produces here. The memo may only use numbers
from this registry, and verify.py checks every number in the memo against it.
"""
from dataclasses import dataclass, asdict
import json
import math

UNITS = ("gbp", "pct", "count", "ratio", "pp", "days")


@dataclass
class Metric:
    id: str
    label: str
    value: float
    unit: str          # gbp | pct (stored as fraction, 0.25 = 25%) | count | ratio | pp (fraction) | days
    section: str
    definition: str = ""

    def display(self) -> str:
        v = self.value
        if self.unit == "gbp":
            sign, a = ("-" if v < 0 else ""), abs(v)
            if a >= 1e6:
                return f"{sign}£{a/1e6:,.2f}M"
            if a >= 1e3:
                return f"{sign}£{a/1e3:,.1f}k"
            return f"{sign}£{a:,.2f}"
        if self.unit == "pct":
            return f"{v*100:.1f}%"
        if self.unit == "pp":
            return f"{v*100:+.1f} pts"
        if self.unit == "ratio":
            return f"{v:.2f}x"
        if self.unit == "days":
            return f"{v:.0f} days"
        return f"{v:,.0f}"


class Registry:
    def __init__(self):
        self._m: dict[str, Metric] = {}

    def add(self, id, label, value, unit, section, definition=""):
        if unit not in UNITS:
            raise ValueError(f"bad unit {unit}")
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"metric {id} is not finite")
        if id in self._m:
            raise ValueError(f"duplicate metric id {id}")
        self._m[id] = Metric(id, label, value, unit, section, definition)
        return self._m[id]

    def __getitem__(self, id) -> Metric:
        return self._m[id]

    def __contains__(self, id):
        return id in self._m

    def __iter__(self):
        return iter(self._m.values())

    def __len__(self):
        return len(self._m)

    def to_records(self):
        return [asdict(m) | {"display": m.display()} for m in self._m.values()]

    def to_json(self, path):
        with open(path, "w") as f:
            json.dump(self.to_records(), f, indent=2)

    @classmethod
    def from_json(cls, path):
        r = cls()
        with open(path) as f:
            for d in json.load(f):
                d.pop("display", None)
                r._m[d["id"]] = Metric(**d)
        return r
