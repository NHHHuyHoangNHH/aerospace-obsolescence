"""
engine/train.py
===================
Train XGBoost model — GCP only.

Input  : BigQuery  → aerospace_obs.parts
Output : BigQuery  → aerospace_obs.risk_scores
         GCS       → gs://{GCS_BUCKET}/models/model_v{version}.pkl
                      gs://{GCS_BUCKET}/models/model_latest.pkl

Env:
    GCP_PROJECT   = nhh0608
    GCS_BUCKET    = nhh0608-data
    BQ_DATASET    = aerospace_obs   (optional, default)

Chạy:
    export $(cat .env | xargs)
    python engine/train.py
    python engine/train.py --version 2
"""

import argparse
import json
import os
import pickle
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, mean_absolute_error, r2_score
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb
import tempfile, json
from google.cloud.bigquery import LoadJobConfig, SourceFormat, WriteDisposition
from google.cloud import bigquery, storage

# ── GCP config ────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
ENV_PATH   = ROOT / ".env"
load_dotenv(ENV_PATH)
PROJECT    = os.environ["GCP_PROJECT"]
BUCKET     = os.environ["GCS_BUCKET"]
BQ_DATASET = os.environ.get("BQ_DATASET", "aerospace_obs")
# ─────────────────────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")


# ── Load data từ BigQuery ─────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    client = bigquery.Client(project=PROJECT)
    df = client.query(
        f"SELECT * FROM `{PROJECT}.{BQ_DATASET}.parts`"
    ).to_dataframe()
    log(f"Loaded {len(df):,} rows from BigQuery:{BQ_DATASET}.parts")
    return df


# ── Feature engineering ───────────────────────────────────────────────────────

def build_features(df: pd.DataFrame):
    fe = df.copy()
    current_year = datetime.now().year

    fe["part_age_years"]        = current_year - fe["manufacture_year"].clip(1970, current_year)
    fe["lead_time_norm"]        = fe["lead_time_days"] / 365.0
    fe["low_stock_flag"]        = (fe["stock_level"] < 20).astype(int)
    fe["no_alt_supplier_flag"]  = (fe["num_alternative_suppliers"] == 0).astype(int)
    fe["last_order_date"]       = pd.to_datetime(fe["last_order_date"], errors="coerce")
    fe["days_since_last_order"] = (pd.Timestamp("2024-12-31") - fe["last_order_date"]).dt.days.fillna(999)

    cat_cols = ["category", "supplier", "region", "aircraft_model",
                "criticality", "alternative_part_available"]
    encoders = {}
    for col in cat_cols:
        le = LabelEncoder()
        fe[col + "_enc"] = le.fit_transform(fe[col].fillna("Unknown"))
        encoders[col] = le

    feature_cols = [
        "part_age_years", "lead_time_days", 
        "lead_time_norm",
        "stock_level", "low_stock_flag", "unit_price_usd", "mtbf_hours",
        "num_alternative_suppliers", "no_alt_supplier_flag", "days_since_last_order",
        "category_enc", "supplier_enc", "region_enc",
        "aircraft_model_enc", "criticality_enc", "alternative_part_available_enc",
    ]

    X       = fe[feature_cols].fillna(0)
    y_label = fe["obsolescence_label"]
    y_score = fe["obsolescence_score"]

    log(f"Features: {len(feature_cols)} cols × {len(X):,} rows")
    log(f"Label distribution: {y_label.value_counts().to_dict()}")
    return X, y_label, y_score, feature_cols, encoders


# ── Train ─────────────────────────────────────────────────────────────────────

def train_classifier(X_train, y_train, X_val, y_val):
    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric="logloss", random_state=42, verbosity=0, n_jobs=32,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    y_prob = model.predict_proba(X_val)[:, 1]
    y_pred = model.predict(X_val)
    auc = roc_auc_score(y_val, y_prob)
    log(f"Classifier — AUC: {auc:.4f}")
    log(f"\n{classification_report(y_val, y_pred, target_names=['Active','Obsolete'])}")
    return model, auc


