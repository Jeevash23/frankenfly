import {expect, openApp, resetToy, test} from './helpers';

test.beforeEach(async ({request}) => {
  await resetToy(request);
});

test('pages survive a reload and follow Back and Forward', async ({page}) => {
  await openApp(page);
  const nav = page.getByRole('navigation', {name: 'Main navigation'});
  await nav.getByRole('link', {name: 'Atlas'}).click();
  await expect(page).toHaveURL(/#\/anatomy\/atlas$/);
  await nav.getByRole('link', {name: 'Build a circuit'}).click();
  await expect(page).toHaveURL(/#\/connectome\/build$/);
  await expect(nav.getByRole('link', {name: 'Build a circuit'})).toHaveAttribute(
    'aria-current',
    'page',
  );

  await page.reload();
  await expect(page.getByRole('heading', {level: 1, name: 'Build a circuit'})).toBeVisible();
  await expect(nav.getByRole('link', {name: 'Build a circuit'})).toHaveAttribute(
    'aria-current',
    'page',
  );
  // The committed side-balanced circuits are listed like the others, and say how they were built.
  const circuits = page.getByRole('table').filter({hasText: 'Seeds · readout'});
  await expect(
    circuits.getByRole('row', {name: /^fafb783-dna02-balanced committed · left\/right balanced/}),
  ).toBeVisible();
  await expect(circuits.getByRole('row', {name: /^fafb783-dna02 committed\b/})).not.toContainText(
    'balanced',
  );

  await page.goBack();
  await expect(page).toHaveURL(/#\/anatomy\/atlas$/);
  await expect(page.getByRole('heading', {level: 1, name: 'Male & female anatomy'})).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#\/connectome\/build$/);

  await nav.getByRole('link', {name: 'Protocols & comparisons'}).click();
  await expect(page).toHaveURL(/#\/experiments\/protocols$/);
  await page.reload();
  await expect(
    page.getByRole('heading', {level: 1, name: 'Protocols & comparisons'}),
  ).toBeVisible();
});

test('the builder sends side balance, never with a whole-brain build', async ({page, request}) => {
  test.skip(
    !(await request.get('/api/connectome/catalog')).ok(),
    'The builder form needs the prepared FlyWire catalog (scripts/build_circuit.py prepare).',
  );
  await openApp(page, '#/connectome/build');
  await page.getByLabel('Circuit name').fill('e2e-never-built');
  await page.getByLabel('Add a seed').fill('DNa02');
  await page.getByRole('button', {name: 'Add seed', exact: true}).click();
  const balance = page.getByRole('checkbox', {name: /^Balance left and right/});
  await expect(balance).toHaveAccessibleName(/sampling assumption, not a correction/);
  await balance.check();
  await expect(page.getByRole('button', {name: 'Build circuit'})).toBeEnabled();
  await page.getByRole('checkbox', {name: /^Whole brain/}).check();
  await expect(page.getByText(/a whole-brain build has no cap/)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Build circuit'})).toBeDisabled();
});

// The suite never quits: the server is shared by every test and stopped by Playwright.
test('the Quit dialog opens and can be dismissed', async ({page}) => {
  await openApp(page);
  await page.getByRole('button', {name: 'Quit', exact: true}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', {name: 'Finish this session.'})).toBeVisible();
  await expect(dialog.getByRole('button', {name: /Save current run & quit/})).toBeVisible();
  await expect(dialog.getByRole('button', {name: 'Quit without saving'})).toBeVisible();
  await dialog.getByRole('button', {name: 'Keep working'}).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('banner').getByText('Local connection')).toBeVisible();
});
