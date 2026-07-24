# Databricks notebook source
# MAGIC %md
# MAGIC # Day 1, Step 1: Medallion pipeline source
# MAGIC
# MAGIC **IMPORTANT, read before running.** This file is *pipeline source*, not
# MAGIC a normal notebook. Do not run it cell by cell. It does nothing useful
# MAGIC interactively. It is attached to an ETL pipeline object and run by the
# MAGIC pipeline engine.
# MAGIC
# MAGIC ### How to run it
# MAGIC 1. Left rail: Jobs & Pipelines, then Create, then ETL pipeline.
# MAGIC 2. Point the pipeline source at this file.
# MAGIC 3. Set the pipeline default catalog to `workspace` and default schema
# MAGIC    to `lakehouse_day1` (the schema created by 00_setup).
# MAGIC 4. Click Start. The pipeline builds bronze, silver, gold as a DAG.
# MAGIC
# MAGIC ### The architect point
# MAGIC A declarative pipeline separates *what the data should be* from *how and
# MAGIC when it is computed*. Each function below declares a dataset. The engine
# MAGIC works out dependency order, runs them, tracks lineage, and enforces the
# MAGIC data quality expectations. That separation is the whole idea, and it is
# MAGIC why pipeline source is not interactive: there is no "now" to run a cell in.

# COMMAND ----------

# Current module (Lakeflow Spark Declarative Pipelines).
# Legacy tutorials use `import dlt`; that still works but is the old name.
from pyspark import pipelines as dp
from pyspark.sql.functions import col, to_date, year, month, current_timestamp

# COMMAND ----------

# MAGIC %md
# MAGIC ## BRONZE, raw landing
# MAGIC
# MAGIC Bronze ingests source data as is, with no cleaning. It is the immutable
# MAGIC landing zone: if a downstream layer has a bug, bronze can always be
# MAGIC reprocessed from. The only thing added is an ingestion timestamp for
# MAGIC auditability. System design note: bronze trades storage cost for
# MAGIC reprocessability and audit, a deliberate exchange.

# COMMAND ----------

@dp.table(
    name="bronze_sales_transactions",
    comment="Raw sales transactions ingested as is from samples.bakehouse."
)
def bronze_sales_transactions():
    return (
        spark.read.table("samples.bakehouse.sales_transactions")
        .withColumn("_ingested_at", current_timestamp())
    )

# COMMAND ----------

@dp.table(
    name="bronze_sales_customers",
    comment="Raw customer dimension ingested as is from samples.bakehouse."
)
def bronze_sales_customers():
    return (
        spark.read.table("samples.bakehouse.sales_customers")
        .withColumn("_ingested_at", current_timestamp())
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## SILVER, cleaned and conformed
# MAGIC
# MAGIC Silver applies validation and typing. The `@dp.expect_or_drop`
# MAGIC decorators are data quality expectations: rows failing them are dropped
# MAGIC and counted, and the count is visible in the pipeline UI. This is the
# MAGIC declarative answer to "where does data quality live": in the pipeline
# MAGIC definition, enforced and measured, not in scattered manual checks.
# MAGIC
# MAGIC SQL equivalent of an expectation, for comparison:
# MAGIC   CONSTRAINT valid_qty EXPECT (quantity > 0) ON VIOLATION DROP ROW

# COMMAND ----------

@dp.table(
    name="silver_sales_transactions",
    comment="Validated, typed sales transactions. Bad rows dropped and counted."
)
@dp.expect_or_drop("valid_quantity", "quantity > 0")
@dp.expect_or_drop("valid_amount", "totalPrice > 0")
@dp.expect_or_drop("has_transaction_date", "dateTime IS NOT NULL")
def silver_sales_transactions():
    return (
        spark.read.table("LIVE.bronze_sales_transactions")
        .withColumn("transaction_date", to_date(col("dateTime")))
        .select(
            "transactionID",
            "customerID",
            "product",
            col("quantity").cast("int").alias("quantity"),
            col("totalPrice").cast("double").alias("total_price"),
            "transaction_date",
        )
    )

# COMMAND ----------

@dp.table(
    name="silver_sales_customers",
    comment="Validated customer dimension."
)
@dp.expect_or_drop("has_customer_id", "customerID IS NOT NULL")
def silver_sales_customers():
    return (
        spark.read.table("LIVE.bronze_sales_customers")
        .select(
            "customerID",
            "first_name",
            "last_name",
            "city",
            "state",
            "country",
        )
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## GOLD, business-ready aggregates
# MAGIC
# MAGIC Gold is the read-optimized serving layer: shaped for consumption, joined
# MAGIC and aggregated so a dashboard or a Genie query does not pay the cost of
# MAGIC raw computation. Day 3 builds the SQL dashboard and the Genie space on
# MAGIC top of these gold tables.

# COMMAND ----------

@dp.table(
    name="gold_daily_revenue",
    comment="Daily revenue and transaction counts. Serving layer for dashboards."
)
def gold_daily_revenue():
    df = spark.read.table("LIVE.silver_sales_transactions")
    return (
        df.groupBy("transaction_date")
        .agg(
            {"total_price": "sum", "transactionID": "count"}
        )
        .withColumnRenamed("sum(total_price)", "daily_revenue")
        .withColumnRenamed("count(transactionID)", "transaction_count")
        .withColumn("year", year(col("transaction_date")))
        .withColumn("month", month(col("transaction_date")))
    )

# COMMAND ----------

@dp.table(
    name="gold_revenue_by_state",
    comment="Revenue by customer state. Joins the transaction fact to the customer dimension."
)
def gold_revenue_by_state():
    tx = spark.read.table("LIVE.silver_sales_transactions")
    cust = spark.read.table("LIVE.silver_sales_customers")
    return (
        tx.join(cust, on="customerID", how="inner")
        .groupBy("state")
        .agg({"total_price": "sum", "transactionID": "count"})
        .withColumnRenamed("sum(total_price)", "state_revenue")
        .withColumnRenamed("count(transactionID)", "transaction_count")
    )
