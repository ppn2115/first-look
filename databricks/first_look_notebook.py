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
res = run(RAW_PATH)
for c in res.checks:
    print(f"[{c.status}] {c.name}: {c.detail}")

# COMMAND ----------

# MAGIC %md ## Write the three layers as Delta tables

# COMMAND ----------

from firstlook.load import load_raw
raw = load_raw(RAW_PATH)
spark.createDataFrame(raw.astype({"customer_id": "float"})).write.mode("overwrite").saveAsTable("first_look_raw")

lines = res.lines.copy()
for col in ["month", "cohort"]:
    lines[col] = lines[col].astype(str)
lines["customer_id"] = lines["customer_id"].astype("float")
lines["age"] = lines["age"].astype("float")
keep = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id",
        "country", "kind", "revenue", "month", "cohort", "age", "segment"]
spark.createDataFrame(lines[keep]).write.mode("overwrite").saveAsTable("first_look_lines")

spark.createDataFrame(res.waterfall).write.mode("overwrite").saveAsTable("first_look_integrity")
print("Delta tables: first_look_raw, first_look_lines, first_look_integrity")

# COMMAND ----------

# MAGIC %md ## Cross-check: cohort retention in Spark SQL must match the Python triangle

# COMMAND ----------

sql = open(os.path.join(REPO, "databricks/cohort_retention.sql")).read()
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
