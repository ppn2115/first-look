"""Build the analysis-ready table from integrity output.

One row per product line (sales and cancellations), with month, cohort and segment.
Cohorts and segments are defined from SALES only, so a return can never create a cohort.
"""
import pandas as pd

from .config import Config, DEFAULT


def build_lines(sales: pd.DataFrame, cancellations: pd.DataFrame, cfg: Config = DEFAULT) -> pd.DataFrame:
    s = sales.assign(kind="sale")
    c = cancellations.assign(kind="cancellation")
    cols = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price",
            "customer_id", "country", "line_revenue"]
    lines = pd.concat([s[cols + ["kind"]], c[cols + ["kind"]]], ignore_index=True)
    lines["month"] = lines["invoice_date"].dt.to_period("M")
    lines["revenue"] = lines["line_revenue"]

    ident = lines[lines["customer_id"].notna()]
    sale_ident = ident[ident["kind"] == "sale"]

    cohort = sale_ident.groupby("customer_id")["month"].min().rename("cohort")
    first_date = sale_ident.groupby("customer_id")["invoice_date"].min().rename("first_purchase")

    order_vals = sale_ident.groupby(["customer_id", "invoice"])["revenue"].sum()
    median_order = order_vals.groupby("customer_id").median().rename("median_order_value")
    segment = (median_order >= cfg.large_account_median_order_gbp).map(
        {True: "Large accounts", False: "Small accounts"}).rename("segment")

    cust = pd.concat([cohort, first_date, median_order, segment], axis=1)
    lines = lines.join(cust, on="customer_id")
    # Customers who only ever cancelled (no sale in file) get no cohort
    lines["period"] = period_of(lines["month"], cfg)
    m, c = lines["month"], lines["cohort"]
    lines["age"] = ((m.dt.year - c.dt.year) * 12 + (m.dt.month - c.dt.month)).astype("Int64")
    return lines, cust


def period_of(month: pd.Series, cfg: Config = DEFAULT) -> pd.Series:
    p0 = (month >= pd.Period(cfg.period_0[0])) & (month <= pd.Period(cfg.period_0[1]))
    p1 = (month >= pd.Period(cfg.period_1[0])) & (month <= pd.Period(cfg.period_1[1]))
    out = pd.Series(pd.NA, index=month.index, dtype="object")
    out[p0] = "P0"
    out[p1] = "P1"
    return out
