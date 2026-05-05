import { IsOptional, IsString, IsInt, Min, Max } from 'class-validator';
import { Type } from 'class-transformer';

export class EarlyWarningQueryDto {
  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(500)
  @Type(() => Number)
  limit: number = 20;

  @IsOptional()
  @IsString()
  tier?: string;         // Critical | High | Medium | Low

  @IsOptional()
  @IsString()
  category?: string;     // Avionics | Hydraulics | ...

  @IsOptional()
  @IsString()
  aircraft?: string;     // partial match, e.g. "C-17"
}