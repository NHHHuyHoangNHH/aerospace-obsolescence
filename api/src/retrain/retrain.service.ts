import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DbService } from '../db/db.service';
import { RetrainDto } from './retrain.dto';
import { spawn } from 'child_process';
import * as path from 'path';

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

    // Chạy async, không block response
    this._runRetrainJob(newVersion, jobId);

    return {
      success: true,
      message: 'Retraining job started in background.',
      data: {
        job_id:           jobId,
        new_version:      newVersion,
        previous_version: currentVersion,
        reason,
        target_parts:     dto.target_parts?.length
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

  private _runRetrainJob(version: string, jobId: string) {
    this.isRetraining = true;

    const projectRoot =
      this.config.get<string>('PROJECT_ROOT') ||
      path.resolve(__dirname, '../../../..');

    const python = this.config.get<string>('PYTHON_BIN') || 'python3';

    // GCP env vars truyền vào subprocess
    const gcpEnv = {
      ...process.env,
      GCP_PROJECT: this.config.get<string>('GCP_PROJECT') || process.env.GCP_PROJECT,
      GCS_BUCKET:  this.config.get<string>('GCS_BUCKET')  || process.env.GCS_BUCKET,
      BQ_DATASET:  this.config.get<string>('BQ_DATASET')  || process.env.BQ_DATASET || 'aerospace_obs',
    };

    // Chạy 2 scripts tuần tự: train.py → embeddings.py
    this._spawnScript(
      python,
      [path.join(projectRoot, 'engine', 'train.py'), '--version', version],
      projectRoot,
      gcpEnv,
      jobId,
      'train.py',
      (trainCode) => {
        if (trainCode !== 0) {
          this.logger.error(`❌ train.py failed (exit ${trainCode}) — skipping embeddings`);
          this.isRetraining = false;
          return;
        }
        this.logger.log(`✅ train.py done — running embeddings.py...`);
        this._spawnScript(
          python,
          [path.join(projectRoot, 'engine', 'embeddings.py'), '--top-n', '50', '--rebuild-index'],
          projectRoot,
          gcpEnv,
          jobId,
          'embeddings.py',
          (embedCode) => {
            this.isRetraining = false;
            if (embedCode === 0) {
              this.logger.log(`✅ Retrain job ${jobId} completed (version: ${version})`);
            } else {
              this.logger.error(`❌ embeddings.py failed (exit ${embedCode})`);
            }
          },
        );
      },
    );
  }

  private _spawnScript(
    python: string,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    jobId: string,
    label: string,
    onClose: (code: number) => void,
  ) {
    this.logger.log(`Running: ${python} ${args.join(' ')}`);
    const child = spawn(python, args, { cwd, env });

    child.stdout.on('data', (d) =>
      this.logger.log(`[${label}] ${d.toString().trim()}`),
    );
    child.stderr.on('data', (d) =>
      this.logger.warn(`[${label} stderr] ${d.toString().trim()}`),
    );
    child.on('close', onClose);
    child.on('error', (err) => {
      this.logger.error(`Failed to spawn ${label}: ${err.message}`);
      this.isRetraining = false;
    });
  }
}