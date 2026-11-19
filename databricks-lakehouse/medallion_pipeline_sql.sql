-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Day 1, Step 1 (SQL version): Medallion pipeline source
-- MAGIC
-- MAGIC This is the SQL counterpart to `medallion_pipeline.py`. Same medallion
-- MAGIC logic, same dataset graph, expressed in SQL instead of Python.
-- MAGIC
-- MAGIC **Same rules as the Python version:** this is pipeline source, not an
-- MAGIC interactive notebook. Attach it to an ETL pipeline and run it there.
-- MAGIC
-- MAGIC To run Python and SQL side by side as two separate pipelines, point
-- MAGIC this one at default schema `lakehouse_day1_sql` so the outputs of the
-- MAGIC two versions never collide. Running both is optional; the real value
-- MAGIC is reading the two files next to each other.
-- MAGIC
-- MAGIC ### Materialized view vs streaming table
-- MAGIC The bakehouse source is a static table, so each layer is a MATERIALIZED
-- MAGIC VIEW: it recomputes from its full source on each pipeline run. A
-- MAGIC STREAMING TABLE would process only new rows incrementally, used when
-- MAGIC the source is an append stream. Same declarative model, different
-- MAGIC refresh semantics. For a batch source, materialized view is correct.

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## BRONZE, raw landing
-- MAGIC Ingest as is, add an ingestion timestamp. Immutable, reprocessable.

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW bronze_sales_transactions
  COMMENT "Raw sales transactions ingested as is from samples.bakehouse."
AS SELECT *, current_timestamp() AS _ingested_at
   FROM samples.bakehouse.sales_transactions;

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW bronze_sales_customers
  COMMENT "Raw customer dimension ingested as is from samples.bakehouse."
AS SELECT *, current_timestamp() AS _ingested_at
   FROM samples.bakehouse.sales_customers;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## SILVER, cleaned and conformed
-- MAGIC The CONSTRAINT ... EXPECT ... ON VIOLATION DROP ROW clauses are the
-- MAGIC data quality expectations. They are the exact SQL equivalent of the
-- MAGIC Python `@dp.expect_or_drop` decorators: failing rows are dropped and
-- MAGIC counted, and the counts appear in the pipeline UI.

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW silver_sales_transactions(
  CONSTRAINT valid_quantity      EXPECT (quantity > 0)            ON VIOLATION DROP ROW,
  CONSTRAINT valid_amount        EXPECT (total_price > 0)         ON VIOLATION DROP ROW,
  CONSTRAINT has_transaction_date EXPECT (transaction_date IS NOT NULL) ON VIOLATION DROP ROW
)
  COMMENT "Validated, typed sales transactions. Bad rows dropped and counted."
AS SELECT
     transactionID,
     customerID,
     product,
     CAST(quantity AS INT)        AS quantity,
     CAST(totalPrice AS DOUBLE)   AS total_price,
     to_date(dateTime)            AS transaction_date
   FROM LIVE.bronze_sales_transactions;

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW silver_sales_customers(
  CONSTRAINT has_customer_id EXPECT (customerID IS NOT NULL) ON VIOLATION DROP ROW
)
  COMMENT "Validated customer dimension."
AS SELECT customerID, first_name, last_name, city, state, country
   FROM LIVE.bronze_sales_customers;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## GOLD, business-ready aggregates
-- MAGIC Read-optimized serving layer. Day 3 builds the SQL dashboard and the
-- MAGIC Genie space on these gold tables.

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW gold_daily_revenue
  COMMENT "Daily revenue and transaction counts. Serving layer for dashboards."
AS SELECT
     transaction_date,
     SUM(total_price)        AS daily_revenue,
     COUNT(transactionID)    AS transaction_count,
     year(transaction_date)  AS year,
     month(transaction_date) AS month
   FROM LIVE.silver_sales_transactions
   GROUP BY transaction_date;

-- COMMAND ----------

CREATE OR REFRESH MATERIALIZED VIEW gold_revenue_by_state
  COMMENT "Revenue by customer state. Joins transaction fact to customer dimension."
AS SELECT
     c.state,
     SUM(t.total_price)     AS state_revenue,
     COUNT(t.transactionID) AS transaction_count
   FROM LIVE.silver_sales_transactions t
   JOIN LIVE.silver_sales_customers c
     ON t.customerID = c.customerID
   GROUP BY c.state;
