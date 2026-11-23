"""Data integrity: classify every raw row into exactly one bucket, then tie out.

Order matters: a row gets the FIRST bucket it qualifies for. Because every row lands in
exactly one bucket, the bucket totals must add back to the raw total to the penny. That
tie-out is the core check: if it fails, nothing downstream is trusted.

Buckets (in priority order):
  sheet_overlap      the same invoice delivered in two sheets (kept once, in the earlier sheet)
  duplicate_line     an identical line repeated within the same invoice
  bad_debt_adjust    'A' invoices (accounting adjustments, not sales)
  non_product        postage, fees, manual lines, vouchers, test codes
  cancellation       'C' invoices on products (returns / cancelled orders)
  invalid            zero or negative price, or negative quantity outside a cancellation
  sale               a valid product sale
"""
from dataclasses import dataclass, field

import pandas as pd

from .config import Config, DEFAULT
from .metrics import Registry

BUCKET_ORDER = ["sheet_overlap", "duplicate_line", "bad_debt_adjust", "non_product",
                "cancellation", "invalid", "sale"]
BUCKET_LABELS = {
    "sheet_overlap": "Duplicate invoices across sheets",
    "duplicate_line": "Duplicate lines within an invoice",
    "bad_debt_adjust": "Bad-debt adjustments",
    "non_product": "Non-product lines (postage, fees, manual)",
    "cancellation": "Product cancellations / returns",
    "invalid": "Invalid lines (zero price, unexplained negatives)",
    "sale": "Valid product sales",
}


@dataclass
class Check:
    name: str
    status: str            # PASS | WARN | FAIL
    detail: str
    value: float | None = None


@dataclass
class IntegrityResult:
    classified: pd.DataFrame
    waterfall: pd.DataFrame
    checks: list = field(default_factory=list)
    sales: pd.DataFrame = None          # valid product sales
    cancellations: pd.DataFrame = None  # product cancellations (negative revenue)

    @property
    def passed(self) -> bool:
        return not any(c.status == "FAIL" for c in self.checks)


def classify(raw: pd.DataFrame, cfg: Config = DEFAULT) -> pd.Series:
    bucket = pd.Series(pd.NA, index=raw.index, dtype="object")

    def assign(mask, name):
        nonlocal bucket
        m = mask & bucket.isna()
        bucket[m] = name

    # 1. Same invoice appears in more than one sheet: keep the first sheet's copy
    # group on integer codes, not text: same result, a fraction of the memory
    inv_code = pd.factorize(raw["invoice"])[0]
    sheet_code = pd.Series(pd.factorize(raw["source_sheet"], sort=True)[0], index=raw.index)
    g = sheet_code.groupby(inv_code)
    sheets_per_invoice = g.transform("nunique")
    first_sheet = g.transform("min")
    assign((sheets_per_invoice > 1) & (sheet_code != first_sheet), "sheet_overlap")

    # 2. Exact duplicate lines (among rows not already removed)
    key = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id"]
    # hash each row's key once (much lighter than comparing 7 text columns row by row)
    remaining = bucket.isna()
    h = pd.util.hash_pandas_object(raw.loc[remaining, key], index=False)
    dup_idx = h[h.duplicated(keep="first")].index
    assign(raw.index.isin(dup_idx), "duplicate_line")

    inv_prefix = raw["invoice"].str[0]
    is_product = raw["stock_code"].str.match(cfg.product_code_regex) & \
        ~raw["stock_code"].isin(cfg.non_product_codes)

    assign(inv_prefix == "A", "bad_debt_adjust")
    assign(~is_product, "non_product")
    assign(inv_prefix == "C", "cancellation")
    assign((raw["price"] <= 0) | (raw["quantity"] <= 0), "invalid")
    assign(pd.Series(True, index=raw.index), "sale")
    return bucket


