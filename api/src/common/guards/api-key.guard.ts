import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Reflector } from '@nestjs/core';

export const IS_PUBLIC_KEY = 'isPublic';

@Injectable()
export class ApiKeyGuard implements CanActivate {
  constructor(
    private config: ConfigService,
    private reflector: Reflector,
  ) {}

  canActivate(context: ExecutionContext): boolean {
    // Cho phép endpoints được đánh dấu @Public() bỏ qua auth
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) return true;

    const request = context.switchToHttp().getRequest();
    const apiKey =
      request.headers['x-api-key'] ||
      request.query['api_key'];

    const validKey = this.config.get<string>('API_KEY') || 'dev-secret-key';

    if (!apiKey || apiKey !== validKey) {
      throw new UnauthorizedException(
        'Invalid or missing API key. Pass X-API-Key header.',
      );
    }
    return true;
  }
}