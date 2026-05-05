"""
Aerospace Obsolescence Crawler
================================
Crawl ~1000 articles từ RSS feeds + fallback synthetic articles.
Output: JSONL file → upload lên GCS + BigQuery (nếu có GCP env).

Chạy local:
    python crawler/crawler.py
    python crawler/crawler.py --limit 200   # test nhanh
    python crawler/crawler.py --out data/articles.jsonl

Chạy trên Cloud Run Job:
    GCP_PROJECT, GCS_BUCKET, BQ_DATASET được set qua env vars
"""

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── RSS sources ────────────────────────────────────────────────────────────────
RSS_SOURCES = [
    # Aviation / Aerospace
    {"url": "https://www.flightglobal.com/rss",                                                            "topic": "aviation"},
    {"url": "https://aviationweek.com/rss.xml",                                                            "topic": "aviation"},
    {"url": "https://www.aerosociety.com/news/feed/",                                                      "topic": "aviation"},
    {"url": "https://www.airport-technology.com/feed/",                                                    "topic": "aviation"},
    {"url": "https://www.aviationpros.com/rss/",                                                           "topic": "aviation"},
    {"url": "https://simpleflying.com/feed/",                                                              "topic": "aviation"},
    {"url": "https://theaviationist.com/feed/",                                                            "topic": "aviation"},
    # Defense / Military
    {"url": "https://www.defensenews.com/arc/outboundfeeds/rss/",                                          "topic": "defense"},
    {"url": "https://breakingdefense.com/feed/",                                                           "topic": "defense"},
    {"url": "https://www.defensedaily.com/feed",                                                           "topic": "defense"},
    {"url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/",                                             "topic": "defense"},
    {"url": "https://www.janes.com/feeds/news",                                                            "topic": "defense"},
    # Supply chain
    {"url": "https://www.supplychaindive.com/feeds/news/",                                                 "topic": "supply_chain"},
    {"url": "https://www.logisticsmgmt.com/rss/all",                                                       "topic": "supply_chain"},
    {"url": "https://www.supplychainbrain.com/rss",                                                        "topic": "supply_chain"},
    {"url": "https://www.inboundlogistics.com/cms/rss/",                                                   "topic": "supply_chain"},
    # Semiconductors / Electronics
    {"url": "https://www.eenewseurope.com/rss.xml",                                                        "topic": "semiconductors"},
    {"url": "https://www.electronicdesign.com/rss.xml",                                                    "topic": "semiconductors"},
    {"url": "https://www.eetimes.com/feed/",                                                               "topic": "semiconductors"},
    {"url": "https://semiengineering.com/feed/",                                                           "topic": "semiconductors"},
    {"url": "https://www.electronicspecifier.com/rss",                                                     "topic": "semiconductors"},
    # Regulations
    {"url": "https://www.federalregister.gov/documents/search.rss?conditions[term]=aerospace+obsolescence", "topic": "regulations"},
    {"url": "https://www.faa.gov/rss/news_update.xml",                                                     "topic": "regulations"},
    {"url": "https://www.easa.europa.eu/newsroom-and-events/news/rss.xml",                                 "topic": "regulations"},
    # Chemicals / Materials
    {"url": "https://www.chemistryworld.com/feeds/news",                                                   "topic": "chemicals"},
    {"url": "https://www.materials-today.com/rss/news",                                                    "topic": "chemicals"},
    # Market / General
    {"url": "https://feeds.reuters.com/reuters/businessNews",                                              "topic": "market"},
    {"url": "https://feeds.reuters.com/reuters/technologyNews",                                            "topic": "market"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",                                   "topic": "market"},
]

RELEVANCE_KEYWORDS = [
    "obsolescence", "obsolete", "end-of-life", "end of life", "eol",
    "discontinued", "phased out", "legacy component", "component shortage",
    "supply chain", "aerospace", "aviation", "defense", "military",
    "semiconductor", "chip shortage", "electronic component",
    "aircraft", "boeing", "airbus", "avionics", "spare parts",
    "procurement", "maintenance", "mil-spec", "rohs", "reach",
    "single source", "sole source", "lifecycle", "sustainment",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AerospaceObsolescenceCrawler/1.0; "
        "+https://github.com/example/aerospace-obsolescence)"
    )
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def clean_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def is_relevant(title: str, summary: str) -> bool:
    blob = (title + " " + summary).lower()
    return any(kw in blob for kw in RELEVANCE_KEYWORDS)


def fetch_full_text(url: str, timeout: int = 10) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["nav", "footer", "script", "style", "aside", "header"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.body
        if article:
            return re.sub(r"\s+", " ", article.get_text(separator=" ")).strip()[:5000]
    except Exception:
        pass
    return ""


def parse_date(entry) -> str:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1).replace("www.", "") if m else ""


def _extract_tags(text: str) -> list:
    text_lower = text.lower()
    tag_map = {
        "obsolescence":  ["obsolescence", "obsolete", "end-of-life", "discontinued"],
        "supply_chain":  ["supply chain", "shortage", "logistics", "procurement"],
        "semiconductors":["semiconductor", "chip", "electronic component", "integrated circuit"],
        "boeing":        ["boeing", "c-17", "globemaster", "737", "747", "787"],
        "regulations":   ["regulation", "faa", "easa", "mil-spec", "rohs", "reach", "itar"],
        "maintenance":   ["maintenance", "sustainment", "spare parts", "mro"],
        "military":      ["military", "defense", "air force", "navy", "army"],
    }
    return [tag for tag, kws in tag_map.items() if any(kw in text_lower for kw in kws)]


# ── Core crawl ─────────────────────────────────────────────────────────────────

def crawl_feed(source: dict, seen_ids: set, fetch_full: bool = False) -> list:
    url, topic = source["url"], source["topic"]
    articles = []
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        if feed.bozo and not feed.entries:
            log.warning("  ✗ Bad feed: %s", url)
            return []

        for entry in feed.entries:
            link = getattr(entry, "link", "") or ""
            if not link:
                continue
            aid = article_id(link)
            if aid in seen_ids:
                continue

            title   = clean_text(getattr(entry, "title", ""))
            summary = clean_text(getattr(entry, "summary", "") or getattr(entry, "description", ""))

            if not is_relevant(title, summary):
                continue

            full_text = ""
            if fetch_full:
                full_text = fetch_full_text(link)
                time.sleep(0.5)

            articles.append({
                "article_id":    aid,
                "url":           link,
                "title":         title,
                "summary":       summary,
                "full_text":     full_text,
                "topic":         topic,
                "source_feed":   url,
                "source_domain": _domain(link),
                "published_at":  parse_date(entry),
                "crawled_at":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tags":          json.dumps(_extract_tags(title + " " + summary)),
                "word_count":    len((summary + " " + full_text).split()),
            })
            seen_ids.add(aid)

        log.info("  ✓ %-55s  +%d articles", url[:55], len(articles))
    except Exception as e:
        log.warning("  ✗ Error (%s): %s", url[:50], e)

    return articles


# ── Synthetic fallback ─────────────────────────────────────────────────────────

SYNTHETIC_TEMPLATES = [
    {"title": "Semiconductor shortage continues to impact aerospace MRO operations",
     "summary": "Ongoing global semiconductor shortages are causing significant disruptions to aerospace maintenance, repair, and overhaul (MRO) operations. Legacy avionics components built on discontinued chip architectures are particularly vulnerable, with lead times extending beyond 18 months for some critical single-source parts.",
     "topic": "semiconductors", "tags": ["obsolescence", "semiconductors", "supply_chain"]},
    {"title": "Boeing C-17 Globemaster sustainment challenges as component lifecycle ends",
     "summary": "The U.S. Air Force faces growing sustainment challenges for the C-17 Globemaster III fleet as key components approach end-of-life. Multiple avionics systems and hydraulic components manufactured in the 1990s are now obsolete, with no direct replacement available from original suppliers.",
     "topic": "defense", "tags": ["obsolescence", "boeing", "military", "maintenance"]},
    {"title": "RoHS directive impact on aerospace electronic component availability",
     "summary": "The European Union's RoHS directive restricting hazardous substances continues to create challenges for aerospace manufacturers who rely on legacy components that cannot meet the updated environmental requirements. Tin whisker growth in lead-free solder remains a concern for high-reliability aerospace applications.",
     "topic": "regulations", "tags": ["regulations", "obsolescence", "semiconductors"]},
    {"title": "Supply chain disruptions drive aerospace parts obsolescence acceleration",
     "summary": "Geopolitical tensions and post-pandemic supply chain restructuring are accelerating parts obsolescence across the aerospace sector. Suppliers are consolidating product lines and discontinuing low-volume aerospace-grade components, forcing OEMs to qualify replacement parts or maintain costly last-time-buy inventory.",
     "topic": "supply_chain", "tags": ["supply_chain", "obsolescence"]},
    {"title": "FAA issues guidance on approved equivalent parts for legacy aircraft",
     "summary": "The Federal Aviation Administration has released updated guidance on the use of approved equivalent parts (AEPs) for legacy commercial aircraft whose original components have been discontinued. The guidance covers airworthiness approval processes and documentation requirements for operators seeking to maintain aging fleets.",
     "topic": "regulations", "tags": ["regulations", "aviation", "maintenance"]},
    {"title": "Military aviation faces growing DMSMS challenges across legacy fleets",
     "summary": "Diminishing Manufacturing Sources and Material Shortages (DMSMS) continue to pose significant operational readiness challenges for military aviation. Defense contractors report that up to 30% of components in some legacy platform Bills of Materials are currently at risk of obsolescence within the next five years.",
     "topic": "defense", "tags": ["obsolescence", "military", "supply_chain"]},
    {"title": "Counterfeit electronic parts remain threat in aerospace supply chain",
     "summary": "The proliferation of counterfeit electronic components continues to threaten aerospace supply chain integrity as original manufacturers discontinue production of legacy parts. Open market brokers offering obsolete components are a primary source of counterfeits, according to industry watchdogs.",
     "topic": "supply_chain", "tags": ["supply_chain", "semiconductors", "aviation"]},
    {"title": "Additive manufacturing offers path forward for obsolete aerospace parts",
     "summary": "Additive manufacturing (3D printing) is increasingly being adopted as a solution for producing obsolete aerospace parts where traditional suppliers have discontinued production. Both Boeing and Airbus have approved additive manufacturing for select non-structural components.",
     "topic": "aviation", "tags": ["aviation", "obsolescence", "maintenance"]},
    {"title": "EASA updates airworthiness requirements for aging aircraft components",
     "summary": "The European Union Aviation Safety Agency has published updated airworthiness requirements specifically addressing aging aircraft components and obsolescence management. The new regulations require operators to maintain active lifecycle monitoring programs.",
     "topic": "regulations", "tags": ["regulations", "aviation", "obsolescence"]},
    {"title": "Integrated circuit obsolescence threatens avionics modernization programs",
     "summary": "Military and commercial avionics modernization programs are facing significant cost overruns due to integrated circuit obsolescence. Many programs designed in the 2000s relied on ASICs that are no longer manufactured, requiring expensive redesign efforts or FPGA-based replacements.",
     "topic": "semiconductors", "tags": ["semiconductors", "obsolescence", "aviation", "military"]},
]


def generate_synthetic_articles(count: int, seen_ids: set) -> list:
    import random
    import datetime as dt_module
    random.seed(99)
    articles = []
    domains  = ["aviationweek.com", "defensenews.com", "flightglobal.com",
                "semiengineering.com", "supplychaindive.com", "janes.com",
                "easa.europa.eu", "faa.gov", "electronicdesign.com"]
    base_date = datetime(2022, 1, 1, tzinfo=timezone.utc)

    for i in range(count):
        tpl    = SYNTHETIC_TEMPLATES[i % len(SYNTHETIC_TEMPLATES)]
        suffix = f" — Report {i // len(SYNTHETIC_TEMPLATES) + 1}" if i >= len(SYNTHETIC_TEMPLATES) else ""
        url    = f"https://{random.choice(domains)}/articles/obs-{i:04d}"
        aid    = article_id(url)
        if aid in seen_ids:
            continue
        pub_date = (base_date.replace(tzinfo=None) + dt_module.timedelta(days=random.randint(0, 900)))
        pub_date = pub_date.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        articles.append({
            "article_id":    aid,
            "url":           url,
            "title":         tpl["title"] + suffix,
            "summary":       tpl["summary"],
            "full_text":     tpl["summary"],
            "topic":         tpl["topic"],
            "source_feed":   "synthetic",
            "source_domain": random.choice(domains),
            "published_at":  pub_date,
            "crawled_at":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tags":          json.dumps(tpl["tags"]),
            "word_count":    len(tpl["summary"].split()),
        })
        seen_ids.add(aid)

    return articles


# ── GCS + BigQuery upload ──────────────────────────────────────────────────────

def upload_to_gcs(articles: list, out_path: Path):
    from google.cloud import storage
    gcp_project = os.environ["GCP_PROJECT"]
    gcs_bucket  = os.environ["GCS_BUCKET"]

    client    = storage.Client(project=gcp_project)
    bucket    = client.bucket(gcs_bucket)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    blob_name = f"raw/crawled_{timestamp}.jsonl"
    bucket.blob(blob_name).upload_from_filename(str(out_path))
    log.info("Uploaded → gs://%s/%s", gcs_bucket, blob_name)


def load_to_bq(articles: list):
    from google.cloud import bigquery
    from google.cloud.bigquery import LoadJobConfig, SourceFormat, WriteDisposition

    gcp_project = os.environ["GCP_PROJECT"]
    bq_dataset  = os.environ.get("BQ_DATASET", "aerospace_obs")
    table_ref   = f"{gcp_project}.{bq_dataset}.articles"
    client      = bigquery.Client(project=gcp_project)

    # Dedup — chỉ insert article chưa có trong BQ
    try:
        existing_ids = {r.article_id for r in client.query(
            f"SELECT article_id FROM `{table_ref}`"
        ).result()}
        log.info("Existing articles in BQ: %d", len(existing_ids))
    except Exception:
        existing_ids = set()

    new_articles = [a for a in articles if a["article_id"] not in existing_ids]
    log.info("New articles to insert: %d", len(new_articles))

    if not new_articles:
        log.info("No new articles — skipping BQ insert")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for a in new_articles:
            tmp.write(json.dumps(a, ensure_ascii=False, default=str) + "\n")
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        client.load_table_from_file(f, table_ref, job_config=LoadJobConfig(
            source_format=SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=WriteDisposition.WRITE_APPEND,
            autodetect=True,
        )).result()

    os.unlink(tmp_path)
    log.info("Inserted %d new articles → BigQuery:%s.articles", len(new_articles), bq_dataset)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Aerospace Obsolescence Crawler")
    parser.add_argument("--out",       default="articles.jsonl", help="Output JSONL file")
    parser.add_argument("--limit",     type=int, default=1100,   help="Target article count")
    parser.add_argument("--full-text", action="store_true",      help="Fetch full page text (slower)")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen_ids:     set  = set()
    all_articles: list = []

    log.info("=== Starting crawl (target: %d articles) ===", args.limit)

    # 1. RSS crawl
    for i, source in enumerate(RSS_SOURCES, 1):
        if len(all_articles) >= args.limit:
            break
        log.info("[%d/%d] Crawling: %s", i, len(RSS_SOURCES), source["topic"])
        all_articles.extend(crawl_feed(source, seen_ids, fetch_full=args.full_text))
        time.sleep(0.3)

    rss_count = len(all_articles)
    log.info("RSS crawl done: %d articles", rss_count)

    # 2. Synthetic fallback nếu chưa đủ
    if len(all_articles) < args.limit:
        needed = args.limit - len(all_articles)
        log.info("Generating %d synthetic articles...", needed)
        all_articles.extend(generate_synthetic_articles(needed, seen_ids))

    # 3. Ghi ra JSONL local
    with open(out_path, "w", encoding="utf-8") as f:
        for art in all_articles:
            f.write(json.dumps(art, ensure_ascii=False) + "\n")
    log.info("Written %d articles → %s", len(all_articles), out_path)

    # 4. Upload GCS + BigQuery (chỉ khi có GCP env)
    if os.environ.get("GCP_PROJECT"):
        log.info("=== Uploading to GCP ===")
        upload_to_gcs(all_articles, out_path)
        load_to_bq(all_articles)
    else:
        log.info("GCP_PROJECT not set — local mode only")

    # 5. Stats
    log.info("=== Done ===")
    log.info("Total  : %d", len(all_articles))
    log.info("RSS    : %d", rss_count)
    log.info("Synth  : %d", len(all_articles) - rss_count)
    topic_counts: dict = {}
    for a in all_articles:
        topic_counts[a["topic"]] = topic_counts.get(a["topic"], 0) + 1
    for topic, cnt in sorted(topic_counts.items(), key=lambda x: -x[1]):
        log.info("  %-20s %d", topic, cnt)


if __name__ == "__main__":
    main()