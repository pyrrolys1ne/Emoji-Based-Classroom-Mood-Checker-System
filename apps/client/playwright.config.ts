import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

process.env.PLAYWRIGHT_BROWSERS_PATH ??= fileURLToPath(
  new URL('../../.local/browsers', import.meta.url),
);
const cwd = fileURLToPath(new URL('.', import.meta.url));
const chromiumChannel = process.env.PLAYWRIGHT_CHROMIUM_CHANNEL;
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  workers: 2,
  timeout: 45000,
  expect: { timeout: 10000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5184',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: '**/api.spec.ts',
      use: {
        browserName: 'chromium',
        channel: chromiumChannel,
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'firefox',
      testIgnore: '**/api.spec.ts',
      use: { browserName: 'firefox', viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      testIgnore: '**/api.spec.ts',
      use: {
        browserName: 'chromium',
        channel: chromiumChannel,
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'api-chromium',
      testMatch: '**/api.spec.ts',
      use: { browserName: 'chromium', channel: chromiumChannel, baseURL: 'http://127.0.0.1:5185' },
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --port 5184 --strictPort',
      cwd,
      env: { VITE_DATA_MODE: 'demo' },
      url: 'http://127.0.0.1:5184',
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: 'npm run dev -- --port 5185 --strictPort',
      cwd,
      env: { VITE_DATA_MODE: 'api' },
      url: 'http://127.0.0.1:5185',
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
