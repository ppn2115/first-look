"""Growth drivers: revenue driver tree, new vs repeat, segments, concentration, price/volume/mix.

Periods: P0 = Dec 2009–Nov 2010, P1 = Dec 2010–Nov 2011 (twelve full months each; Dec 2011
is a 9-day stub and excluded). Revenue is net product revenue (sales less cancellations).
"""
import numpy as np
import pandas as pd

from .config import Config, DEFAULT
from .metrics import Registry


def monthly_series(lines: pd.DataFrame) -> pd.DataFrame:
    kind = np.where(lines["customer_id"].isna(), "No customer ID",
                    np.where(lines["month"] == lines["cohort"], "New customers", "Repeat customers"))
    m = lines["revenue"].groupby([lines["month"], kind]).sum().unstack(fill_value=0)
    m.index.name, m.columns.name = "month", "type"
    m["Total"] = m.sum(axis=1)
    return m


def driver_tree(lines: pd.DataFrame, reg: Registry, cfg: Config):
    d = lines[lines["period"].notna()]
    S = "drivers"
    tot = d.groupby("period")["revenue"].sum()
    reg.add("rev_p0", f"Net product revenue {cfg.period_0[0]} to {cfg.period_0[1]}", tot["P0"], "gbp", S)
    reg.add("rev_p1", f"Net product revenue {cfg.period_1[0]} to {cfg.period_1[1]}", tot["P1"], "gbp", S)
    reg.add("rev_growth", "Net product revenue growth, P1 vs P0", tot["P1"] / tot["P0"] - 1, "pct", S)

    idn = d[d["customer_id"].notna()]
    rows = {}
    for p in ("P0", "P1"):
        x = idn[idn["period"] == p]
        sales = x[x["kind"] == "sale"]
        cust = sales["customer_id"].nunique()
        orders = sales["invoice"].nunique()
        rev = x["revenue"].sum()
        rows[p] = {"revenue": rev, "customers": cust, "orders": orders,
                   "orders_per_customer": orders / cust, "aov": rev / orders}
    tree = pd.DataFrame(rows).T
    # identity check: revenue = customers × orders/customer × AOV
    tree["identity_check"] = tree["customers"] * tree["orders_per_customer"] * tree["aov"] - tree["revenue"]
    tree.loc["change"] = tree.loc["P1"] / tree.loc["P0"] - 1

    for k, lab, unit in [("customers", "Active customers", "count"),
                         ("orders_per_customer", "Orders per active customer", "ratio"),
                         ("aov", "Average order value (net)", "gbp"),
                         ("revenue", "Revenue from identified customers", "gbp")]:
        reg.add(f"{k}_p0", f"{lab}, P0", tree.loc["P0", k], unit, S)
        reg.add(f"{k}_p1", f"{lab}, P1", tree.loc["P1", k], unit, S)
        reg.add(f"{k}_growth", f"{lab}, change P1 vs P0", tree.loc["change", k], "pct", S)

    tree.loc["change", "identity_check"] = float("nan")

    # Revenue with no customer ID: if headline growth and identified growth diverge, say so
    anon = d[d["customer_id"].isna()].groupby("period")["revenue"].sum()
    reg.add("anon_rev_p0", "Net revenue with no customer ID, P0", anon.get("P0", 0), "gbp", S)
    reg.add("anon_rev_p1", "Net revenue with no customer ID, P1", anon.get("P1", 0), "gbp", S)
    reg.add("anon_rev_growth", "Growth in revenue with no customer ID, P1 vs P0",
            anon.get("P1", 0) / anon.get("P0", 1) - 1, "pct", S)
    reg.add("anon_rev_share_p1", "Share of P1 net revenue with no customer ID",
            anon.get("P1", 0) / tot["P1"], "pct", S)

    # New vs repeat in P1
    p1 = idn[idn["period"] == "P1"]
    new_rev = p1.loc[p1["month"] == p1["cohort"], "revenue"].sum()
    reg.add("repeat_rev_share_p1", "Share of P1 identified revenue from repeat customers",
            1 - new_rev / p1["revenue"].sum(), "pct", S,
            "Repeat = revenue in any month after the customer's first purchase month")
    new_cust_p1 = p1.loc[p1["cohort"] >= pd.Period(cfg.period_1[0]), "customer_id"].nunique()
    reg.add("new_customers_p1", "New customers acquired in P1", new_cust_p1, "count", S)
    return tree


def segments(lines: pd.DataFrame, reg: Registry, cfg: Config):
    d = lines[lines["period"].notna()]
    d = d[d["segment"].notna()]
    t = d.groupby(["segment", "period"]).agg(revenue=("revenue", "sum"),
                                             customers=("customer_id", "nunique")).unstack()
    S = "segments"
    total_p1 = t[("revenue", "P1")].sum()
    for seg, key in (("Large accounts", "large"), ("Small accounts", "small")):
        reg.add(f"{key}_rev_share_p1", f"{seg}: share of identified P1 revenue",
                t.loc[seg, ("revenue", "P1")] / total_p1, "pct", S,
                f"{seg} = median order value {'≥' if key == 'large' else '<'} £{cfg.large_account_median_order_gbp:,.0f}")
        reg.add(f"{key}_rev_growth", f"{seg}: revenue growth P1 vs P0",
                t.loc[seg, ("revenue", "P1")] / t.loc[seg, ("revenue", "P0")] - 1, "pct", S)
        reg.add(f"{key}_customers_p1", f"{seg}: active customers in P1", t.loc[seg, ("customers", "P1")], "count", S)
    return t


