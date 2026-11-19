# Databricks notebook source
# MAGIC %md
# MAGIC # Trip Planner — Step 0: Explore Destinations and Check Vector Search
# MAGIC
# MAGIC Before building the destination trip-planner agent, two things must be
# MAGIC confirmed:
# MAGIC
# MAGIC 1. **The full list of destinations** — the planner will be generic (works
# MAGIC    for any destination the user names), so it needs to know exactly which
# MAGIC    destinations and countries exist in the data.
# MAGIC 2. **Whether Vector Search is available** on Free Edition — this decides
# MAGIC    how the RAG (retrieval) part of the planner is built.
# MAGIC
# MAGIC Run every cell top to bottom and share the output.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. All destinations and their countries
# MAGIC
# MAGIC The planner accepts a city OR a country, so we need both columns.

# COMMAND ----------

dest = spark.sql("""
    SELECT destination_id, destination, country, state_or_province
    FROM samples.wanderbricks.destinations
    ORDER BY country, destination
""")
print(f"Total destinations: {dest.count()}\n")
dest.show(50, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Countries covered (and how many destinations each has)

# COMMAND ----------

spark.sql("""
    SELECT country, COUNT(*) AS destination_count,
           concat_ws(', ', collect_list(destination)) AS destinations
    FROM samples.wanderbricks.destinations
    GROUP BY country
    ORDER BY country
""").show(50, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. How many properties each destination has
# MAGIC
# MAGIC The planner recommends properties, so each destination needs some.

# COMMAND ----------

spark.sql("""
    SELECT d.destination, d.country, COUNT(p.property_id) AS property_count,
           ROUND(MIN(p.base_price), 0) AS min_price,
           ROUND(AVG(p.base_price), 0) AS avg_price,
           ROUND(MAX(p.base_price), 0) AS max_price
    FROM samples.wanderbricks.destinations d
    LEFT JOIN samples.wanderbricks.properties p
           ON d.destination_id = p.destination_id
    GROUP BY d.destination, d.country
    ORDER BY property_count DESC
""").show(50, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. A look at the destination description text (the RAG source)
# MAGIC
# MAGIC The 'description' column is the unstructured text the RAG tool will use.
# MAGIC Print one example so we can see what it contains.

# COMMAND ----------

row = spark.sql("""
    SELECT destination, country, description
    FROM samples.wanderbricks.destinations
    WHERE destination = 'Paris'
    LIMIT 1
""").collect()

if row:
    r = row[0]
    print(f"DESTINATION: {r['destination']} ({r['country']})")
    print("=" * 60)
    desc = r['description'] or ""
    print(f"Description length: {len(desc)} characters\n")
    print("First 1200 characters:\n")
    print(desc[:1200])
else:
    print("Paris not found — check the destination name in cell 1's output.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Is Vector Search available on this workspace?
# MAGIC
# MAGIC This is the key check. It does NOT create anything — it only tries to
# MAGIC import the client and list any existing endpoints. The outcome decides
# MAGIC the RAG approach:
# MAGIC  - If available  -> build RAG with managed Databricks Vector Search.
# MAGIC  - If not        -> build RAG with in-notebook embedding + similarity
# MAGIC                     search (the pattern still works, just not the
# MAGIC                     managed service).

# COMMAND ----------

VECTOR_SEARCH_OK = False
try:
    from databricks.vector_search.client import VectorSearchClient
    print("Step 1: databricks-vector-search package is importable.")
    try:
        vsc = VectorSearchClient(disable_notice=True)
        endpoints = vsc.list_endpoints()
        print("Step 2: VectorSearchClient created and list_endpoints() worked.")
        eps = endpoints.get("endpoints", []) if isinstance(endpoints, dict) else endpoints
        print(f"  Existing Vector Search endpoints: {len(eps)}")
        VECTOR_SEARCH_OK = True
        print("\nRESULT: Vector Search appears AVAILABLE.")
    except Exception as e:
        print(f"Step 2 FAILED: client created but the service call did not work:")
        print(f"  {type(e).__name__}: {e}")
        print("\nRESULT: Vector Search likely NOT available on this tier.")
except ImportError:
    print("databricks-vector-search package is not installed.")
    print("Attempting install...")
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "pip", "install",
                        "databricks-vector-search", "-q"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("Installed. Re-run this cell to test the service.")
    else:
        print(f"Install failed: {r.stderr[:300]}")
        print("\nRESULT: proceed with the in-notebook RAG fallback.")

print(f"\nVECTOR_SEARCH_OK = {VECTOR_SEARCH_OK}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Done
# MAGIC
# MAGIC Share the output. With the destination list confirmed and the Vector
# MAGIC Search question answered, the trip-planner agent can be built:
# MAGIC  - a destination-info tool (RAG over the description text)
# MAGIC  - a property-finder tool (queries the properties table)
# MAGIC  - a budget tool (nights x price vs the user's budget)
# MAGIC  - an agent that orchestrates them, generic across all destinations.
