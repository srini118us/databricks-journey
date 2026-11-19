# Databricks notebook source
# MAGIC %md
# MAGIC # Day 1, Step 2: Explore the results, and Delta Sharing
# MAGIC
# MAGIC **What this is:** a normal interactive notebook. Run it cell by cell
# MAGIC *after* the medallion pipeline has completed a successful run.
# MAGIC
# MAGIC Two parts:
# MAGIC - Part A inspects what the pipeline produced (lineage, quality, layers).
# MAGIC - Part B is the Delta Sharing block.

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "lakehouse_day1"
print(f"Reading from {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part A: inspect the medallion output

# COMMAND ----------

display(spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}"))

# COMMAND ----------

# MAGIC %md
# MAGIC The three layers, side by side. Note row counts shrink bronze to silver:
# MAGIC that drop is the data quality expectations doing their job.

# COMMAND ----------

for layer in ["bronze_sales_transactions", "silver_sales_transactions"]:
    cnt = spark.table(f"{CATALOG}.{SCHEMA}.{layer}").count()
    print(f"{layer}: {cnt:,} rows")

# COMMAND ----------

display(spark.table(f"{CATALOG}.{SCHEMA}.gold_daily_revenue").orderBy("transaction_date"))

# COMMAND ----------

from pyspark.sql.functions import col
display(spark.table(f"{CATALOG}.{SCHEMA}.gold_revenue_by_state").orderBy(col("state_revenue").desc()))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Delta Lake: time travel
# MAGIC
# MAGIC Every gold table is a Delta table with a transaction log. DESCRIBE
# MAGIC HISTORY shows every version. This is the audit and rollback property
# MAGIC that makes the medallion layers reprocessable rather than disposable.

# COMMAND ----------

display(spark.sql(f"DESCRIBE EXTENDED {CATALOG}.{SCHEMA}.gold_daily_revenue"))

# COMMAND ----------

# MAGIC %md
# MAGIC In the Catalog explorer, open gold_daily_revenue and click the Lineage
# MAGIC tab. The graph back to bronze and to samples.bakehouse was built by the
# MAGIC pipeline automatically. Nothing declared the lineage; it is a byproduct
# MAGIC of the declarative model. That is the architect takeaway for Part A.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part B: Delta Sharing
# MAGIC
# MAGIC Delta Sharing is the open protocol for sharing live data across
# MAGIC accounts without copying it. This matters well beyond Day 1: SAP
# MAGIC Business Data Cloud delivers SAP data into Databricks as a Delta Share.
# MAGIC The "Delta Shares received" node already in the Catalog tree is exactly
# MAGIC that pattern. Understanding consumer and provider sides now is what
# MAGIC makes the later SAP integration a thin swap, not new learning.

# COMMAND ----------

# MAGIC %md
# MAGIC ### B1: the consumer side (works on Free Edition)
# MAGIC
# MAGIC The workspace already has a received share named `samples`. Reading
# MAGIC from it is reading shared data hosted by another account. No copy was
# MAGIC made; this is the live shared table.

# COMMAND ----------

display(spark.sql("SHOW SCHEMAS IN samples"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### B2: the provider side (attempt; may be gated on Free Edition)
# MAGIC
# MAGIC Creating a share as a provider touches cross-account features and may
# MAGIC not complete on Free Edition. Attempt it. If it errors, that is an
# MAGIC expected tier limit, not a mistake: note it in the runbook and do the
# MAGIC hands-on provider flow later in the company workspace, where the real
# MAGIC SAP-to-BDC share lives anyway.

# COMMAND ----------

# Attempt: create a share and add one gold table to it.
try:
    spark.sql("CREATE SHARE IF NOT EXISTS day1_demo_share "
              "COMMENT 'Day 1 learning share'")
    spark.sql(f"ALTER SHARE day1_demo_share "
              f"ADD MATERIALIZED VIEW {CATALOG}.{SCHEMA}.gold_daily_revenue")
    print("Provider side works on this tier. Share created.")
    display(spark.sql("SHOW SHARES"))
except Exception as e:
    print("Provider-side sharing appears gated on this tier.")
    print("Expected on Free Edition. Record in runbook, do hands-on later.")
    print(f"Detail: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Architect summary for Day 1
# MAGIC
# MAGIC Built today: a declarative medallion pipeline (bronze immutable landing,
# MAGIC silver validated with measured quality expectations, gold serving
# MAGIC aggregates), with automatic Unity Catalog lineage, Delta time travel,
# MAGIC and the Delta Sharing consumer pattern that the eventual SAP BDC
# MAGIC integration will reuse directly.
