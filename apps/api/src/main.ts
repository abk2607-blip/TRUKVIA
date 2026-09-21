import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { starletteTrailingSlash } from './common/starlette-compat';
import { captureRawBody } from './fin/raw-body';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { logger: ['error', 'warn', 'log'] });
  // Paths this app serves; used by the Starlette trailing-slash port.
  const served = new Set(['/api/vendors', '/api/vendor-bills', '/api/fin/day-book', '/api/fin/day-closures', '/api/fin/day-status']);
  app.use(starletteTrailingSlash(() => served));
  // Must precede Nest's own body parser, which init() installs after this.
  app.use(captureRawBody());
  const port = Number(process.env.PORT ?? 8003);
  await app.listen(port, '127.0.0.1');
  console.log(JSON.stringify({ msg: 'nest_listening', port, url: `http://127.0.0.1:${port}` }));
}

void bootstrap();
