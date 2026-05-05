"""
Enhanced Synthetic Article Generator
=====================================
Tạo 1100 articles đa dạng, realistic cho aerospace obsolescence.
Dùng khi RSS không accessible (sandbox / offline).

Output: articles.jsonl  (same schema as crawler.py)
"""

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(42)

# ── Building blocks ────────────────────────────────────────────────────────────

TOPICS = {
    "aviation":      0.15,
    "defense":       0.20,
    "supply_chain":  0.20,
    "semiconductors":0.20,
    "regulations":   0.15,
    "chemicals":     0.05,
    "market":        0.05,
}

SOURCES = {
    "aviation":       ["aviationweek.com", "flightglobal.com", "simpleflying.com", "theaviationist.com"],
    "defense":        ["defensenews.com", "breakingdefense.com", "janes.com", "c4isrnet.com"],
    "supply_chain":   ["supplychaindive.com", "logisticsmgmt.com", "supplychainbrain.com"],
    "semiconductors": ["semiengineering.com", "eetimes.com", "electronicdesign.com", "eenewseurope.com"],
    "regulations":    ["faa.gov", "easa.europa.eu", "federalregister.gov", "transportation.gov"],
    "chemicals":      ["chemistryworld.com", "materials-today.com", "chemengonline.com"],
    "market":         ["reuters.com", "bloomberg.com", "ft.com", "wsj.com"],
}

AIRCRAFT = [
    "Boeing C-17 Globemaster III", "Boeing 737 MAX", "Boeing 747-8",
    "Boeing 787 Dreamliner", "Boeing AH-64 Apache", "F/A-18 Super Hornet",
    "C-130J Super Hercules", "Airbus A320neo", "Airbus A380",
    "Lockheed Martin F-35", "Bell V-280 Valor", "Sikorsky UH-60 Black Hawk",
]

COMPONENTS = [
    "inertial navigation unit", "flight management computer", "hydraulic actuator",
    "power distribution unit", "avionics bus controller", "radar altimeter",
    "digital flight data recorder", "fuel quantity management system",
    "environmental control system", "landing gear actuator", "VHF transceiver",
    "satellite communication unit", "turbine blade assembly", "fuel control unit",
    "cockpit display unit", "traffic collision avoidance system",
    "engine control module", "brake control valve", "oxygen generation system",
    "anti-icing controller",
]

SUPPLIERS = [
    "Honeywell Aerospace", "Raytheon Technologies", "GE Aviation",
    "Parker Hannifin", "Safran Group", "BAE Systems", "L3 Technologies",
    "TransDigm Group", "Heico Corporation", "Moog Inc.",
    "Curtiss-Wright", "Kaman Aerospace", "Triumph Group", "Ducommun",
]

REASONS = [
    "the original manufacturer has discontinued production",
    "the component no longer meets updated MIL-SPEC requirements",
    "global semiconductor shortages have made sourcing impossible",
    "the sole supplier was acquired and the product line discontinued",
    "RoHS/REACH compliance requirements cannot be met with current materials",
    "the underlying silicon process node is no longer supported by fabs",
    "raw material supply has been disrupted due to geopolitical factors",
    "lead-free transition has changed solder compatibility",
    "ITAR reclassification has restricted export of the component",
    "market demand is insufficient to sustain continued production",
]

MITIGATIONS = [
    "last-time-buy inventory strategy",
    "reverse engineering and re-qualification of a replacement part",
    "FPGA-based redesign of the legacy ASIC",
    "additive manufacturing for non-structural components",
    "alternative supplier qualification under FAA/EASA approval",
    "form-fit-function replacement sourcing",
    "organic depot-level repair capability development",
    "commercial off-the-shelf (COTS) technology insertion",
]

REGULATIONS = [
    "FAA Advisory Circular AC 20-62E",
    "EASA Part 21 Subpart K",
    "MIL-STD-3018 (Parts Management)",
    "SAE JA1011 obsolescence management standard",
    "DoD Instruction 4140.01 supply chain risk management",
    "EU RoHS Directive 2011/65/EU",
    "REACH Regulation EC 1907/2006",
    "ITAR Part 121 munitions list controls",
    "AS9100 Rev D quality management requirements",
    "NATO STANAG 4174 materiel management",
]

# ── Title / summary templates ──────────────────────────────────────────────────

