# Databricks notebook source
# MAGIC %md
# MAGIC # Day 3: Databricks SQL and Genie
# MAGIC
# MAGIC **What this is:** a normal interactive notebook. Run it after Day 1's
# MAGIC pipeline has produced the gold tables.
# MAGIC
# MAGIC Day 3 has two halves:
# MAGIC - Part A: query the gold tables with Databricks SQL, the basis of a
# MAGIC   dashboard.
# MAGIC - Part B: prepare the gold tables for Genie by adding comments, then
# MAGIC   create the Genie space in the UI.
# MAGIC
# MAGIC Part B is the direct head start on the pending Text-to-SQL POC: Genie
# MAGIC is the Databricks-native natural-language path that POC compares against
# MAGIC the Joule path.

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "lakehouse_day1"
print(f"Working in {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part A: Databricks SQL on the gold tables
# MAGIC
# MAGIC These queries are what a SQL dashboard tile runs underneath. Run them
# MAGIC here first; then in the SQL Editor each becomes a dashboard
# MAGIC visualization. Databricks SQL uses the serverless SQL warehouse, a
# MAGIC compute type tuned for fast interactive queries, separate from the
# MAGIC notebook's compute.

# COMMAND ----------

# Revenue trend over time, a line-chart tile.
display(spark.sql(f"""
    SELECT transaction_date, daily_revenue, transaction_count
    FROM {CATALOG}.{SCHEMA}.gold_daily_revenue
    ORDER BY transaction_date
"""))

# COMMAND ----------

# Revenue by state, a bar-chart tile.
display(spark.sql(f"""
    SELECT state, state_revenue, transaction_count
    FROM {CATALOG}.{SCHEMA}.gold_revenue_by_state
    ORDER BY state_revenue DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC To build the dashboard: open SQL Editor in the left rail, paste a query
# MAGIC above, Run, then add a visualization and pick the chart type. Save each
# MAGIC as a dashboard tile. The dashboard reads gold only, never silver or
# MAGIC bronze: the serving layer exists so consumers never pay raw-data cost.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part B: prepare the gold tables for Genie
# MAGIC
# MAGIC Genie translates natural-language questions to SQL. Its accuracy
# MAGIC depends almost entirely on metadata: table comments, column comments,
# MAGIC and sample values. A table called `gold_revenue_by_state` with no
# MAGIC comments forces Genie to guess what `state_revenue` means. The same
# MAGIC table with comments lets it answer reliably.
# MAGIC
# MAGIC This is the core Day 3 lesson and the core POC lesson: natural-language
# MAGIC querying is a metadata problem before it is a model problem.

# COMMAND ----------

# Add a table-level comment.
spark.sql(f"""
    COMMENT ON TABLE {CATALOG}.{SCHEMA}.gold_daily_revenue IS
    'Daily sales revenue and transaction counts for the bakehouse business.
     One row per calendar date. Use for revenue trends over time.'
""")

# Add column-level comments.
for col, desc in [
    ("transaction_date", "The calendar date of the sales activity."),
    ("daily_revenue", "Total revenue in dollars for that date."),
    ("transaction_count", "Number of sales transactions on that date."),
]:
    spark.sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.gold_daily_revenue "
              f"ALTER COLUMN {col} COMMENT '{desc}'")

print("Comments added to gold_daily_revenue.")

# COMMAND ----------

spark.sql(f"""
    COMMENT ON TABLE {CATALOG}.{SCHEMA}.gold_revenue_by_state IS
    'Sales revenue aggregated by the customer home state.
     One row per state. Use for geographic revenue comparison.'
""")

for col, desc in [
    ("state", "The US state of the customer."),
    ("state_revenue", "Total revenue in dollars from customers in that state."),
    ("transaction_count", "Number of transactions from that state."),
]:
    spark.sql(f"ALTER TABLE {CATALOG}.{SCHEMA}.gold_revenue_by_state "
              f"ALTER COLUMN {col} COMMENT '{desc}'")

print("Comments added to gold_revenue_by_state.")

# COMMAND ----------

# Confirm the comments landed.
display(spark.sql(f"DESCRIBE TABLE EXTENDED {CATALOG}.{SCHEMA}.gold_daily_revenue"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the Genie space (UI)
# MAGIC
# MAGIC 1. Left rail: Genie Spaces, then New.
# MAGIC 2. Add the two gold tables as data assets:
# MAGIC    `workspace.lakehouse_day1.gold_daily_revenue` and
# MAGIC    `workspace.lakehouse_day1.gold_revenue_by_state`.
# MAGIC 3. Open the space and ask, in plain English:
# MAGIC    - "What was total revenue in May 2024?"
# MAGIC    - "Which state had the highest revenue?"
# MAGIC    - "Show revenue by date as a chart."
# MAGIC 4. For each answer, click to see the SQL Genie generated. That is the
# MAGIC    learning: watch the translation.
# MAGIC
# MAGIC ### The experiment that teaches the lesson
# MAGIC Ask a question before adding comments and after. With comments, Genie
# MAGIC resolves ambiguous terms reliably; without, it guesses. To tune further,
# MAGIC use Configure, then Instructions, to add example SQL and plain-text
# MAGIC business rules. Aim for around five tested example queries; that is the
# MAGIC documented bar for a reliable space.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Architect summary for Day 3
# MAGIC
# MAGIC Databricks SQL serves the gold layer to dashboards over a warehouse
# MAGIC tuned for interactive queries. Genie adds a natural-language layer on
# MAGIC the same governed tables, and its accuracy is a function of metadata
# MAGIC quality, not model magic. For the Text-to-SQL POC, the takeaway is that
# MAGIC the Databricks-native path (Genie) and the comparison path (Joule) both
# MAGIC depend on the same thing: well-annotated, governed tables underneath.
