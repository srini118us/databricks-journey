# Use Case 8 — SAP Procurement / Vendor Multi-Agent + Evaluation + SAC Export

> **Published write-up:** [After You Ship the Agent, the Real Work Begins](https://medium.com/@nivasrini620/after-you-ship-the-agent-the-real-work-begins-a3bad4478131)

**Purpose.** Build vendor-performance gold with a **data-confidence guard**, expose
it to the **Vendor-Performance-Analyst** agent, wire up the supervisor over all
specialists, and hand-build a drift-monitoring evaluation harness. Then export
gold to SAP Analytics Cloud.

![SAP BDC to Databricks finance architecture](images/hero_swimlane.png)

## Files

- `01_procurement_gold.ipynb` — builds `workspace.default.gold_vendor_performance`
  (one row/vendor: OTIF, on-time, in-full, invoice-accuracy, rejection rate, cycle
  time, order value) from the SAP vendor-performance share, with full comments.
  Records a finding that the 10-digit SAP supplier master cannot join to the
  V001-V021 vendor feed, so no vendor-master table is built.
- `02_vendor_agent_tools.ipynb` — UC functions `get_vendor_performance(vendor_id)`
  (single-vendor deep dive, sets a `data_confidence = LOW` flag when < 30 PO lines)
  and `rank_vendors_by_metric(metric, top_n, worst_first)` (excludes < 30-line
  vendors so a one-order "100% on-time" cannot top the leaderboard).
- `03_evaluation_harness.ipynb` — probes the agent serving endpoints
  (`mas-*-endpoint` for cash_flow/vendor/supervisor), builds a governed golden test
  set `workspace.default.eval_golden_set` (8 cases G01-G08), code-based scorers
  (routing / correctness / responded, plus a governance low-confidence check), and
  a runner that appends every run to `workspace.default.eval_results` (the drift record).
- `04_sac_export.ipynb` — exports `gold_vendor_performance` and
  `gold_monthly_cashflow` as single-file CSVs to `/tmp/sac_export/...` for import
  into SAP Analytics Cloud.
- `agent_config_records.md` — the Agent Bricks agents captured as records (they are
  managed platform objects, not files): **SAP-Finance-Supervisor** + three
  sub-agents (**Cash-Flow-Analyst**, **Vendor-Performance-Analyst**,
  **Journal-Risk-Analyst**), their tools, backing gold tables, and system
  instructions including the "never present an anomaly as confirmed fraud" rule.

## Outputs

- Table `gold_vendor_performance`; UC functions `get_vendor_performance`,
  `rank_vendors_by_metric`; eval tables `eval_golden_set`, `eval_results`; SAC CSV export.

## The three things that make this more than a chatbot

1. **Governance that survives the hierarchy** — the < 30-line confidence guard is
   created in the gold layer, carried by the UC function, read by the specialist,
   and passed up through the supervisor to reach the user as an honest warning.
2. **A supervisor that synthesizes** — for a "finance overview" it consults both
   specialists and links worsening vendor delivery to the company codes whose cash
   conversion is slipping — an answer neither specialist could produce alone.
3. **Drift monitoring** — the hand-built harness scores the live agents on a
   governed golden set and accumulates results into `eval_results` over time.
