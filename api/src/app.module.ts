import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { APP_FILTER, APP_GUARD, Reflector } from '@nestjs/core';
import { DbModule } from './db/db.module';
import { PartsModule } from './parts/parts.module';
import { RetrainModule } from './retrain/retrain.module';
import { ApiKeyGuard } from './common/guards/api-key.guard';
import { AllExceptionsFilter } from './common/filters/all-exceptions.filter';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    DbModule,
    PartsModule,
    RetrainModule,
  ],
  providers: [
    Reflector,
    { provide: APP_FILTER, useClass: AllExceptionsFilter },
  ],
})
export class AppModule {}