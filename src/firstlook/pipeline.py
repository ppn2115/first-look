"""One call: raw file in, full First Look results out.

    python -m firstlook.pipeline data/raw/online_retail_ii.parquet
"""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import sys

import pandas as pd

from .config import Config, DEFAULT
from .metrics import Registry
from .load import load_raw
from .integrity import run_integrity, Check
from .prep import build_lines
from .cohorts import run_cohorts
from .drivers import run_drivers


@dataclass
class Results:
    registry: Registry
    checks: list
    waterfall: pd.DataFrame
    cohorts: dict
    drivers: dict
    lines: pd.DataFrame = field(repr=False, default=None)

    @property
    def passed(self):
        return not any(c.status == "FAIL" for c in self.checks)


def analysis_checks(res_c: dict, res_d: dict, cfg: Config) -> list:
    checks = []
    tri = res_c["customer_triangle"]
    ok = bool((tri[0].round(9) == 1).all())
    checks.append(Check("Cohort triangle: month 0 is 100% for every cohort", "PASS" if ok else "FAIL",
                        f"{len(tri)} cohorts checked"))
    ok = bool((tri.fillna(0) <= 1 + 1e-9).all().all())
    checks.append(Check("Cohort triangle: no cohort retains more customers than it started with",
                        "PASS" if ok else "FAIL", "All cells ≤ 100%"))
    checks.append(Check("Left-censored first cohort excluded from averages", "WARN",
                        f"{res_c['left_censored_cohort']} cohort holds every pre-existing customer; "
                        "shown in the triangle but excluded from retention averages"))
    tree = res_d["driver_tree"]
    err = float(tree.loc[["P0", "P1"], "identity_check"].abs().max())
    checks.append(Check("Driver tree: customers × orders/customer × AOV = revenue",
                        "PASS" if err < cfg.tie_out_tolerance_gbp else "FAIL", f"Max gap £{err:,.4f}"))
    r = float(res_d["pvm_residual"])
    checks.append(Check("Price/volume/mix bridge closes to the change in sales",
                        "PASS" if abs(r) < cfg.tie_out_tolerance_gbp else "FAIL", f"Residual £{r:,.4f}"))
    return checks


def run(path, cfg: Config = DEFAULT, keep_lines: bool = False) -> Results:
    import gc
    reg = Registry()
    raw = load_raw(path)
    integ = run_integrity(raw, reg, cfg)
    lines, _ = build_lines(integ.sales, integ.cancellations, cfg)
    checks, waterfall = integ.checks, integ.waterfall
    del raw, integ  # free the full raw table before analysis
    gc.collect()
    c = run_cohorts(lines, reg, cfg)
    d = run_drivers(lines, reg, cfg)
    checks = checks + analysis_checks(c, d, cfg)
    return Results(reg, checks, waterfall, c, d, lines if keep_lines else None)


def save(res: Results, out_dir="outputs"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res.registry.to_json(out / "metrics.json")
    with open(out / "checks.json", "w") as f:
        json.dump([asdict(c) for c in res.checks], f, indent=2, default=float)
    res.waterfall.to_csv(out / "integrity_waterfall.csv", index=False)
    res.cohorts["customer_triangle"].to_csv(out / "cohort_customer_retention.csv")
    res.cohorts["revenue_triangle"].to_csv(out / "cohort_revenue_retention.csv")
    res.drivers["driver_tree"].to_csv(out / "driver_tree.csv")
    res.drivers["pvm_bridge"].to_csv(out / "pvm_bridge.csv", index=False)
    res.drivers["monthly"].to_csv(out / "monthly_revenue.csv")
    res.drivers["concentration"]["top_products"].to_csv(out / "top_products.csv", index=False)
    res.drivers["concentration"]["customer_curve"].to_csv(out / "customer_curve.csv", index=False)
    res.cohorts["cohort_size"].rename("customers").to_csv(out / "cohort_size.csv")
    with open(out / "run_info.json", "w") as f:
        json.dump({"left_censored_cohort": res.cohorts["left_censored_cohort"],
                   "last_full_month": res.cohorts["last_full_month"],
                   "pvm_residual": float(res.drivers["pvm_residual"])}, f, indent=2)


def load_saved(out_dir="outputs") -> Results:
    """Rebuild Results from the files save() wrote: the app uses this for the sample data so it
    never has to hold a million rows in memory. Same numbers, read from disk."""
    out = Path(out_dir)

    def tri(name):
        t = pd.read_csv(out / name, index_col=0)
        t.index = pd.PeriodIndex(t.index, freq="M")
        t.columns = [int(c) for c in t.columns]
        return t

    info = json.load(open(out / "run_info.json"))
    checks = [Check(**c) for c in json.load(open(out / "checks.json"))]
    size = pd.read_csv(out / "cohort_size.csv", index_col=0)["customers"]
    size.index = pd.PeriodIndex(size.index, freq="M")
    monthly = pd.read_csv(out / "monthly_revenue.csv", index_col=0)
    cohorts = {"customer_triangle": tri("cohort_customer_retention.csv"),
               "revenue_triangle": tri("cohort_revenue_retention.csv"),
               "cohort_size": size, "left_censored_cohort": info["left_censored_cohort"],
               "last_full_month": info["last_full_month"]}
    drivers = {"monthly": monthly,
               "driver_tree": pd.read_csv(out / "driver_tree.csv", index_col=0),
               "pvm_bridge": pd.read_csv(out / "pvm_bridge.csv"),
               "pvm_residual": info["pvm_residual"],
               "concentration": {"top_products": pd.read_csv(out / "top_products.csv", dtype={"stock_code": str}),
                                 "customer_curve": pd.read_csv(out / "customer_curve.csv")}}
    return Results(Registry.from_json(out / "metrics.json"), checks,
                   pd.read_csv(out / "integrity_waterfall.csv"), cohorts, drivers, None)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/online_retail_ii.parquet"
    r = run(path)
    save(r)
    for c in r.checks:
        print(f"[{c.status}] {c.name}: {c.detail}")
    print(f"\n{len(r.registry)} metrics computed. Integrity {'PASSED' if r.passed else 'FAILED'}.")
