import 'dotenv/config';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.enableCors({
    // Jamais `origin: true` par défaut (audit 2026-07-27) : sans FRONTEND_URL,
    // seul le dashboard local (port 3002) est autorisé.
    origin: process.env.FRONTEND_URL?.split(',') ?? ['http://localhost:3002'],
    credentials: true,
  });
  // L'API n'a aucune authentification : on n'écoute que la boucle locale par
  // défaut. API_HOST=0.0.0.0 reste possible mais doit être un choix explicite.
  await app.listen(
    process.env.PORT ?? 3001,
    process.env.API_HOST ?? '127.0.0.1',
  );
}
void bootstrap();
