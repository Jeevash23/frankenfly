# Contributing to DigitalFly

Thank you for helping. DigitalFly is a research and teaching workbench, so two things matter as much as working code: runs must stay reproducible, and every part of a model must say honestly what it is (data-derived, assumed, engineered or a published model). Bug reports, scientific questions and small, focused pull requests are all welcome.

- **Bugs and feature ideas:** open an issue with the matching template.
- **Scientific questions** about the models, data or results: use the "Scientific question" template.
- **Security problems:** do not open a public issue; see [SECURITY.md](SECURITY.md).

## Setup

You need Python 3.12, Node.js 22.12–26 with npm, and an OpenGL backend for the physics and 3D views (see [running the tests](#running-the-tests)).

```sh
git clone https://github.com/Jeevash23/frankenfly.git
cd frankenfly
./scripts/setup.sh        # project-local backend/.venv and frontend/node_modules, from hashed lockfiles
./scripts/dev.sh          # hot-reloading UI at http://127.0.0.1:5173; restart it after Python changes
```

Optional installs, needed only for the features or tests that use them, are described in [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) and [docs/evidence/README.md](docs/evidence/README.md#before-you-start): the vision lock and pretrained networks for FlyVis eyes, the data lock and prepared FlyWire archive for building circuits, and the recorded-fly download.

## Running the tests

```sh
./scripts/check.sh          # backend tests including FlyGym physics, frontend format check, tests and build
./scripts/check.sh --fast   # the same without the FlyGym physics tests (what CI runs)
npm --prefix frontend run format     # format the frontend with Prettier before committing
npm --prefix frontend run typecheck
```

The FlyGym tests (marked `flygym`) need an OpenGL context. Even the ones that render nothing import MuJoCo's GL bindings. On a desktop session the default works. On headless Linux, DigitalFly picks EGL; to choose a backend yourself:

```sh
MUJOCO_GL=egl ./scripts/check.sh                   # needs libEGL
MUJOCO_GL=osmesa ./scripts/check.sh                # needs libOSMesa
xvfb-run -a env MUJOCO_GL=glfw ./scripts/check.sh  # a virtual display; works wherever Xvfb and Mesa's libGL are installed
```

To run only the physics tests: `xvfb-run -a env MUJOCO_GL=glfw backend/.venv/bin/python -m pytest backend/tests -m flygym -q` (one to two minutes). Tests that need FlyVis, the prepared FlyWire archive or the recorded fly skip with a reason when those are missing; `pytest -rs` lists them.

GitHub Actions runs `./scripts/check.sh --fast` equivalents and the frontend typecheck on Ubuntu for every pull request. It does not run the physics tests, so run them locally whenever you touch the body, engines, experiment, worker or neural code, and say in the pull request that you did.

## The replay-safety rule

Saved runs replay exactly, and published numbers come from committed circuits and default parameters. A change must not move those numbers silently:

- Committed circuits (`data/circuits/*.json`), default parameters and existing recorded runs must keep producing the same numbers. `scripts/replay.py` must still reproduce exported runs within `1e-8`, and `test_fast_flygym_path_matches_upstream_controller_bitwise` (in `backend/tests/test_experiment.py`) must still pass.
- Put new behavior behind an option whose default reproduces today's numbers.
- If a change is itself a fix of wrong behavior and has to change numbers, say so plainly in the pull request and in the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md), and update the affected tables in the docs.
- The fast FlyGym controller path in `backend/src/digitalfly/simulation/engines.py` re-implements FlyGym's arithmetic in the same order. Do not reorder or "simplify" it.
- Do not edit committed circuit files by hand. Rebuild them with `scripts/build_circuit.py`, which records its sources, hashes and parameters.

## Scientific labels

Every model component is labeled as data-derived, assumed, engineered or a published model, in the code, the provenance of exports and the docs. Keep those labels accurate when you add or change something, and never present an engineered choice as biology. Results describe what these models compute, not fly biology; issues and docs should say so too.

## Data and licensing rules

Code and documentation are Apache-2.0. Data is not: it keeps its source license, and much of it is non-commercial.

- **Never commit raw downloads.** FlyWire downloads and the prepared archive (`.cache/circuits/`), recordings (`.cache/recordings/`) and FlyVis networks (`.cache/flyvis/`) stay in the ignored cache. `data/atlas/`, `data/circuits/` and `data/recordings/` are not ignored, so check `git status` before committing anything under `data/`.
- **New data needs provenance.** Add its source URL, release, size and SHA-256 to the folder's `downloads.json`, its license to the folder's `LICENSE.md`, and a credit to [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md). Only add data whose license allows redistribution, and say what it is derived from.
- **FlyWire-derived data is CC BY-NC 4.0**, non-commercial, including every circuit and FlyVis bridge. Label new FlyWire-derived files that way in their own headers.
- **One license per file** where you can. `data/atlas/female.json` and `male.json` combine sections under different licenses; do not add more files like them.
- **Code from other projects** must have an Apache-2.0-compatible license (for example MIT, BSD or Apache-2.0). Add its copyright and license notice to [NOTICE](NOTICE) and a line to docs/ATTRIBUTION.md. Do not copy GPL code into the project; the GPL-3.0 navis-flybrains surfaces are data, kept separately.
- **Dependencies** come from hashed lockfiles. Do not add a runtime dependency without discussing it in an issue first; regenerate locks as [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) describes.
- **Contributions are licensed under Apache-2.0**, as section 5 of the [license](LICENSE) says.

## Code, tests and docs

- Match the surrounding code: its density, naming, terse comments and error style.
- Every bug fix gets a regression test, and every new option a test. Prefer the toy engine (`engine="toy"`), which needs no graphics.
- When you change behavior, update the guides that describe it ([docs/USAGE.md](docs/USAGE.md), [docs/RESEARCH.md](docs/RESEARCH.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) and add a line to the `Unreleased` section of the changelog.
- Generated output stays local: `runs/`, `docs/evidence/` (except its README) and `.cache/` are ignored. Exports record your platform string and can contain local paths in error messages, so review any you attach to an issue.

## Commits and pull requests

- One focused change per commit. Subject: a short imperative sentence, without a trailing period, such as `Cap threads per worker in parallel toolkit runs`. Then a blank line and a short body saying why.
- Fill in the pull request template: what changed, the checks you ran (including the physics tests if relevant), the replay impact and the data-license impact.
- Keep pull requests small enough to review in one sitting. Large changes are easier to land after an issue that agrees on the approach.