def make_article(idx: int, topic: str) -> dict:
    comp   = random.choice(COMPONENTS)
    ac     = random.choice(AIRCRAFT)
    supp   = random.choice(SUPPLIERS)
    reason = random.choice(REASONS)
    mitig  = random.choice(MITIGATIONS)
    reg    = random.choice(REGULATIONS)
    domain = random.choice(SOURCES[topic])
    url    = f"https://{domain}/article/{topic}-{idx:04d}"

    # ── Vary titles + summaries by topic ──────────────────────────────────────
    if topic == "aviation":
        title = random.choice([
            f"Aviation industry faces growing obsolescence risk for {comp} systems",
            f"{ac} operators report increased difficulty sourcing {comp}",
            f"Aging {comp} fleet creates MRO challenges for commercial aviation",
            f"OEM discontinues {comp} support, airlines seek alternatives",
            f"Airworthiness directive issued over {comp} obsolescence concern",
        ])
        summary = (
            f"Commercial aviation operators are experiencing significant challenges "
            f"sourcing {comp} for aging {ac} fleets as {reason}. "
            f"The situation is forcing maintenance organizations to evaluate {mitig} "
            f"as a viable path forward. Regulatory bodies have begun reviewing {reg} "
            f"to address the growing gap between airworthiness requirements and "
            f"component availability. Industry analysts estimate that without intervention, "
            f"operational disruptions could affect up to 15% of the affected fleet within 24 months."
        )
        tags = ["aviation", "obsolescence", "maintenance"]

    elif topic == "defense":
        title = random.choice([
            f"DMSMS alert issued for {comp} used in {ac} program",
            f"Pentagon report highlights {comp} obsolescence risk across legacy fleets",
            f"Defense sustainment program struggles with {comp} end-of-life",
            f"{ac} readiness threatened as {comp} supplier exits market",
            f"DoD working group addresses {comp} diminishing manufacturing sources",
        ])
        summary = (
            f"The Department of Defense has identified a critical Diminishing Manufacturing "
            f"Sources and Material Shortages (DMSMS) situation affecting the {comp} "
            f"used across multiple {ac} variants, as {reason}. "
            f"{supp}, the prime contractor, is evaluating {mitig} to sustain operational "
            f"readiness. The program office has invoked provisions under {reg} to expedite "
            f"the approval process for replacement components. Without resolution, "
            f"mission capable rates for affected platforms could decline significantly "
            f"within the next 18 months."
        )
        tags = ["obsolescence", "military", "supply_chain", "maintenance"]

    elif topic == "supply_chain":
        title = random.choice([
            f"Supply chain disruption accelerates {comp} obsolescence timeline",
            f"Single-source risk for {comp} exposes aerospace supply chain vulnerability",
            f"Geopolitical tensions drive {comp} shortage for aerospace sector",
            f"Broker market risks rise as {comp} enters obsolescence phase",
            f"Aerospace supply chain resilience review targets {comp} dependencies",
        ])
        summary = (
            f"A new industry analysis has highlighted critical supply chain vulnerabilities "
            f"surrounding the {comp}, a key component used across multiple aerospace platforms "
            f"including the {ac}. {reason.capitalize()}, creating a single-point-of-failure risk "
            f"for operators who have not yet implemented {mitig}. "
            f"The report recommends that procurement teams assess their exposure and establish "
            f"alternative sourcing strategies in alignment with {reg}. "
            f"Industry consultants warn that open-market broker sourcing carries elevated "
            f"counterfeit risk for this component category."
        )
        tags = ["supply_chain", "obsolescence"]

    elif topic == "semiconductors":
        title = random.choice([
            f"Legacy chip at heart of {comp} faces production discontinuation",
            f"Semiconductor foundry exits process node used in {comp} design",
            f"ASIC obsolescence forces redesign of {comp} for {ac}",
            f"Chip shortage delays {comp} replacement qualification by 18 months",
            f"FPGA migration planned for obsolete {comp} processor core",
        ])
        summary = (
            f"A critical semiconductor obsolescence event is affecting the {comp} "
            f"installed across {ac} variants operated by both military and commercial customers. "
            f"The underlying integrated circuit, manufactured by a subsidiary of {supp}, "
            f"is being discontinued because {reason}. "
            f"Engineers are evaluating {mitig} as the primary technical path forward, "
            f"though re-qualification under {reg} is expected to take 18-36 months. "
            f"In the interim, last-time-buy orders are being coordinated to bridge the gap "
            f"and prevent operational gaps in the affected fleets."
        )
        tags = ["semiconductors", "obsolescence", "aviation"]

    elif topic == "regulations":
        title = random.choice([
            f"New guidance issued on approved equivalent parts for obsolete {comp}",
            f"Regulatory update addresses {comp} lifecycle management requirements",
            f"Airworthiness authority mandates proactive obsolescence planning for {comp}",
            f"{reg} updated to reflect {comp} end-of-life management practices",
            f"Compliance deadline set for operators still using legacy {comp}",
        ])
        summary = (
            f"Aviation regulatory authorities have issued updated guidance addressing "
            f"the obsolescence of the {comp} currently installed in {ac} variants. "
            f"The updated {reg} establishes new requirements for operators to document "
            f"and demonstrate proactive lifecycle management strategies. "
            f"Operators have 24 months to comply, with approved mitigation pathways including "
            f"{mitig}. Failure to demonstrate compliance may result in airworthiness "
            f"certificate limitations. The regulation was prompted in part by increasing "
            f"industry reports of {comp} availability issues because {reason}."
        )
        tags = ["regulations", "aviation", "obsolescence"]

    elif topic == "chemicals":
        title = random.choice([
            f"Specialty fluid used with {comp} faces REACH restriction",
            f"RoHS compliance drives reformulation of {comp} sealing materials",
            f"Chemical supply disruption affects {comp} production schedule",
            f"Lubricant obsolescence creates maintenance challenge for {comp} systems",
            f"Environmental regulations accelerate {comp} material phase-out",
        ])
        summary = (
            f"New environmental regulations are creating obsolescence pressure on specialty "
            f"chemical compounds used in the production and maintenance of the {comp}. "
            f"The restriction, enforced under {reg}, prohibits continued use of key substances "
            f"that {reason}. "
            f"Aerospace MRO providers are working with {supp} to qualify reformulated "
            f"alternatives, though compatibility testing with legacy {ac} airframe materials "
            f"is ongoing. Transition timelines are expected to align with scheduled "
            f"heavy maintenance visits to minimize operational disruption."
        )
        tags = ["chemicals", "regulations", "obsolescence"]

    else:  # market
        title = random.choice([
            f"Market consolidation threatens long-term {comp} availability",
            f"Investor pressure drives {supp} to exit low-margin {comp} business",
            f"M&A activity creates supply uncertainty for aerospace {comp} market",
            f"Economic analysis: true cost of {comp} obsolescence for operators",
            f"Analyst report flags {comp} single-source risk for aerospace OEMs",
        ])
        summary = (
            f"A new market analysis from an aerospace consulting firm has flagged growing "
            f"financial and operational risks associated with {comp} market concentration. "
            f"With {supp} representing the sole source for this component used in {ac} variants, "
            f"recent merger and acquisition activity in the sector has raised concerns that "
            f"{reason}. "
            f"The report estimates the total cost of obsolescence mitigation through {mitig} "
            f"at $50-200M across the affected fleet, depending on retrofit scope. "
            f"Investors and program managers are urged to factor these lifecycle costs into "
            f"long-term fleet planning assumptions."
        )
        tags = ["market", "supply_chain", "obsolescence"]

    # Published date: spread across 2019–2024
    days_ago = random.randint(0, 365 * 5)
    pub_dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    pub_str = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    crawled_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    article_id = hashlib.md5(url.encode()).hexdigest()

    return {
        "article_id":    article_id,
        "url":           url,
        "title":         title,
        "summary":       summary,
        "full_text":     summary,   # same as summary for synthetic
        "topic":         topic,
        "source_feed":   "synthetic",
        "source_domain": domain,
        "published_at":  pub_str,
        "crawled_at":    crawled_str,
        "tags":          tags,
        "word_count":    len(summary.split()),
    }


def generate(n: int = 1100, out: str = "articles.jsonl"):
    # Weighted topic distribution
    topics = list(TOPICS.keys())
    weights = list(TOPICS.values())

    articles = []
    seen_urls = set()

    while len(articles) < n:
        topic = random.choices(topics, weights=weights, k=1)[0]
        art = make_article(len(articles), topic)
        if art["url"] not in seen_urls:
            seen_urls.add(art["url"])
            articles.append(art)

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    # Stats
    from collections import Counter
    topic_cnt = Counter(a["topic"] for a in articles)
    print(f"✅  Generated {len(articles)} articles → {out}")
    print("\nBy topic:")
    for t, c in topic_cnt.most_common():
        print(f"  {t:<20} {c}")
    print(f"\nSample article:\n  Title  : {articles[0]['title']}")
    print(f"  Topic  : {articles[0]['topic']}")
    print(f"  Domain : {articles[0]['source_domain']}")
    print(f"  Words  : {articles[0]['word_count']}")


if __name__ == "__main__":
    generate()