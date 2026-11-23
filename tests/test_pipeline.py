"""Pipeline tests on a tiny hand-built file where the right answers are known."""
import pandas as pd
import pytest

from firstlook.config import Config
from firstlook.integrity import run_integrity, classify
from firstlook.load import load_raw
from firstlook.metrics import Registry
from firstlook.pipeline import run
from firstlook.cohorts import repeat_rate
from firstlook.prep import build_lines

CFG = Config(period_0=("2010-01", "2010-03"), period_1=("2010-04", "2010-06"))


def row(inv, code, qty, date, price, cust, sheet="S1"):
    return dict(Invoice=inv, StockCode=code, Description=code, Quantity=qty, InvoiceDate=date,
                Price=price, **{"Customer ID": cust}, Country="United Kingdom", sheet=sheet)


@pytest.fixture
def raw(tmp_path):
    rows = [
        row("1001", "10001", 10, "2010-01-05", 2.0, 1),     # cust 1 first order Jan  (£20)
        row("1002", "10002", 5, "2010-02-10", 4.0, 1),      # cust 1 repeat Feb (£20)
        row("1003", "10001", 4, "2010-01-20", 2.5, 2),      # cust 2 Jan only (£10)
        row("1004", "10003", 2, "2010-04-03", 10.0, 3),     # cust 3 Apr (£20), new product
        row("1004", "10003", 2, "2010-04-03", 10.0, 3),     # exact duplicate line
        row("C1005", "10001", -2, "2010-02-01", 2.0, 1),    # cancellation (−£4)
        row("1006", "POST", 1, "2010-02-01", 15.0, 1),      # postage
        row("1007", "10002", 3, "2010-05-01", 4.0, None),   # no customer id (£12)
        row("1008", "10001", 0, "2010-05-02", 0.0, 2),      # invalid
        row("A1009", "B", 1, "2010-05-03", -50.0, None),    # bad debt adjust
        row("1010", "10001", 6, "2010-06-30", 3.0, 1, sheet="S2"),
        row("1010", "10001", 6, "2010-06-30", 3.0, 1, sheet="S1"),   # same invoice in 2 sheets
    ]
    df = pd.DataFrame(rows)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    path = tmp_path / "t.xlsx"
    with pd.ExcelWriter(path) as w:
        for s, g in df.groupby("sheet"):
            g.drop(columns="sheet").to_excel(w, sheet_name=s, index=False)
    return load_raw(path)


def test_every_row_gets_exactly_one_bucket(raw):
    b = classify(raw, CFG)
    assert b.notna().all()
    assert b.value_counts().to_dict() == {
        "sale": 6, "sheet_overlap": 1, "duplicate_line": 1, "cancellation": 1,
        "non_product": 1, "invalid": 1, "bad_debt_adjust": 1}


def test_tie_out_passes_and_net_revenue_is_right(raw):
    reg = Registry()
    res = run_integrity(raw, reg, CFG)
    assert res.passed
    # sales 20+20+10+20+12+18 = 100, cancellation −4
    assert reg["gross_product_sales"].value == pytest.approx(100)
    assert reg["net_product_revenue"].value == pytest.approx(96)
    assert reg["overlap_revenue"].value == pytest.approx(18)


def test_tie_out_fails_if_a_row_goes_missing(raw, monkeypatch):
    import firstlook.integrity as integ
    real = integ.classify
    monkeypatch.setattr(integ, "classify", lambda r, c: real(r, c).where(r["row_id"] != 0, None))
    res = run_integrity(raw, Registry(), CFG)
    assert not res.passed


def test_repeat_rate_excludes_customers_without_full_window(raw):
    reg = Registry()
    res = run_integrity(raw, reg, CFG)
    lines, _ = build_lines(res.sales, res.cancellations, CFG)
    adj, naive, n_elig, n_all = repeat_rate(lines, 90, exclude_cohorts=[])
    # data ends 30 Jun; eligible = first purchase on/before 1 Apr → custs 1 and 2; cust 1 repeated
    assert n_elig == 2 and adj == pytest.approx(0.5)
    assert n_all == 3 and naive == pytest.approx(1 / 3)


def test_full_pipeline_on_real_sample_passes():
    import os
    p = "data/raw/online_retail_ii.parquet"
    if not os.path.exists(p):
        pytest.skip("sample data not present")
    r = run(p)
    assert r.passed
    assert abs(r.drivers["pvm_residual"]) < 0.01
