# Use Case 3 — Databricks SQL + Genie (Day 3)

**Purpose.** Serve the gold layer to business users two ways: a Databricks SQL
dashboard and a Genie natural-language space. Core lesson: Genie accuracy is a
**metadata** problem (table/column comments) before it is a model problem.

## Files

- `databricks-lakehouse/04_sql_and_genie.py` — Part A runs the dashboard tile
  queries on bakehouse gold; Part B adds table/column comments to
  `gold_daily_revenue` and `gold_revenue_by_state` to prepare a Genie space.
- `Bakehouse Sales Day 3.lvdash.json` — Databricks SQL dashboard, page "Revenue":
  time series of `SUM(daily_revenue)` and `SUM(transaction_count)` by
  `transaction_date` over `workspace.lakehouse_day1.gold_daily_revenue`.

## Outputs

- A saved SQL dashboard and a Genie space over the two gold tables.
- Experiment worth running: ask Genie a question before vs after adding comments —
  the accuracy difference is the lesson. ~5 tested example queries is the
  documented bar for a reliable Genie space.

## Notes

Genie Space creation can be gated on the trial tier. Runbook: `runbook_day3.md`
(in Downloads).
