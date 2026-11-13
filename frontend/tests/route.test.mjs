import test from 'node:test';
import assert from 'node:assert/strict';
import {GROUPS, REDIRECTS, ROUTES, ROUTE_IDS, parseHash, routeHash} from '../src/route.ts';

test('every page has a unique address in one of the sidebar groups', () => {
  assert.equal(new Set(ROUTES.map((r) => r.path)).size, ROUTES.length);
  assert.equal(new Set(ROUTE_IDS).size, ROUTES.length);
  for (const r of ROUTES) {
    assert.ok(GROUPS.includes(r.group), `${r.id} is in a known group`);
    assert.match(r.path, /^\/[a-z]+(\/[a-z]+)?$/);
    assert.ok(r.description.length > 20 && r.description.length < 110, `${r.id} has one line`);
  }
  // The groups the sidebar shows, in order, with the pages the redesign asked for.
  const grouped = Object.fromEntries(GROUPS.map((g) => [g, ROUTES.filter((r) => r.group === g)]));
  assert.deepEqual(
    grouped.Experiments.map((r) => r.id),
    ['protocols', 'library', 'jobs'],
  );
  assert.deepEqual(
    grouped.Connectome.map((r) => r.id),
    ['explorer', 'build', 'circuit'],
  );
  assert.deepEqual(
    grouped.Anatomy.map((r) => r.id),
    ['atlas', 'connectivity'],
  );
  assert.deepEqual(
    grouped.Extend.map((r) => r.id),
    ['plugins', 'agents'],
  );
});

test('the canonical addresses parse to their page without a redirect', () => {
  for (const r of ROUTES) {
    const parsed = parseHash(`#${r.path}`);
    assert.equal(parsed.route, r.id);
    assert.equal(parsed.redirect, null, r.path);
    assert.equal(routeHash(r.id), `#${r.path}`);
  }
});

test('addresses from before the sidebar redirect to the page that holds the same view', () => {
  const expected = {
    '#/experiments': 'protocols',
    '#/atlas': 'atlas',
    '#/atlas/anatomy': 'atlas',
    '#/atlas/circuit': 'circuit',
    '#/atlas/build': 'build',
    '#/atlas/explore': 'explorer',
    '#/atlas/connectivity': 'connectivity',
    // Without the leading slash, as some old links were written.
    '#atlas/build': 'build',
    '#experiments': 'protocols',
  };
  for (const [hash, route] of Object.entries(expected)) {
    const parsed = parseHash(hash);
    assert.equal(parsed.route, route, hash);
    assert.equal(parsed.redirect, routeHash(route), hash);
  }
  // Every redirect lands on a real page.
  for (const target of Object.values(REDIRECTS)) assert.ok(ROUTE_IDS.includes(target));
});

test('section roots, trailing slashes and missing addresses resolve, unknown ones open the Overview', () => {
  assert.deepEqual(
    [
      parseHash('#/validate'),
      parseHash('#/connectome'),
      parseHash('#/anatomy'),
      parseHash('#/extend'),
    ].map((r) => r.route),
    ['scorecard', 'explorer', 'atlas', 'plugins'],
  );
  assert.equal(parseHash('#/workbench/').route, 'workbench');
  assert.equal(parseHash('#/workbench/').redirect, '#/workbench');
  assert.equal(parseHash('#workbench').redirect, '#/workbench');
  for (const hash of ['', '#', '#/']) {
    assert.equal(parseHash(hash).route, 'overview');
    assert.equal(parseHash(hash).redirect, '#/overview');
  }
  const unknown = parseHash('#/somewhere/else');
  assert.equal(unknown.route, 'overview');
  assert.equal(unknown.redirect, '#/overview');
});

test('parameters survive a redirect', () => {
  const parsed = parseHash('#/atlas/explore?type=DNa02');
  assert.equal(parsed.route, 'explorer');
  assert.equal(parsed.params.get('type'), 'DNa02');
  assert.equal(parsed.redirect, '#/connectome/explorer?type=DNa02');
  assert.equal(parseHash('#/connectome/explorer?type=LC10a').redirect, null);
});
