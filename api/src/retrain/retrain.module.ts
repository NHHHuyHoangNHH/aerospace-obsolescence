import { Module } from '@nestjs/common';
import { RetrainController } from './retrain.controller';
import { RetrainService } from './retrain.service';

@Module({
  controllers: [RetrainController],
  providers: [RetrainService],
})
export class RetrainModule {}