def concentration(lines: pd.DataFrame, reg: Registry, cfg: Config):
    d = lines
    p1 = d[(d["period"] == "P1") & (d["kind"] == "sale")]
    S = "concentration"
    by_sku = p1.groupby("stock_code").agg(revenue=("revenue", "sum"),
                                          description=("description", "first")).sort_values("revenue", ascending=False)
    total = by_sku["revenue"].sum()
    top = by_sku.head(cfg.top_n_products)
    reg.add("top10_sku_share", f"Top {cfg.top_n_products} products' share of P1 product sales",
            top["revenue"].sum() / total, "pct", S)
    cum = by_sku["revenue"].cumsum() / total
    reg.add("skus_for_80pct", "Products needed to make 80% of P1 sales", int((cum < 0.8).sum() + 1), "count", S)
    reg.add("sku_count_p1", "Products sold in P1", len(by_sku), "count", S)

    by_cust = p1[p1["customer_id"].notna()].groupby("customer_id")["revenue"].sum().sort_values(ascending=False)
    n = len(by_cust)
    reg.add("top1pct_cust_share", "Top 1% of customers' share of identified P1 sales",
            by_cust.head(max(1, n // 100)).sum() / by_cust.sum(), "pct", S)
    reg.add("top10pct_cust_share", "Top 10% of customers' share of identified P1 sales",
            by_cust.head(max(1, n // 10)).sum() / by_cust.sum(), "pct", S)
    reg.add("top_customer_share", "Largest single customer's share of identified P1 sales",
            by_cust.iloc[0] / by_cust.sum(), "pct", S)

    by_country = p1.groupby("country")["revenue"].sum().sort_values(ascending=False)
    reg.add("uk_share_p1", "United Kingdom share of P1 product sales",
            by_country.get("United Kingdom", 0) / by_country.sum(), "pct", S)
    top_cust = by_cust.reset_index().rename(columns={"revenue": "p1_sales"})
    return {"top_products": top.reset_index(), "customer_curve": by_cust.reset_index(),
            "countries": by_country.reset_index()}


def pvm_bridge(lines: pd.DataFrame, reg: Registry, cfg: Config):
    """Price / volume / mix bridge on gross product sales, P0 → P1, at product level.

    volume = (U1 − U0) × base-period average price at base mix
    mix    = U1 × Σ (share1 − share0) × price0        (common products)
    price  = Σ units1 × (price1 − price0)             (common products)
    plus revenue from new products and lost revenue from discontinued products.
    Components sum exactly to the change in gross product sales.
    """
    d = lines
    s = d[(d["kind"] == "sale") & d["period"].notna()]
    g = s.groupby(["stock_code", "period"]).agg(units=("quantity", "sum"), rev=("revenue", "sum")).unstack(fill_value=0)
    u0, u1 = g[("units", "P0")], g[("units", "P1")]
    r0, r1 = g[("rev", "P0")], g[("rev", "P1")]
    common = (u0 > 0) & (u1 > 0)
    new = (u0 == 0) & (u1 > 0)
    gone = (u0 > 0) & (u1 == 0)

    p0 = r0[common] / u0[common]
    p1 = r1[common] / u1[common]
    U0, U1 = u0[common].sum(), u1[common].sum()
    s0, s1 = u0[common] / U0, u1[common] / U1
    base_avg_price = (s0 * p0).sum()

    volume = (U1 - U0) * base_avg_price
    mix = U1 * ((s1 - s0) * p0).sum()
    price = (u1[common] * (p1 - p0)).sum()
    new_rev = r1[new].sum()
    lost_rev = -r0[gone].sum()
    start, end = r0.sum(), r1.sum()

    bridge = pd.DataFrame({
        "step": ["P0 gross product sales", "Volume", "Mix", "Price", "New products",
                 "Discontinued products", "P1 gross product sales"],
        "value": [start, volume, mix, price, new_rev, lost_rev, end],
    })
    residual = start + volume + mix + price + new_rev + lost_rev - end
    S = "pvm"
    reg.add("pvm_start", "Gross product sales P0 (bridge start)", start, "gbp", S)
    reg.add("pvm_end", "Gross product sales P1 (bridge end)", end, "gbp", S)
    reg.add("pvm_volume", "Bridge: volume effect", volume, "gbp", S)
    reg.add("pvm_mix", "Bridge: mix effect", mix, "gbp", S)
    reg.add("pvm_price", "Bridge: price effect", price, "gbp", S,
            "Change in realised price per unit on continuing products (includes changes in discount tiers)")
    reg.add("pvm_new", "Bridge: revenue from new products", new_rev, "gbp", S)
    reg.add("pvm_lost", "Bridge: revenue lost from discontinued products", lost_rev, "gbp", S)
    reg.add("pvm_new_share_p1", "New products' share of P1 gross product sales", new_rev / end, "pct", S)
    return bridge, residual


def run_drivers(lines: pd.DataFrame, reg: Registry, cfg: Config = DEFAULT) -> dict:
    tree = driver_tree(lines, reg, cfg)
    seg = segments(lines, reg, cfg)
    conc = concentration(lines, reg, cfg)
    bridge, residual = pvm_bridge(lines, reg, cfg)
    return {"monthly": monthly_series(lines), "driver_tree": tree, "segments": seg,
            "concentration": conc, "pvm_bridge": bridge, "pvm_residual": residual}
