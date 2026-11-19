# Databricks notebook source
# MAGIC %md
# MAGIC # Wanderbricks Exploration — Step 0
# MAGIC
# MAGIC **Purpose:** before building any ETL or agent, confirm the real tables and
# MAGIC column names in `samples.wanderbricks`. This is the "verify before you build"
# MAGIC habit from Day 1 — never write pipeline code against assumed column names.
# MAGIC
# MAGIC Run every cell top to bottom. Then share the output so the ETL can be built
# MAGIC against the real schema.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. List every table in the wanderbricks schema

# COMMAND ----------

spark.sql("SHOW TABLES IN samples.wanderbricks").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Inspect each table's columns and a few sample rows
# MAGIC
# MAGIC For each table: print the column names and types, then preview 5 rows.

# COMMAND ----------

# Tables seen in Discover. If SHOW TABLES above lists others, add them here.
tables = ["properties", "bookings", "payments", "destinations"]

for t in tables:
    full = f"samples.wanderbricks.{t}"
    print("=" * 70)
    print(f"TABLE: {full}")
    print("=" * 70)
    try:
        # column names and types
        print("\n--- COLUMNS ---")
        spark.sql(f"DESCRIBE {full}").show(truncate=False)
        # row count
        cnt = spark.sql(f"SELECT COUNT(*) AS n FROM {full}").collect()[0]["n"]
        print(f"\n--- ROW COUNT: {cnt} ---")
        # sample rows
        print("\n--- SAMPLE ROWS (5) ---")
        spark.sql(f"SELECT * FROM {full} LIMIT 5").show(truncate=True)
    except Exception as e:
        print(f"  Could not read {full}: {e}")
    print("\n")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Done
# MAGIC
# MAGIC Share the output of cells 1 and 2. With the real table and column names
# MAGIC confirmed, the next notebook will build:
# MAGIC  - a medallion ETL (bronze -> silver -> gold) on the wanderbricks data
# MAGIC  - gold analytics tables (bookings by destination, revenue trends, etc.)
# MAGIC  - a tool-calling agent whose tools query those gold tables
