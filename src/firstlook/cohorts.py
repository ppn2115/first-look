"""Cohort retention (customers and revenue) and the censoring-adjusted 90-day repeat rate.

Two biases this module handles explicitly:
  * Left-censoring: the file starts Dec 2009, so the Dec 2009 "cohort" contains every
    existing customer, not new ones. It is shown but excluded from averages.
  * Right-censoring: customers acquired near the end of the file have not had time to
    repeat. Retention at age k only uses cohorts that have actually reached age k, and the
    90-day repeat rate only uses customers with a full 90 days of history.
"""
import pandas as pd

from .config import Config, DEFAULT
from .metrics import Registry


def _complete(lines, last_full_month):
    # age < 0 = a cancellation of a sale made before the customer's first sale in the file
    # (i.e. before the file starts); flagged in integrity, excluded here
    return lines[(lines["month"] <= last_full_month) & lines["cohort"].notna() & (lines["age"] >= 0)]


def retention_triangles(lines: pd.DataFrame, last_full_month: pd.Period):
    d = _complete(lines, last_full_month)
    sales = d[d["kind"] == "sale"]
    active = sales.groupby(["cohort", "age"])["customer_id"].nunique().unstack()
    size = active[0]
    cust_ret = active.div(size, axis=0)

    rev = d.groupby(["cohort", "age"])["revenue"].sum().unstack()
    rev_ret = rev.div(rev[0], axis=0)

    # Blank out cells beyond the observed horizon (they are unknown, not zero)
    max_age = {c: (last_full_month - c).n for c in cust_ret.index}
    for c in cust_ret.index:
        cust_ret.loc[c, cust_ret.columns > max_age[c]] = float("nan")
        rev_ret.loc[c, rev_ret.columns > max_age[c]] = float("nan")
    # Observed-but-inactive cells should be 0, not NaN
    for c in cust_ret.index:
        cols = [a for a in cust_ret.columns if a <= max_age[c]]
        cust_ret.loc[c, cols] = cust_ret.loc[c, cols].fillna(0)
        rev_ret.loc[c, cols] = rev_ret.loc[c, cols].fillna(0)
    return cust_ret, rev_ret, size, rev[0]


def weighted_retention(ret: pd.DataFrame, weights: pd.Series, age: int, exclude: list):
    """Cohort-size-weighted retention at a given age, using only cohorts that reached that age."""
    r = ret.drop(index=[e for e in exclude if e in ret.index])
    if age not in r.columns:
        return float("nan"), 0
    col = r[age].dropna()
    w = weights.reindex(col.index)
    return float((col * w).sum() / w.sum()), len(col)


def repeat_rate(lines: pd.DataFrame, window_days: int, exclude_cohorts: list):
    """Share of new customers who place a second order within `window_days` of the first.

    Returns (adjusted, naive, n_eligible). 'Naive' includes customers who have not yet had
    `window_days` of history, which biases the rate down.
    """
    s = lines[(lines["kind"] == "sale") & lines["customer_id"].notna()]
    s = s[~s["cohort"].isin(exclude_cohorts)]
    orders = s.groupby(["customer_id", "invoice"])["invoice_date"].min().reset_index()
    orders = orders.sort_values(["customer_id", "invoice_date"])
    first = orders.groupby("customer_id")["invoice_date"].min()
    # second order = first order on a later timestamp than the first
    later = orders.merge(first.rename("first"), left_on="customer_id", right_index=True)
    later = later[later["invoice_date"] > later["first"]]
    second = later.groupby("customer_id")["invoice_date"].min()
    df = pd.DataFrame({"first": first}).join(second.rename("second"))
    df["repeat"] = (df["second"] - df["first"]).dt.days <= window_days
    end = lines["invoice_date"].max()
    eligible = df[df["first"] <= end - pd.Timedelta(days=window_days)]
    return float(eligible["repeat"].mean()), float(df["repeat"].mean()), len(eligible), len(df)


def run_cohorts(lines: pd.DataFrame, reg: Registry, cfg: Config = DEFAULT) -> dict:
    end = lines["invoice_date"].max()
    last_full = end.to_period("M") if end.day == end.days_in_month else end.to_period("M") - 1
    first_cohort = lines["cohort"].min()
    exclude = [first_cohort]  # left-censored

    cust_ret, rev_ret, size, rev0 = retention_triangles(lines, last_full)
    S = "cohorts"
    out = {"customer_triangle": cust_ret, "revenue_triangle": rev_ret,
           "cohort_size": size, "cohort_first_month_revenue": rev0,
           "left_censored_cohort": str(first_cohort), "last_full_month": str(last_full)}

    for age in (1, 3, 6, 12):
        v, n = weighted_retention(cust_ret, size, age, exclude)
        reg.add(f"cust_ret_m{age}", f"Customer retention at month {age} (weighted avg of cohorts)", v, "pct", S,
                f"Share of a cohort buying in month {age} after first purchase; {n} cohorts reached this age; "
                f"{first_cohort} cohort excluded (pre-existing customers)")
        reg.add(f"cohorts_m{age}", f"Cohorts that have reached month {age}", n, "count", S)
        v, n = weighted_retention(rev_ret, rev0, age, exclude)
        reg.add(f"rev_ret_m{age}", f"Revenue retention at month {age} (cohort revenue vs month 0)", v, "pct", S,
                f"Cohort revenue in month {age} ÷ cohort revenue in its first month; {n} cohorts. If this is above "
                "customer retention, the customers who stay buy more per head than the cohort did in month 0. "
                "That can mean bigger buyers are the ones who stay (selection), not that customers grew; "
                "this data cannot tell which.")

    # Are newer cohorts retaining worse? Compare H1 2010 vs H1 2011 cohorts at month 3
    def group_m3(start, stop):
        idx = [c for c in cust_ret.index if pd.Period(start) <= c <= pd.Period(stop)]
        col = cust_ret.loc[idx, 3].dropna()
        w = size.reindex(col.index)
        return float((col * w).sum() / w.sum())
    a, b = group_m3("2010-01", "2010-06"), group_m3("2011-01", "2011-06")
    reg.add("m3_ret_h1_2010", "Month-3 customer retention, Jan–Jun 2010 cohorts", a, "pct", S)
    reg.add("m3_ret_h1_2011", "Month-3 customer retention, Jan–Jun 2011 cohorts", b, "pct", S)
    reg.add("m3_ret_change", "Change in month-3 retention, 2011 vs 2010 cohorts", b - a, "pp", S)

    adj, naive, n_elig, n_all = repeat_rate(lines, cfg.repeat_window_days, exclude)
    reg.add("repeat_90d", "90-day repeat rate, new customers with 90+ days of history", adj, "pct", S,
            f"{n_elig:,} eligible new customers; second order within 90 days of first")
    reg.add("repeat_90d_naive", "90-day repeat rate if recent customers are wrongly included", naive, "pct", S,
            f"All {n_all:,} new customers, including those acquired in the last 90 days")
    reg.add("repeat_90d_eligible", "New customers with 90+ days of history", n_elig, "count", S)
    reg.add("new_customers_total", "New customers acquired after the first month", n_all, "count", S)
    reg.add("existing_customers_dec09", f"Customers already active in the first month ({first_cohort})",
            size[first_cohort], "count", S)
    return out
