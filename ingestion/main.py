"""
ingestion/main.py
==================
Ingest historical CSV parts data lên Google Cloud.
- Upload raw CSV → GCS/raw/
- Normalize → GCS/processed/
- Load → BigQuery:parts

Articles được xử lý riêng bởi crawler/crawler.py (Cloud Run Job).

Yêu cầu:
    pip install google-cloud-storage google-cloud-bigquery python-dotenv

Chạy:
    python ingestion/main.py
"""

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery, storage
from google.cloud.bigquery import LoadJobConfig, SourceFormat, WriteDisposition

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data" / "raw"
CSV_FILE = DATA_DIR / "aerospace_parts_dataset.csv"

# ── GCP config ────────────────────────────────────────────────────────────────
PROJECT    = os.environ["GCP_PROJECT"]
BUCKET     = os.environ["GCS_BUCKET"]
BQ_DATASET = os.environ.get("BQ_DATASET", "aerospace_obs")
REGION     = os.environ.get("GCP_REGION", "asia-southeast1")
# ─────────────────────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")


# ── GCS ───────────────────────────────────────────────────────────────────────

def upload_to_gcs(local_path: Path, gcs_folder: str) -> str:
    client    = storage.Client(project=PROJECT)
    blob_name = f"{gcs_folder}/{local_path.name}"
    client.bucket(BUCKET).blob(blob_name).upload_from_filename(str(local_path))
    uri = f"gs://{BUCKET}/{blob_name}"
    log(f"  Uploaded → {uri}")
    return uri


def save_processed_to_gcs(data: list[dict], filename: str):
    client    = storage.Client(project=PROJECT)
    blob_name = f"processed/{filename}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        tmp_path = f.name

    client.bucket(BUCKET).blob(blob_name).upload_from_filename(tmp_path)
    os.unlink(tmp_path)
    log(f"  Uploaded → gs://{BUCKET}/{blob_name}")


# ── Normalize ─────────────────────────────────────────────────────────────────

def normalize_parts(csv_path: Path) -> list[dict]:
    rows = []
    now  = datetime.now(timezone.utc).isoformat()

    with open(csv_path, encoding="utf-8") as f:
        for raw in csv.DictReader(f):

            def to_int(v, default=0):
                try: return int(v)
                except: return default

            def to_float(v, default=0.0):
                try: return float(v)
                except: return default

            def to_date(v):
                v = (v or "").strip()
                if not v: return None
                try: return datetime.strptime(v, "%Y-%m-%d").strftime("%Y-%m-%d")
                except: return None

            row = {
                "part_id":                    raw.get("part_id", "").strip(),
                "part_name":                  raw.get("part_name", "").strip(),
                "category":                   raw.get("category", "").strip(),
                "aircraft_model":             raw.get("aircraft_model", "").strip(),
                "supplier":                   raw.get("supplier", "").strip(),
                "region":                     raw.get("region", "").strip(),
                "manufacture_year":           to_int(raw.get("manufacture_year")),
                "lead_time_days":             to_int(raw.get("lead_time_days")),
                "stock_level":                to_int(raw.get("stock_level")),
                "unit_price_usd":             to_float(raw.get("unit_price_usd")),
                "last_order_date":            to_date(raw.get("last_order_date")),
                "last_reviewed_date":         to_date(raw.get("last_reviewed_date")),
                "lifecycle_status":           raw.get("lifecycle_status", "Unknown").strip(),
                "criticality":                raw.get("criticality", "Medium").strip(),
                "mtbf_hours":                 to_int(raw.get("mtbf_hours")),
                "num_alternative_suppliers":  to_int(raw.get("num_alternative_suppliers")),
                "alternative_part_available": raw.get("alternative_part_available", "").strip(),
                "obsolescence_score":         to_float(raw.get("obsolescence_score")),
                "obsolescence_label":         to_int(raw.get("obsolescence_label")),
                "obsolescence_reason":        raw.get("obsolescence_reason", "").strip(),
                "expected_obsolescence_date": to_date(raw.get("expected_obsolescence_date")),
                "ingested_at":                now,
            }
            if row["part_id"]:
                rows.append(row)

    log(f"  Normalized {len(rows):,} parts")
    return rows


# ── BigQuery ──────────────────────────────────────────────────────────────────

