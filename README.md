# Aerospace Parts Obsolescence Risk System

AI/ML demo trên Google Cloud để phân tích **obsolescence risk** cho phụ tùng hàng không vũ trụ (aerospace parts), tạo early warning insights và retrieval bằng embeddings.

---

## Architecture

![System Architecture](media/architecture.png)

### Component phân loại theo batch / real-time

| Component | Mode | Trigger |
|---|---|---|
| `ingestion/main.py` | Batch | Thủ công khi có CSV mới |
| `crawler/crawler.py` | Batch | Cloud Run Job — Scheduler Chủ nhật 1:00 AM |
| `retrain_pipeline.py` | Batch | Cloud Run Job — trigger bởi API hoặc Scheduler |
| `engine/train.py` | Batch | Chạy bên trong retrain-job |
| `engine/embeddings.py` | Batch | Chạy bên trong retrain-job (sau train.py) |
| `NestJS API` | Real-time | HTTP request |
| `dashboard/app.py` | Real-time | Local Gradio UI |

---

## Repository Structure

```
aerospace-obsolescence/
├── ingestion/
│   ├── main.py                  # CSV → GCS + BigQuery (parts only)
│   └── generate_mock_data.py    # Tạo 5,000 rows mock data
├── crawler/
│   ├── crawler.py               # RSS crawl + GCS/BQ upload
│   ├── generate_articles.py     # Standalone article generator
│   ├── requirements.txt
│   └── Dockerfile               # Cloud Run Job: crawler-job
├── engine/
│   ├── train.py                 # XGBoost → GCS model + BQ risk_scores
│   ├── embeddings.py            # Bi-Encoder + Cross-Encoder → BQ part_evidence
│   ├── retrain_pipeline.py      # Wrapper: train.py → embeddings.py
│   └── Dockerfile               # Cloud Run Job: retrain-job
├── api/                         # NestJS API
│   ├── src/
│   │   ├── parts/               # /parts endpoints
│   │   ├── retrain/             # /retrain endpoints — trigger retrain-job
│   │   ├── db/                  # BigQuery service
│   │   └── common/guards/       # API key auth
│   └── Dockerfile
├── dashboard/
│   └── app.py                   # Gradio UI (5 tabs)
├── infra/
│   └── setup_gcp.sh
├── data/                        # Local only — gitignored
├── .env.example
├── .gitignore
└── README.md
```

---

## AI/ML Engine Architecture

### Obsolescence Risk Scoring (XGBoost)

**Input:** 16 features từ BigQuery `parts` table

| Feature | Ý nghĩa | Importance |
|---|---|---|
| `stock_level` | Tồn kho hiện tại | 0.25 |
| `num_alternative_suppliers` | Số nhà cung cấp thay thế | 0.21 |
| `low_stock_flag` | stock < 20 | 0.12 |
| `part_age_years` | Số năm kể từ manufacture_year | 0.11 |
| `alternative_part_available_enc` | Yes/Partial/No encoded | 0.09 |
| `lead_time_days` | Thời gian cung ứng (ngày) | 0.08 |
| `category_enc`, `supplier_enc`... | Label-encoded categoricals | ... |

**Output:**
- `risk_score` (0.0–1.0) từ XGBoost Regressor
- `risk_label` (0/1) từ XGBoost Classifier
- `risk_tier`: Critical (≥0.75) / High (≥0.45) / Medium (≥0.25) / Low

**Metrics:** AUC ~0.99 | MAE ~0.05

### Article Retrieval + Evidence Linking (2-stage)

**Stage 1 — Bi-Encoder** (`all-MiniLM-L6-v2`):
- Embed 1,100 articles → vector index lưu GCS
- Cosine similarity → top-50 candidates

**Stage 2 — Cross-Encoder Reranker** (`ms-marco-MiniLM-L-6-v2`):
- BERT đọc (query, document) cùng lúc → full cross-attention
- Rerank top-50 → top-5 articles chính xác nhất

**Retrieval vs Analysis:**
- Embeddings = **retrieval** (tìm articles liên quan)
- XGBoost = **analysis/prediction** (tính risk score)

---

## Schema Design

### BigQuery Tables

```sql
-- parts (ingest từ CSV)
part_id, part_name, category, aircraft_model, supplier, region,
manufacture_year, lead_time_days, stock_level, unit_price_usd,
last_order_date, lifecycle_status, criticality, mtbf_hours,
num_alternative_suppliers, alternative_part_available,
obsolescence_score, obsolescence_label, obsolescence_reason,
expected_obsolescence_date, ingested_at

-- articles (append từ crawler hàng tuần)
article_id, url, title, summary, full_text, topic,
source_domain, published_at, crawled_at, tags, word_count, ingested_at

-- risk_scores (overwrite mỗi lần retrain)
part_id, risk_score, risk_label, risk_tier,
top_features (JSON), model_version, scored_at

-- part_evidence (overwrite mỗi lần retrain)
part_id, risk_score, risk_tier, summary,
risk_factors (JSON), article_links (JSON), generated_at
```

### GCS Structure

```
gs://nhh0608-data/
├── raw/
│   ├── aerospace_parts_dataset.csv
│   └── crawled_YYYYMMDD_HHMMSS.jsonl   ← crawler job output
├── processed/
│   └── parts_normalized.jsonl
└── models/
    ├── model_v1.pkl
    ├── model_v2.pkl
    ├── model_latest.pkl                 ← luôn là version mới nhất
    └── article_index.pkl               ← Bi-Encoder vector index
```

---

## Setup & Deployment

### Prerequisites
- Python 3.10+, Node.js 20+, Docker
- Google Cloud SDK (`gcloud`)
- GCP Project với billing enabled

### 1. Clone & Config

