import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DbService } from '../db/db.service';
import { RetrainDto } from './retrain.dto';

@Injectable()
export class RetrainService {
  private readonly logger = new Logger(RetrainService.name);
  private isRetraining = false;

  constructor(
    private db: DbService,
    private config: ConfigService,
  ) {}

  // ── POST /retrain ──────────────────────────────────────────────────────────
  async triggerRetrain(dto: RetrainDto) {
    if (this.isRetraining) {
      return {
        success: false,
        message: 'Retraining already in progress. Try again later.',
        status: 'busy',
      };
    }

    const currentVersion = await this._getCurrentModelVersion();
    const newVersion = dto.version || this._incrementVersion(currentVersion);
    const reason = dto.reason || 'manual_trigger';
    const jobId = `retrain_${Date.now()}`;

    this.logger.log(`Retrain triggered — version: ${newVersion}, reason: ${reason}, jobId: ${jobId}`);

    this._runRetrainJob(newVersion, jobId);

    return {
      success: true,
      message: 'Retraining job started in background.',
      data: {
        job_id:             jobId,
        new_version:        newVersion,
        previous_version:   currentVersion,
        reason,
        target_parts:       dto.target_parts?.length
          ? `${dto.target_parts.length} specific parts`
          : 'all parts',
        started_at:         new Date().toISOString(),
        estimated_duration: '3-8 minutes',
      },
    };
  }

  // ── GET /retrain/status ────────────────────────────────────────────────────
  async getStatus() {
    const [currentVersion, lastScored, totalScored, totalParts, versions] =
      await Promise.all([
        this._getCurrentModelVersion(),
        this.db.queryOne(
          `SELECT scored_at, model_version FROM ${this.db.table('risk_scores')}
           ORDER BY scored_at DESC LIMIT 1`,
        ),
        this.db.queryOne<{ count: number }>(
          `SELECT COUNT(*) AS count FROM ${this.db.table('risk_scores')}`,
        ),
        this.db.queryOne<{ count: number }>(
          `SELECT COUNT(*) AS count FROM ${this.db.table('parts')}`,
        ),
        this.db.query(
          `SELECT model_version, COUNT(*) AS parts_scored, MAX(scored_at) AS scored_at
           FROM ${this.db.table('risk_scores')}
           GROUP BY model_version ORDER BY scored_at DESC`,
        ),
      ]);

    return {
      success: true,
      data: {
        is_retraining:   this.isRetraining,
        current_version: currentVersion,
        total_parts:     totalParts?.count ?? 0,
        scored_parts:    totalScored?.count ?? 0,
        last_scored_at:  lastScored?.['scored_at'] ?? null,
        model_history:   versions,
      },
    };
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  private async _getCurrentModelVersion(): Promise<string> {
    const row = await this.db.queryOne(
      `SELECT model_version FROM ${this.db.table('risk_scores')}
       ORDER BY scored_at DESC LIMIT 1`,
    );
    return row?.['model_version'] ?? 'v1';
  }

  private _incrementVersion(v: string): string {
    const match = v.match(/v?(\d+)/);
    if (!match) return 'v2';
    return `v${parseInt(match[1]) + 1}`;
  }

  // ── Trigger Cloud Run Job (không spawn Python trong container) ─────────────
  private _runRetrainJob(version: string, jobId: string) {
    this.isRetraining = true;

    const project = this.config.get<string>('GCP_PROJECT') || process.env.GCP_PROJECT;
    const region  = this.config.get<string>('GCP_REGION')  || process.env.GCP_REGION || 'asia-southeast1';
    const url     = `https://run.googleapis.com/v2/projects/${project}/locations/${region}/jobs/retrain-job:run`;

    this.logger.log(`Triggering Cloud Run Job: retrain-job (version: ${version})`);

    const trigger = async () => {
      try {
        const { GoogleAuth } = await import('google-auth-library');
        const auth   = new GoogleAuth({ scopes: ['https://www.googleapis.com/auth/cloud-platform'] });
        const client = await auth.getClient();

        const res = await client.request({
          url,
          method: 'POST',
          data: {
            overrides: {
              containerOverrides: [{
                args: ['retrain_pipeline.py', '--version', version],
                env: [
                  { name: 'GCP_PROJECT', value: project },
                  { name: 'GCS_BUCKET',  value: this.config.get<string>('GCS_BUCKET') || process.env.GCS_BUCKET },
                  { name: 'BQ_DATASET',  value: this.config.get<string>('BQ_DATASET') || process.env.BQ_DATASET || 'aerospace_obs' },
                ],
              }],
            },
          },
        });

        const execution = (res.data as any)?.name?.split('/').pop() ?? 'unknown';
        this.logger.log(`✅ retrain-job started — execution: ${execution}, jobId: ${jobId}`);

      } catch (err: any) {
        this.logger.error(`❌ Failed to trigger retrain-job: ${err.message}`);
      } finally {
        this.isRetraining = false;
      }
    };

    trigger();
  }
}