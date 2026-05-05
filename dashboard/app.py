"""
dashboard/app.py — Aerospace Obsolescence Risk Dashboard
=========================================================
pip install gradio requests
python dashboard/app.py
"""

import os
import subprocess
import requests
import gradio as gr
from pathlib import Path
from dotenv import load_dotenv

ROOT       = Path(__file__).parent.parent
ENV_PATH   = ROOT / "api" / ".env"
load_dotenv(ENV_PATH)

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.environ.get("API_BASE")
API_KEY  = os.environ.get("API_KEY")
GCP_PROJECT = os.environ.get("GCP_PROJECT")
HEADERS  = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

CATEGORIES = [
    "All", "Avionics", "Hydraulics", "Landing Gear", "Engine Components",
    "Electrical Systems", "Fuel Systems", "Navigation", "Communication",
    "Structural", "Environmental Control", "Flight Controls", "Lighting",
]

TIER_ICON  = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
SEV_ICON   = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
/* ── Global ─────────────────────────────────────────── */
body, .gradio-container { font-family: 'Inter', system-ui, sans-serif !important; }

/* ── Header banner ───────────────────────────────────── */
.header-banner {
    background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
    border-radius: 14px;
    padding: 28px 32px;
    margin-bottom: 20px;
    color: white !important;
}
.header-banner h1 { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: white !important; }
.header-banner p  { font-size: 13px; opacity: 0.75; margin: 0; color: white !important; }
.header-banner .api-badge {
    display: inline-block; margin-top: 10px;
    background: rgba(255,255,255,0.12); border-radius: 6px;
    padding: 3px 10px; font-size: 11px; font-family: monospace; color: white;
}

