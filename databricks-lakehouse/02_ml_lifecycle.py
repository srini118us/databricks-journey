# Databricks notebook source
# MAGIC %md
# MAGIC # Day 2: The ML lifecycle, end to end
# MAGIC
# MAGIC **What this is:** a normal interactive notebook. Run it cell by cell,
# MAGIC *after* the Day 1 medallion pipeline has completed a successful run, so
# MAGIC the silver and gold tables exist.
# MAGIC
# MAGIC ### The connected story
# MAGIC Day 1 built the medallion: bronze, silver, gold. Day 2 takes the silver
# MAGIC transactions, builds a customer feature table, trains a model, and takes
# MAGIC it through the full lifecycle. This is the real lakehouse shape: data
# MAGIC layer feeds feature layer feeds model feeds serving.
# MAGIC
# MAGIC ### Tiered by design
# MAGIC The notebook runs in four tiers. Tiers 1 and 2 work on any compute.
# MAGIC Tiers 3 and 4 touch features that may be gated on Free Edition; each is
# MAGIC wrapped so a tier limit is a noted outcome, not a blocked notebook.
# MAGIC - Tier 1: feature engineering
# MAGIC - Tier 2: train + MLflow tracking   (certain to work)
# MAGIC - Tier 3: register in Unity Catalog model registry  (attempt)
# MAGIC - Tier 4: Model Serving endpoint     (attempt)

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "lakehouse_day1"   # same schema Day 1 wrote into
MODEL_NAME = f"{CATALOG}.{SCHEMA}.customer_spend_tier"
print(f"Source schema: {CATALOG}.{SCHEMA}")
print(f"Model will register as: {MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tier 1: feature engineering
# MAGIC
# MAGIC Aggregate silver transactions to one row per customer. This customer
# MAGIC feature table is itself a gold-grade asset: it could equally have been
# MAGIC a gold table in the Day 1 pipeline. Where feature logic lives, pipeline
# MAGIC vs notebook, is an architecture choice; here it sits with the model for
# MAGIC teaching clarity.

# COMMAND ----------

from pyspark.sql.functions import countDistinct, count, sum as _sum, max as _max, datediff, current_date

silver_tx = spark.table(f"{CATALOG}.{SCHEMA}.silver_sales_transactions")

customer_features = (
    silver_tx.groupBy("customerID")
    .agg(
        _sum("total_price").alias("total_spend"),
        count("transactionID").alias("transaction_count"),
        countDistinct("product").alias("distinct_products"),
        _max("transaction_date").alias("last_purchase_date"),
    )
    .withColumn("days_since_last_purchase",
                datediff(current_date(), "last_purchase_date"))
    .drop("last_purchase_date")
)

display(customer_features)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Create the label
# MAGIC
# MAGIC Spend tier from total_spend terciles: 0 low, 1 mid, 2 high. This is the
# MAGIC classification target. Deriving the label from the data is a deliberate
# MAGIC step: in a real project the label comes from a business definition, and
# MAGIC where it is defined is itself a governance question.

# COMMAND ----------

import pyspark.sql.functions as F

q = customer_features.approxQuantile("total_spend", [0.33, 0.66], 0.01)
low_cut, high_cut = q[0], q[1]
print(f"Tercile cuts: low<={low_cut:.2f}, high>{high_cut:.2f}")

labeled = customer_features.withColumn(
    "spend_tier",
    F.when(F.col("total_spend") <= low_cut, 0)
     .when(F.col("total_spend") <= high_cut, 1)
     .otherwise(2)
)

# Persist the feature table as Delta. It becomes a reusable, governed asset.
labeled.write.mode("overwrite").saveAsTable(
    f"{CATALOG}.{SCHEMA}.customer_features")
print(f"Feature table saved: {CATALOG}.{SCHEMA}.customer_features")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tier 2: train, with MLflow tracking
# MAGIC
# MAGIC This tier works on any compute. Move to pandas for scikit-learn; the
# MAGIC customer table is small (one row per customer), so this is safe and
# MAGIC well inside Free Edition limits. Every run is logged to MLflow:
# MAGIC parameters, metrics, and the model artifact with a signature.

# COMMAND ----------

import mlflow
import mlflow.sklearn
from mlflow.models.signature import infer_signature
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

pdf = spark.table(f"{CATALOG}.{SCHEMA}.customer_features").toPandas()

FEATURES = ["transaction_count",
            "distinct_products", "days_since_last_purchase"]
X = pdf[FEATURES]
y = pdf["spend_tier"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y)

# COMMAND ----------

# MLflow 3 defaults the registry to Unity Catalog (databricks-uc). Set it
# explicitly so the notebook is unambiguous.
mlflow.set_registry_uri("databricks-uc")

# Train two configurations so the MLflow experiment UI has runs to compare.
# Comparing runs is the point of tracking: reproducibility and selection.
configs = [
    {"n_estimators": 50,  "max_depth": 4},
    {"n_estimators": 200, "max_depth": 8},
]

run_results = []
for cfg in configs:
    with mlflow.start_run(run_name=f"rf_{cfg['n_estimators']}_{cfg['max_depth']}") as run:
        model = RandomForestClassifier(random_state=42, **cfg)
        model.fit(X_train, y_train)

        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        f1 = f1_score(y_test, preds, average="weighted")

        mlflow.log_params(cfg)
        mlflow.log_metric("accuracy", acc)
        mlflow.log_metric("f1_weighted", f1)

        # A signature is REQUIRED for Unity Catalog registration.
        signature = infer_signature(X_train, model.predict(X_train))
        mlflow.sklearn.log_model(
            sk_model=model,
             artifact_path="model",
            signature=signature,
            input_example=X_train.iloc[:3],
        )

        run_results.append({"run_id": run.info.run_id, "accuracy": acc,
                             "f1": f1, "cfg": cfg})
        print(f"  {cfg} -> accuracy {acc:.3f}, f1 {f1:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC Open the Experiments tab in the left rail. Both runs appear with their
# MAGIC parameters and metrics, comparable on one screen. That comparability,
# MAGIC not the model itself, is what MLflow tracking buys: every result is
# MAGIC reproducible and selectable.

# COMMAND ----------

best = max(run_results, key=lambda r: r["f1"])
print(f"Best run: {best['run_id']}  f1={best['f1']:.3f}  cfg={best['cfg']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tier 3: register in the Unity Catalog model registry
# MAGIC
# MAGIC ATTEMPT. Registering to Unity Catalog for ML workloads may require a
# MAGIC Dedicated access-mode compute. On Free Edition serverless this can be
# MAGIC gated. If it errors, that is an expected tier limit: note it in the
# MAGIC runbook and do registration in the company workspace later. Tier 2
# MAGIC already delivered the core lesson.

# COMMAND ----------

try:
    registered = mlflow.register_model(
        model_uri=f"runs:/{best['run_id']}/model",
        name=MODEL_NAME,
    )
    print(f"Registered {MODEL_NAME} version {registered.version}")

    # Promotion is an alias, not a code change. Setting an alias is the
    # operational gate that marks a version as the one serving uses.
    from mlflow.tracking import MlflowClient
    client = MlflowClient()
    client.set_registered_model_alias(
        name=MODEL_NAME, alias="champion", version=registered.version)
    print(f"Alias 'champion' -> version {registered.version}")

except Exception as e:
    print("Model registration appears gated on this tier.")
    print("Expected possibility on Free Edition. Record in runbook.")
    print(f"Detail: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tier 4: Model Serving endpoint
# MAGIC
# MAGIC ATTEMPT. Serving turns the registered model into a REST endpoint.
# MAGIC Endpoint creation may be gated on Free Edition. If so, note it; the
# MAGIC architecture lesson stands either way.
# MAGIC
# MAGIC The serving step is best done in the UI: Serving in the left rail,
# MAGIC Create serving endpoint, choose the registered model and the champion
# MAGIC alias. The code below is the programmatic equivalent.

# COMMAND ----------

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput, ServedEntityInput)

    w = WorkspaceClient()
    endpoint_name = "customer-spend-tier-endpoint"

    w.serving_endpoints.create(
        name=endpoint_name,
        config=EndpointCoreConfigInput(
            served_entities=[
                ServedEntityInput(
                    entity_name=MODEL_NAME,
                    entity_version=registered.version,
                    scale_to_zero_enabled=True,
                    workload_size="Small",
                )
            ]
        ),
    )
    print(f"Serving endpoint '{endpoint_name}' creation started.")
    print("Check the Serving tab; it takes a few minutes to go Ready.")

except Exception as e:
    print("Model Serving appears gated on this tier, or registration above did not complete.")
    print("Expected possibility on Free Edition. Record in runbook.")
    print(f"Detail: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Architect summary for Day 2
# MAGIC
# MAGIC The lifecycle, not the model, is the lesson. Tracking makes every run
# MAGIC reproducible and comparable. The Unity Catalog registry governs and
# MAGIC versions the model and gives lineage back to the feature table and the
# MAGIC notebook. The alias is the promotion gate: moving a model to production
# MAGIC is an alias change, not a code change (the deploy-model vs deploy-code
# MAGIC distinction, covered in the runbook). Serving exposes it as a REST
# MAGIC endpoint. The next file, 03, wires a retraining job in Workflows so the
# MAGIC whole chain runs on a schedule rather than by hand.