def train_regressor(X_train, y_train, X_val, y_val):
    model = xgb.XGBRegressor(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0, n_jobs=32,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    y_pred = model.predict(X_val).clip(0, 1)
    mae = mean_absolute_error(y_val, y_pred)
    r2  = r2_score(y_val, y_pred)
    log(f"Regressor  — MAE: {mae:.4f}  R²: {r2:.4f}")
    return model, mae


def get_top_features(model, feature_cols, top_n=5):
    ranked = sorted(zip(feature_cols, model.feature_importances_),
                    key=lambda x: x[1], reverse=True)[:top_n]
    return [{"feature": f, "importance": round(float(v), 4)} for f, v in ranked]


# ── Score all parts ───────────────────────────────────────────────────────────

def score_all_parts(df, X, classifier, regressor, feature_cols, version_str) -> list[dict]:
    probs     = classifier.predict_proba(X)[:, 1]
    scores    = regressor.predict(X).clip(0, 1)
    top_feats = get_top_features(classifier, feature_cols)
    now       = datetime.now(timezone.utc).isoformat()

    results = []
    for i, (_, row) in enumerate(df.iterrows()):
        score = float(scores[i])
        tier  = ("Critical" if score >= 0.75 else
                 "High"     if score >= 0.45 else
                 "Medium"   if score >= 0.25 else "Low")
        results.append({
            "part_id":       row["part_id"],
            "risk_score":    round(score, 4),
            "risk_label":    int(probs[i] >= 0.5),
            "risk_tier":     tier,
            "top_features":  json.dumps(top_feats),
            "model_version": version_str,
            "scored_at":     now,
        })
    return results


# ── Save risk scores → BigQuery ───────────────────────────────────────────────

def save_risk_scores(records: list[dict]):
    

    client    = bigquery.Client(project=PROJECT)
    table_ref = f"{PROJECT}.{BQ_DATASET}.risk_scores"

    # Ghi ra file JSONL tạm rồi load lên — tránh streaming buffer
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        for r in records:
            tmp.write(json.dumps(r, default=str) + "\n")
        tmp_path = tmp.name

    job_config = LoadJobConfig(
        source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )

    with open(tmp_path, "rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=job_config)
    job.result()  # chờ xong

    os.unlink(tmp_path)
    log(f"Saved {len(records):,} risk scores → BigQuery:risk_scores")


# ── Save model → GCS ──────────────────────────────────────────────────────────

def save_model(artifact: dict, version: str):
    bucket = storage.Client(project=PROJECT).bucket(BUCKET)

    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        pickle.dump(artifact, tmp)
        tmp_path = tmp.name

    for blob_name in [f"models/model_v{version}.pkl", "models/model_latest.pkl"]:
        bucket.blob(blob_name).upload_from_filename(tmp_path)
        log(f"Uploaded → gs://{BUCKET}/{blob_name}")

    os.unlink(tmp_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1", help="Model version string")
    args = parser.parse_args()
    version_str = f"v{args.version}"

    log("=" * 55)
    log("ML Engine — Train Obsolescence Risk Model")
    log(f"Project: {PROJECT}  |  Bucket: {BUCKET}  |  Version: {version_str}")
    log("=" * 55)

    df = load_data()

    log("\n[1/4] Building features...")
    X, y_label, y_score, feature_cols, encoders = build_features(df)
    X_train, X_val, yl_train, yl_val, ys_train, ys_val = train_test_split(
        X, y_label, y_score, test_size=0.2, random_state=42, stratify=y_label
    )
    log(f"Train: {len(X_train):,}  Val: {len(X_val):,}")

    log("\n[2/4] Training classifier...")
    classifier, auc = train_classifier(X_train, yl_train, X_val, yl_val)

    log("\n[3/4] Training regressor...")
    regressor, mae = train_regressor(X_train, ys_train, X_val, ys_val)

    log("\n[4/4] Scoring all parts...")
    records = score_all_parts(df, X, classifier, regressor, feature_cols, version_str)
    save_risk_scores(records)

    log("\nTop features:")
    for f in get_top_features(classifier, feature_cols):
        log(f"  {f['feature']:<35} {'█' * int(f['importance'] * 40)} {f['importance']:.4f}")

    tiers = {}
    for r in records:
        tiers[r["risk_tier"]] = tiers.get(r["risk_tier"], 0) + 1
    log("\nRisk tier distribution:")
    for tier in ["Critical", "High", "Medium", "Low"]:
        count = tiers.get(tier, 0)
        log(f"  {tier:<10} {count:>5} parts  ({count/len(records)*100:.1f}%)")

    save_model({
        "classifier":   classifier,
        "regressor":    regressor,
        "encoders":     encoders,
        "feature_cols": feature_cols,
        "metrics":      {"auc": round(auc, 4), "mae": round(mae, 4)},
        "version":      version_str,
        "trained_at":   datetime.now(timezone.utc).isoformat(),
    }, args.version)

    log("\n" + "=" * 55)
    log("✅ Done!")
    log(f"  AUC   : {auc:.4f}  |  MAE: {mae:.4f}  |  Parts: {len(records):,}")
    log(f"  Model : gs://{BUCKET}/models/model_v{args.version}.pkl")
    log("=" * 55)


if __name__ == "__main__":
    main()