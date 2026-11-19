# Databricks notebook source
# MAGIC %md
# MAGIC # Day 1, Step 0: Project setup
# MAGIC
# MAGIC Run this notebook once, interactively, before anything else.
# MAGIC It creates the schema that every Day 1 and Day 2 artifact writes into.
# MAGIC
# MAGIC **What this is:** a normal interactive notebook. Run cell by cell.
# MAGIC **Why separate from the pipeline:** the declarative pipeline cannot create
# MAGIC its own target schema, and pipeline source code is not run interactively.
# MAGIC Setup work belongs in a plain notebook like this one.

# COMMAND ----------

# MAGIC %md
# MAGIC ## The one line that changes per environment
# MAGIC
# MAGIC On personal Free Edition the catalog is `workspace`. On a company
# MAGIC workspace it may be a named catalog. Change CATALOG here and nowhere else

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "lakehouse_day1"

print(f"Target: {CATALOG}.{SCHEMA}")
# git sync test

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the schema
# MAGIC
# MAGIC IF NOT EXISTS makes this notebook safe to re-run. If schema creation
# MAGIC fails with a permission error on a governed workspace, skip this cell
# MAGIC and set SCHEMA = "default" above instead, then continue.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print(f"Schema {CATALOG}.{SCHEMA} is ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Confirm the source data is reachable
# MAGIC
# MAGIC Day 1 reads from the built-in `samples.bakehouse` schema. This cell
# MAGIC confirms it is visible before the pipeline depends on it.

# COMMAND ----------

display(spark.sql("SHOW TABLES IN samples.bakehouse"))

# COMMAND ----------

# MAGIC %md
# MAGIC Expected: a list including `sales_transactions`, `sales_customers`,
# MAGIC `sales_suppliers`, `sales_franchises`. If this errors, the `samples`
# MAGIC catalog is not attached; stop and re-check the Catalog explorer.

# COMMAND ----------

# Quick peek at the main fact table the pipeline will ingest.
display(spark.sql("SELECT * FROM samples.bakehouse.sales_transactions LIMIT 5"))
