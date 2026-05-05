#!/bin/bash
# =============================================================================
# setup_gcp.sh — Chạy 1 lần để setup toàn bộ GCP cho project
# Yêu cầu: đã cài gcloud và đã chạy `gcloud init`
#
# Cách dùng:
#   chmod +x setup_gcp.sh
#   ./setup_gcp.sh
# =============================================================================

set -e  # dừng nếu có lỗi

# ── Cấu hình — SỬA 2 dòng này theo project của bạn ───────────────────────────
PROJECT_ID="nhh0608"   # thay bằng Project ID thật của bạn
REGION="asia-southeast1"                      # Singapore — gần VN nhất
# ─────────────────────────────────────────────────────────────────────────────

BUCKET_NAME="${PROJECT_ID}-data"
BQ_DATASET="aerospace_obs"

echo ""
echo "=============================================="
echo "  GCP Setup — Aerospace Obsolescence Project"
echo "=============================================="
echo "  Project  : $PROJECT_ID"
echo "  Region   : $REGION"
echo "  Bucket   : gs://$BUCKET_NAME"
echo "  BQ       : $BQ_DATASET"
echo "=============================================="
echo ""

# 1) Set active project
echo "[1/6] Setting active project..."
gcloud config set project "$PROJECT_ID"

# 2) Enable các APIs cần thiết
echo "[2/6] Enabling required APIs (may take 1-2 min)..."
gcloud services enable \
  storage.googleapis.com \
  bigquery.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com

echo "      APIs enabled."

# 3) Tạo GCS bucket
echo "[3/6] Creating GCS bucket: gs://$BUCKET_NAME ..."
if gsutil ls -b "gs://$BUCKET_NAME" &>/dev/null; then
  echo "      Bucket already exists, skipping."
else
  gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://$BUCKET_NAME"
  echo "      Bucket created."
fi

# Tạo folder structure trong bucket (bằng cách tạo file placeholder)
echo "      Creating folder structure..."
echo "placeholder" | gsutil cp - "gs://$BUCKET_NAME/raw/.keep"
echo "placeholder" | gsutil cp - "gs://$BUCKET_NAME/processed/.keep"
echo "placeholder" | gsutil cp - "gs://$BUCKET_NAME/models/.keep"
echo "placeholder" | gsutil cp - "gs://$BUCKET_NAME/logs/.keep"
echo "      Folders: raw/ · processed/ · models/ · logs/"

# 4) Tạo BigQuery dataset
echo "[4/6] Creating BigQuery dataset: $BQ_DATASET ..."
if bq ls --project_id="$PROJECT_ID" "$BQ_DATASET" &>/dev/null; then
  echo "      Dataset already exists, skipping."
else
  bq --location="$REGION" mk \
    --dataset \
    --description="Aerospace parts obsolescence risk data" \
    "${PROJECT_ID}:${BQ_DATASET}"
  echo "      Dataset created."
fi

# 5) Tạo BigQuery tables từ schema
echo "[5/6] Creating BigQuery tables..."

# Table: parts
bq mk --force \
  --table \
  --description="Aerospace parts with risk scores" \
  "${PROJECT_ID}:${BQ_DATASET}.parts" \
  "part_id:STRING,\
part_name:STRING,\
category:STRING,\
aircraft_model:STRING,\
supplier:STRING,\
region:STRING,\
manufacture_year:INTEGER,\
lead_time_days:INTEGER,\
stock_level:INTEGER,\
unit_price_usd:FLOAT,\
last_order_date:DATE,\
last_reviewed_date:DATE,\
lifecycle_status:STRING,\
criticality:STRING,\
mtbf_hours:INTEGER,\
num_alternative_suppliers:INTEGER,\
alternative_part_available:STRING,\
obsolescence_score:FLOAT,\
obsolescence_label:INTEGER,\
obsolescence_reason:STRING,\
expected_obsolescence_date:DATE,\
ingested_at:TIMESTAMP"

echo "      Table 'parts' created."

# Table: articles
bq mk --force \
  --table \
  --description="Crawled articles about aerospace obsolescence" \
  "${PROJECT_ID}:${BQ_DATASET}.articles" \
  "article_id:STRING,\
url:STRING,\
title:STRING,\
summary:STRING,\
full_text:STRING,\
topic:STRING,\
source_feed:STRING,\
source_domain:STRING,\
published_at:TIMESTAMP,\
crawled_at:TIMESTAMP,\
tags:STRING,\
word_count:INTEGER,\
ingested_at:TIMESTAMP"

echo "      Table 'articles' created."

# Table: risk_scores (output của ML model)
bq mk --force \
  --table \
  --description="ML model risk score predictions" \
  "${PROJECT_ID}:${BQ_DATASET}.risk_scores" \
  "part_id:STRING,\
risk_score:FLOAT,\
risk_label:INTEGER,\
risk_tier:STRING,\
top_features:STRING,\
model_version:STRING,\
scored_at:TIMESTAMP"

echo "      Table 'risk_scores' created."

# 6) Tạo Artifact Registry repo (để push Docker images)
echo "[6/6] Creating Artifact Registry repository..."
if gcloud artifacts repositories describe aerospace-repo \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  echo "      Repository already exists, skipping."
else
  gcloud artifacts repositories create aerospace-repo \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker images for aerospace obsolescence services"
  echo "      Repository created."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Setup complete!"
echo "=============================================="
echo ""
echo "  GCS bucket   : gs://$BUCKET_NAME"
echo "  BQ dataset   : $PROJECT_ID:$BQ_DATASET"
echo "  BQ tables    : parts · articles · risk_scores"
echo "  Docker repo  : $REGION-docker.pkg.dev/$PROJECT_ID/aerospace-repo"
echo ""
echo "  Next step: chạy ingestion script để upload data"
echo "  python ingestion/main.py"
echo ""