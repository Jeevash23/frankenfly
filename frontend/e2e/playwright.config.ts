// End-to-end tests of the built app against the kinematic toy engine, in headless Chromium.
// Run from the repository with `npm --prefix frontend run build` then `npm --prefix frontend run e2e`.
// The backend's environment (backend/.venv) must exist; the server is started here and stopped after.
import {defineConfig, devices} from '@playwright/test';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const PORT = 8199;

export default defineConfig({
  testDir: '.',
  outputDir: 'test-results',
  // One simulation per server: tests share it, so they run one at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 90_000,
  expect: {timeout: 15_000},
  reporter: process.env.CI
    ? [['list'], ['html', {open: 'never', outputFolder: 'playwright-report'}]]
    : [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: `http://127.0.0.1:${PORT}`,
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Chromium comes from PLAYWRIGHT_BROWSERS_PATH (here /opt/pw-browsers) or `npx playwright install`.
  webServer: {
    command: `./scripts/start.sh --toy --port ${PORT}`,
    cwd: ROOT,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