PARTS_SCHEMA = [
    bigquery.SchemaField("part_id",                    "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("part_name",                  "STRING"),
    bigquery.SchemaField("category",                   "STRING"),
    bigquery.SchemaField("aircraft_model",             "STRING"),
    bigquery.SchemaField("supplier",                   "STRING"),
    bigquery.SchemaField("region",                     "STRING"),
    bigquery.SchemaField("manufacture_year",           "INTEGER"),
    bigquery.SchemaField("lead_time_days",             "INTEGER"),
    bigquery.SchemaField("stock_level",                "INTEGER"),
    bigquery.SchemaField("unit_price_usd",             "FLOAT"),
    bigquery.SchemaField("last_order_date",            "DATE"),
    bigquery.SchemaField("last_reviewed_date",         "DATE"),
    bigquery.SchemaField("lifecycle_status",           "STRING"),
    bigquery.SchemaField("criticality",                "STRING"),
    bigquery.SchemaField("mtbf_hours",                 "INTEGER"),
    bigquery.SchemaField("num_alternative_suppliers",  "INTEGER"),
    bigquery.SchemaField("alternative_part_available", "STRING"),
    bigquery.SchemaField("obsolescence_score",         "FLOAT"),
    bigquery.SchemaField("obsolescence_label",         "INTEGER"),
    bigquery.SchemaField("obsolescence_reason",        "STRING"),
    bigquery.SchemaField("expected_obsolescence_date", "DATE"),
    bigquery.SchemaField("ingested_at",                "TIMESTAMP"),
]

RISK_SCORES_SCHEMA = [
    bigquery.SchemaField("part_id",       "STRING", mode="REQUIRED"),
    bigquery.SchemaField("risk_score",    "FLOAT"),
    bigquery.SchemaField("risk_label",    "INTEGER"),
    bigquery.SchemaField("risk_tier",     "STRING"),
    bigquery.SchemaField("top_features",  "STRING"),
    bigquery.SchemaField("model_version", "STRING"),
    bigquery.SchemaField("scored_at",     "TIMESTAMP"),
]


def ensure_bq_tables(client: bigquery.Client):
    dataset_ref          = bigquery.Dataset(f"{PROJECT}.{BQ_DATASET}")
    dataset_ref.location = REGION
    client.create_dataset(dataset_ref, exists_ok=True)
    log(f"  Dataset ready: {BQ_DATASET}")

    for name, schema in [("parts", PARTS_SCHEMA), ("risk_scores", RISK_SCORES_SCHEMA)]:
        client.create_table(
            bigquery.Table(f"{PROJECT}.{BQ_DATASET}.{name}", schema=schema),
            exists_ok=True,
        )
        log(f"  Table ready: {name}")


def load_to_bq(client: bigquery.Client, table_name: str, rows: list[dict]):
    if not rows:
        return
    table_ref = f"{PROJECT}.{BQ_DATASET}.{table_name}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for row in rows:
            tmp.write(json.dumps(row, default=str) + "\n")
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        client.load_table_from_file(f, table_ref, job_config=LoadJobConfig(
            source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        )).result()

    os.unlink(tmp_path)
    log(f"  Loaded {len(rows):,} rows → BigQuery:{table_name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log("=" * 55)
    log("Ingestion — Aerospace Parts CSV → GCP")
    log(f"Project : {PROJECT}  |  Bucket: {BUCKET}  |  Dataset: {BQ_DATASET}")
    log("Articles → handled separately by crawler/crawler.py (Cloud Run Job)")
    log("=" * 55)

    if not CSV_FILE.exists():
        raise FileNotFoundError(
            f"\nKhông tìm thấy: {CSV_FILE}\n"
            f"Chạy: python ingestion/generate_mock_data.py\n"
            f"Rồi copy CSV vào: {DATA_DIR}/"
        )

    log("\n[1/4] Uploading raw CSV → GCS/raw/...")
    upload_to_gcs(CSV_FILE, "raw")

    log("\n[2/4] Normalizing parts...")
    parts = normalize_parts(CSV_FILE)

    log("\n[3/4] Uploading processed → GCS/processed/...")
    save_processed_to_gcs(parts, "parts_normalized.jsonl")

    log("\n[4/4] Loading into BigQuery...")
    bq_client = bigquery.Client(project=PROJECT)
    ensure_bq_tables(bq_client)
    load_to_bq(bq_client, "parts", parts)

    log("\n" + "=" * 55)
    log("✅ Done!")
    log(f"  Parts : {len(parts):,} rows → BigQuery:{BQ_DATASET}.parts")
    log(f"  Raw   : gs://{BUCKET}/raw/{CSV_FILE.name}")
    log(f"  Proc  : gs://{BUCKET}/processed/parts_normalized.jsonl")
    log("=" * 55)
    log("\nNext: python engine/train.py")


if __name__ == "__main__":
    main()