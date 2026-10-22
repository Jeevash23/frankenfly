## What and why

<!-- What this changes and why. Link the issue it closes, if any. -->

## Checks run

<!-- Tick what you ran locally. CI also runs the backend tests on Python 3.12–3.14, the FlyGym physics tests under Xvfb, the frontend checks and browser end-to-end tests, the dependency audits and, when packaging files change, the Docker build. -->

- [ ] `./scripts/check.sh --fast`
- [ ] FlyGym physics tests (`./scripts/check.sh`, or headless: `xvfb-run -a env MUJOCO_GL=glfw ./scripts/check.sh`); needed when the body, engines, experiment, worker or neural code changes
- [ ] `npm --prefix frontend run format` and `npm --prefix frontend run typecheck`, if the frontend changed
- [ ] New or changed behavior has a test; a bug fix has a regression test
- [ ] Optional-asset tests ran, if relevant (FlyVis, prepared FlyWire archive, recorded fly), or they are listed as skipped below

<!-- Paste the test summary lines, e.g. "88 passed". -->

## Replay impact

<!-- Committed circuits, default parameters and recorded runs must keep producing the same numbers. -->

- [ ] No change to the numbers that existing runs, committed circuits or default settings produce (`scripts/replay.py` still reproduces exported runs; the bitwise FlyGym fast-path test passes)
- [ ] New behavior is behind an option whose default reproduces today's numbers
- [ ] This intentionally changes numbers, because it fixes wrong behavior: explained below and in the `Unreleased` section of CHANGELOG.md

## Data license impact

- [ ] No data files added or changed
- [ ] Data added or changed: its source, release, size and SHA-256 are in the folder's `downloads.json`, its license in the folder's `LICENSE.md`, and its credit in docs/ATTRIBUTION.md
- [ ] FlyWire-derived files are labeled CC BY-NC 4.0 (non-commercial); no raw downloads, recordings or caches are committed
- [ ] Code adapted from another project has a compatible license, and its notice is in NOTICE

## Docs

- [ ] User-facing changes are described in docs/USAGE.md, docs/RESEARCH.md or docs/ARCHITECTURE.md, and in the `Unreleased` section of CHANGELOG.md
