# Use Case 2 — ML Lifecycle (Day 2)

**Purpose.** Take one model through the full Databricks ML lifecycle: feature
table -> MLflow tracking -> Unity Catalog model registry -> Model Serving -> a
scheduled retraining job. The point is the lifecycle, not the model.

**Dataset.** Silver bakehouse transactions from Use Case 1 (`workspace.lakehouse_day1`).

## Files

- `databricks-lakehouse/02_ml_lifecycle.py` — builds `customer_features` (one row
  per customer: spend, tx count, distinct products, recency), derives a
  `spend_tier` (tercile) label, trains a **RandomForestClassifier** with MLflow
  tracking (logs accuracy / f1_weighted, sweeps configs), registers
  `workspace.lakehouse_day1.customer_spend_tier` in the UC registry with a
  `champion` alias, and attempts a Model Serving endpoint `customer-spend-tier-endpoint`.
- `databricks-lakehouse/03_retraining_task.py` — the unattended job version:
  rebuilds features, trains one RandomForest, registers a new model version.
  Designed to run as a scheduled Workflow job (deploy-code pattern).

## Outputs

- Feature table `customer_features`; registered model `customer_spend_tier`
  (with `champion` alias); serving endpoint `customer-spend-tier-endpoint` (if not gated).
- Concepts: MLflow experiments, model signatures, UC model registry + alias
  promotion gate, Model Serving, scheduled retraining, deploy-code vs deploy-model.

## Notes

UC model registration and Model Serving may require Dedicated compute and can be
gated on Free Edition; the architecture lesson stands and the hands-on moves to a
company workspace. Runbook: `runbook_day2.md` (in Downloads).
