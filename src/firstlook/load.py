"""Load a raw transaction file into a standard 'raw' table.

Raw = the file exactly as delivered, plus two lineage columns (source_sheet, row_id).
Nothing is dropped here; every decision about what to exclude happens in integrity.py
so it can be counted and audited.
"""
from pathlib import Path

import pandas as pd

COLUMN_MAP = {
    "Invoice": "invoice", "InvoiceNo": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price", "UnitPrice": "price",
    "Customer ID": "customer_id", "CustomerID": "customer_id",
    "Country": "country",
}
REQUIRED = ["invoice", "stock_code", "quantity", "invoice_date", "price", "customer_id", "country"]


def _standardize(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    df = df.rename(columns=COLUMN_MAP)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if "description" not in df.columns:
        df["description"] = ""
    out = pd.DataFrame({
        "invoice": df["invoice"].astype(str).str.strip(),
        "stock_code": df["stock_code"].astype(str).str.strip(),
        "description": df["description"].astype("string").fillna(""),
        "quantity": pd.to_numeric(df["quantity"]).astype("int64"),
        "invoice_date": pd.to_datetime(df["invoice_date"]),
        "price": pd.to_numeric(df["price"]).astype(float),
        "customer_id": pd.to_numeric(df["customer_id"], errors="coerce").astype("Int64"),
        "country": df["country"].astype(str).str.strip(),
    })
    out["source_sheet"] = sheet
    return out


def load_raw(path: str | Path) -> pd.DataFrame:
    """Read .xlsx (all sheets), .csv or .parquet into the standard raw schema."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        sheets = pd.read_excel(path, sheet_name=None,
                               dtype={"Invoice": str, "InvoiceNo": str, "StockCode": str})
        parts = [_standardize(d, name) for name, d in sheets.items()]
    elif suffix == ".csv":
        parts = [_standardize(pd.read_csv(path, dtype={"Invoice": str, "StockCode": str}), path.stem)]
    elif suffix == ".parquet":
        d = pd.read_parquet(path)
        if "source_sheet" in d.columns and "invoice" in d.columns:  # already standard
            parts = [d.drop(columns=["row_id"], errors="ignore")]
        else:
            parts = [_standardize(d, path.stem)]
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    raw = pd.concat(parts, ignore_index=True)
    raw.insert(0, "row_id", range(len(raw)))
    raw["line_revenue"] = raw["quantity"] * raw["price"]
    return raw
