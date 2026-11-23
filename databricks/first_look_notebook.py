# Databricks notebook source
# MAGIC %md
# MAGIC # First Look on Databricks
# MAGIC Runs the same pipeline as the repo on Databricks, writes **raw → clean → analysis** Delta tables,
# MAGIC and reproduces the cohort triangle in Spark SQL as a cross-check on the Python result.
# MAGIC
# MAGIC **Setup (Databricks Free Edition):**
# MAGIC 1. Workspace → Create → Git folder → paste the GitHub repo URL.
# MAGIC 2. Upload `data/raw/online_retail_ii.parquet` to a volume, or point `RAW_PATH` at the repo copy.
# MAGIC 3. Run all cells.

# COMMAND ----------

# MAGIC %pip install plotly anthropic

# COMMAND ----------

import os, sys
REPO = os.path.abspath(os.path.join(os.getcwd(), ".."))   # notebook runs from <repo>/databricks
sys.path.insert(0, os.path.join(REPO, "src"))
RAW_PATH = os.path.join(REPO, "data/raw/online_retail_ii.parquet")

from firstlook.pipeline import run
res = run(RAW_PATH, keep_lines=True)
for c in res.checks:
    print(f"[{c.status}] {c.name}: {c.detail}")

# COMMAND ----------

# MAGIC %md ## Write the three layers as Delta tables

# COMMAND ----------

import pandas as pd
from firstlook.load import load_raw


def spark_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Spark needs one type per column: nullable ints -> float, text/periods -> plain strings."""
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[c] = s
        elif str(s.dtype) in ("Int64", "Int32") or pd.api.types.is_float_dtype(s):
            out[c] = s.astype("float64")
        elif pd.api.types.is_integer_dtype(s):
            out[c] = s.astype("int64")
        else:
            out[c] = s.astype("string").fillna("").astype(str)
    return out


raw = load_raw(RAW_PATH)
spark.createDataFrame(spark_safe(raw)).write.mode("overwrite").saveAsTable("first_look_raw")

keep = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id",
        "country", "kind", "revenue", "month", "cohort", "age", "segment"]
spark.createDataFrame(spark_safe(res.lines[keep])).write.mode("overwrite").saveAsTable("first_look_lines")

spark.createDataFrame(spark_safe(res.waterfall)).write.mode("overwrite").saveAsTable("first_look_integrity")
print("Delta tables: first_look_raw, first_look_lines, first_look_integrity")

# COMMAND ----------

# MAGIC %md ## Cross-check: cohort retention in Spark SQL must match the Python triangle

# COMMAND ----------

sql = open(os.path.join(REPO, "databricks/cohort_retention.sql")).read().strip().rstrip(";")
spark_tri = spark.sql(sql).toPandas()
spark_tri["cohort_month"] = spark_tri["cohort_month"].astype(str).str[:7]

py_tri = res.cohorts["customer_triangle"]
mismatch = 0
for _, r in spark_tri.iterrows():
    py = py_tri.loc[r["cohort_month"], int(r["month_number"])]
    if abs(py - r["retention"]) > 1e-3:
        mismatch += 1
print(f"Compared {len(spark_tri)} cohort cells: {mismatch} mismatches")
assert mismatch == 0

# COMMAND ----------

display(spark.sql(sql))
