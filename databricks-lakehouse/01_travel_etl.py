# Databricks notebook source
# MAGIC %md
# MAGIC # Travel Booking Analytics — Notebook 1: the ETL
# MAGIC
# MAGIC **Use case:** build a medallion pipeline on the built-in `samples.wanderbricks`
# MAGIC travel-booking dataset, ending in gold analytics tables. Notebook 2 then puts
# MAGIC a tool-calling agent on top of these gold tables.
# MAGIC
# MAGIC **What this notebook does**
# MAGIC  - Bronze: ingest the four core wanderbricks tables as-is.
# MAGIC  - Silver: clean, join, and derive — one trustworthy row per booking,
# MAGIC    enriched with property and destination detail.
# MAGIC  - Gold: business-ready aggregates an analyst (or an agent) will query.
# MAGIC
# MAGIC Run top to bottom. Safe to re-run — every table uses CREATE OR REPLACE.
# MAGIC
# MAGIC **Architecture note:** this is the same medallion pattern as Day 1, on a new
# MAGIC and richer dataset. Bronze = raw landing, silver = cleaned & joined,
# MAGIC gold = business-ready. Consumers (the agent in Notebook 2) read gold only.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Setup — target location

# COMMAND ----------

CATALOG = "workspace"
SCHEMA  = "travel_analytics"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"USE {CATALOG}.{SCHEMA}")
print(f"Working in {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Bronze — ingest the raw wanderbricks tables
# MAGIC
# MAGIC Bronze is the raw landing zone: the source data copied in as-is, with an
# MAGIC ingestion timestamp. No cleaning yet. If anything downstream breaks, bronze
# MAGIC is the untouched copy to rebuild from.

# COMMAND ----------

bronze_sources = {
    "bronze_bookings":     "samples.wanderbricks.bookings",
    "bronze_properties":   "samples.wanderbricks.properties",
    "bronze_destinations": "samples.wanderbricks.destinations",
    "bronze_payments":     "samples.wanderbricks.payments",
}

for bronze_name, source in bronze_sources.items():
    spark.sql(f"""
        CREATE OR REPLACE TABLE {bronze_name} AS
        SELECT *, current_timestamp() AS _ingested_at
        FROM {source}
    """)
    cnt = spark.sql(f"SELECT COUNT(*) AS n FROM {bronze_name}").collect()[0]["n"]
    print(f"  {bronze_name:22s} <- {source:35s}  {cnt:>8,} rows")

print("\nBronze layer complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Silver — clean, join, and enrich
# MAGIC
# MAGIC Silver turns raw bronze into one trustworthy, enriched row per booking:
# MAGIC  - keep only valid bookings (a positive amount, check_out after check_in)
# MAGIC  - join each booking to its property, and the property to its destination
# MAGIC  - derive `nights` and a `booking_month`
# MAGIC
# MAGIC This is the "cleaned and joined" layer — detailed, but trustworthy.

# COMMAND ----------

spark.sql("""
    CREATE OR REPLACE TABLE silver_bookings AS
    SELECT
        b.booking_id,
        b.property_id,
        p.destination_id,
        p.title              AS property_title,
        p.property_type,
        d.destination,
        d.country,
        d.state_or_province,
        b.check_in,
        b.check_out,
        datediff(b.check_out, b.check_in) AS nights,
        b.guests_count,
        b.total_amount,
        b.status,
        date_trunc('month', b.check_in)   AS booking_month
    FROM bronze_bookings b
    JOIN bronze_properties  p ON b.property_id    = p.property_id
    JOIN bronze_destinations d ON p.destination_id = d.destination_id
    WHERE b.total_amount > 0
      AND b.check_out > b.check_in
""")

s_cnt = spark.sql("SELECT COUNT(*) AS n FROM silver_bookings").collect()[0]["n"]
b_cnt = spark.sql("SELECT COUNT(*) AS n FROM bronze_bookings").collect()[0]["n"]
print(f"silver_bookings: {s_cnt:,} rows  (from {b_cnt:,} bronze bookings)")
print(f"  {b_cnt - s_cnt:,} rows dropped as invalid (non-positive amount or bad dates)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Gold — business-ready analytics tables
# MAGIC
# MAGIC Gold tables are the aggregated, business-ready outputs. Each one answers a
# MAGIC class of business question. The agent in Notebook 2 reads only these.

# COMMAND ----------

# Gold 1 — revenue and bookings by destination
spark.sql("""
    CREATE OR REPLACE TABLE gold_revenue_by_destination AS
    SELECT
        destination,
        country,
        COUNT(*)                       AS total_bookings,
        ROUND(SUM(total_amount), 2)    AS total_revenue,
        ROUND(AVG(total_amount), 2)    AS avg_booking_value,
        ROUND(AVG(nights), 1)          AS avg_nights
    FROM silver_bookings
    GROUP BY destination, country
    ORDER BY total_revenue DESC
""")

# Gold 2 — revenue trend by month
spark.sql("""
    CREATE OR REPLACE TABLE gold_monthly_revenue AS
    SELECT
        booking_month,
        COUNT(*)                       AS total_bookings,
        ROUND(SUM(total_amount), 2)    AS total_revenue,
        ROUND(AVG(total_amount), 2)    AS avg_booking_value
    FROM silver_bookings
    GROUP BY booking_month
    ORDER BY booking_month
""")

# Gold 3 — revenue by property type
spark.sql("""
    CREATE OR REPLACE TABLE gold_revenue_by_property_type AS
    SELECT
        property_type,
        COUNT(*)                       AS total_bookings,
        ROUND(SUM(total_amount), 2)    AS total_revenue,
        ROUND(AVG(total_amount), 2)    AS avg_booking_value
    FROM silver_bookings
    GROUP BY property_type
    ORDER BY total_revenue DESC
""")

# Gold 4 — payment method breakdown (joins silver bookings to payments)
spark.sql("""
    CREATE OR REPLACE TABLE gold_payment_methods AS
    SELECT
        pay.payment_method,
        COUNT(*)                       AS payment_count,
        ROUND(SUM(pay.amount), 2)      AS total_paid
    FROM bronze_payments pay
    JOIN silver_bookings sb ON pay.booking_id = sb.booking_id
    WHERE pay.status = 'completed'
    GROUP BY pay.payment_method
    ORDER BY total_paid DESC
""")

print("Gold tables built:")
for t in ["gold_revenue_by_destination", "gold_monthly_revenue",
          "gold_revenue_by_property_type", "gold_payment_methods"]:
    n = spark.sql(f"SELECT COUNT(*) AS n FROM {t}").collect()[0]["n"]
    print(f"  {t:34s} {n:>6,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Preview the gold tables

# COMMAND ----------

print("TOP 10 DESTINATIONS BY REVENUE")
spark.sql("SELECT * FROM gold_revenue_by_destination LIMIT 10").show(truncate=False)

print("MONTHLY REVENUE TREND")
spark.sql("SELECT * FROM gold_monthly_revenue").show(truncate=False)

print("REVENUE BY PROPERTY TYPE")
spark.sql("SELECT * FROM gold_revenue_by_property_type").show(truncate=False)

print("PAYMENT METHODS")
spark.sql("SELECT * FROM gold_payment_methods").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Done
# MAGIC
# MAGIC The gold layer for the travel-analytics use case is built:
# MAGIC  - `gold_revenue_by_destination`
# MAGIC  - `gold_monthly_revenue`
# MAGIC  - `gold_revenue_by_property_type`
# MAGIC  - `gold_payment_methods`
# MAGIC
# MAGIC Notebook 2 builds a tool-calling agent whose tools query exactly these tables.
