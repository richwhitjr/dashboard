import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: 'demo-capture.spec.ts',
      use: { browserName: 'chromium' },
    },
    {
      name: 'demo-capture',
      testMatch: 'demo-capture.spec.ts',
      use: {
        browserName: 'chromium',
        viewport: { width: 1280, height: 800 },
        video: { mode: 'on', size: { width: 1280, height: 800 } },
        screenshot: 'off',
        launchOptions: { slowMo: 50 },
      },
    },
  ],
});
