-- Day 1: Medallion pipeline source (SQL)
-- Pipeline source, run by the pipeline engine. Bronze, then silver, then gold.

-- BRONZE: raw landing, ingested as is with an ingestion timestamp.

CREATE OR REFRESH MATERIALIZED VIEW bronze_sales_transactions
  COMMENT "Raw sales transactions ingested as is from samples.bakehouse."
AS SELECT *, current_timestamp() AS _ingested_at
   FROM samples.bakehouse.sales_transactions;

CREATE OR REFRESH MATERIALIZED VIEW bronze_sales_customers
  COMMENT "Raw customer dimension ingested as is from samples.bakehouse."
AS SELECT *, current_timestamp() AS _ingested_at
   FROM samples.bakehouse.sales_customers;

-- SILVER: validated and typed. The CONSTRAINT EXPECT clauses are data
-- quality expectations; rows that fail are dropped and counted.

CREATE OR REFRESH MATERIALIZED VIEW silver_sales_transactions(
  CONSTRAINT valid_quantity       EXPECT (quantity > 0)                ON VIOLATION DROP ROW,
  CONSTRAINT valid_amount         EXPECT (total_price > 0)             ON VIOLATION DROP ROW,
  CONSTRAINT has_transaction_date EXPECT (transaction_date IS NOT NULL) ON VIOLATION DROP ROW
)
  COMMENT "Validated, typed sales transactions. Bad rows dropped and counted."
AS SELECT
     transactionID,
     customerID,
     product,
     CAST(quantity AS INT)      AS quantity,
     CAST(totalPrice AS DOUBLE) AS total_price,
     to_date(dateTime)          AS transaction_date
   FROM LIVE.bronze_sales_transactions;

CREATE OR REFRESH MATERIALIZED VIEW silver_sales_customers(
  CONSTRAINT has_customer_id EXPECT (customerID IS NOT NULL) ON VIOLATION DROP ROW
)
  COMMENT "Validated customer dimension."
AS SELECT customerID, first_name, last_name, city, state, country
   FROM LIVE.bronze_sales_customers;

-- GOLD: business-ready aggregates, the read-optimized serving layer.

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
