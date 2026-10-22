import {expect, test as base, type APIRequestContext, type Page} from '@playwright/test';

// The toy engine with the engineered model and geometric sensing: what start.sh --toy runs.
export const TOY = {engine: 'toy', sensor_model: 'geometric', neural_model: 'engineered'};

// A name no earlier run of the suite has used, for tags and presets.
export const unique = (prefix: string) =>
  `${prefix}-${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;

// A fresh toy run, paused, whatever an earlier test left selected.
export async function resetToy(request: APIRequestContext, config: object = {}) {
  const response = await request.post('/api/reset', {data: {...TOY, ...config}});
  expect(response.ok(), await response.text()).toBe(true);
}

export async function status(request: APIRequestContext) {
  const response = await request.get('/api/status');
  expect(response.ok()).toBe(true);
  return response.json();
}

// Deletes saved runs; a run of the live run is released by a reset first.
export async function deleteRuns(request: APIRequestContext, keys: Iterable<string>) {
  const all = [...keys];
  if (!all.length) return;
  await resetToy(request);
  for (const key of all) {
    const response = await request.delete(`/api/runs/${key}`);
    expect([200, 404], `delete ${key}`).toContain(response.status());
  }
}

// The app at a page, once it is connected to the local server.
export async function openApp(page: Page, hash = '#/workbench') {
  await page.goto(`/${hash}`);
  await expect(page.getByRole('banner').getByText('Local connection')).toBeVisible();
}

// Uncaught page errors fail every test; console errors are collected for the tests that check them.
export const test = base.extend<{consoleErrors: string[]}>({
  consoleErrors: [
    async ({page}, use) => {
      const errors: string[] = [];
      const uncaught: string[] = [];
      page.on('console', (message) => {
        if (message.type() === 'error') errors.push(message.text());
      });
      page.on('pageerror', (error) => uncaught.push(error.message));
      await use(errors);
      expect(uncaught, 'uncaught errors in the page').toEqual([]);
    },
    {auto: true},
  ],
});

export {expect};
