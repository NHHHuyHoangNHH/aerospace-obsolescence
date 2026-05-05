import { Injectable, OnModuleInit, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { BigQuery } from '@google-cloud/bigquery';

@Injectable()
export class DbService implements OnModuleInit {
  private readonly logger = new Logger(DbService.name);
  private bq: BigQuery;
  private project: string;
  private dataset: string;

  constructor(private config: ConfigService) {}

  async onModuleInit() {
    this.project = this.config.get<string>('GCP_PROJECT');
    this.dataset = this.config.get<string>('BQ_DATASET') || 'aerospace_obs';

    if (!this.project) {
      throw new Error('Missing GCP_PROJECT env variable');
    }

    this.bq = new BigQuery({ projectId: this.project });
    this.logger.log(`Connected to BigQuery: ${this.project}.${this.dataset}`);
  }

  // Chạy query BigQuery, trả về rows
  async query<T = any>(sql: string): Promise<T[]> {
    const [rows] = await this.bq.query({ query: sql, location: 'asia-southeast1' });
    return rows as T[];
  }

  // Lấy 1 row đầu tiên
  async queryOne<T = any>(sql: string): Promise<T | null> {
    const rows = await this.query<T>(sql);
    return rows[0] ?? null;
  }

  // Helper: escape string để tránh SQL injection cơ bản
  escape(value: string): string {
    return value.replace(/'/g, "\\'");
  }

  // Helper: table ref đầy đủ
  table(name: string): string {
    return `\`${this.project}.${this.dataset}.${name}\``;
  }
}