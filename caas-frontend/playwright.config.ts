import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for hopnshoppe.
 *
 * Prerequisite: `docker compose up -d` must be running with all services healthy.
 *
 * Run: npm run test:e2e
 * Report: npm run test:e2e:report
 */
export default defineConfig({
  testDir: './e2e/tests',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  timeout: 30_000,
  expect: { timeout: 10_000 },
});
