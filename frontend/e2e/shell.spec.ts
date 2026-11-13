import {expect, openApp, resetToy, test} from './helpers';

// The app shell: old addresses, the sidebar, the theme toggle, the command palette and the
// phone drawer.

test.beforeEach(async ({request}) => {
  await resetToy(request);
});

test('addresses from before the sidebar open the page that holds the same view', async ({page}) => {
  for (const [old, now, title] of [
    ['#/experiments', '#/experiments/protocols', 'Protocols & comparisons'],
    ['#/atlas/anatomy', '#/anatomy/atlas', 'Male & female anatomy'],
    ['#/atlas/circuit', '#/connectome/circuit', 'Live circuit'],
    ['#/atlas/build', '#/connectome/build', 'Build a circuit'],
    ['#/atlas/explore', '#/connectome/explorer', 'Connectivity explorer'],
    ['#/atlas/connectivity', '#/anatomy/connectivity', 'Imported connectivity'],
    ['#/somewhere', '#/overview', 'Overview'],
  ]) {
    await page.goto(`/${old}`);
    await expect(page).toHaveURL(new RegExp(`${now.replace(/[/#]/g, '\\$&')}$`));
    await expect(page.getByRole('heading', {level: 1, name: title, exact: true})).toBeVisible();
  }
  // A redirect replaces the old address, so Back does not bounce through it.
  await page.goto('/#/workbench');
  await page.goto('/#/atlas/build');
  await expect(page).toHaveURL(/#\/connectome\/build$/);
  await page.goBack();
  await expect(page).toHaveURL(/#\/workbench$/);
});

test('the Overview summarises the lab and links to every section', async ({page}) => {
  await openApp(page, '#/overview');
  await expect(
    page.getByText('Results are properties of these models, not fly biology.'),
  ).toBeVisible();
  for (const name of [
    'Simulation',
    'Quick actions',
    'Recent runs',
    'Jobs',
    'Scorecards',
    'Plugins',
  ])
    await expect(page.getByRole('heading', {level: 2, name, exact: true})).toBeVisible();
  await expect(page.getByText('PAUSED', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: /Explore DNa02/}).click();
  await expect(page).toHaveURL(/#\/connectome\/explorer$/);
  await expect(page.getByRole('heading', {level: 1, name: 'Connectivity explorer'})).toBeVisible();
  await expect(page.getByLabel('Cell types or neurons', {exact: false}).first()).toHaveValue(
    /DNa02/,
  );
});

test('the theme toggle switches to dark, is remembered, and can follow the system again', async ({
  page,
}) => {
  await page.emulateMedia({colorScheme: 'light'});
  await openApp(page, '#/overview');
  const html = page.locator('html');
  const canvas = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const light = await canvas();
  await page.getByRole('button', {name: 'Switch to the dark theme'}).click();
  await expect(html).toHaveAttribute('data-theme', 'dark');
  expect(await canvas()).not.toBe(light);
  expect(await page.evaluate(() => localStorage.getItem('digitalfly.theme'))).toBe('dark');

  // Remembered across a reload, applied before the app starts.
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByRole('button', {name: 'Switch to the light theme'})).toBeVisible();

  // Without a choice, the system's dark preference applies through the media query.
  await page.evaluate(() => localStorage.removeItem('digitalfly.theme'));
  await page.emulateMedia({colorScheme: 'dark'});
  await page.reload();
  await expect(html).not.toHaveAttribute('data-theme', /./);
  expect(await canvas()).not.toBe(light);
  await page.getByRole('button', {name: 'Switch to the light theme'}).click();
  await expect(html).toHaveAttribute('data-theme', 'light');
  expect(await canvas()).toBe(light);
});

test('Ctrl+K opens the command palette to jump to pages and run actions', async ({page}) => {
  await openApp(page, '#/workbench');
  await page.keyboard.press('Control+k');
  const palette = page.getByRole('dialog', {name: 'Command palette'});
  await expect(palette).toBeVisible();
  const search = palette.getByRole('combobox', {name: /Search pages/});
  await expect(search).toBeFocused();
  await search.fill('run lib');
  await expect(palette.getByRole('option').first()).toContainText('Run library');
  await page.keyboard.press('Enter');
  await expect(palette).toHaveCount(0);
  await expect(page).toHaveURL(/#\/experiments\/library$/);

  // Arrow keys move the highlight; Escape closes.
  await page.keyboard.press('Control+k');
  await search.fill('score');
  const options = palette.getByRole('option');
  await expect(options.first()).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('ArrowDown');
  await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('Escape');
  await expect(palette).toHaveCount(0);

  // An action: the theme.
  await page.getByRole('button', {name: 'Search pages, actions and cell types'}).click();
  await search.fill('dark theme');
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('the sidebar collapses to icons and remembers it; arrow keys move between pages', async ({
  page,
}) => {
  await openApp(page, '#/overview');
  const nav = page.getByRole('navigation', {name: 'Main navigation'});
  await page.getByRole('button', {name: 'Collapse the sidebar'}).click();
  await expect(page.locator('.app-shell')).toHaveAttribute('data-sidebar', 'collapsed');
  // The labels hide, the links keep their names.
  await expect(nav.getByRole('link', {name: 'Run library'})).toBeVisible();
  await page.reload();
  await expect(page.locator('.app-shell')).toHaveAttribute('data-sidebar', 'collapsed');
  await page.getByRole('button', {name: 'Expand the sidebar'}).click();
  await expect(page.locator('.app-shell')).toHaveAttribute('data-sidebar', 'expanded');

  await nav.getByRole('link', {name: 'Overview'}).focus();
  await page.keyboard.press('ArrowDown');
  await expect(nav.getByRole('link', {name: 'Workbench'})).toBeFocused();
  await page.keyboard.press('End');
  await expect(nav.getByRole('link', {name: 'Agents & MCP'})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/extend\/agents$/);
});

test('on a phone the sidebar is a drawer', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await openApp(page, '#/overview');
  const nav = page.getByRole('navigation', {name: 'Main navigation'});
  await expect(nav).toBeHidden();
  await page.getByRole('button', {name: 'Open navigation'}).click();
  await expect(nav).toBeVisible();
  await nav.getByRole('link', {name: 'Scorecard'}).click();
  await expect(page).toHaveURL(/#\/validate\/scorecard$/);
  await expect(nav).toBeHidden();
  await expect(page.getByRole('heading', {level: 1, name: 'Validation scorecard'})).toBeFocused();
  // Escape closes it too, and nothing scrolls sideways.
  await page.getByRole('button', {name: 'Open navigation'}).click();
  await page.keyboard.press('Escape');
  await expect(nav).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
