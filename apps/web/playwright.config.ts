import { defineConfig } from '@playwright/test';

/**
 * E2E journeys (testing-strategy §4) against a real API + Postgres + the built SPA, with a
 * throwaway synthetic database (tools/e2e/serve.sh). Run with `make e2e`.
 */
const PORT = Number(process.env.E2E_PORT ?? 8123);

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false, // journeys share one seeded database
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.MOMENTUM_E2E_CHROMIUM
      ? { executablePath: process.env.MOMENTUM_E2E_CHROMIUM }
      : {},
  },
  webServer: {
    command: '../../tools/e2e/serve.sh',
    url: `http://localhost:${PORT}/healthz`,
    env: { E2E_PORT: String(PORT) },
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
