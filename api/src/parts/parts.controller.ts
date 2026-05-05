import {
  Controller,
  Get,
  Param,
  Query,
  UseGuards,
} from '@nestjs/common';
import { PartsService } from './parts.service';
import { EarlyWarningQueryDto } from './parts.dto';
import { ApiKeyGuard } from '../common/guards/api-key.guard';

@Controller('parts')
@UseGuards(ApiKeyGuard)
export class PartsController {
  constructor(private readonly partsService: PartsService) {}

  /**
   * GET /api/v1/parts/early-warning
   * Trả về danh sách parts risk cao nhất.
   *
   * Query params:
   *   limit    — số lượng trả về (default 20, max 500)
   *   tier     — filter theo risk tier: Critical | High | Medium | Low
   *   category — filter theo category: Avionics | Hydraulics | ...
   *   aircraft — partial match tên aircraft model
   *
   * Phải đặt TRƯỚC /:id để NestJS không nhầm "early-warning" là part_id
   */
  @Get('early-warning')
  async earlyWarning(@Query() query: EarlyWarningQueryDto) {
    return this.partsService.getEarlyWarning({
      limit:    query.limit,
      tier:     query.tier,
      category: query.category,
      aircraft: query.aircraft,
    });
  }

  /**
   * GET /api/v1/parts/stats
   * Dashboard stats: tổng số parts, phân bố risk tier, model version...
   */
  @Get('stats')
  async stats() {
    return this.partsService.getStats();
  }

  /**
   * GET /api/v1/parts/:id/risk-score
   * Risk score + evidence cho 1 part cụ thể.
   *
   * Response gồm:
   *   - thông tin part
   *   - risk score + tier + top features
   *   - risk factors giải thích tại sao risk cao
   *   - related articles (đã rerank bằng Cross-Encoder)
   */
  @Get(':id/risk-score')
  async riskScore(@Param('id') id: string) {
    return this.partsService.getRiskScore(id);
  }
}