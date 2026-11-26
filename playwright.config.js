import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
    { name: 'mobile-webkit', use: { ...devices['iPhone 13'] } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run build && .venv/bin/uvicorn tests.e2e.app:app --host 127.0.0.1 --port 4173 --no-access-log',
    url: 'http://127.0.0.1:4173/health',
    env: {
      LITELLM_LOCAL_MODEL_COST_MAP: 'True',
      LLM_MODEL: 'test',
      LLM_API_KEY: 'synthetic-key',
      DATABASE_PATH: ':memory:',
    },
  },
});
