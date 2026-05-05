import { Injectable, NotFoundException, Logger } from '@nestjs/common';
import { DbService } from '../db/db.service';

@Injectable()
export class PartsService {
  private readonly logger = new Logger(PartsService.name);

  constructor(private db: DbService) {}

  // ── GET /parts/:id/risk-score ──────────────────────────────────────────────
  async getRiskScore(partId: string) {
    const id = this.db.escape(partId);

    const part = await this.db.queryOne(
      `SELECT * FROM ${this.db.table('parts')} WHERE part_id = '${id}'`,
    );
    if (!part) {
      throw new NotFoundException(`Part '${partId}' not found`);
    }

    const score = await this.db.queryOne(
      `SELECT * FROM ${this.db.table('risk_scores')} WHERE part_id = '${id}'`,
    );

    const evidence = await this.db.queryOne(
      `SELECT * FROM ${this.db.table('part_evidence')} WHERE part_id = '${id}'`,
    );

    const riskFactors  = this._parseJson(evidence?.['risk_factors'], []);
    const articleLinks = this._parseJson(evidence?.['article_links'], []);
    const topFeatures  = this._parseJson(score?.['top_features'], []);

    return {
      success: true,
      data: {
        part: {
          part_id:          part['part_id'],
          part_name:        part['part_name'],
          category:         part['category'],
          aircraft_model:   part['aircraft_model'],
          supplier:         part['supplier'],
          lifecycle_status: part['lifecycle_status'],
          manufacture_year: part['manufacture_year'],
          lead_time_days:   part['lead_time_days'],
          stock_level:      part['stock_level'],
          criticality:      part['criticality'],
        },
        risk: {
          score:         score?.['risk_score'] ?? null,
          label:         score?.['risk_label'] ?? null,
          tier:          score?.['risk_tier'] ?? 'Unknown',
          model_version: score?.['model_version'] ?? null,
          scored_at:     score?.['scored_at'] ?? null,
          top_features:  topFeatures,
        },
        evidence: {
          summary:          evidence?.['summary'] ?? null,
          risk_factors:     riskFactors,
          related_articles: articleLinks.slice(0, 5),
          generated_at:     evidence?.['generated_at'] ?? null,
        },
      },
    };
  }

  // ── GET /parts/early-warning ───────────────────────────────────────────────
  async getEarlyWarning(options: {
    limit: number;
    tier?: string;
    category?: string;
    aircraft?: string;
  }) {
    const { limit, tier, category, aircraft } = options;

    const conditions: string[] = ['r.risk_score IS NOT NULL'];

    if (tier)     conditions.push(`r.risk_tier = '${this.db.escape(tier)}'`);
    if (category) conditions.push(`p.category = '${this.db.escape(category)}'`);
    if (aircraft) conditions.push(`p.aircraft_model LIKE '%${this.db.escape(aircraft)}%'`);

    const where = conditions.join(' AND ');

    const rows = await this.db.query(
      `SELECT
         p.part_id, p.part_name, p.category, p.aircraft_model,
         p.supplier, p.lifecycle_status, p.manufacture_year,
         p.lead_time_days, p.stock_level, p.criticality,
         p.num_alternative_suppliers, p.alternative_part_available,
         r.risk_score, r.risk_tier, r.model_version,
         e.summary AS evidence_summary
       FROM ${this.db.table('parts')} p
       JOIN ${this.db.table('risk_scores')} r ON p.part_id = r.part_id
       LEFT JOIN ${this.db.table('part_evidence')} e ON p.part_id = e.part_id
       WHERE ${where}
       ORDER BY r.risk_score DESC
       LIMIT ${limit}`,
    );

    const tierCounts = rows.reduce<Record<string, number>>((acc, r) => {
      const t = r['risk_tier'] as string;
      acc[t] = (acc[t] || 0) + 1;
      return acc;
    }, {});

    return {
      success: true,
      meta: {
        total:       rows.length,
        tier_counts: tierCounts,
        filters:     { tier, category, aircraft },
      },
      data: rows.map((r) => ({
        part_id:                   r['part_id'],
        part_name:                 r['part_name'],
        category:                  r['category'],
        aircraft_model:            r['aircraft_model'],
        supplier:                  r['supplier'],
        lifecycle_status:          r['lifecycle_status'],
        manufacture_year:          r['manufacture_year'],
        lead_time_days:            r['lead_time_days'],
        stock_level:               r['stock_level'],
        criticality:               r['criticality'],
        num_alternative_suppliers: r['num_alternative_suppliers'],
        risk_score:                r['risk_score'],
        risk_tier:                 r['risk_tier'],
        evidence_summary:          r['evidence_summary'] ?? null,
      })),
    };
  }

  // ── GET /parts/stats ───────────────────────────────────────────────────────
  async getStats() {
    const [total, scored, withEvidence, tiers, categories, latestModel] =
      await Promise.all([
        this.db.queryOne<{ count: number }>(
          `SELECT COUNT(*) AS count FROM ${this.db.table('parts')}`,
        ),
        this.db.queryOne<{ count: number }>(
          `SELECT COUNT(*) AS count FROM ${this.db.table('risk_scores')}`,
        ),
        this.db.queryOne<{ count: number }>(
          `SELECT COUNT(*) AS count FROM ${this.db.table('part_evidence')}`,
        ),
        this.db.query(
          `SELECT risk_tier, COUNT(*) AS count
           FROM ${this.db.table('risk_scores')}
           GROUP BY risk_tier ORDER BY count DESC`,
        ),
        this.db.query(
          `SELECT p.category, AVG(r.risk_score) AS avg_score, COUNT(*) AS count
           FROM ${this.db.table('parts')} p
           JOIN ${this.db.table('risk_scores')} r ON p.part_id = r.part_id
           GROUP BY p.category ORDER BY avg_score DESC`,
        ),
        this.db.queryOne(
          `SELECT model_version, scored_at
           FROM ${this.db.table('risk_scores')}
           ORDER BY scored_at DESC LIMIT 1`,
        ),
      ]);

    return {
      success: true,
      data: {
        total_parts:            total?.count ?? 0,
        scored_parts:           scored?.count ?? 0,
        parts_with_evidence:    withEvidence?.count ?? 0,
        risk_tier_distribution: tiers,
        top_risk_categories:    categories.slice(0, 5),
        latest_model_version:   latestModel?.['model_version'] ?? null,
        last_scored_at:         latestModel?.['scored_at'] ?? null,
      },
    };
  }

  // ── Helper ─────────────────────────────────────────────────────────────────
  private _parseJson(value: any, fallback: any): any {
    if (!value) return fallback;
    if (typeof value !== 'string') return value;
    try { return JSON.parse(value); }
    catch { return fallback; }
  }
}