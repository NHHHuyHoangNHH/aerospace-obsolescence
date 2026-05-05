import { Controller, Post, Get, Body, UseGuards } from '@nestjs/common';
import { RetrainService } from './retrain.service';
import { RetrainDto } from './retrain.dto';
import { ApiKeyGuard } from '../common/guards/api-key.guard';

@Controller('retrain')
@UseGuards(ApiKeyGuard)
export class RetrainController {
  constructor(private readonly retrainService: RetrainService) {}

  /**
   * POST /api/v1/retrain
   * Trigger retrain ML model với data mới.
   *
   * Body (optional):
   *   version      — "v2" (nếu không truyền tự tăng)
   *   reason       — "new_csv_upload" | "scheduled_weekly" | ...
   *   target_parts — ["BCA-00001", "AES-00042"] (nếu không → toàn bộ)
   *
   * Response trả về ngay (job chạy async ở background).
   * Dùng GET /retrain/status để kiểm tra tiến trình.
   */
  @Post()
  async triggerRetrain(@Body() dto: RetrainDto) {
    return this.retrainService.triggerRetrain(dto);
  }

  /**
   * GET /api/v1/retrain/status
   * Xem trạng thái retrain hiện tại + lịch sử các model version.
   */
  @Get('status')
  async status() {
    return this.retrainService.getStatus();
  }
}