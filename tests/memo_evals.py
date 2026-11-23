"""Eval set for the memo verifier.

Each case is a claim an LLM might write, the metrics it cites, and whether the verifier
must PASS or BLOCK it. Half are deliberately wrong in the ways LLMs actually go wrong:
invented numbers, transposed digits, wrong units, wrong scale, wrong direction, citing the
wrong metric, citing a metric that doesn't exist.
"""
from firstlook.metrics import Registry


def eval_registry() -> Registry:
    r = Registry()
    r.add("rev_growth", "Net product revenue growth, P1 vs P0", 0.0192, "pct", "drivers")
    r.add("revenue_growth", "Revenue from identified customers, change P1 vs P0", -0.0203, "pct", "drivers")
    r.add("anon_rev_growth", "Growth in revenue with no customer ID, P1 vs P0", 0.321, "pct", "drivers")
    r.add("rev_p1", "Net product revenue 2010-12 to 2011-11", 9_330_412.0, "gbp", "drivers")
    r.add("m3_ret_change", "Change in month-3 retention, 2011 vs 2010 cohorts", -0.0391, "pp", "cohorts")
    r.add("repeat_90d", "90-day repeat rate, new customers with 90+ days of history", 0.4376, "pct", "cohorts")
    r.add("repeat_90d_naive", "90-day repeat rate if recent customers are wrongly included", 0.4311, "pct", "cohorts")
    r.add("orders_per_customer_p1", "Orders per active customer, P1", 4.1134, "ratio", "drivers")
    r.add("new_customers_p1", "New customers acquired in P1", 1585, "count", "drivers")
    r.add("top10_sku_share", "Top 10 products' share of P1 product sales", 0.0851, "pct", "concentration")
    r.add("top1pct_cust_share", "Top 1% of customers' share of identified P1 sales", 0.307, "pct", "concentration")
    r.add("pvm_volume", "Bridge: volume effect", -1_568_011.0, "gbp", "pvm")
    r.add("pvm_new", "Bridge: revenue from new products", 2_046_904.0, "gbp", "pvm")
    r.add("pvm_lost", "Bridge: revenue lost from discontinued products", -704_200.8, "gbp", "pvm")
    r.add("m3_ret_h1_2010", "Month-3 customer retention, Jan–Jun 2010 cohorts", 0.2400, "pct", "cohorts")
    r.add("m3_ret_h1_2011", "Month-3 customer retention, Jan–Jun 2011 cohorts", 0.2010, "pct", "cohorts")
    r.add("large_rev_share_p1", "Large accounts: share of identified P1 revenue", 0.464, "pct", "segments")
    r.add("large_rev_growth", "Large accounts: revenue growth P1 vs P0", -0.0060, "pct", "segments")
    r.add("overlap_revenue", "Revenue double-counted across sheets", 377_488.45, "gbp", "integrity")
    return r


CASES = [
    # ---- should PASS
    dict(id="pass_exact", expect="PASS", metric_ids=["rev_growth"],
         text="Net product revenue grew 1.9% year over year."),
    dict(id="pass_rounded", expect="PASS", metric_ids=["repeat_90d"],
         text="About 44% of new customers order again within 90 days."),
    dict(id="pass_scaled_gbp", expect="PASS", metric_ids=["rev_p1"],
         text="The latest twelve months delivered £9.33M of net product revenue."),
    dict(id="pass_pp_change", expect="PASS", metric_ids=["m3_ret_change"],
         text="Month-3 retention fell 3.9 pts for 2011 cohorts compared with 2010 cohorts."),
    dict(id="pass_label_literals", expect="PASS", metric_ids=["top10_sku_share", "top1pct_cust_share"],
         text="The top 10 products are only 8.5% of sales, but the top 1% of customers drive 30.7%."),
    dict(id="pass_two_metrics", expect="PASS", metric_ids=["revenue_growth", "anon_rev_growth"],
         text="Revenue from identified customers fell 2.0% while revenue with no customer ID grew 32.1%."),
    dict(id="pass_qualitative", expect="PASS", metric_ids=[],
         text="Management should explain why so many orders lack a customer ID."),
    # ---- real-run false positives (claims Claude wrote that are correct and must pass)
    dict(id="pass_fell_between_levels", expect="PASS", metric_ids=["m3_ret_h1_2010", "m3_ret_h1_2011"],
         text="Month-3 retention fell from 24.0% for January–June 2010 cohorts to 20.1% for 2011 cohorts."),
    dict(id="pass_two_clauses_two_directions", expect="PASS", metric_ids=["pvm_new", "pvm_lost"],
         text="New products added £2.05M while discontinued products removed £704.2k."),
    dict(id="pass_explicit_negative_sign", expect="PASS", metric_ids=["large_rev_growth"],
         text="Large accounts had revenue growth of -0.6%."),
    dict(id="pass_level_with_down_word", expect="PASS", metric_ids=["large_rev_share_p1", "large_rev_growth"],
         text="Large accounts shrank, at 46.4% of identified revenue and down 0.6%."),
    dict(id="pass_date_not_a_number", expect="PASS", metric_ids=[],
         text="The data ends on 09 Dec 2011, so the partial final month is excluded."),
    # ---- must BLOCK
    dict(id="block_invented", expect="BLOCK", metric_ids=["rev_growth"],
         text="Net product revenue grew 12% year over year."),
    dict(id="block_transposed", expect="BLOCK", metric_ids=["anon_rev_growth"],
         text="Revenue with no customer ID grew 23.1%."),
    dict(id="block_pct_for_pp", expect="BLOCK", metric_ids=["m3_ret_change"],
         text="Month-3 retention fell 3.9% for newer cohorts."),
    dict(id="block_wrong_scale", expect="BLOCK", metric_ids=["overlap_revenue"],
         text="The file double-counted £377.5M of revenue."),
    dict(id="block_wrong_direction", expect="BLOCK", metric_ids=["revenue_growth"],
         text="Revenue from identified customers grew 2.0%."),
    dict(id="block_wrong_direction_gbp", expect="BLOCK", metric_ids=["pvm_volume"],
         text="Higher volumes added £1.57M to sales."),
    dict(id="pass_negative_gbp", expect="PASS", metric_ids=["pvm_volume"],
         text="Lower volumes on continuing products cut sales by £1.57M."),
    dict(id="block_uncited", expect="BLOCK", metric_ids=["repeat_90d"],
         text="The 90-day repeat rate is 43.8%, versus 43.1% if recent customers are included."),
    dict(id="block_unknown_metric", expect="BLOCK", metric_ids=["ltv_cac"],
         text="LTV/CAC is a healthy 3.2x."),
    dict(id="block_explicit_negative_on_positive", expect="BLOCK", metric_ids=["pvm_new"],
         text="New products contributed -£2.05M."),
    dict(id="block_number_not_a_metric", expect="BLOCK", metric_ids=["repeat_90d"],
         text="The 90-day repeat rate of 43.8% rests on just 11 cohorts."),
    dict(id="block_wrong_count", expect="BLOCK", metric_ids=["new_customers_p1"],
         text="The business acquired 1,855 new customers in the latest year."),
]
