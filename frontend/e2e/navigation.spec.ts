import {expect, openApp, resetToy, test} from './helpers';

test.beforeEach(async ({request}) => {
  await resetToy(request);
});

test('the page and atlas tab survive a reload and follow Back', async ({page}) => {
  await openApp(page);
  await page.getByRole('tab', {name: 'Neural atlas'}).click();
  await expect(page).toHaveURL(/#\/atlas\/anatomy$/);
  await page.getByRole('tab', {name: 'Build a circuit'}).click();
  await expect(page).toHaveURL(/#\/atlas\/build$/);

  await page.reload();
  await expect(page.getByRole('tab', {name: 'Neural atlas'})).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.getByRole('tab', {name: 'Build a circuit'})).toHaveAttribute(
    'aria-selected',
    'true',
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
  await expect(page).toHaveURL(/#\/atlas\/anatomy$/);
  await expect(page.getByRole('tab', {name: 'Male & female anatomy'})).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.goForward();
  await expect(page).toHaveURL(/#\/atlas\/build$/);

  await page.getByRole('tab', {name: 'Experiments'}).click();
  await expect(page).toHaveURL(/#\/experiments$/);
  await page.reload();
  await expect(page.getByRole('heading', {name: /The experiment notebook/})).toBeVisible();
  await expect(page.getByRole('tab', {name: 'Experiments'})).toHaveAttribute(
    'aria-selected',
    'true',
  );
});

test('the builder sends side balance, never with a whole-brain build', async ({page, request}) => {
  test.skip(
    !(await request.get('/api/connectome/catalog')).ok(),
    'The builder form needs the prepared FlyWire catalog (scripts/build_circuit.py prepare).',
  );
  await openApp(page, '#/atlas/build');
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
