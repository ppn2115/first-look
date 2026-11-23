"""First Look: turn a raw transaction file into a verified first-look diligence pack.

    streamlit run app.py
"""
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from firstlook.pipeline import run  # noqa: E402
from firstlook.metrics import Registry  # noqa: E402

SAMPLE = Path(__file__).parent / "data/raw/online_retail_ii.parquet"
MEMO = Path(__file__).parent / "outputs/memo.json"

# Validated reference palette (light mode)
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
SEQ = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e8e7e3"
ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "VERIFIED": "✅", "QUALITATIVE": "💬", "BLOCKED": "⛔"}

st.set_page_config(page_title="First Look · diligence pack", page_icon="🔎", layout="wide")


def style(fig, h=380, legend=True):
    fig.update_layout(template="plotly_white", height=h, margin=dict(l=10, r=10, t=40, b=10),
                      font=dict(family="Inter, Arial, sans-serif", size=13, color=INK2),
                      title_font=dict(size=15, color=INK), hoverlabel=dict(bgcolor="white"),
                      showlegend=legend,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


@st.cache_resource(show_spinner="Running the pipeline: integrity checks, cohorts, drivers…")
def run_cached(path: str, _key: str):
    return run(path)


# ---------------------------------------------------------------- data source
st.sidebar.title("🔎 First Look")
st.sidebar.caption("Raw transaction file → verified first-look diligence pack.")
up = st.sidebar.file_uploader("Upload your own file (optional)", type=["xlsx", "csv", "parquet"],
                              help="Columns: Invoice, StockCode, Description, Quantity, InvoiceDate, "
                                   "Price, Customer ID, Country")
if up is not None:
    tmp = Path(tempfile.gettempdir()) / up.name
    tmp.write_bytes(up.getvalue())
    path, key, is_sample = str(tmp), f"{up.name}-{up.size}", False
else:
    path, key, is_sample = str(SAMPLE), "sample", True

try:
    R = run_cached(path, key)
except Exception as e:  # bad upload: say why instead of crashing
    st.error(f"Could not process this file: {e}")
    st.stop()

M: Registry = R.registry
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Data:** {'UCI Online Retail II (sample)' if is_sample else up.name}")
n_fail = sum(c.status == "FAIL" for c in R.checks)
n_warn = sum(c.status == "WARN" for c in R.checks)
st.sidebar.markdown(f"**Integrity:** {'❌ FAILED' if n_fail else '✅ passed'} · {n_warn} disclosed issues")
st.sidebar.markdown(f"**Metrics computed:** {len(M)}")
st.sidebar.markdown("---")
st.sidebar.caption("Every number in the memo is checked against these computed metrics by code. "
                   "Unverified numbers are blocked. See the Audit tab.")

st.title("First look: UK online gift-ware retailer" if is_sample else f"First look: {up.name}")
st.caption("Dec 2009 – Dec 2011 · periods compared: P0 = Dec 2009–Nov 2010, P1 = Dec 2010–Nov 2011 "
           "(Dec 2011 is a 9-day stub and excluded from year-over-year figures)")

k = st.columns(5)
k[0].metric("Net product revenue, P1", M["rev_p1"].display(), f"{M['rev_growth'].value:+.1%} vs P0")
k[1].metric("Identified-customer revenue", M["revenue_p1"].display(), f"{M['revenue_growth'].value:+.1%} vs P0")
k[2].metric("No-customer-ID revenue", M["anon_rev_p1"].display(), f"{M['anon_rev_growth'].value:+.1%} vs P0",
            delta_color="off")
k[3].metric("90-day repeat rate", M["repeat_90d"].display(), help=M["repeat_90d"].definition)
k[4].metric("Month-3 retention, 2011 cohorts", M["m3_ret_h1_2011"].display(),
            M["m3_ret_change"].display())

t_int, t_an, t_memo, t_audit = st.tabs(["① Data integrity", "② Analysis", "③ AI memo", "④ Audit"])

# ---------------------------------------------------------------- integrity
with t_int:
    st.subheader("From the file as delivered to revenue we can trust")
    st.write("Every row is classified into exactly one bucket, so the buckets must add back to the raw "
             "total to the penny. If they don't, nothing downstream is trusted.")
    wf = R.waterfall.set_index("bucket")
    short = {"sheet_overlap": "Sheet overlap<br>(double-counted)", "duplicate_line": "Duplicate<br>lines",
             "bad_debt_adjust": "Bad-debt<br>adjustments", "non_product": "Postage, fees,<br>manual lines",
             "invalid": "Invalid<br>lines"}
    steps = [("Raw file<br>total", M["raw_revenue"].value, "absolute")]
    for b in ["sheet_overlap", "duplicate_line", "bad_debt_adjust", "non_product", "invalid"]:
        v = -wf.loc[b, "revenue"]
        if abs(v) > 0.005:
            steps.append((short[b], v, "relative"))
    steps.append(("Net product<br>revenue", M["net_product_revenue"].value, "total"))
    fig = go.Figure(go.Waterfall(
        x=[s[0] for s in steps], y=[s[1] / 1e6 for s in steps], measure=[s[2] for s in steps],
        increasing=dict(marker_color=BLUE), decreasing=dict(marker_color=ORANGE),
        totals=dict(marker_color=GREY), connector=dict(line=dict(color=GRID)),
        text=[f"£{s[1]/1e6:,.2f}M" if s[2] != "relative" else f"{s[1]/1e3:+,.0f}k" for s in steps],
        textposition="outside", hovertemplate="%{x}<br>£%{y:,.3f}M<extra></extra>"))
    fig.update_yaxes(range=[M["net_product_revenue"].value / 1e6 * 0.97, M["raw_revenue"].value / 1e6 * 1.01],
                     tickprefix="£", ticksuffix="M", tickformat=",.1f")
    st.plotly_chart(style(fig, 420, legend=False), width="stretch")
    st.caption("Axis starts at £18M to make the adjustments visible. Bad-debt adjustments are negative lines, so "
               "removing them adds back. Cancellations stay in net revenue (they are real returns); see the table.")

    show = R.waterfall.copy()
    show["revenue"] = show["revenue"].map(lambda v: f"£{v:,.2f}")
    show["share_of_raw_revenue"] = show["share_of_raw_revenue"].map(lambda v: f"{v:.2%}")
    show["rows"] = show["rows"].map(lambda v: f"{int(v):,}")
    st.dataframe(show.drop(columns="bucket").rename(columns={
        "label": "Bucket", "rows": "Rows", "revenue": "Revenue", "share_of_raw_revenue": "Share of raw"}),
        hide_index=True, width="stretch")

    st.subheader("Checks")
    for c in R.checks:
        st.markdown(f"{ICON[c.status]} **{c.name}** · {c.detail}")

# ---------------------------------------------------------------- analysis
with t_an:
    st.subheader("Revenue by month: new vs repeat customers")
    mo = R.drivers["monthly"].copy()
    mo.index = mo.index.astype(str)
    fig = go.Figure()
    for col, colr in [("Repeat customers", BLUE), ("New customers", ORANGE), ("No customer ID", AQUA)]:
        if col in mo:
            fig.add_bar(x=mo.index, y=mo[col], name=col, marker_color=colr,
                        marker_line=dict(color="white", width=1),
                        hovertemplate=f"{col}<br>%{{x}}: £%{{y:,.0f}}<extra></extra>")
    fig.update_layout(barmode="stack", legend_traceorder="normal")
    fig.update_yaxes(tickprefix="£", tickformat=",.2s")
    st.plotly_chart(style(fig, 360), width="stretch")
    st.caption(f"Repeat customers are {M['repeat_rev_share_p1'].display()} of identified revenue in P1. "
               f"Dec 2009 shows as 'new' only because the file starts then. Strong Q4 seasonality.")

    st.subheader("Cohort retention")
    c1, c2 = st.columns([3, 2])
    with c1:
        kind = st.radio("Measure", ["Customers (share still buying)", "Revenue (vs. first month)"],
                        horizontal=True, label_visibility="collapsed")
        tri = R.cohorts["customer_triangle" if kind.startswith("Customers") else "revenue_triangle"]
        tri = tri[[c for c in tri.columns if 1 <= c <= 23]]  # month 0 is always 100%
        z = tri.values * 100
        zmax = 60 if kind.startswith("Customers") else 80
        txt = [[("" if pd.isna(v) else f"{v:.0f}") for v in row] for row in z]
        fig = go.Figure(go.Heatmap(
            z=z, x=[str(c) for c in tri.columns], y=[str(i) for i in tri.index], text=txt,
            texttemplate="%{text}", textfont=dict(size=9),
            colorscale=[[i / (len(SEQ) - 1), c] for i, c in enumerate(SEQ)], zmin=0, zmax=zmax,
            xgap=2, ygap=2, colorbar=dict(title="%", ticksuffix="%"),
            hovertemplate="Cohort %{y}, month %{x}: %{z:.1f}%<extra></extra>"))
        fig.update_yaxes(autorange="reversed", title="First-purchase month")
        fig.update_xaxes(title="Months since first purchase", showgrid=False)
        st.plotly_chart(style(fig, 560, legend=False), width="stretch")
        st.caption(f"Month 0 (always 100%) is omitted. Blank cells are months a cohort has not reached yet (unknown, not zero). The "
                   f"{R.cohorts['left_censored_cohort']} row holds every customer already active when the file "
                   "starts, so it retains better and is excluded from averages.")
    with c2:
        st.markdown("**Are newer cohorts worse?** Average retention curve by acquisition half-year")
        ct = R.cohorts["customer_triangle"]
        size = R.cohorts["cohort_size"]
        fig = go.Figure()
        for (a, b, name, colr) in [("2010-01", "2010-06", "Jan–Jun 2010 cohorts", BLUE),
                                   ("2011-01", "2011-06", "Jan–Jun 2011 cohorts", ORANGE)]:
            idx = [c for c in ct.index if pd.Period(a) <= c <= pd.Period(b)]
            sub, w = ct.loc[idx, 1:12], size[idx]
            curve = sub.mul(w, axis=0).sum() / sub.notna().mul(w, axis=0).sum()
            curve = curve[sub.notna().sum() == len(idx)]  # only ages every cohort in the group reached
            fig.add_scatter(x=curve.index, y=curve.values * 100, mode="lines+markers", name=name,
                            line=dict(color=colr, width=2), marker=dict(size=8),
                            hovertemplate=name + "<br>Month %{x}: %{y:.1f}%<extra></extra>")
        fig.update_yaxes(ticksuffix="%", rangemode="tozero")
        fig.update_xaxes(title="Months since first purchase", dtick=1)
        st.plotly_chart(style(fig, 360), width="stretch")
        st.markdown(f"Month-3 retention: **{M['m3_ret_h1_2010'].display()}** (2010 cohorts) → "
                    f"**{M['m3_ret_h1_2011'].display()}** (2011 cohorts), {M['m3_ret_change'].display()}.")
        st.markdown(f"**90-day repeat rate: {M['repeat_90d'].display()}**, using only the "
                    f"{M['repeat_90d_eligible'].display()} new customers with a full 90 days of history. "
                    f"Including recent customers would give {M['repeat_90d_naive'].display()}.")

    st.subheader("What drove growth: customers × orders per customer × order value")
    tree = R.drivers["driver_tree"]
    d1, d2, d3, d4 = st.columns(4)
    for col, key_, lab in [(d1, "revenue", "Identified-customer revenue"), (d2, "customers", "Active customers"),
                           (d3, "orders_per_customer", "Orders per customer"), (d4, "aov", "Average order value")]:
        col.metric(lab, M[f"{key_}_p1"].display(), f"{M[f'{key_}_growth'].value:+.1%} vs P0")
    st.caption("Revenue = customers × orders per customer × AOV holds exactly in both periods (see Audit). "
               f"Headline revenue grew {M['rev_growth'].display()} only because revenue with no customer ID "
               f"grew {M['anon_rev_growth'].display()}.")

    st.subheader("Price / volume / mix bridge, P0 → P1 (gross product sales)")
    br = R.drivers["pvm_bridge"]
    meas = ["absolute"] + ["relative"] * 5 + ["total"]
    fig = go.Figure(go.Waterfall(
        x=br["step"].str.replace(" products", "<br>products").str.replace(" gross product sales", "<br>sales"),
        y=br["value"] / 1e6, measure=meas,
        increasing=dict(marker_color=BLUE), decreasing=dict(marker_color=ORANGE),
        totals=dict(marker_color=GREY), connector=dict(line=dict(color=GRID)),
        text=[f"£{v/1e6:,.2f}M" if m != "relative" else f"{v/1e6:+,.2f}M" for v, m in zip(br["value"], meas)],
        textposition="outside", hovertemplate="%{x}<br>£%{y:,.2f}M<extra></extra>"))
    fig.update_yaxes(tickprefix="£", ticksuffix="M", tickformat=",.0f",
                     range=[0, br["value"].iloc[[0, -1]].max() / 1e6 * 1.35])
    st.plotly_chart(style(fig, 400, legend=False), width="stretch")
    st.caption(f"Continuing products lost volume; new products added {M['pvm_new'].display()} "
               f"({M['pvm_new_share_p1'].display()} of P1 sales). 'Price' is realised price per unit, so it "
               "also moves with customers' discount tiers.")

    st.subheader("Concentration and segments")
    e1, e2 = st.columns(2)
    with e1:
        cc = R.drivers["concentration"]["customer_curve"]
        cum = cc["revenue"].cumsum() / cc["revenue"].sum()
        x = (pd.Series(range(1, len(cc) + 1)) / len(cc)) * 100
        fig = go.Figure(go.Scatter(x=x, y=cum * 100, mode="lines", line=dict(color=BLUE, width=2),
                                   name="Customers", hovertemplate="Top %{x:.1f}% of customers: "
                                                                    "%{y:.1f}% of sales<extra></extra>"))
        fig.update_xaxes(title="% of customers (largest first)", ticksuffix="%")
        fig.update_yaxes(title="% of identified P1 sales", ticksuffix="%", range=[0, 100])
        fig.update_layout(title="Customer concentration")
        st.plotly_chart(style(fig, 340, legend=False), width="stretch")
        st.markdown(f"Top 1% of customers: **{M['top1pct_cust_share'].display()}** of sales · top 10%: "
                    f"**{M['top10pct_cust_share'].display()}** · largest customer: "
                    f"**{M['top_customer_share'].display()}**.")
    with e2:
        st.markdown("**Top products, P1**")
        tp = R.drivers["concentration"]["top_products"].copy()
        tp["revenue"] = tp["revenue"].map(lambda v: f"£{v:,.0f}")
        st.dataframe(tp.rename(columns={"stock_code": "Code", "description": "Product", "revenue": "P1 sales"}),
                     hide_index=True, width="stretch", height=400)
        st.markdown(f"Top 10 products: **{M['top10_sku_share'].display()}** of sales; "
                    f"{M['skus_for_80pct'].display()} of {M['sku_count_p1'].display()} products make 80%.")
    st.markdown(f"**Segments** (median order value ≥ £500 = large account): large accounts are "
                f"{M['large_rev_share_p1'].display()} of identified P1 revenue "
                f"({M['large_rev_growth'].display()} vs P0), small accounts {M['small_rev_share_p1'].display()} "
                f"({M['small_rev_growth'].display()}). UK is {M['uk_share_p1'].display()} of product sales.")

# ---------------------------------------------------------------- memo
with t_memo:
    memo_data = json.load(open(MEMO)) if MEMO.exists() else None
    if not is_sample:
        st.info("The memo is generated offline with an API key (`python -m firstlook.memo`), so the public "
                "app never calls the model. For an uploaded file, the analysis above is live; the memo is "
                "shown for the sample data only.")
    elif memo_data is None:
        st.warning("No memo generated yet. Run `python -m firstlook.memo` with ANTHROPIC_API_KEY set.")
    else:
        final = memo_data["final"]
        s = final["summary"]
        st.success(f"✅ {s['numbers_checked']} numbers checked against computed metrics · "
                   f"{s['verified']} claims verified · {s['blocked']} blocked and removed · "
                   f"{len(memo_data['attempts'])} generation attempt(s)")
        st.caption(f"Written by {memo_data['model']} from the computed metrics only (no raw data) on "
                   f"{memo_data['generated_at'][:10]}. Every number below was checked by code; hover a "
                   "claim's tag to see which metrics it cites.")
        st.header(final["memo"].get("title", "First-look memo"))
        for sec in final["memo"]["sections"]:
            if not sec["claims"]:
                continue
            st.subheader(sec["heading"])
            for c in sec["claims"]:
                tag = " · ".join(c["metric_ids"]) if c["metric_ids"] else "qualitative"
                st.markdown(f"- {c['text']} <span title='{tag}' style='color:{GREY};font-size:0.8em'>"
                            f"[{'✓ ' + str(len(c['metric_ids'])) + ' metric(s)' if c['metric_ids'] else 'no numbers'}]"
                            f"</span>", unsafe_allow_html=True)

# ---------------------------------------------------------------- audit
with t_audit:
    st.subheader("1 · Data checks")
    st.dataframe(pd.DataFrame([{"Status": f"{ICON[c.status]} {c.status}", "Check": c.name, "Detail": c.detail}
                               for c in R.checks]), hide_index=True, width="stretch")

    st.subheader("2 · Memo verification, claim by claim")
    memo_data = json.load(open(MEMO)) if MEMO.exists() else None
    if memo_data and is_sample:
        for i, att in enumerate(memo_data["attempts"], 1):
            st.markdown(f"**Attempt {i}:** {att['summary']['verified']} verified, "
                        f"{att['summary']['qualitative']} qualitative, {att['summary']['blocked']} blocked")
            st.dataframe(pd.DataFrame([{
                "Status": f"{ICON[c['status']]} {c['status']}", "Section": c["section"], "Claim": c["text"],
                "Cites": ", ".join(c["metric_ids"]), "Why blocked": "; ".join(c["errors"])}
                for c in att["claims"]]), hide_index=True, width="stretch")
    else:
        st.caption("Available once a memo has been generated for the sample data.")

    st.subheader("3 · Every computed metric")
    st.caption("The memo may only use these numbers. Each has an id the memo must cite.")
    st.dataframe(pd.DataFrame([{"id": m.id, "Metric": m.label, "Value": m.display(), "Section": m.section,
                                "Definition": m.definition} for m in M]),
                 hide_index=True, width="stretch", height=420)

    st.subheader("4 · How the verifier is tested")
    st.markdown("An eval set of 24 claims (`tests/memo_evals.py`) includes 11 deliberately wrong ones: an invented "
                "number, transposed digits, % written for percentage points, £M for £k, \"grew\" for a decline, "
                "a real number from an uncited metric, a metric that doesn't exist, and a wrong count. All must be "
                "blocked, and the correct ones must pass, for the test suite to pass.")