```bash
git clone https://github.com/your-username/aerospace-obsolescence
cd aerospace-obsolescence
cp .env.example .env
# Điền GCP_PROJECT, GCS_BUCKET, BQ_DATASET
```

### 2. GCP Setup

```bash
gcloud auth login && gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
chmod +x infra/setup_gcp.sh && ./infra/setup_gcp.sh
```

### 3. Generate & Ingest Parts Data

```bash
pip install google-cloud-storage google-cloud-bigquery pandas python-dotenv

python ingestion/generate_mock_data.py
# copy CSV vào data/raw/

export $(cat .env | xargs)
python ingestion/main.py
```

### 4. Deploy Crawler Job

```bash
cd crawler
docker build -t asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/crawler:latest .
docker push asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/crawler:latest

gcloud run jobs create crawler-job \
  --image=asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/crawler:latest \
  --region=asia-southeast1 \
  --set-env-vars="GCP_PROJECT=PROJECT,GCS_BUCKET=BUCKET,BQ_DATASET=aerospace_obs"

# Chạy lần đầu để có articles
gcloud run jobs execute crawler-job --region=asia-southeast1
```

### 5. Deploy Retrain Job

```bash
cd engine
docker build -t asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/retrain:latest .
docker push asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/retrain:latest

gcloud run jobs create retrain-job \
  --image=asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/retrain:latest \
  --region=asia-southeast1 \
  --memory=2Gi \
  --set-env-vars="GCP_PROJECT=PROJECT,GCS_BUCKET=BUCKET,BQ_DATASET=aerospace_obs"

# Chạy lần đầu
gcloud run jobs execute retrain-job --region=asia-southeast1
```

### 6. Deploy NestJS API

```bash
cd api
npm install && npm run build

docker build -t asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/api:latest .
docker push asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/api:latest

gcloud run deploy aerospace-api \
  --image=asia-southeast1-docker.pkg.dev/PROJECT/aerospace-repo/api:latest \
  --platform=managed --region=asia-southeast1 --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT=PROJECT,GCS_BUCKET=BUCKET,BQ_DATASET=aerospace_obs,API_KEY=YOUR_KEY,GCP_REGION=asia-southeast1"
```

### 7. Setup Cloud Scheduler

```bash
# Crawler — Chủ nhật 1:00 AM
gcloud scheduler jobs create http crawler-weekly \
  --location=asia-southeast1 --schedule="0 1 * * 0" \
  --uri="https://asia-southeast1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/crawler-job:run" \
  --http-method=POST \
  --oauth-service-account-email=SA_EMAIL

# Retrain — Chủ nhật 2:00 AM (sau crawler)
gcloud scheduler jobs create http retrain-weekly \
  --location=asia-southeast1 --schedule="0 2 * * 0" \
  --uri="https://YOUR_RUN_URL/api/v1/retrain" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-API-Key=YOUR_KEY" \
  --message-body='{"reason":"scheduled_weekly"}'
```

### 8. Run Gradio Dashboard

```bash
pip install gradio requests
export API_KEY=YOUR_KEY
python dashboard/app.py
# Mở http://localhost:7860
```

---

## API Reference

Header bắt buộc: `X-API-Key: YOUR_KEY`

| Endpoint | Method | Mô tả |
|---|---|---|
| `/api/v1/parts/stats` | GET | Tổng quan hệ thống |
| `/api/v1/parts/early-warning` | GET | Top parts risk cao, filter tier/category/aircraft |
| `/api/v1/parts/:id/risk-score` | GET | Risk score + evidence + articles |
| `/api/v1/retrain` | POST | Trigger retrain-job (Cloud Run Job) |
| `/api/v1/retrain/status` | GET | Trạng thái + model history |

---

## Model Retraining Flow

```
Trigger → POST /api/v1/retrain
  │
  ▼
NestJS API trigger Cloud Run Job: retrain-job
  │
  ▼
retrain_pipeline.py
  ├── [1/2] train.py --version N
  │     ├── Load parts từ BigQuery
  │     ├── Train XGBoost (AUC ~0.99, MAE ~0.05)
  │     ├── Score 5,000 parts → BigQuery:risk_scores (WRITE_TRUNCATE)
  │     └── Upload model_vN.pkl + model_latest.pkl → GCS
  │
  └── [2/2] embeddings.py --top-n 50 --rebuild-index
        ├── Load articles từ BigQuery
        ├── Rebuild Bi-Encoder index → GCS
        ├── Cross-Encoder rerank top-50 parts
        └── Save evidence → BigQuery:part_evidence (WRITE_TRUNCATE)
```

**Rollback:**
```bash
gsutil cp gs://BUCKET/models/model_v1.pkl gs://BUCKET/models/model_latest.pkl
```

---

## Deployed Endpoints (Live)

- **API:** `https://aerospace-api-1034183854132.asia-southeast1.run.app`
- **Dashboard:** `python dashboard/app.py` → `http://localhost:7860`

---

## Assumptions & Limitations

**Assumptions:**
- Data synthetic với correlation có chủ đích giữa features và label
- Articles gồm RSS thật + synthetic fallback
- Retrain dùng `WRITE_TRUNCATE` — overwrite toàn bộ mỗi lần

**Limitations:**
- AUC ~0.99 do data synthetic; real data sẽ thấp hơn
- `part_evidence` chỉ cover top-50 parts, chưa toàn bộ 5,000
- Chưa có model evaluation gate trước khi promote version mới
- `is_retraining` flag trong API reset khi container restart

**Production improvements:**
- Vertex AI Training Job cho retrain (không bị timeout Cloud Run)
- Incremental embedding update thay vì rebuild toàn bộ
- Model evaluation gate (AUC threshold trước khi promote)
- Vertex AI Vector Search thay vì pkl trên GCS