/* ── Metric cards ────────────────────────────────────── */
.metric-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 18px 20px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.metric-card .val  { font-size: 28px; font-weight: 700; color: #111827; line-height: 1; }
.metric-card .lbl  { font-size: 11px; color: #6b7280; margin-top: 4px; text-transform: uppercase; letter-spacing: .04em; }
.metric-card .sub  { font-size: 11px; color: #9ca3af; margin-top: 2px; }
.metric-critical   { border-top: 3px solid #ef4444 !important; }
.metric-model      { border-top: 3px solid #6366f1 !important; }
.metric-total      { border-top: 3px solid #0ea5e9 !important; }
.metric-evidence   { border-top: 3px solid #10b981 !important; }

/* ── Section headers ─────────────────────────────────── */
.section-header {
    font-size: 12px; font-weight: 600; color: #6b7280;
    text-transform: uppercase; letter-spacing: .06em;
    border-bottom: 1px solid #f3f4f6; padding-bottom: 8px; margin-bottom: 12px;
}

/* ── Tier pills ──────────────────────────────────────── */
.pill {
    display: inline-block; border-radius: 99px;
    padding: 2px 9px; font-size: 11px; font-weight: 600;
}
.pill-Critical { background: #fee2e2; color: #991b1b; }
.pill-High     { background: #ffedd5; color: #9a3412; }
.pill-Medium   { background: #dbeafe; color: #1e40af; }
.pill-Low      { background: #dcfce7; color: #166534; }

/* ── Risk score bar ──────────────────────────────────── */
.risk-bar-wrap { background: #f3f4f6; border-radius: 99px; height: 8px; overflow: hidden; }
.risk-bar-fill { height: 100%; border-radius: 99px; }

/* ── Part card (detail view) ─────────────────────────── */
.part-card {
    background: #f9fafb; border: 1px solid #e5e7eb;
    border-radius: 12px; padding: 20px 24px;
}

/* ── Tab styling ─────────────────────────────────────── */
.tab-nav button { font-size: 13px !important; font-weight: 500 !important; }

/* ── Action buttons ──────────────────────────────────── */
.btn-primary { background: #2563eb !important; }
.btn-danger  { background: #dc2626 !important; }

/* ── Dataframe ───────────────────────────────────────── */
.dataframe thead th { background: #f8fafc !important; font-size: 12px !important; }
.dataframe tbody tr:hover { background: #f0f9ff !important; }

/* ── Info boxes ──────────────────────────────────────── */
.info-box {
    background: #eff6ff; border: 1px solid #bfdbfe;
    border-radius: 8px; padding: 10px 14px;
    font-size: 13px; color: #1e40af;
}
.warn-box {
    background: #fffbeb; border: 1px solid #fde68a;
    border-radius: 8px; padding: 10px 14px;
    font-size: 13px; color: #92400e;
}
.success-box {
    background: #f0fdf4; border: 1px solid #bbf7d0;
    border-radius: 8px; padding: 10px 14px;
    font-size: 13px; color: #166534;
}
"""


# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(path):
    r = requests.get(f"{API_BASE}{path}", headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()

def api_post(path, body):
    r = requests.post(f"{API_BASE}{path}", headers=HEADERS, json=body, timeout=20)
    r.raise_for_status()
    return r.json()

def _dt(val):
    if isinstance(val, dict): val = val.get("value", "")
    return str(val)[:19] if val else "—"

def _score_bar(score, width=24):
    filled = int(score * width)
    return "█" * filled + "░" * (width - filled)


# ── Tab 1: Dashboard (Stats) ──────────────────────────────────────────────────

def load_dashboard():
    try:
        d = api_get("/api/v1/parts/stats")["data"]
        tiers = {t["risk_tier"]: int(t["count"]) for t in d["risk_tier_distribution"]}

        overview = f"""<div class="header-banner">
<h1>✈️ Aerospace Parts Obsolescence Risk</h1>
<p>AI/ML early warning · XGBoost + Bi-Encoder + Cross-Encoder · Google Cloud</p>
<span class="api-badge">🟢 {API_BASE}</span>
</div>

<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px">
<div class="metric-card metric-total">
  <div class="val">{int(d['total_parts']):,}</div>
  <div class="lbl">Total Parts</div>
</div>
<div class="metric-card metric-critical">
  <div class="val" style="color:#ef4444">{tiers.get('Critical',0):,}</div>
  <div class="lbl">Critical Risk</div>
  <div class="sub">🔴 immediate attention</div>
</div>
<div class="metric-card metric-evidence">
  <div class="val" style="color:#10b981">{int(d['parts_with_evidence']):,}</div>
  <div class="lbl">With Evidence</div>
  <div class="sub">articles linked</div>
</div>
<div class="metric-card metric-model">
  <div class="val" style="color:#6366f1;font-size:20px">{d['latest_model_version']}</div>
  <div class="lbl">Model Version</div>
  <div class="sub">{_dt(d.get('last_scored_at'))}</div>
</div>
</div>"""

        # Tier distribution
        total = sum(tiers.values()) or 1
        tier_bars = ""
        for tier, color in [("Critical","#ef4444"),("High","#f97316"),("Medium","#3b82f6"),("Low","#22c55e")]:
            cnt = tiers.get(tier, 0)
            pct = cnt / total * 100
            tier_bars += f"""<div style="margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
    <span>{TIER_ICON.get(tier,'')} {tier}</span>
    <span style="color:#6b7280">{cnt:,} &nbsp;({pct:.1f}%)</span>
  </div>
  <div class="risk-bar-wrap">
    <div class="risk-bar-fill" style="width:{pct:.1f}%;background:{color}"></div>
  </div>
</div>"""

        # Top categories table
        cat_rows = "".join(
            f"<tr><td style='padding:6px 8px'>{c['category']}</td>"
            f"<td style='padding:6px 8px;text-align:center'>"
            f"<span style='font-weight:600;color:#dc2626'>{float(c['avg_score']):.3f}</span></td>"
            f"<td style='padding:6px 8px;text-align:center;color:#6b7280'>{int(c['count']):,}</td></tr>"
            for c in d["top_risk_categories"]
        )

        overview += f"""<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
<div>
  <div class="section-header">Risk Tier Distribution</div>
  {tier_bars}
</div>
<div>
  <div class="section-header">Top Risk Categories</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#f8fafc;font-size:11px;color:#6b7280">
      <th style="padding:6px 8px;text-align:left">Category</th>
      <th style="padding:6px 8px">Avg Score</th>
      <th style="padding:6px 8px">Parts</th>
    </tr></thead>
    <tbody>{cat_rows}</tbody>
  </table>
</div>
</div>"""

        return overview
    except Exception as e:
        return f'<div class="warn-box">❌ Error loading dashboard: {e}</div>'


# ── Tab 2: Early Warning ──────────────────────────────────────────────────────

def load_early_warning(tier, category, limit):
    try:
        params = f"?limit={int(limit)}"
        if tier != "All": params += f"&tier={tier}"
        if category != "All": params += f"&category={category}"
        d = api_get(f"/api/v1/parts/early-warning{params}")
        if not d.get("success") or not d.get("data"):
            return [], "No parts found."

        rows = []
        for p in d["data"]:
            score = float(p["risk_score"])
            icon  = TIER_ICON.get(p["risk_tier"], "⚪")
            rows.append([
                p["part_id"],
                p["part_name"],
                p["category"],
                p["aircraft_model"],
                p["lifecycle_status"],
                f"{score:.3f}",
                f"{icon} {p['risk_tier']}",
                (p.get("evidence_summary") or "")[:90],
            ])

        meta = d.get("meta", {})
        filters = []
        if tier != "All": filters.append(f"Tier: **{tier}**")
        if category != "All": filters.append(f"Category: **{category}**")
        summary = f"Found **{meta.get('total', len(rows))}** parts" + (f" · {' · '.join(filters)}" if filters else "")
        return rows, summary
    except Exception as e:
        return [], f"❌ {e}"


# ── Tab 3: Part Detail ────────────────────────────────────────────────────────

def load_part_detail(part_id):
    if not part_id or not part_id.strip():
        return '<div class="info-box">💡 Enter a Part ID above and press Enter or click Lookup.</div>', "", ""
    try:
        d = api_get(f"/api/v1/parts/{part_id.strip()}/risk-score")
        if not d.get("success"):
            msg = d.get("message", {})
            if isinstance(msg, dict): msg = msg.get("message", "Not found")
            return f'<div class="warn-box">❌ {msg}</div>', "", ""

        part     = d["data"]["part"]
        risk     = d["data"]["risk"]
        evidence = d["data"]["evidence"]

        # ── Part card ──
        lc = part['lifecycle_status']
        lc_color = {"Obsolete":"#dc2626","Discontinued":"#dc2626","End-of-Life":"#ea580c","Phased-Out":"#d97706"}.get(lc,"#16a34a")

        info_html = f"""<div class="part-card">
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">
  <div>
    <div style="font-size:17px;font-weight:700;color:#111827">{part['part_name']}</div>
    <div style="font-family:monospace;font-size:12px;color:#6b7280;margin-top:2px">{part['part_id']}</div>
  </div>
  <span style="background:{lc_color}15;color:{lc_color};border:1px solid {lc_color}40;
    border-radius:99px;padding:3px 10px;font-size:12px;font-weight:600">{lc}</span>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px">
  <div><span style="color:#6b7280">Category</span><br><b>{part['category']}</b></div>
  <div><span style="color:#6b7280">Aircraft</span><br><b>{part['aircraft_model']}</b></div>
  <div><span style="color:#6b7280">Supplier</span><br><b>{part['supplier']}</b></div>
  <div><span style="color:#6b7280">Criticality</span><br><b>{part['criticality']}</b></div>
  <div><span style="color:#6b7280">Manufacture Year</span><br><b>{part['manufacture_year']}</b></div>
  <div><span style="color:#6b7280">Lead Time</span><br><b>{part['lead_time_days']} days</b></div>
  <div><span style="color:#6b7280">Stock Level</span><br><b>{part['stock_level']} units</b></div>
</div>
</div>"""

        # ── Risk card ──
        score     = float(risk['score'] or 0)
        tier      = risk['tier']
        tier_color = {"Critical":"#ef4444","High":"#f97316","Medium":"#3b82f6","Low":"#22c55e"}.get(tier,"#6b7280")
        bar_pct   = f"{score*100:.1f}"

        feat_rows = "".join(
            f"<tr><td style='padding:5px 8px;font-family:monospace;font-size:12px'>{f['feature']}</td>"
            f"<td style='padding:5px 8px'>"
            f"<div style='display:flex;align-items:center;gap:8px'>"
            f"<div style='flex:1;background:#f3f4f6;border-radius:99px;height:6px'>"
            f"<div style='width:{float(f['importance'])*400:.0f}px;max-width:100%;background:#6366f1;border-radius:99px;height:6px'></div></div>"
            f"<span style='font-size:12px;color:#6b7280;width:45px;text-align:right'>{float(f['importance']):.4f}</span>"
            f"</div></td></tr>"
            for f in risk.get("top_features", [])
        )

        sev_colors = {"critical":"#dc2626","high":"#ea580c","medium":"#d97706","low":"#16a34a"}
        factor_items = "".join(
            f"<div style='display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6'>"
            f"<span style='font-size:16px'>{SEV_ICON.get(f['severity'],'⚪')}</span>"
            f"<div><span style='font-size:10px;font-weight:700;color:{sev_colors.get(f['severity'],"#6b7280")};text-transform:uppercase'>"
            f"{f['severity']}</span><br><span style='font-size:13px;color:#374151'>{f['message']}</span></div></div>"
            for f in evidence.get("risk_factors", [])
        )

        risk_html = f"""<div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:20px;border-top:4px solid {tier_color}">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <div>
    <div style="font-size:13px;color:#6b7280;margin-bottom:4px">RISK SCORE</div>
    <div style="font-size:36px;font-weight:800;color:{tier_color};line-height:1">{score:.3f}</div>
  </div>
  <div style="text-align:right">
    <span style="background:{tier_color}20;color:{tier_color};border-radius:8px;padding:6px 14px;font-size:14px;font-weight:700">{TIER_ICON.get(tier,'')} {tier}</span>
    <div style="font-size:11px;color:#9ca3af;margin-top:6px">Model {risk['model_version']} · {_dt(risk.get('scored_at'))}</div>
  </div>
</div>
<div class="risk-bar-wrap" style="margin-bottom:16px">
  <div class="risk-bar-fill" style="width:{bar_pct}%;background:{tier_color}"></div>
</div>
<div style="font-size:12px;color:#6b7280;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.04em">Top Features</div>
<table style="width:100%;border-collapse:collapse">
  <tbody>{feat_rows}</tbody>
</table>
<div style="font-size:12px;color:#6b7280;margin:14px 0 8px;font-weight:600;text-transform:uppercase;letter-spacing:.04em">Risk Factors</div>
{factor_items}
</div>"""

        # ── Articles ──
        arts = evidence.get("related_articles", [])
        if not arts:
            articles_html = '<div class="info-box">No evidence articles available for this part.</div>'
        else:
            cards = ""
            for i, a in enumerate(arts, 1):
                sim   = float(a.get("similarity_score") or 0)
                cross = float(a.get("cross_score") or 0)
                snippet = (a.get("snippet") or "")[:180]
                cards += f"""<div style="background:white;border:1px solid #e5e7eb;border-radius:10px;
  padding:14px 16px;margin-bottom:8px">
  <div style="font-size:13px;font-weight:600;color:#111827;margin-bottom:6px">{i}. {a['title']}</div>
  <div style="display:flex;gap:12px;font-size:11px;color:#6b7280;margin-bottom:8px">
    <span>🌐 {a['source']}</span>
    <span>🏷️ {a['topic']}</span>
    <span>Similarity: <b>{sim:.3f}</b></span>
    <span>Cross-encoder: <b>{cross:+.2f}</b></span>
  </div>
  <div style="font-size:12px;color:#4b5563;font-style:italic">{snippet}…</div>
</div>"""
            articles_html = f"""<div>
<div style="font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:10px">
  📰 Related Articles — Bi-Encoder + Cross-Encoder Reranked
</div>
{cards}
</div>"""

        return info_html, risk_html, articles_html
    except Exception as e:
        return f'<div class="warn-box">❌ Error: {e}</div>', "", ""


# ── Tab 4: Crawler ────────────────────────────────────────────────────────────

def trigger_crawler():
    try:
        result = subprocess.run(
            ["gcloud","run","jobs","execute","crawler-job",
             "--region=asia-southeast1", f"--project={GCP_PROJECT}", "--format=json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            import json as _j
            try:
                name = _j.loads(result.stdout).get("metadata",{}).get("name","").split("/")[-1]
            except Exception:
                name = "started"
            import datetime
            return f"""<div class="success-box">
✅ <b>Crawler job started!</b><br>
Execution: <code>{name}</code> · Started: <code>{datetime.datetime.now().strftime('%H:%M:%S')}</code><br>
<small>Job takes ~2 minutes. Refresh executions below to monitor.</small>
</div>"""
        return f'<div class="warn-box">❌ {result.stderr[:400]}</div>'
    except FileNotFoundError:
        return '<div class="warn-box">❌ <code>gcloud</code> CLI not found. Install Google Cloud SDK.</div>'
    except Exception as e:
        return f'<div class="warn-box">❌ {e}</div>'


def load_crawler_executions():
    try:
        result = subprocess.run(
            ["gcloud","run","jobs","executions","list","--job=crawler-job",
             "--region=asia-southeast1", f"--project={GCP_PROJECT}", "--limit=5","--format=json"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return '<div class="warn-box">❌ Cannot load executions. Make sure gcloud is authenticated.</div>'

        import json as _j
        exs = _j.loads(result.stdout or "[]")
        if not exs:
            return '<div class="info-box">No executions found yet.</div>'

        rows = ""
        for ex in exs:
            name  = ex.get("metadata",{}).get("name","").split("/")[-1]
            st    = ex.get("status",{})
            ok    = st.get("succeededCount",0)
            fail  = st.get("failedCount",0)
            start = _dt(st.get("startTime",""))
            end   = _dt(st.get("completionTime",""))
            badge = "✅ Succeeded" if ok else "❌ Failed" if fail else "🔄 Running"
            color = "#16a34a" if ok else "#dc2626" if fail else "#d97706"
            rows += f"""<tr>
  <td style="padding:8px 10px;font-family:monospace;font-size:12px">{name}</td>
  <td style="padding:8px 10px"><span style="color:{color};font-weight:600">{badge}</span></td>
  <td style="padding:8px 10px;font-size:12px;color:#6b7280">{start}</td>
  <td style="padding:8px 10px;font-size:12px;color:#6b7280">{end}</td>
</tr>"""

        return f"""<table style="width:100%;border-collapse:collapse;font-size:13px;background:white;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">
<thead><tr style="background:#f8fafc;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em">
  <th style="padding:8px 10px;text-align:left">Execution</th>
  <th style="padding:8px 10px;text-align:left">Status</th>
  <th style="padding:8px 10px;text-align:left">Started</th>
  <th style="padding:8px 10px;text-align:left">Completed</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>"""
    except FileNotFoundError:
        return '<div class="warn-box">❌ <code>gcloud</code> CLI not found.</div>'
    except Exception as e:
        return f'<div class="warn-box">❌ {e}</div>'


# ── Tab 5: Retrain ────────────────────────────────────────────────────────────

def load_retrain_status():
    try:
        d = api_get("/api/v1/retrain/status")["data"]
        is_training = d["is_retraining"]
        status_html = (
            '<span style="color:#d97706;font-weight:600">🔄 Retraining in progress...</span>'
            if is_training else
            '<span style="color:#16a34a;font-weight:600">✅ Idle</span>'
        )

        hist_rows = ""
        for h in d.get("model_history", []):
            scored = _dt(h.get("scored_at"))
            hist_rows += f"""<tr>
  <td style="padding:8px 10px;font-weight:700;color:#6366f1">{h['model_version']}</td>
  <td style="padding:8px 10px;text-align:center">{int(h['parts_scored']):,}</td>
  <td style="padding:8px 10px;font-family:monospace;font-size:12px;color:#6b7280">{scored}</td>
</tr>"""

        return f"""<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
<div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:18px">
  <div class="section-header">Current Status</div>
  <table style="width:100%;font-size:13px;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#6b7280">Status</td><td>{status_html}</td></tr>
    <tr><td style="padding:6px 0;color:#6b7280">Current version</td>
        <td style="font-weight:700;color:#6366f1">{d['current_version']}</td></tr>
    <tr><td style="padding:6px 0;color:#6b7280">Total parts</td>
        <td>{int(d['total_parts']):,}</td></tr>
    <tr><td style="padding:6px 0;color:#6b7280">Scored parts</td>
        <td>{int(d['scored_parts']):,}</td></tr>
  </table>
</div>
<div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:18px">
  <div class="section-header">Model History</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="font-size:11px;color:#6b7280">
      <th style="padding:8px 10px;text-align:left">Version</th>
      <th style="padding:8px 10px">Parts</th>
      <th style="padding:8px 10px;text-align:left">Scored At</th>
    </tr></thead>
    <tbody>{hist_rows}</tbody>
  </table>
</div>
</div>"""
    except Exception as e:
        return f'<div class="warn-box">❌ {e}</div>'


def trigger_retrain(version, reason):
    try:
        body = {"reason": reason.strip() or "dashboard_trigger"}
        if version.strip(): body["version"] = version.strip()
        d = api_post("/api/v1/retrain", body)
        if not d.get("success"):
            return f'<div class="warn-box">❌ {d.get("message","Failed")}</div>'
        data = d["data"]
        return f"""<div class="success-box">
✅ <b>Retrain job started!</b><br>
Job: <code>{data['job_id']}</code> · Version: <b>{data['new_version']}</b> · Est. {data['estimated_duration']}<br>
<small>Refresh status below to monitor progress.</small>
</div>"""
    except Exception as e:
        return f'<div class="warn-box">❌ {e}</div>'


# ── Build UI ──────────────────────────────────────────────────────────────────

with gr.Blocks(css=CSS, title="Aerospace Obsolescence Risk") as app:

    with gr.Tabs(elem_classes=["tab-nav"]):

        # Tab 1 — Dashboard
        with gr.Tab("🏠 Dashboard"):
            with gr.Row():
                btn_refresh = gr.Button("🔄 Refresh", size="sm", scale=0)
            dashboard_out = gr.HTML()
            btn_refresh.click(load_dashboard, outputs=dashboard_out)
            app.load(load_dashboard, outputs=dashboard_out)

        # Tab 2 — Early Warning
        with gr.Tab("⚠️ Early Warning"):
            with gr.Row():
                tier_dd  = gr.Dropdown(["All","Critical","High","Medium","Low"],
                                       value="Critical", label="Risk Tier", scale=1)
                cat_dd   = gr.Dropdown(CATEGORIES, value="All", label="Category", scale=2)
                limit_sl = gr.Slider(5, 50, value=10, step=5, label="Limit", scale=1)
                btn_ew   = gr.Button("🔍 Search", variant="primary", scale=1)

            ew_summary = gr.Markdown()
            ew_table   = gr.Dataframe(
                headers=["Part ID","Name","Category","Aircraft","Lifecycle","Score","Tier","Evidence"],
                datatype=["str"]*8, interactive=False, wrap=True,
            )
            btn_ew.click(load_early_warning, inputs=[tier_dd, cat_dd, limit_sl], outputs=[ew_table, ew_summary])
            app.load(lambda: load_early_warning("Critical","All",10), outputs=[ew_table, ew_summary])

        # Tab 3 — Part Detail
        with gr.Tab("🔍 Part Detail"):
            with gr.Row():
                part_id_in = gr.Textbox(label="Part ID", placeholder="e.g. MIL-00837", scale=5)
                btn_detail = gr.Button("Lookup →", variant="primary", scale=1)

            with gr.Row():
                info_out = gr.HTML()
                risk_out = gr.HTML()

            articles_out = gr.HTML()

            gr.HTML('<div class="info-box" style="margin-top:8px">💡 Copy a Part ID from the Early Warning tab above.</div>')

            for trigger in [btn_detail.click, part_id_in.submit]:
                trigger(load_part_detail, inputs=part_id_in, outputs=[info_out, risk_out, articles_out])

        # Tab 4 — Crawler
        with gr.Tab("🕷️ Crawler"):
            gr.HTML("""<div class="info-box">
RSS Crawler → GCS + BigQuery &nbsp;·&nbsp; Auto-runs <b>every Sunday 1:00 AM UTC</b> via Cloud Scheduler
</div>""")
            with gr.Row():
                btn_crawl     = gr.Button("🚀 Run Crawler Now", variant="primary")
                btn_crawl_ref = gr.Button("🔄 Refresh Executions", size="sm")

            crawl_result   = gr.HTML()
            executions_out = gr.HTML()

            btn_crawl.click(trigger_crawler, outputs=crawl_result)
            btn_crawl_ref.click(load_crawler_executions, outputs=executions_out)
            app.load(load_crawler_executions, outputs=executions_out)

        # Tab 5 — Retrain
        with gr.Tab("🔄 Retrain"):
            gr.HTML("""<div class="info-box">
XGBoost retrain + embedding index rebuild &nbsp;·&nbsp; Auto-runs <b>every Sunday 2:00 AM UTC</b> via Cloud Scheduler
</div>""")
            with gr.Row():
                version_in  = gr.Textbox(label="Version (optional)", placeholder="e.g. 3", scale=1)
                reason_in   = gr.Textbox(label="Reason", value="manual_trigger", scale=3)
                btn_trigger = gr.Button("🚀 Trigger Retrain", variant="stop", scale=1)

            retrain_result = gr.HTML()
            btn_trigger.click(trigger_retrain, inputs=[version_in, reason_in], outputs=retrain_result)

            gr.HTML("<hr style='margin:16px 0;border:none;border-top:1px solid #e5e7eb'>")
            with gr.Row():
                btn_status = gr.Button("🔄 Refresh Status", size="sm", scale=0)
            status_out = gr.HTML()
            btn_status.click(load_retrain_status, outputs=status_out)
            app.load(load_retrain_status, outputs=status_out)


if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        share=False,
    )