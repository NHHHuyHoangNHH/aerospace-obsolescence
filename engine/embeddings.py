"""
engine/embeddings.py  —  GCP version
============================================================
Pipeline 2 giai đoạn:
  Stage 1 — Bi-Encoder (MiniLM-L6-v2)  : embed articles → cosine similarity → top-50
  Stage 2 — Cross-Encoder (ms-marco)   : rerank → top-5

Input  : BigQuery aerospace_obs.articles + aerospace_obs.risk_scores
Output : BigQuery aerospace_obs.part_evidence
         GCS      gs://{BUCKET}/models/article_index.pkl

Env:
    GCP_PROJECT, GCS_BUCKET, BQ_DATASET

Chạy:
    export $(cat .env | xargs)
    python engine/embeddings.py
    python engine/embeddings.py --part-id BCA-00042
    python engine/embeddings.py --top-n 100 --rebuild-index
"""

import argparse
import json
import os
import pickle
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

import numpy as np
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import cosine_similarity as cos_sim
from google.cloud import bigquery, storage

# ── GCP config ────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
ENV_PATH   = ROOT / ".env"
load_dotenv(ENV_PATH)
PROJECT    = os.environ["GCP_PROJECT"]
BUCKET     = os.environ["GCS_BUCKET"]
BQ_DATASET = os.environ.get("BQ_DATASET", "aerospace_obs")

INDEX_GCS_PATH = "models/article_index.pkl"

# ── Models ────────────────────────────────────────────────────────────────────
BI_ENCODER_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RETRIEVAL_K = 50
RERANK_K    = 5
# ─────────────────────────────────────────────────────────────────────────────


def log(msg: str):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")


# ── GCS helpers ───────────────────────────────────────────────────────────────

def upload_index_to_gcs(index: dict):
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        pickle.dump(index, tmp)
        tmp_path = tmp.name
    storage.Client(project=PROJECT).bucket(BUCKET).blob(INDEX_GCS_PATH).upload_from_filename(tmp_path)
    os.unlink(tmp_path)
    log(f"Index uploaded → gs://{BUCKET}/{INDEX_GCS_PATH}")


def download_index_from_gcs() -> dict | None:
    try:
        blob = storage.Client(project=PROJECT).bucket(BUCKET).blob(INDEX_GCS_PATH)
        if not blob.exists():
            return None
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
            blob.download_to_filename(tmp.name)
            with open(tmp.name, "rb") as f:
                index = pickle.load(f)
        os.unlink(tmp.name)
        log(f"Index loaded from gs://{BUCKET}/{INDEX_GCS_PATH} — {len(index['meta'])} articles")
        return index
    except Exception as e:
        log(f"Could not load index from GCS: {e}")
        return None


# ── BigQuery helpers ──────────────────────────────────────────────────────────

def load_articles_from_bq() -> list[dict]:
    client = bigquery.Client(project=PROJECT)
    rows = list(client.query(
        f"SELECT article_id, url, title, summary, topic, tags, source_domain "
        f"FROM `{PROJECT}.{BQ_DATASET}.articles`"
    ).result())
    log(f"Loaded {len(rows)} articles from BigQuery")
    return [dict(r) for r in rows]


def load_parts_from_bq(part_id: str = None, top_n: int = 50) -> list[dict]:
    client = bigquery.Client(project=PROJECT)
    if part_id:
        query = f"""
            SELECT p.*, r.risk_score, r.risk_tier
            FROM `{PROJECT}.{BQ_DATASET}.parts` p
            LEFT JOIN `{PROJECT}.{BQ_DATASET}.risk_scores` r USING (part_id)
            WHERE p.part_id = '{part_id}'
        """
    else:
        query = f"""
            SELECT p.*, r.risk_score, r.risk_tier
            FROM `{PROJECT}.{BQ_DATASET}.parts` p
            LEFT JOIN `{PROJECT}.{BQ_DATASET}.risk_scores` r USING (part_id)
            ORDER BY r.risk_score DESC
            LIMIT {top_n}
        """
    rows = list(client.query(query).result())
    log(f"Loaded {len(rows)} parts from BigQuery")
    return [dict(r) for r in rows]


