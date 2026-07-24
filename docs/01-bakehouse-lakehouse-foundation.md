# Use Case 1 — Bakehouse Lakehouse Foundation (Day 1)

**Purpose.** Learn the lakehouse fundamentals: a declarative bronze -> silver ->
gold medallion pipeline with data-quality expectations, and Delta Sharing.

**Dataset.** `samples.bakehouse` (Databricks sample), schema `workspace.lakehouse_day1`.

## Files

- `databricks-lakehouse/00_setup 2026-05-24 00-49-11.py` — creates schema
  `workspace.lakehouse_day1`, confirms `samples.bakehouse` is reachable (run-once bootstrap).
- `New Pipeline 2026-05-23 21-03/transformations/my_transformation.sql` — the
  declarative Lakeflow/DLT pipeline source: bronze materialized views
  (`bronze_sales_transactions`, `bronze_sales_customers`), silver views with
  `CONSTRAINT ... EXPECT ... ON VIOLATION DROP ROW` quality checks, and gold views
  `gold_daily_revenue`, `gold_revenue_by_state`.
- `databricks-lakehouse/medallion_pipeline.py` / `medallion_pipeline_sql.sql` —
  Python and SQL forms of the same medallion pipeline (added from the Day 1 source).
- `databricks-lakehouse/01_explore_and_sharing.py` — Part A inspects the medallion
  output (bronze->silver row-count drop, gold tables, Delta time-travel & lineage);
  Part B demonstrates Delta Sharing consumer side and attempts the provider side
  (`CREATE SHARE day1_demo_share`, expected to be gated on Free Edition).

## Outputs

- Tables: `gold_daily_revenue`, `gold_revenue_by_state` (in `workspace.lakehouse_day1`).
- Concepts demonstrated: declarative vs imperative pipelines, data-quality
  expectations, Delta transaction log / time travel, automatic lineage, Delta Sharing.

## Runbook

The step-by-step Day 1 runbook (What / Where / How / Why) is `runbook_day1.md`
(currently in Downloads; can be moved into `docs/` if you want it in-repo).
