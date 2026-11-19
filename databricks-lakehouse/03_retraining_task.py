# Databricks notebook source
# MAGIC %md
# MAGIC # Day 2 continued: the retraining task
# MAGIC
# MAGIC **What this is:** a notebook designed to be run by a scheduled job,
# MAGIC not by hand. It is the same lifecycle as `02_ml_lifecycle.py`, condensed
# MAGIC into one unattended run: rebuild features, train, register a new version.
# MAGIC
# MAGIC ### How it becomes a job
# MAGIC Jobs & Pipelines, Create, Job. Add one task of type Notebook pointing at
# MAGIC this file. Set a schedule (for learning, a daily trigger is fine; you
# MAGIC can also just press Run now once). The job runs this notebook end to
# MAGIC end with no person watching.
# MAGIC
# MAGIC ### Why a job, not a notebook
# MAGIC A model goes stale as new data arrives. Retraining by hand does not
# MAGIC scale and is not auditable. A Workflow job makes retraining scheduled,
# MAGIC logged, and repeatable. Each run produces a new registered model
# MAGIC version, so the registry becomes a dated history of the model.
# MAGIC
# MAGIC ### The deploy-code idea, made concrete
# MAGIC This notebook IS the deploy-code pattern in miniature. The job promotes
# MAGIC *code* (this notebook) and the model is retrained inside the run, rather
# MAGIC than a pre-built artifact being copied in. The retrained model is
# MAGIC therefore provably built from current, governed data.

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "lakehouse_day1"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.customer_spend_tier"

import mlflow
mlflow.set_registry_uri("databricks-uc")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: rebuild the feature table
# MAGIC Same aggregation as the Day 2 notebook. In a scheduled run this picks
# MAGIC up whatever new transactions have landed in silver since last time.

# COMMAND ----------

from pyspark.sql.functions import (countDistinct, count, sum as _sum,
                                   max as _max, datediff, current_date)
import pyspark.sql.functions as F

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

q = customer_features.approxQuantile("total_spend", [0.33, 0.66], 0.01)
labeled = customer_features.withColumn(
    "spend_tier",
    F.when(F.col("total_spend") <= q[0], 0)
     .when(F.col("total_spend") <= q[1], 1)
     .otherwise(2)
)
labeled.write.mode("overwrite").saveAsTable(
    f"{CATALOG}.{SCHEMA}.customer_features")
print("Feature table rebuilt.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: train and log
# MAGIC One configuration here, not a comparison sweep. A scheduled retrain
# MAGIC produces one new candidate; configuration search belongs in
# MAGIC interactive development, not the unattended job.

# COMMAND ----------

from mlflow.models.signature import infer_signature
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

pdf = spark.table(f"{CATALOG}.{SCHEMA}.customer_features").toPandas()
FEATURES = ["total_spend", "transaction_count",
            "distinct_products", "days_since_last_purchase"]
X, y = pdf[FEATURES], pdf["spend_tier"]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y)

with mlflow.start_run(run_name="scheduled_retrain") as run:
    model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                   random_state=42)
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    f1 = f1_score(y_test, preds, average="weighted")

    mlflow.log_params({"n_estimators": 200, "max_depth": 8})
    mlflow.log_metric("accuracy", acc)
    mlflow.log_metric("f1_weighted", f1)

    signature = infer_signature(X_train, model.predict(X_train))
    mlflow.sklearn.log_model(
        sk_model=model, name="model",
        signature=signature, input_example=X_train.iloc[:3])
    run_id = run.info.run_id
    print(f"Retrain run {run_id}: accuracy {acc:.3f}, f1 {f1:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: register the new version
# MAGIC Attempt, with the same Free Edition caveat as the Day 2 notebook. A
# MAGIC real deploy-code pipeline would add a quality gate here: only move the
# MAGIC champion alias if the new f1 beats the current champion. That gate is
# MAGIC described in the runbook; kept simple here.

# COMMAND ----------

try:
    registered = mlflow.register_model(
        model_uri=f"runs:/{run_id}/model", name=MODEL_NAME)
    print(f"Registered {MODEL_NAME} version {registered.version}")
except Exception as e:
    print("Registration gated on this tier (expected on Free Edition).")
    print(f"Detail: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Done
# MAGIC When this notebook is the task in a Workflow job, every scheduled run
# MAGIC repeats Steps 1 to 3 unattended. The Runs tab of the job is the audit
# MAGIC trail: each run dated, its metrics visible, its model version recorded.

