import {expect, openApp, resetToy, status, test, unique} from './helpers';

const presets = new Set<string>();

test.beforeEach(async ({request}) => {
  await resetToy(request);
});

test.afterAll(async ({playwright}) => {
  const request = await playwright.request.newContext({baseURL: test.info().project.use.baseURL});
  for (const name of presets) await request.delete(`/api/configs/${name}`);
  await resetToy(request);
  await request.dispose();
});

test('the app loads without console errors and shows its version', async ({
  page,
  request,
  consoleErrors,
}) => {
  await openApp(page);
  await expect(page.getByRole('heading', {name: /The sensorimotor workbench/})).toBeVisible();
  const {version} = await (await request.get('/api/health')).json();
  await expect(page.getByRole('banner').getByText(`v${version}`, {exact: true})).toBeVisible();
  await expect(page.getByText('PAUSED', {exact: true})).toBeVisible();
  await expect(page.getByText('Toy demo: a kinematic body, not FlyGym physics')).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test('run, pause and step', async ({page, request}) => {
  await openApp(page);
  await page.getByRole('button', {name: /Run simulation/}).click();
  await expect(page.getByText('RUNNING', {exact: true})).toBeVisible();
  await expect.poll(async () => (await status(request)).sample.step).toBeGreaterThan(0);
  await page.getByRole('button', {name: /Pause/}).click();
  await expect(page.getByText('PAUSED', {exact: true})).toBeVisible();

  // Space runs and pauses too, when no control has focus.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press('Space');
  await expect(page.getByText('RUNNING', {exact: true})).toBeVisible();
  await page.keyboard.press('Space');
  await expect(page.getByText('PAUSED', {exact: true})).toBeVisible();

  const before = (await status(request)).sample.step;
  await page.getByRole('button', {name: 'Step', exact: true}).click();
  await expect.poll(async () => (await status(request)).sample.step).toBe(before + 1);
  expect((await status(request)).status).toBe('paused');
});

test('the target moves by clicking the arena and with the arrow keys', async ({page, request}) => {
  await openApp(page);
  const arena = page.getByRole('application', {name: /Arena map/}).first();
  const box = (await arena.boundingBox())!;
  // The square drawing area, letterboxed in the element; (20, 20) mm is three quarters across
  // and a quarter down.
  const side = Math.min(box.width, box.height);
  const left = box.x + (box.width - side) / 2,
    top = box.y + (box.height - side) / 2;
  await page.mouse.click(left + side * 0.75, top + side * 0.25);
  await expect
    .poll(async () => (await status(request)).config.stimulus)
    .toMatchObject({x: expect.closeTo(20, 0), y: expect.closeTo(20, 0)});
  const {x, y} = (await status(request)).config.stimulus;
  await expect(page.getByLabel('Target X position')).toHaveValue(String(x));

  await arena.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Shift+ArrowDown');
  const moved = {x: Math.round((x + 1) * 10) / 10, y: Math.round((y - 5) * 10) / 10};
  await expect.poll(async () => (await status(request)).config.stimulus).toMatchObject(moved);
  await expect(page.getByLabel('Target X position')).toHaveValue(String(moved.x));
  await expect(page.getByLabel('Target Y position')).toHaveValue(String(moved.y));
  await expect(arena).toHaveAccessibleName(new RegExp(`target at \\(${moved.x}, ${moved.y}\\)`));
});

test('the connectome model takes a cell-type manipulation', async ({page, request}) => {
  await openApp(page);
  await page.getByLabel('Neural model').selectOption({label: 'Connectome circuit'});
  await expect.poll(async () => (await status(request)).config.neural_model).toBe('connectome');
  await expect(page.getByRole('combobox', {name: 'Connectome circuit'})).toBeVisible();

  const cellType = page.getByRole('combobox', {name: 'Cell type', exact: true});
  await expect(cellType).toBeEnabled({timeout: 30_000});
  await cellType.fill('DNa02');
  await page.getByLabel('Side', {exact: true}).selectOption('left');
  await page.getByLabel('Manipulation', {exact: true}).selectOption('silence');
  await page.getByRole('button', {name: /^Apply DNa02 left silenced/}).click();

  const inForce = page.getByRole('list', {name: 'Cell-type manipulations in force'});
  await expect(inForce.getByText('DNa02 left silenced')).toBeVisible();
  await expect
    .poll(async () => (await status(request)).interventions.cell_types)
    .toEqual([{name: 'DNa02', side: 'left', mode: 'silence', value: 0}]);
  await page.getByRole('button', {name: 'Remove: DNa02 left silenced'}).click();
  await expect(inForce).toHaveCount(0);

  // Activation needs a value above 0; a type is held at rest by silencing it.
  await cellType.fill('DNa02');
  await page.getByLabel('Manipulation', {exact: true}).selectOption('activate');
  const rate = page.getByLabel('Clamped rate', {exact: true});
  await expect(rate).toHaveValue('0.6');
  await rate.fill('0');
  await expect(page.getByText(/clamps the rate above 0, up to 1/)).toBeVisible();
  await expect(page.getByRole('button', {name: /activated \(rate 0\)$/})).toBeDisabled();
  await rate.fill('0.3');
  await page.getByRole('button', {name: /^Apply DNa02 left activated \(rate 0\.3\)/}).click();
  await expect(inForce.getByText('DNa02 left activated (rate 0.3)')).toBeVisible();
  await expect
    .poll(async () => (await status(request)).interventions.cell_types)
    .toEqual([{name: 'DNa02', side: 'left', mode: 'activate', value: 0.3}]);
});

test('presets are saved, loaded and deleted', async ({page, request}) => {
  const name = unique('e2e-preset');
  presets.add(name);
  await openApp(page);
  await page.getByRole('button', {name: 'Save current settings as preset'}).click();
  await page.getByLabel('Preset name').fill(name);
  await page.getByLabel('Description (optional)').fill('Saved by the end-to-end tests');
  await page.getByRole('button', {name: 'Save preset'}).click();
  await expect(page.getByText(`Saved the current settings as ${name}.`)).toBeVisible();
  const picker = page.getByLabel('Named configuration');
  await expect(picker).toHaveValue(name);

  // A run that has advanced asks before it is replaced.
  await page.getByRole('button', {name: 'Step', exact: true}).click();
  await expect.poll(async () => (await status(request)).sample.step).toBe(1);
  await page.getByRole('button', {name: 'Load preset'}).click();
  const confirm = page.getByRole('group', {name: 'Replace the current run?'});
  const loaded = page.getByText(`Loaded ${name}. The run starts paused.`);
  await expect(confirm.or(loaded)).toBeVisible();
  if (await confirm.isVisible()) await confirm.getByRole('button', {name: `Load ${name}`}).click();
  await expect(loaded).toBeVisible();
  expect((await status(request)).sample.step).toBe(0);

  await page.getByRole('button', {name: `Delete preset ${name}`}).click();
  await page
    .getByRole('group', {name: `Delete ${name}?`})
    .getByRole('button', {name: 'Delete', exact: true})
    .click();
  await expect(page.getByText(`Deleted ${name}.`)).toBeVisible();
  const {configs} = await (await request.get('/api/configs')).json();
  expect(configs.map((c: {name: string}) => c.name)).not.toContain(name);
  presets.delete(name);
});
