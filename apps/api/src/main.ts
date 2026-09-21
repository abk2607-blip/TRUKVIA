import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { starletteTrailingSlash } from './common/starlette-compat';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { logger: ['error', 'warn', 'log'] });
  // Paths this app serves; used by the Starlette trailing-slash port.
  const served = new Set(['/api/vendors', '/api/vendor-bills', '/api/fin/day-book', '/api/fin/day-closures']);
  app.use(starletteTrailingSlash(() => served));
  const port = Number(process.env.PORT ?? 8003);
  await app.listen(port, '127.0.0.1');
  console.log(JSON.stringify({ msg: 'nest_listening', port, url: `http://127.0.0.1:${port}` }));
}

void bootstrap();
