# Use Case 4 — Travel Analytics: ETL + Tool-Calling Agent (+ Guardrails / MCP)

**Purpose.** Build a second medallion pipeline on a travel dataset, then put a
tool-calling LLM agent over its gold tables, and extend it with production
concepts (guardrails + MCP-shaped tools).

**Dataset.** `samples.wanderbricks` (properties, bookings, payments, destinations),
schema `workspace.travel_analytics`.

## Files

- `databricks-lakehouse/00_wanderbricks_explore.py` — schema/row-count/sample recon.
- `databricks-lakehouse/01_travel_etl.py` — bronze (4 raw) -> `silver_bookings`
  (cleaned/joined/enriched) -> gold tables `gold_revenue_by_destination`,
  `gold_monthly_revenue`, `gold_revenue_by_property_type`, `gold_payment_methods`.
- `databricks-lakehouse/02_travel_agent.py` — tool-calling agent over the gold
  tables using LLM endpoint `databricks-meta-llama-3-3-70b-instruct`; four Python
  tools (top_destinations, monthly_trend, revenue_by_property_type, payment_methods)
  plus a manual tool-selection/answer loop.
- `databricks-lakehouse/03_travel_agent_guardrails_mcp.py` — adds an in/out
  guardrails layer and rewrites the four tools in formal **MCP** shape
  (name/description/inputSchema manifest, `MCP_TOOLS`), hand-built since managed
  Gateway/MCP hosting is tier-gated.

## Dashboards

- `Top Destinations by Revenue.lvdash.json` — bar chart, top-10 destinations by
  `total_revenue` from `gold_revenue_by_destination`.
- `Travel Booking Analytics.lvdash.json` — line chart, monthly `total_revenue` /
  `total_bookings` from `gold_monthly_revenue`.

## Outputs

Four travel gold tables; a working tool-calling agent; an MCP-shaped, guardrailed
version of that agent; two dashboards.
