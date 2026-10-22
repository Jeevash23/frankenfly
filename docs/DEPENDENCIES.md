# Dependencies and platform requirements

## Requirements

- A POSIX shell for the launch/setup scripts.
- Python **3.12**, selected from PATH, supplied explicitly through `PYTHON_BIN`, or (when [uv](https://docs.astral.sh/uv/) is installed and no other 3.12 is found) a uv-managed Python 3.12. The project environment is still created with `python -m venv` and installed from the hashed lock with pip. Python 3.13 and 3.14 also work when chosen through `PYTHON_BIN`, without FlyVis; see the [support policy](#python-and-node-support-policy).
- Node.js **22.12–26** and npm for installing/building the frontend. Vite 7 needs Node 22.12 or newer. The frontend unit tests import TypeScript directly through Node's built-in type stripping, which the test script enables explicitly for Node 22.12–22.17 (later releases enable it by default). Node 24 is the recommended LTS release.
- An offscreen OpenGL context for the body camera and compound-eye sensing. Geometric sensing with `--no-render` can run without those images.

No GPU or CUDA installation is required. Setup creates a project-local `backend/.venv`; it does not install drivers or change system settings. Each checkout should create its own environment and frontend dependencies.

Reference validation covers macOS/ARM64 (v0.2) and x86-64 Linux with EGL rendering (v0.3 and v0.4). Other environments have not been validated by this project. Use the commands below to check a new environment rather than treating one platform's results as a compatibility guarantee.

## Chosen stack

**FlyGym distribution `flygym==2.1.0`**, with the current v2 composition/simulation API. No `flygym-gymnasium` distribution is installed. The paper's NeuroMechFly v2 body model and the Python package's 2.x API are distinct version labels.

| Dependency | Tested version |
| --- | --- |
| Python requirement | `>=3.12,<3.15`; 3.12 is the recorded stack |
| FlyGym | 2.1.0 |
| MuJoCo | 3.9.0 |
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| Numba | 0.67.0 |
| Pillow | 12.3.0 (see the [Pillow exception](#security-audits-and-exceptions)) |
| FastAPI / Starlette | 0.141.1 / 1.6.0 |
| Uvicorn | 0.53.0 |
| Pydantic | 2.13.5 |
| websockets | 17.1 |
| psutil | 7.2.2 |
| certifi | 2026.10.19 |
| pytest / httpx | 9.1.1 / 0.28.1 |
| pip / pip-tools / setuptools | 26.2.2 / 7.6.2 / 84.0.0 |
| pyarrow (circuit build only, not the app) | 25.0.1 |
| Node requirement | 22.12–26; CI uses 24 and 22.12.0 |
| React / React DOM | 19.3.1 |
| Vite / React plugin | 7.3.7 / 5.2.0 |
| TypeScript | 5.9.3 |
| Prettier (formatting) | 3.9.10 |
| Playwright test runner (`@playwright/test`, end-to-end tests only) | 1.56.1, with its Chromium 141 (browser revision 1194): install it once with `cd frontend && npx playwright install chromium`, then `npm --prefix frontend run build` and `npm --prefix frontend run e2e` |

v0.4 adds no dependencies: spiking dynamics, the general circuit builder, the research toolkit and the fly comparison use NumPy and SciPy, which were already installed. Only `scripts/build_circuit.py prepare` (and the default rebuild of the DNa02 circuit) needs pyarrow from the build-only data lock; `build` reads the prepared NumPy archive.

Full transitive versions and hashes: `backend/requirements.lock`, generated from `backend/pyproject.toml` with pip-tools. The lock includes the test extra. Pillow and MuJoCo are imported directly, so they are declared with FlyGym 2.1.0's own ranges (`pillow>=11,<13`, `mujoco>=3.9,<3.10`); FlyGym still decides their versions. Frontend versions/integrity hashes: `frontend/package-lock.json`; update it with npm 11 (Node 24), because npm 10 drops its `libc` fields. All direct frontend imports are local packages. The runtime installs no PyTorch, JAX, Brian2, CUDA or Warp stack; CPU-only PyTorch comes only with the optional vision lock below. `jaxtyping`, IPython, imageio, ffmpeg and Matplotlib are upstream FlyGym transitives; they are not speculative extra model stacks.

pip itself, pip-tools and setuptools come from a third hashed lock, `backend/requirements-tools.lock`, generated from `backend/requirements-tools.in` with the runtime lock as constraints (so click and packaging match). Setup and CI install it with `--require-hashes` before any other lock. That also replaces the pip a new environment gets from `ensurepip` (24.0 or 25.0.1, both with known advisories) with pip 26.2.2. pip-tools 7.5.3 fails under pip 26.2, so the tools lock carries 7.6.2, which reproduces the runtime and data locks byte for byte.

To deliberately regenerate the Python lock after editing the project specification (from a Python 3.12 environment; the locks are resolved for 3.12):

```sh
PIP_CACHE_DIR="$PWD/.cache/pip" PIP_TOOLS_CACHE_DIR="$PWD/.cache/pip-tools" \
  backend/.venv/bin/pip-compile --extra test --generate-hashes \
  --output-file backend/requirements.lock backend/pyproject.toml
```

pip-compile keeps every existing pin it can. For a security fix in one package, add `--upgrade-package <name>` (for example `certifi`) so nothing else moves, regenerate the data lock as below, and diff the locks before committing. Never use a blanket `--upgrade` for a security refresh: it also moves NumPy, Numba and llvmlite, which changes replay numbers.

To regenerate the tools lock:

```sh
PIP_CACHE_DIR="$PWD/.cache/pip" PIP_TOOLS_CACHE_DIR="$PWD/.cache/pip-tools" \
  backend/.venv/bin/pip-compile --allow-unsafe --generate-hashes \
  --output-file backend/requirements-tools.lock backend/requirements-tools.in
```

Do not hand-maintain an additional requirements file. Setup installs from the locks using `--require-hashes`, then installs the local source without resolving dependencies again.

The circuit builder (`scripts/build_circuit.py`) needs pyarrow, which the app itself never imports. It lives in the optional `data` extra and its own lock, `backend/requirements-data.lock`: the runtime lock plus pyarrow, with hashes for every published wheel (macOS and Linux included). Install it only to rebuild `data/circuits/`:

```sh
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock
```

After regenerating the runtime lock, regenerate this one from it, so shared pins stay identical:

```sh
cp backend/requirements.lock backend/requirements-data.lock
PIP_CACHE_DIR="$PWD/.cache/pip" PIP_TOOLS_CACHE_DIR="$PWD/.cache/pip-tools" \
  backend/.venv/bin/pip-compile --extra test --extra data --generate-hashes \
  --output-file backend/requirements-data.lock backend/pyproject.toml
```

## Security audits and exceptions

The CI security job runs pip-audit (installed from the hashed `.github/requirements-audit.txt`) over the runtime, data, vision and tools locks without installing them, and `npm audit --audit-level=high` over the frontend lockfile. pip-audit cannot look up the vision lock's `+cpu` PyTorch builds and lists them as skipped; the same versions on PyPI have no advisories.

**Pillow exception.** Pillow 12.3.0 has eight advisories in its TIFF, PDF-append, GIF, PPM/ImageMorph and EPS code, all fixed only in Pillow 13.0.0. FlyGym 2.1.0 requires `pillow<13` and there is no 12.x backport, so the audit ignores those eight IDs; `.github/workflows/ci.yml` lists each with its reason. None is reachable: DigitalFly encodes JPEG frames (and the demo GIF) from arrays and decodes only its own JPEG frames; it never opens TIFF, PDF, GIF, PPM/PGM or EPS input. Do not override FlyGym's cap. Drop the exception when a FlyGym release allows Pillow 13; Pillow changes only the JPEG frame bytes, not the telemetry that replay compares.

Dependabot (`.github/dependabot.yml`) opens weekly pull requests for pip, npm and GitHub Actions, with minor and patch updates grouped. It never bumps NumPy, SciPy, Numba, llvmlite, MuJoCo, FlyGym, PyTorch, torchvision or pyarrow: they change replay numbers, so bump them deliberately, re-record the reference runs and run `scripts/replay.py`. Dependabot cannot regenerate the backend `.lock` files; regenerate them with the commands above before merging a pip update. CI's `pip check` fails while `pyproject.toml` and the lock disagree.

A weekly workflow (`.github/workflows/links.yml`, which can also be started by hand) sends a one-byte range request to every URL in `data/*/downloads.json` and every source in `scripts/build_circuit.py`, and fails if one is gone or no longer has its recorded size.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to main:

| Job | Runs |
| --- | --- |
| Backend tests | Python 3.12, 3.13 and 3.14: the tools and runtime locks with `--require-hashes`, `pip check`, then every test except the FlyGym physics tests |
| Frontend checks | Node 24 and Node 22.12.0 (the lower bound): format check, typecheck, unit tests and build |
| FlyGym physics tests | Python 3.12 under Xvfb with Mesa and `MUJOCO_GL=glfw`, including the bitwise check of the fast controller path |
| End-to-end tests | Python 3.12 (hashed locks) and Node 24: Playwright's Chromium, the frontend build, then `npm --prefix frontend run e2e` in headless Chromium against `./scripts/start.sh --toy`; the Playwright report is uploaded when it fails |
| Dependency audit | pip-audit over the four locks and `npm audit --audit-level=high` |

CI installs neither the vision nor the data lock, and has no prepared FlyWire archive or recording, so the FlyVis, circuit-rebuild and recorded-fly tests skip there. Run `./scripts/check.sh` locally with those installed before changing that code.

## Python and Node support policy

- **Python 3.12** is the recorded stack: the reference runs, the evaluations and the vision lock use it, and setup picks it by default. It receives security fixes until October 2028.
- **Python 3.13 and 3.14** run the app and the tests. The runtime and data locks install on both unchanged, and CI runs the fast tests on both. The FlyGym physics tests passed on 3.13.16 and 3.14.6, and short engineered and connectome runs recorded on 3.12 replayed on both with zero error. FlyVis does not install there.
- **Python 3.15** is blocked by FlyGym's `<3.15` and by missing 3.15 wheels for MuJoCo 3.9.0, Numba 0.67.0 and PyTorch 2.14.1.
- **Exact replay** (`scripts/replay.py`, absolute tolerance 1e-8) is only guaranteed on the recorded stack: the same Python minor version and the same locks. Each export records its Python and key package versions in `metadata.json`.
- **Node 24** is the LTS release CI uses by default; it is supported until 2028-04-30. **Node 22** is in maintenance and reaches end of life on 2027-04-30. CI keeps a 22.12.0 job until then; after that the floor in `frontend/package.json` and `scripts/setup.sh` rises to 24. Node 26 joins CI when it becomes LTS.

## Official references checked

- [FlyGym installation](https://neuromechfly.org/installation/)
- [API migration: 1.x versus 2.x](https://neuromechfly.org/migration/)
- [FlyGym source](https://github.com/NeLy-EPFL/flygym)
- [Pinned 2.1.0 source](https://github.com/NeLy-EPFL/flygym/tree/v2.1.0)
- [Turning-controller tutorial](https://neuromechfly.org/tutorials/4d_turning_controller/)
- [Model composition](https://neuromechfly.org/tutorials/1a_basic_model_composition/)
- [Simulation API](https://neuromechfly.org/api_reference/flygym/simulation/)
- [Legacy Gymnasium documentation](https://gymnasium.neuromechfly.org/), identified as a separate API; not mixed into this implementation
- [FastAPI](https://fastapi.tiangolo.com/)
- [Vite setup](https://vite.dev/guide/)

Actual installed Python source was inspected for `make_locomotion_fly`, `HybridTurningController`, `HybridControllerObservation`, `LocomotionAction`, `apply_locomotion_action`, reset/warmup and renderer ownership. Installed package APIs were then executed.

## Reproducing validation

After setup, run from the repository root:

```sh
./scripts/check.sh
backend/.venv/bin/python -m pip check
backend/.venv/bin/python scripts/smoke_flygym.py
backend/.venv/bin/python scripts/benchmark.py
backend/.venv/bin/python scripts/benchmark.py --vision
```

The full checks and benchmarks require graphics access. On Linux without a display or a usable EGL, `./scripts/check.sh` runs the tests under `xvfb-run -a` with `MUJOCO_GL=glfw` when `xvfb-run` is installed (Xvfb plus Mesa's software OpenGL); an explicit `MUJOCO_GL` is left alone. `./scripts/check.sh --fast` intentionally omits FlyGym integration tests and does not establish graphics/body compatibility. To test a running local server, use `backend/.venv/bin/python scripts/probe_local.py`; it advances and resets that server's experiment.

The [status summary](../STATUS.md) records the reference results. [Evidence instructions](evidence/README.md) explain generated outputs, replay and the version-control boundary. Raw logs and device-specific measurements stay local. Benchmark throughput and memory vary with hardware, graphics setup and load.

The reference test stack emitted two upstream deprecation notices (Starlette's httpx adapter and an AnyIO alias); they were not test failures.

## Assets and optional FlyVis review

The FlyGym 2.1.0 wheel was approximately **3.16 MB** and includes simplified NeuroMechFly meshes (at most 2,000 faces per segment), rigging, poses and the walking data used here. Normal startup requires **no extra asset download**. The package supports optional high-resolution meshes from EPFL, but those were not requested or downloaded. If added later, its cache is configured to `data/flygym-assets`, not a global personal directory.

Environment, package-cache and asset sizes vary by platform. They are excluded from the public repository and recreated locally during setup.

v0.2 deferred FlyVis; v0.5 adds it as an optional install (below).


## v0.2 research dependencies

The research features use the existing pinned runtime packages; no extra GPU framework or pretrained model is required. The verified FlyGym 2.1 APIs used are `BaseFly.add_vision`, `Simulation.get_raw_vision`, `Retina.raw_image_to_hex_pxls`, `Simulation.get_joint_angles` and `Simulation.get_bodysegment_contact_forces`. The actual installed Python source was inspected before integration. Eye cameras use the upstream 512×450 fisheye retina and 721 ommatidia per eye.

Anatomy data was downloaded from the official MaleCNS v1.0 bucket and the Bates/Lee lab FAFB v783 compilation. Small surface files came from navis-flybrains; no navis, trimesh, PyTorch, JAX or new graphics dependency was installed. A narrow NumPy reader handles the retained, hash-verified PLY assets. Details, sizes, coordinate assumptions and licensing: [RESEARCH.md](RESEARCH.md).

Reproduce these checks using the commands above. Generated results belong in the ignored evidence directory; the public repository retains generic instructions and the validation summary.

## v0.3 dependencies

The connectome model needs no new runtime package: it uses NumPy and `scipy.sparse`; SciPy was already installed with FlyGym and is now declared directly, with unchanged pins and hashes. Building the circuit needs pyarrow 25.0.1, in the optional `data` extra and `backend/requirements-data.lock`; the app never imports it. The build downloads about 61 MB of FlyWire v783 data (13.5 MB of metadata and 47.3 MB of Parquet column chunks) into the ignored cache; sources and hashes are in `data/circuits/downloads.json`.

The frontend's Node range is 22.12–26. Nothing needs Node 24: Vite 7 and its React plugin need 22.12 or newer, and CI checks 22.12.0 as well as 24. Rollup's optional `@napi-rs/lzma` binary declares a newer Node, but it is a build-tool helper that rollup never loads at run time, and npm skips it on older Node versions.

The continuous-integration workflow is described under [Continuous integration](#continuous-integration).

## v0.5 optional FlyVis vision and recorded fly data

FlyVis 1.2.0 needs PyTorch, so it lives in the optional `vision` extra and its own lock, `backend/requirements-vision.lock`. The app runs without it; the **FlyVis eyes** sensor appears only when it is installed. The lock is universal (Linux and macOS) and hashed for every file: on Linux, `torch 2.14.1+cpu` and `torchvision 0.29.1+cpu` from the PyTorch CPU index; on macOS, the same versions from PyPI (which are CPU builds there). The default PyPI build on Linux would pull about 3.0 GB of CUDA packages; the CPU route is about 261 MB of downloads on Linux x86-64 (PyTorch's wheel is 196,253,677 bytes), adding 54 packages including pandas, scikit-learn, h5py, xarray, Hydra and Google's API client (FlyVis declares them all). Install, then fetch the pretrained networks (3,417,042 bytes, SHA-256 checked against the value FlyVis's own downloader expects; MIT):

```sh
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-vision.lock
backend/.venv/bin/python scripts/fetch_flyvis.py
```

The networks unpack into the ignored `.cache/flyvis/`, which FlyVis also uses for its connectome cache. Checkpoints are loaded with PyTorch's weights-only mode. To regenerate the lock after changing the `vision` extra:

```sh
uv pip compile backend/pyproject.toml --extra test --extra vision --universal --python-version 3.12 \
  --generate-hashes --emit-index-url --index-url https://pypi.org/simple \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
  -c backend/requirements.lock -o backend/requirements-vision.lock
```

The vision lock was validated on x86-64 Linux only; the macOS entries are hashed but have not been installed.

The `vision` extra is marked `python_version < '3.13'`, because FlyVis 1.2.0 and datamate 1.0.0 support Python 3.12 only. The committed vision lock was resolved before that marker existed, and its certifi entry was set to the runtime lock's by hand, because the PyTorch index was unreachable where that change was made. Its next regeneration with the command above should add `python_full_version < '3.13'` markers to the vision-only entries without moving a pin; check the diff.

Recorded fly data needs no package: SciPy reads the MATLAB files. `scripts/fetch_recording.py` downloads a file listed in `data/recordings/downloads.json` into the ignored `.cache/recordings/` and keeps it only if its size, MD5 and SHA-256 match. The first entry is one paired DNa02 recording from Rayshubskiy et al. 2025 (71,381,032 bytes, CC0 1.0).
