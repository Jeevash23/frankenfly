import {deleteRuns, expect, openApp, resetToy, status, test, unique} from './helpers';

// Every run these tests save, deleted after them.
const created = new Set<string>();

test.beforeEach(async ({request}) => {
  await resetToy(request);
});

test.afterAll(async ({playwright}) => {
  const request = await playwright.request.newContext({baseURL: test.info().project.use.baseURL});
  await deleteRuns(request, created);
  await request.dispose();
});

test('a comparison at full speed completes and shows its statistics', async ({page, request}) => {
  await openApp(page, '#/experiments/protocols');
  await page.getByLabel('Comparison seeds').fill('1, 2');
  for (const condition of ['Neural control', 'Left sensor off'])
    await page.getByRole('checkbox', {name: condition, exact: true}).check();
  await page.getByRole('checkbox', {name: /Run as fast as possible/}).check();
  await page.getByRole('button', {name: 'Run comparison'}).click();

  const progress = page.getByRole('region', {name: 'Comparison progress'});
  await expect(progress.getByText(/^COMPLETED/)).toBeVisible({timeout: 60_000});
  const batch = (await status(request)).batch;
  const listing = await request.get(`/api/runs?batch=${batch.id}`);
  for (const run of (await listing.json()).runs) created.add(run.key);
  expect(created.size).toBe(4);

  const statistics = page.getByRole('region', {name: 'Comparison statistics'});
  const conditions = statistics.getByRole('table', {name: /^Per condition/});
  await expect(conditions.getByRole('row', {name: /^Neural control/})).toBeVisible();
  await expect(conditions.getByRole('row', {name: /^Left sensor off/})).toBeVisible();
  // Two seeds: the sample is small, and the table says so.
  await expect(conditions.getByText('small n').first()).toBeVisible();
  await expect(statistics.getByText(/^Small samples: as few as 2 trials/)).toBeVisible();
  const paired = statistics.getByRole('table', {name: /^Paired difference from Neural control/});
  await expect(paired.getByRole('row', {name: /^Left sensor off/})).toBeVisible();
  await expect(
    statistics.getByRole('img', {name: /per condition: mean with 95% interval/}),
  ).toBeVisible();
  await statistics.getByLabel('Metric to chart').selectOption({label: 'Net turn (°)'});
  await expect(statistics.getByRole('img', {name: /^Net turn/})).toBeVisible();

  const csv = await statistics.getByRole('link', {name: 'Download CSV'}).getAttribute('href');
  expect(csv).toBe(`/api/batches/${batch.id}/summary?format=csv`);
  const text = await (await request.get(csv!)).text();
  expect(text.split('\n')[0]).toBe('kind,condition,baseline,metric,n,mean,sd,ci95_low,ci95_high');

  // The library, on its own page, lists the comparison's trials.
  await statistics.getByRole('button', {name: 'Show these trials in the library'}).click();
  await expect(page).toHaveURL(/#\/experiments\/library$/);
  await expect(page.getByLabel('Filter by comparison ID')).toHaveValue(batch.id);
  await expect(page.getByText(/Showing 4 of 4 matching runs/)).toBeVisible();
});

test('a share-safe export is tagged, found by its tag and verified by replay', async ({
  page,
  request,
}) => {
  const tag = unique('e2e');
  await openApp(page);
  for (let i = 1; i <= 3; i++) {
    await page.getByRole('button', {name: 'Step', exact: true}).click();
    await expect.poll(async () => (await status(request)).sample.step).toBe(i);
  }
  await page.getByRole('checkbox', {name: /Share-safe export/}).check();
  await page.getByRole('button', {name: /Export this run/}).click();
  await expect(page.getByRole('status').filter({hasText: 'share-safe'})).toBeVisible();
  const href = await page.getByRole('link', {name: /Download ZIP/}).getAttribute('href');
  const key = href!.match(/\/api\/exports\/(.+)\.zip$/)![1];
  created.add(key);

  await page
    .getByRole('navigation', {name: 'Main navigation'})
    .getByRole('link', {name: 'Run library'})
    .click();
  await page.getByRole('searchbox', {name: 'Search runs'}).fill(key);
  // Each row's export menu is named after its run.
  const row = page
    .getByRole('row')
    .filter({has: page.locator(`summary[aria-label="Export run ${key}"]`)});
  await expect(row).toHaveCount(1);
  await expect(page.getByText(/Showing 1 of 1 matching run\b/)).toBeVisible();

  // Tags are checked before they are sent.
  await row.getByRole('button', {name: `Edit the tags and notes of run ${key}`}).click();
  const form = page.getByRole('form', {name: `Tags and notes of run ${key}`});
  await form.getByLabel('Tags').fill('not/a tag');
  await expect(form.getByText(/is not a tag/)).toBeVisible();
  await expect(form.getByRole('button', {name: 'Save tags and notes'})).toBeDisabled();
  await form.getByLabel('Tags').fill(`${tag}, share-safe`);
  await form.getByLabel('Notes').fill('Exported by the end-to-end tests.');
  await form.getByRole('button', {name: 'Save tags and notes'}).click();
  await expect(page.getByText(`Saved the tags and notes of ${key}.`)).toBeVisible();
  await expect(form).toHaveCount(0);
  const saved = await (await request.get(`/api/runs/${key}`)).json();
  expect(saved.tags).toEqual([tag, 'share-safe']);

  // Filtering by the tag finds this run alone; the chip filters too.
  // Without filters the library lists every run (the comparison's above too).
  const unfiltered = page.getByText(/Showing \d+ of \d+ runs\./);
  await page.getByRole('searchbox', {name: 'Search runs'}).fill('');
  await expect(unfiltered).toBeVisible();
  await page.getByLabel('Filter by tag').fill(tag);
  await expect(page.getByText(/Showing 1 of 1 matching run\b/)).toBeVisible();
  await expect(row).toHaveCount(1);
  await page.getByRole('button', {name: 'Clear filters'}).first().click();
  await expect(page.getByLabel('Filter by tag')).toHaveValue('');
  await expect(unfiltered).toBeVisible();
  await row.getByRole('button', {name: `Show runs tagged ${tag}`}).click();
  await expect(page.getByLabel('Filter by tag')).toHaveValue(tag);
  await expect(row.getByRole('button', {name: `Show runs tagged ${tag}`})).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByText(/Showing 1 of 1 matching run\b/)).toBeVisible();

  await row.getByRole('button', {name: `Verify replay of ${key}`}).click();
  await expect(row.getByText('✓ verified')).toBeVisible({timeout: 60_000});
});
