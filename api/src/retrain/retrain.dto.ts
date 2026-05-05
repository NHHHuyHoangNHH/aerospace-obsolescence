import { IsOptional, IsString, IsArray } from 'class-validator';

export class RetrainDto {
  /**
   * Version string cho model mới.
   * Nếu không truyền, tự tăng từ version hiện tại.
   */
  @IsOptional()
  @IsString()
  version?: string;

  /**
   * Lý do retrain — để log và audit.
   * Ví dụ: "new_csv_upload" | "new_articles" | "scheduled_weekly"
   */
  @IsOptional()
  @IsString()
  reason?: string;

  /**
   * Danh sách part_id muốn score lại sau khi retrain.
   * Nếu không truyền → score toàn bộ parts.
   */
  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  target_parts?: string[];
}