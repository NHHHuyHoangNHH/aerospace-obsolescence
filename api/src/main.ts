import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  app.useGlobalPipes(new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
    transform: true,
  }));

  app.setGlobalPrefix('api/v1');

  const port = process.env.PORT || 3000;
  await app.listen(port);
  console.log(`\n🚀 API running on http://localhost:${port}/api/v1`);
  console.log(`   GET  /api/v1/parts/:id/risk-score`);
  console.log(`   GET  /api/v1/parts/early-warning`);
  console.log(`   POST /api/v1/retrain`);
}
bootstrap();