def run_integrity(raw: pd.DataFrame, reg: Registry, cfg: Config = DEFAULT) -> IntegrityResult:
    df = raw  # classified in place; avoids a full copy of the file
    df["bucket"] = classify(df, cfg)
    checks: list[Check] = []

    # --- Waterfall: rows and revenue by bucket
    g = df.groupby("bucket").agg(rows=("row_id", "size"), revenue=("line_revenue", "sum"))
    g = g.reindex(BUCKET_ORDER).fillna(0)
    g["label"] = [BUCKET_LABELS[b] for b in g.index]
    raw_total = df["line_revenue"].sum()
    g["share_of_raw_revenue"] = g["revenue"] / raw_total
    waterfall = g.reset_index()[["bucket", "label", "rows", "revenue", "share_of_raw_revenue"]]

    # --- Check 1: every row classified exactly once
    n_classified = int(g["rows"].sum())
    checks.append(Check("Every row classified exactly once",
                        "PASS" if n_classified == len(df) and df["bucket"].notna().all() else "FAIL",
                        f"{n_classified:,} of {len(df):,} rows assigned to one bucket", n_classified))

    # --- Check 2: revenue tie-out
    gap = g["revenue"].sum() - raw_total
    checks.append(Check("Revenue tie-out: buckets sum to raw total",
                        "PASS" if abs(gap) <= cfg.tie_out_tolerance_gbp else "FAIL",
                        f"Raw £{raw_total:,.2f}; buckets £{g['revenue'].sum():,.2f}; gap £{gap:,.2f}", gap))

    sales = df[df["bucket"] == "sale"]
    canc = df[df["bucket"] == "cancellation"]
    net_product = sales["line_revenue"].sum() + canc["line_revenue"].sum()

    # --- Check 3: net revenue reconciles to monthly totals (no rows lost when aggregating)
    monthly = (sales.groupby(sales["invoice_date"].dt.to_period("M"))["line_revenue"].sum()
               .add(canc.groupby(canc["invoice_date"].dt.to_period("M"))["line_revenue"].sum(), fill_value=0))
    checks.append(Check("Monthly totals reconcile to net product revenue",
                        "PASS" if abs(monthly.sum() - net_product) <= cfg.tie_out_tolerance_gbp else "FAIL",
                        f"Sum of months £{monthly.sum():,.2f} vs net £{net_product:,.2f}"))

    # --- Disclosed issues (WARN = found and handled, not hidden)
    ov = g.loc["sheet_overlap"]
    checks.append(Check("Duplicate invoices across source sheets",
                        "WARN" if ov["rows"] > 0 else "PASS",
                        f"{int(ov['rows']):,} rows (£{ov['revenue']:,.0f}) delivered twice; counted once",
                        ov["revenue"]))
    du = g.loc["duplicate_line"]
    checks.append(Check("Exact duplicate lines within invoices",
                        "WARN" if du["rows"] > 0 else "PASS",
                        f"{int(du['rows']):,} identical lines (£{du['revenue']:,.0f}) removed; "
                        "could be genuine repeat scans, so flagged for management", du["revenue"]))

    missing_cust_rev = sales.loc[sales["customer_id"].isna(), "line_revenue"].sum()
    missing_share = missing_cust_rev / sales["line_revenue"].sum()
    checks.append(Check("Sales without a customer ID",
                        "WARN" if missing_share > 0.05 else "PASS",
                        f"{missing_share:.1%} of valid sales (£{missing_cust_rev:,.0f}) have no customer ID; "
                        "included in revenue, excluded from customer and cohort analysis", missing_share))

    canc_rate = -canc["line_revenue"].sum() / sales["line_revenue"].sum()
    checks.append(Check("Cancellation rate (share of gross product sales)",
                        "WARN" if canc_rate > 0.05 else "PASS",
                        f"{canc_rate:.1%} of gross product sales cancelled", canc_rate))

    # Cancellations without a matching earlier sale for that customer + product
    if len(canc):
        first_sale = sales.dropna(subset=["customer_id"]).groupby(["customer_id", "stock_code"])["invoice_date"].min()
        c = canc.dropna(subset=["customer_id"]).join(first_sale.rename("first_sale"), on=["customer_id", "stock_code"])
        orphan = c["first_sale"].isna() | (c["first_sale"] > c["invoice_date"])
        orphan_share = -c.loc[orphan, "line_revenue"].sum() / max(-canc["line_revenue"].sum(), 1e-9)
        checks.append(Check("Cancellations with no earlier matching sale in the file",
                            "WARN" if orphan_share > 0.05 else "PASS",
                            f"{orphan_share:.1%} of cancelled £ relate to sales before the file starts or "
                            "not found; netted in the month cancelled", orphan_share))

    future = (df["invoice_date"] > pd.Timestamp.now()).sum()
    checks.append(Check("No future-dated transactions", "PASS" if future == 0 else "FAIL",
                        f"{future} future-dated rows; range {df['invoice_date'].min():%d %b %Y} to "
                        f"{df['invoice_date'].max():%d %b %Y}"))

    last = df["invoice_date"].max()
    partial = last.day < pd.Timestamp(last).days_in_month
    checks.append(Check("Partial final month", "WARN" if partial else "PASS",
                        f"Data ends {last:%d %b %Y}; {last:%b %Y} is partial and excluded from "
                        "year-over-year comparisons" if partial else "Final month complete"))

    # --- Register metrics
    S = "integrity"
    reg.add("raw_rows", "Raw rows delivered", len(df), "count", S)
    reg.add("raw_revenue", "Raw revenue as delivered (qty × price, all rows)", raw_total, "gbp", S)
    reg.add("overlap_revenue", "Revenue double-counted across sheets", ov["revenue"], "gbp", S)
    reg.add("overlap_rows", "Rows double-counted across sheets", ov["rows"], "count", S)
    reg.add("overlap_share_raw", "Double-counted revenue as share of raw revenue", ov["revenue"] / raw_total, "pct", S)
    reg.add("duplicate_line_rows", "Duplicate lines removed", du["rows"], "count", S)
    reg.add("gross_product_sales", "Gross product sales (valid sales)", sales["line_revenue"].sum(), "gbp", S)
    reg.add("cancellations_value", "Product cancellations", -canc["line_revenue"].sum(), "gbp", S)
    reg.add("cancellation_rate", "Cancellations as share of gross product sales", canc_rate, "pct", S)
    reg.add("net_product_revenue", "Net product revenue (sales less cancellations)", net_product, "gbp", S)
    reg.add("non_product_revenue", "Non-product line revenue (postage, fees, manual)",
            g.loc["non_product", "revenue"], "gbp", S)
    reg.add("missing_customer_share", "Share of valid sales with no customer ID", missing_share, "pct", S)
    reg.add("raw_to_net_gap", "Raw revenue minus net product revenue", raw_total - net_product, "gbp", S)

    return IntegrityResult(df, waterfall, checks, sales, canc)