def save_evidence_to_bq(evidence_list: list[dict]):
    client    = bigquery.Client(project=PROJECT)
    table_ref = f"{PROJECT}.{BQ_DATASET}.part_evidence"

    # Tạo table nếu chưa có
    schema = [
        bigquery.SchemaField("part_id",       "STRING", mode="REQUIRED"),
        bigquery.SchemaField("risk_score",    "FLOAT"),
        bigquery.SchemaField("risk_tier",     "STRING"),
        bigquery.SchemaField("summary",       "STRING"),
        bigquery.SchemaField("risk_factors",  "STRING"),
        bigquery.SchemaField("article_links", "STRING"),
        bigquery.SchemaField("generated_at",  "TIMESTAMP"),
    ]
    client.create_table(bigquery.Table(table_ref, schema=schema), exists_ok=True)

    rows = [{
        "part_id":       ev["part_id"],
        "risk_score":    ev["risk_score"],
        "risk_tier":     ev["risk_tier"],
        "summary":       ev["summary"],
        "risk_factors":  json.dumps(ev["risk_factors"], ensure_ascii=False),
        "article_links": json.dumps(ev["article_evidence"], ensure_ascii=False),
        "generated_at":  ev["generated_at"],
    } for ev in evidence_list]

    # Load job để tránh streaming buffer issue
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for r in rows:
            tmp.write(json.dumps(r, default=str) + "\n")
        tmp_path = tmp.name

    from google.cloud.bigquery import LoadJobConfig, SourceFormat, WriteDisposition
    job_config = LoadJobConfig(
        source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    with open(tmp_path, "rb") as f:
        client.load_table_from_file(f, table_ref, job_config=job_config).result()
    os.unlink(tmp_path)
    log(f"Saved {len(rows)} evidence records → BigQuery:part_evidence")


# ── Models ────────────────────────────────────────────────────────────────────

def load_bi_encoder():
    from sentence_transformers import SentenceTransformer
    log(f"Loading Bi-Encoder: {BI_ENCODER_MODEL}")
    return SentenceTransformer(BI_ENCODER_MODEL)


def load_cross_encoder():
    from sentence_transformers.cross_encoder import CrossEncoder
    log(f"Loading Cross-Encoder: {CROSS_ENCODER_MODEL}")
    return CrossEncoder(CROSS_ENCODER_MODEL, max_length=512)


# ── Stage 1: Build index ──────────────────────────────────────────────────────

def build_index(bi_encoder) -> dict:
    articles = load_articles_from_bq()

    texts, meta = [], []
    for a in articles:
        texts.append(f"{a['title']}. {a.get('summary') or ''}")
        meta.append({
            "article_id":    a["article_id"],
            "url":           a.get("url", ""),
            "title":         a.get("title", ""),
            "summary":       (a.get("summary") or "")[:300],
            "topic":         a.get("topic", ""),
            "tags":          a.get("tags", "[]"),
            "source_domain": a.get("source_domain", ""),
        })

    log(f"Encoding {len(texts)} articles...")
    t0 = time.time()
    vectors = bi_encoder.encode(texts, batch_size=64, show_progress_bar=True, convert_to_numpy=True)
    vectors = normalize(vectors).astype(np.float32)
    log(f"  Done in {time.time()-t0:.1f}s — shape: {vectors.shape}")

    index = {
        "vectors":  vectors,
        "meta":     meta,
        "texts":    texts,
        "model":    BI_ENCODER_MODEL,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    upload_index_to_gcs(index)
    return index


def load_index(bi_encoder) -> dict:
    index = download_index_from_gcs()
    if index is None or "texts" not in index:
        log("Building new index...")
        return build_index(bi_encoder)
    return index


# ── Stage 2: Rerank ───────────────────────────────────────────────────────────

def rerank(cross_encoder, query_text: str, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    pairs  = [(query_text, c["_text"]) for c in candidates]
    scores = cross_encoder.predict(pairs, show_progress_bar=False)
    for i, c in enumerate(candidates):
        c["cross_score"] = float(scores[i])
    return sorted(candidates, key=lambda x: x["cross_score"], reverse=True)


def build_part_query(part: dict) -> str:
    parts = [
        part.get("part_name", ""), part.get("category", ""),
        part.get("supplier", ""), part.get("aircraft_model", ""),
        part.get("lifecycle_status", ""), part.get("obsolescence_reason", ""),
    ]
    if part.get("lifecycle_status") in ["End-of-Life", "Discontinued", "Obsolete", "Phased-Out"]:
        parts.append("obsolescence discontinued end of life component")
    if (part.get("lead_time_days") or 0) > 200:
        parts.append("supply chain disruption shortage long lead time")
    if (part.get("num_alternative_suppliers") or 5) == 0:
        parts.append("single source sole supplier no alternative")
    if part.get("category") in ["Avionics", "Electrical Systems", "Navigation", "Communication"]:
        parts.append("semiconductor chip electronic component ASIC FPGA")
    return " ".join(p for p in parts if p).strip()


def retrieve_and_rerank(part, index, bi_encoder, cross_encoder,
                        retrieval_k=RETRIEVAL_K, rerank_k=RERANK_K) -> list[dict]:
    query_text = build_part_query(part)
    q_vec = normalize(bi_encoder.encode([query_text], convert_to_numpy=True)).astype(np.float32)
    sims  = cos_sim(q_vec, index["vectors"])[0]
    top_idx = np.argsort(sims)[::-1][:retrieval_k * 2]

    candidates, seen = [], set()
    for idx in top_idx:
        m = index["meta"][idx]
        if m["title"] in seen:
            continue
        seen.add(m["title"])
        candidates.append({**m, "_text": index["texts"][idx],
                            "similarity_score": round(float(sims[idx]), 4)})
        if len(candidates) >= retrieval_k:
            break

    reranked = rerank(cross_encoder, query_text, candidates)
    results  = []
    for r in reranked[:rerank_k]:
        r.pop("_text", None)
        results.append(r)
    return results


# ── Evidence builder ──────────────────────────────────────────────────────────

LIFECYCLE_MSG = {
    "Obsolete":     "Part đã chính thức obsolete — không còn được sản xuất",
    "Discontinued": "Nhà sản xuất đã ngừng sản xuất hoàn toàn",
    "End-of-Life":  "Part đang trong giai đoạn cuối vòng đời",
    "Phased-Out":   "Part đang được thay thế dần bởi sản phẩm mới hơn",
}


def build_evidence(part: dict, articles: list[dict]) -> dict:
    risk_score = float(part.get("risk_score") or 0)
    risk_tier  = part.get("risk_tier", "Unknown")
    lifecycle  = part.get("lifecycle_status", "Unknown")
    age        = datetime.now().year - int(part.get("manufacture_year") or 2000)
    lead_time  = int(part.get("lead_time_days") or 0)
    stock      = int(part.get("stock_level") or 0)
    n_alt      = int(part.get("num_alternative_suppliers") or 0)
    alt_avail  = part.get("alternative_part_available", "Unknown")
    obs_reason = part.get("obsolescence_reason", "")

    factors = []
    if lifecycle in ["Obsolete", "Discontinued"]:
        factors.append({"factor": "lifecycle_status", "severity": "critical",
                        "message": LIFECYCLE_MSG.get(lifecycle, lifecycle)})
    elif lifecycle in ["End-of-Life", "Phased-Out"]:
        factors.append({"factor": "lifecycle_status", "severity": "high",
                        "message": LIFECYCLE_MSG.get(lifecycle, lifecycle)})
    if age > 20:
        factors.append({"factor": "component_age", "severity": "high",
                        "message": f"Part sản xuất {int(part.get('manufacture_year',2000))} ({age} năm trước)"})
    if lead_time > 200:
        factors.append({"factor": "lead_time", "severity": "high",
                        "message": f"Lead time {lead_time} ngày — nguy cơ supply chain gián đoạn"})
    if stock < 20:
        factors.append({"factor": "low_stock", "severity": "high" if stock < 5 else "medium",
                        "message": f"Tồn kho chỉ còn {stock} units"})
    if n_alt == 0:
        factors.append({"factor": "single_source", "severity": "critical",
                        "message": "Single-source: không có nhà cung cấp thay thế"})
    if alt_avail == "No":
        factors.append({"factor": "no_alternative_part", "severity": "critical",
                        "message": "Không có part thay thế tương đương"})
    if obs_reason:
        factors.append({"factor": "known_obsolescence_reason", "severity": "critical",
                        "message": f"Lý do đã xác nhận: {obs_reason}"})

    article_evidence = [{
        "article_id":       a["article_id"],
        "title":            a["title"],
        "url":              a["url"],
        "topic":            a["topic"],
        "source":           a["source_domain"],
        "similarity_score": a.get("similarity_score", 0),
        "cross_score":      a.get("cross_score", 0),
        "snippet":          a["summary"][:200] + "..." if len(a["summary"]) > 200 else a["summary"],
    } for a in articles]

    top = factors[0]["message"] if factors else "Nhiều yếu tố rủi ro"
    return {
        "part_id":          part["part_id"],
        "part_name":        part.get("part_name", ""),
        "risk_score":       risk_score,
        "risk_tier":        risk_tier,
        "lifecycle_status": lifecycle,
        "summary":          f"Part {part['part_id']} risk {risk_score:.2f} ({risk_tier}). {top}. {len(article_evidence)} articles liên quan.",
        "risk_factors":     factors,
        "article_evidence": article_evidence,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--part-id",       help="Demo 1 part cụ thể")
    parser.add_argument("--top-n",         type=int, default=50)
    parser.add_argument("--retrieval-k",   type=int, default=RETRIEVAL_K)
    parser.add_argument("--rerank-k",      type=int, default=RERANK_K)
    parser.add_argument("--rebuild-index", action="store_true")
    args = parser.parse_args()

    log("=" * 60)
    log("ML Engine — Bi-Encoder + Cross-Encoder [GCP]")
    log(f"Project: {PROJECT}  |  Bucket: {BUCKET}")
    log("=" * 60)

    bi_encoder    = load_bi_encoder()
    cross_encoder = load_cross_encoder()

    log("\n[1/3] Article index...")
    index = build_index(bi_encoder) if args.rebuild_index else load_index(bi_encoder)

    log("\n[2/3] Loading parts from BigQuery...")
    parts = load_parts_from_bq(args.part_id, args.top_n)

    log("\n[3/3] Retrieve + rerank articles per part...")
    evidence_list = []
    for i, part in enumerate(parts):
        risk_score = part.pop("risk_score", 0)
        risk_tier  = part.pop("risk_tier", "Unknown")
        part["risk_score"] = risk_score
        part["risk_tier"]  = risk_tier

        articles = retrieve_and_rerank(part, index, bi_encoder, cross_encoder,
                                       args.retrieval_k, args.rerank_k)
        ev = build_evidence(part, articles)
        evidence_list.append(ev)

        if i < 3 or args.part_id:
            print(f"\n{'─'*60}")
            print(f"  {ev['part_id']} — {ev['part_name']}")
            print(f"  Risk: {ev['risk_score']:.2f} [{ev['risk_tier']}]")
            print(f"  {ev['summary']}")
            for f in ev["risk_factors"][:3]:
                print(f"    [{f['severity'].upper()}] {f['message']}")
            for a in ev["article_evidence"][:3]:
                print(f"    [{a['similarity_score']:.3f}/{a['cross_score']:+.2f}] {a['title'][:55]}")

    save_evidence_to_bq(evidence_list)

    log("\n" + "=" * 60)
    log(f"✅ Done! {len(evidence_list)} evidence records → BigQuery:part_evidence")
    log(f"   Index → gs://{BUCKET}/{INDEX_GCS_PATH}")
    log("=" * 60)


if __name__ == "__main__":
    main()