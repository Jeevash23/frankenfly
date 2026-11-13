# Changelog

All notable changes to DigitalFly are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The version is the one in `backend/pyproject.toml`; every export records it as `application_version`, so a saved run can be matched to the release that produced it. Each release below names its version-bump commit.

Unless an entry says otherwise, a release keeps earlier runs replaying with the same numbers: committed circuits, default parameters and recorded runs are not changed silently.

## [Unreleased]

### Added

- `docs/ROADMAP.md`: the plan from v0.7 to v1.0, with a survey of related tools and datasets.
- **A validation scorecard** (roadmap track A). `scripts/toolkit.py scorecard` and `digitalfly.scorecard` score the engineered model or any circuit, with rate or spiking dynamics, on the toy or FlyGym body, against eight published perturbation → behavior results: DNa02 activated on one side and silenced on both (Rayshubskiy et al. 2025), DNp09 activated on one side (Bidaye et al. 2020), MDN activated (Bidaye et al. 2014), the Giant Fiber (von Reyn et al. 2014), the antennal grooming neurons aDN1/aDN2 (Hampel et al. 2015), left-right symmetry (Buchanan et al. 2015) and sugar taste neurons → MN9 (Shiu et al. 2024). Each test cites its source, manipulates cell types with the existing interventions on matched-seed trials, and gives pass, partial or fail by a rule written down before any model was scored, with the measured number; it is "not testable" when the circuit lacks the cell types and "blocked" when the fly lacks the sense or motor program, and it says when a result follows from the engineered readout ("by construction"). Results go to `runs/toolkit/` and the latest card per model to `runs/scorecards/`. The Experiments page shows them in a **Validation scorecard** panel and scores the Workbench model as a background job (`GET /api/scorecards`, `POST /api/scorecards/run`, job kind `scorecard`). A fast toy-body scorecard of the engineered model and the DNa02 circuit runs with the backend tests. Measured results and caveats: research guide, "Validation scorecard". One measure was corrected after the first FlyGym scores and before release: rotational speed is read over 0.25 s bins, because FlyGym's body yaws with every stride (logged in the guide).

### Fixed

- A background job that failed after printing reported its last printed line as the error instead of its error message: Python buffered the job's output, so the error arrived first. Jobs now run unbuffered.

## [0.6.0] - 2026-10-22

Version-bump commit `ccca791`.

A robustness and research-workflow release. The simulation worker, the toolkit and the circuit builder now survive failures instead of stopping; new engineered manipulations, a motor path, side-balanced circuits and an assumption-sensitivity analysis make the connectome model easier to test; runs can be verified, annotated and summarized from the app; and DigitalFly installs through Docker, a dev container or Python 3.13 and 3.14. Results remain properties of these models, not fly biology.

**Replay compatibility.** Committed circuits and default parameters compute exactly what v0.5 did. Every new model option (cell-type manipulations, the motor path, side balancing, per-type activity recording) is off by default, and runs without them were checked bit for bit against v0.5 output on both committed circuits with rate and spiking dynamics. Runs exported by earlier versions (schemas 2 and 3) still load and replay, including v0.5 spiking runs with live parameter edits, which replay through a compatibility path (below). The FlyGym fast path still matches FlyGym's own controller bit for bit. No pin that changes replay numbers (NumPy, SciPy, Numba, MuJoCo, FlyGym) moved.

**Intentional behavior changes** (details under Changed):

- With spiking dynamics, a live parameter edit now keeps the running network; v0.5 restarted it from rest. This was a bug, which v0.5 runs keep for exact replay.
- Fits to the recorded fly leave out the optogenetic stimulation epochs by default (`--include-stimulus` restores v0.5's fit). The published fly fit has not yet been re-run this way.
- A run that reaches the recording limit pauses instead of failing, and the 10,000-change budget counts only manual input changes.
- When a comparison ends, the Workbench returns to the configuration it had before, and Cancel saves the unfinished trial marked partial.
- `MUJOCO_GL` is no longer forced to `egl`: the first FlyGym start picks a backend that works.
- The `/api/docs` page is gone; the schema stays at `/api/openapi.json`.
- Toolkit sweeps save a failed trial as an error row and carry on, then exit with an error.

### Added

#### Neural models and interventions

- **Per-side cell-type manipulations.** `Interventions.cell_types` takes `{name, side, mode, value}` for any cell type of the running circuit, on the left, the right or both sides: `silence`, `scale` (output × 0–2) or `activate` (independent Poisson input above 0 and up to 500 Hz with spiking dynamics, a rate clamped above 0 and up to 1 with rate dynamics). They work live, as initial interventions, in protocol events and in comparisons, are labeled engineered manipulations (equations in `docs/ARCHITECTURE.md`), are listed in exports and counted in the live view.
- **An engineered motor path** between the readout and the legs, all live-editable and replayed: `readout_weights` per readout type, `readout_pool` (`sum` or `mean`), `motor_delay_ms` (0–500, a delay line of whole neural steps) and `motor_tau_ms` (0–1000, a first-order low-pass). The defaults leave it off.
- `motor_clipped_fraction`, the share of control intervals whose motor command was clipped, in exports, the live connectome block and toolkit trial rows, with a warning in the app when turning is saturated more than half the time.
- **Custom comparison conditions**: labeled conditions with their own interventions and, with the connectome model, live-editable parameters, up to six conditions in all.

#### Circuits and science

- **Side-balanced circuits.** `build_circuit.py build --balance-sides` (`balance_sides` in `POST /api/connectome/build`, **Balance left and right** in the app) applies the neuron cap per cell type and side, keeping each type's left and right neurons in pairs. The header records the rule and a `side_balance` report, and the circuit list says which circuits are balanced. Unbalanced builds are unchanged and still rebuild byte for byte.
- **Two new committed circuits**, `fafb783-dna02-balanced` (3,000 neurons) and `fafb783-steering-balanced` (3,999), with their FlyVis bridges (CC BY-NC 4.0). The original circuits are unchanged and remain the defaults. Measured on these models: balancing reduces the DNa02 circuit's left bias (equal-input turn −0.179 → −0.082 with rate dynamics, −0.683 → −0.188 with spiking dynamics) without removing it, and lifts its toy-body reaching from 0/60 to 10/60 while it still orbits the target (radius 7.5 → 2.9 mm); the balanced steering circuit reaches 60/60 where the original reaches 57/60 (see the research guide).
- **Assumption sensitivity.** `scripts/toolkit.py robustness` reruns the bias curve, the held-target readouts and optionally short reach trials over a grid of the model's assumptions (sign rule, synapse threshold, readout pooling and weights, dynamics, circuit, seed) and reports which qualitative conclusions hold in every variant. The DNa02 circuit's left turns (with equal input, and for targets ahead, to the left and 45° right) hold in all 12 sign-rule × threshold × dynamics variants; of the steering circuit's conclusions only "a target 90° left turns it left" does.
- `scripts/toolkit.py readouts`, the command behind the research guide's table "What the circuits compute"; it reproduces the published values.
- Recorded-fly fits: recordings carry per-sample valid flags (an optional `valid` column in CSV recordings), `compare --include-stimulus`, and each source's rate mean, median and 99th percentile. `compare` takes `--recording` and `--run` more than once and reports the spread of each fit across flies and runs (`compare.summarize_fits`).
- `ablation` and `toolkit.ablation_scan` take `--mode scale` or `activate` with `--value`, and `--side left` or `right`; the default scan computes the same numbers as before.

#### Research toolkit

- Resilient sweeps: a failing trial becomes a row with its settings, configuration and error text; results stream to `.jsonl` and `.csv` as they finish; `--resume` skips trials already saved, matched by a hash of the configuration, the run settings and the circuit file. A worker process that dies (killed, out of memory) costs only the trials it held, which rerun alone.
- Statistics in every `trials` report: Wilson intervals for fractions, seeded bootstrap intervals for means and matched-seed paired differences between conditions (`toolkit.summarize`). Every saved report records the git commit, command line, circuits with their SHA-256, Python, platform and package versions.
- `toolkit.TrialLog` (moved from `scripts/toolkit.py`), which `scripts/evaluate_models.py` now uses to stream every trial, with `--resume` and `--out`.
- `scripts/toolkit.py jump` exposes `jumping_target_run`; `paths` saves its result; `ablation` takes a repeatable `--type` for names with commas.
- `Experiment(record=False)` keeps no samples; toolkit trials use it, so they have no 300-second limit, with identical numbers.
- `scripts/benchmark.py --neural` times one 1 ms neural step of every committed circuit (and local whole-brain builds) with both dynamics; `--flyvis` times FlyVis or records why it was skipped.
- **A Python client for the running app**, `digitalfly.client` (standard library, plus `websockets` for streaming): status, reset, run, pause, step, stimulus, interventions and connectome parameters merged into the current values, export, saved runs, `wait_until` and `stream`. `examples/` has a client script and a toolkit batch over seeds, both run by the tests.
- Downloads (`fetch_recording.py`, `fetch_flyvis.py`, the builder's fetch) retry with backoff, resume interrupted files with HTTP Range requests, and fail in one line; sizes and hashes are still checked.

#### Simulation, replay and exports

- **Replay verification from the app.** **Verify replay** in the run library, or `POST /api/runs/{key}/replay`, checks a saved run in a background process and shows the verdict, including whether the recorded Python, package versions and lockfiles still match (`verified` on each run). `scripts/replay.py` is importable (`replay()`, `verdict()`) and `--save` writes `replay.json`.
- **Background jobs**: replay checks and circuit builds run as low-priority subprocesses, one of each kind at a time, listed by `GET /api/jobs` and stopped by `POST /api/jobs/{id}/cancel`.
- **Configuration presets.** `configs/` ships `default`, `steering-circuit`, `spiking-dna02`, `flyvis-eyes` and `first-experiment`; presets saved in the app go to the ignored `configs/local/` (`GET`/`POST`/`DELETE /api/configs`), each validated in full and listed as unavailable, with the reason, when this computer cannot run it. `start.sh --config` takes a preset name.
- **Export schema 5**: `telemetry.csv` appends the target's bearing and distance, the target in effect and a short intervention code (replay ignores them); metrics add `min_target_distance_mm`; `record_activity: "types"` saves every cell type's mean activity per control step in `activity_types.npz`. Exports also record the lockfile hashes and, for FlyVis runs, the network, checkpoint and bridge hashes.
- **Share-safe exports** (`POST /api/export {"share_safe": true}`, **Share-safe export** in the app) leave out the operating-system string and replace absolute paths and the computer's name.
- `GET /api/schema/state` serves the JSON Schema of the live state; `scripts/gen_types.py` turns it and `/api/openapi.json` into the frontend's `src/api.gen.ts`.

#### Run library and comparisons

- `GET /api/runs` pages (`offset`, `limit`, `X-Total-Count`, `include_empty`) and filters by model, circuit, comparison, tag and text; `DELETE /api/runs/{key}` removes a run's folder and ZIP (never the run being recorded); `PATCH /api/runs/{key}` sets tags and notes, kept in `annotations.json` so `metadata.json` never changes.
- `GET /api/batches/{id}/summary` (and `?format=csv`): per condition, the mean, SD and 95% interval of each metric, and matched-seed differences from the first condition, counting only complete trials once per condition and seed.
- Comparisons can run unpaced (`max_speed`, **Run as fast as possible**) with identical results.

#### Browser UI and accessibility

- Workbench and Live circuit controls for per-side silence, scale and activate, with the manipulations in force and their neuron counts; the motor path with a clipping warning; custom conditions, partial-trial and restore notices on the Experiments page; **Verify replay** and a **Background jobs** panel; presets; a **Share-safe export** checkbox; **Remove protocol (free run)** on the protocol banner.
- The run library pages (**Load more**), filters, deletes after a confirm step, shows tags as filter chips and edits tags and notes; a comparison's **Comparison statistics** show each condition's mean, interval and paired differences, a chart and **Download CSV**, with small-n and wide-interval warnings.
- The Build tab's **Balance left and right**, and a left/right balanced badge in the circuit lists and the live view.
- The page and atlas tab live in the URL (`#/workbench`, `#/atlas/circuit`, …), and unsent drafts (protocol, conditions, builds, imported connectivity) persist in the browser until submitted. Error boundaries offer **Reload this view**.
- Accessibility: page and atlas tabs are tablists with arrow keys; segmented controls carry `aria-pressed`; the circuit diagram is one Tab stop with arrow-key movement; the arena target moves with the arrow keys; every control shows a focus ring; live regions announce only transitions; small text reaches 4.5:1 contrast with an 11 px floor.

#### Installation and operations

- **Docker image** (`Dockerfile`, `docker-compose.yml`): Ubuntu 24.04 with Python 3.12 and the hashed locks, the built interface, and Mesa EGL rendering on the CPU without a display (OSMesa fallback); a non-root user, named volumes for runs, caches and presets, a health check, optional `EXTRAS`, and a port published to 127.0.0.1 only. A **dev container** (`.devcontainer/`) builds its `dev` target. [docs/INSTALL.md](docs/INSTALL.md) covers native installs, Docker, the dev container, headless servers and WSL2 (untested).
- `scripts/setup.sh --backend-only` (no Node.js), `--with builder,flyvis,recording` and `--check`; without options setup does what it did before.
- `scripts/doctor.py` checks Python, the installed lock, Node, the frontend build, OpenGL backends, optional parts, caches, disk space, writable data folders and the port, one line per check with a fix.
- **Python 3.13 and 3.14** run the base app (`requires-python <3.15`) through `PYTHON_BIN`; 3.12 stays the default and the recorded stack, and FlyVis needs 3.12.
- `start.sh --host` (or `DIGITALFLY_HOST`) with the explicit acknowledgement `DIGITALFLY_ALLOW_NETWORK_BIND=1`, and `DIGITALFLY_ALLOWED_ORIGINS` for extra exact origins, for containers and tunnels. Without them the bind and the Host, Origin and CSP checks are unchanged.
- At startup the server removes leftovers of interrupted exports, deletions, replay checks and builds older than an hour. `/api/capabilities` reports the code's own limits, whether compound-eye vision can render, and whether jobs and presets (and saving them) are available; `/api/health` reports the version.

#### CI and quality

- CI runs the fast backend tests on Python 3.12, 3.13 and 3.14 with `pip check` and a check that the generated TypeScript types are current; the frontend on Node 24 and 22.12.0; the FlyGym physics tests under Xvfb; browser end-to-end tests; and pip-audit over every lock plus `npm audit`. A Docker workflow builds and smoke-tests the image, a weekly workflow checks every pinned download URL, and Dependabot proposes grouped weekly updates, leaving the replay-sensitive packages alone. The actions move to v7.
- End-to-end tests with Playwright 1.56.1 (`npm --prefix frontend run e2e`): ten tests drive the built app in headless Chromium against the toy engine.
- `./scripts/check.sh` runs the physics tests under `xvfb-run` when there is no display and no working EGL.
- The backend suite grows from 88 to 356 tests (12 of them FlyGym physics tests) and the frontend unit tests from 27 to 81.
- `CONTRIBUTING.md`, `SECURITY.md`, issue forms, a pull request template, this changelog, `CITATION.cff`, the license notices for every committed data asset, and [docs/evidence/README.md](docs/evidence/README.md) with the command behind every published number.

### Changed

#### Simulation and replay

- **Spiking networks keep their state across live parameter edits.** v0.5 rebuilt the network at every connectome parameter edit, even of the readout-only output gain, so the turn command dropped to zero and the Poisson input restarted from the run's seed. Now only a reset, or a new circuit or input population, restarts it. `scripts/replay.py` restarts the network after each edit in runs exported with schema 3 or earlier, so v0.5 runs still replay exactly. The spiking step also honors its `dt` (multiples of 0.1 ms) instead of ignoring it, with identical numbers at the default 1 ms.
- **Recording limits pause the run.** A run that fills its 30,000 samples, or gets a Step after its protocol ended, pauses with a note and stays valid, instead of entering the error state. The 10,000-event budget counts only manual input changes, and a change past it is refused (409) before it is applied, so Export never fails at the limit. Run, pause, step, speed and export events are logged up to 10,000 per run, then one note. Repeated stimulus, engineered-parameter or speed changes within one control step are saved as one event.
- **Comparisons restore the Workbench** configuration (model, controller, interventions, protocol) when they end, and Cancel saves the unfinished trial marked partial. Every trial's configuration is validated before the first trial starts, the engineered model is refused with FlyVis eyes, and speed changes are accepted during a comparison.
- **Exports run off the simulation thread**: a full-length export held the simulation for 1–6 s and now holds it for 10–40 ms. Exports are written into a hidden `runs/.tmp-*` folder and renamed into place when complete.
- **Commands are checked against what runs.** Reset builds the new circuit (and body) before replacing anything, so a configuration that cannot be built leaves the current run as it was. Interventions are checked against the loaded circuit; live parameter edits and the circuit summary refuse a circuit file rebuilt since it was loaded (409, with Reset offered in the app); the app will not rebuild a circuit in use or load one being built. Invalid interventions or readout weights are 422 both live and at a reset.
- Telemetry gets a new revision only when something changed, is rebuilt at most once a second while not running, and is encoded once per revision for every WebSocket client.
- `MUJOCO_GL` is no longer set to `egl` on machines without a display. Unless you set it, the first FlyGym start tests GLFW (with a display), EGL and OSMesa in child processes and uses the first that renders; with none, physics runs without the 3D view and the message names the fixes.
- `POST /api/reset` and `/api/batch/start` accept configurations up to 1 MB (was 16 KB), the same limit as presets.

#### Neural models

- A live connectome parameter edit reuses the circuit the run loaded instead of reloading it by name.
- With FlyVis eyes, the model's description now describes the per-neuron bridge drive and labels the bridge engineered and unsigned (numbers unchanged).

#### Research toolkit and science

- **Recorded-fly fits leave out stimulation epochs by default**: samples with the optogenetic stimulus on, or on within the preceding 0.5 s, are not used (4.3% of the recording is stimulated). `compare --include-stimulus` (`exclude_stimulus=False`) keeps them as v0.5 did; recordings without such flags fit exactly as before. The fly's fit in the research guide was computed with them included and is labeled so.
- `toolkit.run_trials` returns error rows instead of raising; `trials` and `scripts/evaluate_models.py` exit with an error if any trial failed. `evaluate_models.py` runs identical trials once (360 of its 400 toy trials are distinct) and saves partial runs under their own name.
- The CLI refuses a seed or target position given both in `--set`/`--vary` and through `--seeds`/`--bearings`/`--distances` (it used to overwrite them silently) and keeps `stimulus.intensity`. `--vary` takes one JSON list of objects; dotted settings fill an unset group; an out-of-range setting stops the command in one line. `ablation` refuses readout types and unknown names before scanning (it silently dropped readout types).
- Worker processes, including `ablation_scan`'s, inherit the BLAS and OpenMP thread cap before NumPy loads.
- The builder writes circuits atomically through a temporary file and removes only the same name's other format, refuses names ending in `.flyvis`, and asks for the FlyWire metadata's recorded GCS generation.

#### Interface and API

- The live state is typed (Pydantic models for its batch, connectome, metrics and vision parts) and fields without a value are left out rather than sent as null; the frontend's types are generated from the schemas.
- The app's version comes from `/api/health` instead of a hard-coded label, and the model notes, loop and control-mode labels follow the active model and sensor. Switching to the engineered model with FlyVis eyes also switches to rendered compound eyes, with a note.
- Each command tracks its own pending state instead of one global busy flag, so the rest of the interface stays usable; quick successive edits build on the request still in flight; the intensity slider sends while dragging (at most every 200 ms) and once on release.
- The connectivity library lists newest first; run summaries are cached by modification time.

#### Dependencies

- Pillow and MuJoCo are declared as direct dependencies with FlyGym 2.1.0's own ranges; no pin moved.
- React and React DOM 19.3.1, Prettier 3.9.10, pip-tools 7.6.2.
- Python 3.13 and 3.14 are allowed for the base app; the `vision` extra is marked `python_version < '3.13'`.
- `--vision` is unchanged and still means rendered compound eyes with the engineered green-object detector, not FlyVis; the documentation now says so wherever it appears.

### Fixed

#### Simulation and replay

- A failing command or display update could end the only simulation thread, after which every request waited 25 s for a 503. The worker now answers the failing command, puts the run into the error state if its state cannot be published, and a stopped worker answers 503 at once.
- `scripts/replay.py` ignored the circuit SHA-256 that connectome runs record and failed with a shape error after a rebuild; it now stops and names both hashes (`--allow-circuit-mismatch` tries anyway). A NaN or a missing row or column in `telemetry.csv` passed replay unnoticed; it now fails. Readout cell types whose names contain commas no longer make `telemetry.csv` unreadable to replay. A damaged telemetry row no longer turns the run detail into a server error.
- When the run's own data failed validation during a command (a non-finite pose after a step), the server answered 422 as if the request were wrong; it is now a 500.
- `/api/capabilities` always reported compound-eye vision as available; it now reports whether a renderer works.

#### Neural models and circuits

- A circuit file with a cell-type index past the lookup table, a negative super-class index or a missing field loaded and failed later (sometimes as a 500); the loader now checks every lookup column and edge endpoint and names the field.
- A cell type listed without neurons gave a NaN mean that the live state could not send; it is 0. The committed circuits have no such type.
- FlyVis eyes on an input population that the bridge does not reach left the circuit silently blind; this is refused with a reason now.
- Building `steer` deleted every `steer.*` circuit, including `steer.v2` and the FlyVis bridge `steer.flyvis.json`, and a crash mid-write left a truncated file.
- `--hops`, `--threshold`, `--cap` and `--offline` given before the builder's subcommand were silently replaced by its defaults; the cap report's weakest kept path no longer goes missing when the cap leaves a deeper hop empty.
- The FlyVis eye-orientation docstrings said the left eye is mirrored (the code mirrors the right), and the docs claimed more direction testing than exists (only T4 in the right eye is checked).

#### Toolkit and library

- One failing trial, a dead worker process or the recording limit aborted a whole sweep, and nothing was saved until every trial had finished.
- Toolkit trials of 300 simulated seconds or more failed on the app's recording limit.
- The run and connectivity libraries silently stopped at 100 entries.
- `fetch_recording.py` printed a raw traceback on network errors and restarted a lost download from zero.

#### Browser UI

- Applying a gain blanked the Live circuit view; the circuit summary is now keyed on the circuit file's SHA-256 and structural parameters, and is cleared when a build finishes. A late path-trace answer could replace a newer one.
- Dragging the intensity slider did not work while its request was in flight, and one command disabled every control.
- The interface showed v0.3 and outdated model notes.
- Ctrl+C stopped the launcher with a traceback.

### Removed

- The interactive API page at `/api/docs`, which rendered blank under the app's own Content Security Policy (it would need scripts from a CDN). The schema stays at `/api/openapi.json`, and the live state's schema is at `/api/schema/state`.

### Security

- certifi 2026.10.19 in the runtime, data and vision locks: 2026.7.22 still bundled the emSign ECC Root CA - G3, whose intermediates were compromised (PYSEC-2026-4320).
- Vite 7.3.7 (advisories in its bundled launch-editor, dev server only) and source-map-js 1.2.2 (a build-time denial of service); `npm audit` reports none.
- pip 26.2.2, pip-tools 7.6.2 and setuptools now come from a hashed lock (`backend/requirements-tools.lock`), installed before any other lock: a new environment's ensurepip pip (24.0 or 25.0.1) carries known advisories, and the build tools were installed without hashes.
- Listening on any address other than 127.0.0.1 or localhost (`::1` included) requires `DIGITALFLY_ALLOW_NETWORK_BIND=1`, since the API has no login; extra origins must be exact, and a malformed value stops the launcher.
- Replay verdicts, circuit files and column chunks, run annotations, presets and staged export ZIPs are written to new files created exclusively under random names, so a link planted at a predictable name is never followed.
- Run deletion refuses links and anything not named like a run, and presets are limited to 1 MB and cannot replace a shipped preset.
- `.npmrc`, editor and assistant files are ignored in every folder (a `frontend/.npmrc` holding an npm token could be committed), as are raw files copied into `data/recordings/`.
- The eight Pillow 12.3.0 advisories that FlyGym's `pillow<13` blocks are documented as unreachable (DigitalFly decodes only its own JPEG frames) and ignored by ID in the audit.

## [0.5.0] - 2026-10-13

Version-bump commit `66c6d59`.

### Added

- **FlyVis eyes (optional).** A new sensor model, `flyvis`, runs the rendered compound-eye images through FlyVis 1.2.0 (Lappalainen et al. 2024), a connectome-constrained model of the optic lobe, and lets its cell types drive each circuit's visual projection neurons through FlyWire v783 wiring, with rate or spiking dynamics. It renders the eyes every 50 ms, steps FlyVis every 10 ms and adapts to the starting scene for 0.5 s. It needs the FlyGym body, the connectome model and a circuit with a bridge, and runs at about 0.11–0.15× real time. Install it with `backend/requirements-vision.lock` (CPU-only PyTorch, hashed for Linux and macOS) and `scripts/fetch_flyvis.py`, which downloads the pretrained networks (3.4 MB) and keeps them only if the SHA-256 matches; checkpoints are loaded weights-only. Without FlyVis the app works and the option is unavailable, with the reason shown.
- **FlyVis bridges.** `build_circuit.py flyvis-bridge --circuit NAME` writes `<circuit>.flyvis.json`: FlyWire v783 synapse counts from FlyVis-modelled optic-lobe types onto each visual projection neuron, by eye, tied to the circuit's SHA-256. Bridges for both committed circuits are included (CC BY-NC 4.0).
- **A recorded fly to compare with.** `scripts/fetch_recording.py` downloads one paired left/right DNa02 recording from Rayshubskiy et al. 2025 (Harvard Dataverse, CC0, 71 MB) into `.cache/recordings/` and keeps it only if its size, MD5 and SHA-256 match. `data/recordings/` holds the download manifest and license.
- `compare.rayshubskiy_recording` converts those recordings as the authors' MIT-licensed analysis code does (spike detection, firing rates, yaw calibration). The sign of yaw is undocumented in the files, so it is an explicit setting (`toolkit.py compare --positive-yaw`), defaulting to the direction inferred from the data and the paper.
- `compare.fit_filter`, a cross-validated linear filter that measures how much held-out turning a readout predicts, and `toolkit.jumping_target_run`, which records runs whose target jumps from side to side. `toolkit.py compare` reads the `.mat` files directly.

### Changed

- Parallel toolkit workers limit OpenMP, MKL and OpenBLAS threads to their share of the cores, so FlyVis runs no longer oversubscribe the CPU. Results do not change.

## [0.4.0] - 2026-10-13

Version-bump commit `913acfa`.

### Added

- **Any circuit.** The connectome model loads circuits by name from `data/circuits/` and the ignored `data/circuits/local/` (format 1 or 2, JSON or a NumPy archive). Its steering readout, sensor input and an optional walking-speed population are set by cell type.
- **Spiking dynamics.** The leaky integrate-and-fire model and constants of Shiu et al. 2024, in Brian2's update order, with 0.1 ms substeps, a 1.8 ms synaptic delay, a 2.2 ms refractory period and Poisson sensor input. The run seed makes spiking runs repeatable, and they replay exactly.
- **General circuit builder.** `build_circuit.py prepare` converts the cached FlyWire v783 downloads once into a prepared archive and a cell-type catalog; `build_circuit.py build` selects a circuit around any cell types or root IDs with NumPy only, or every connected neuron with `--whole-brain` (134,180 neurons at 5 synapses).
- **Builds from the app.** A **Build a circuit** tab with catalog autocomplete and a build log, backed by `GET`/`POST /api/connectome/build`, which runs one validated builder subprocess at a time. Built-in circuit names are refused.
- **A steering circuit**, `fafb783-steering.json`: DNa01, DNa02 and DNp09 and their presynaptic partners up to two hops back (4,000 neurons, 120,728 connections, 1,650 cell types), with an equal-weight readout over the three types.
- **Research toolkit.** `digitalfly.toolkit` and `scripts/toolkit.py` run closed-loop trials and parameter sweeps (serially or in spawned processes, with identical results), open-loop bias curves with a left-right mirror test, ablation scans over every cell type and path tracing, and save CSV and JSON under the ignored `runs/toolkit/`.
- **Fits against recordings.** `digitalfly.compare` fits rotational velocity to the right − left firing rate of a readout pair, choosing the lag with the best r², for recordings in a documented CSV or NumPy format and for exported runs; `toolkit.py compare` runs it.
- Endpoints that list circuits (`/api/connectome/circuits`), trace the strongest cell-type paths (`/api/connectome/paths`) and serve the cell-type catalog (`/api/connectome/catalog`).
- Workbench circuit and dynamics selectors; a live circuit view for any circuit that draws every readout pair, traces paths and edits populations.

### Changed

- The model is renamed `connectome`. The v0.3 name `connectome_dna02` is still accepted, and runs recorded with v0.3 still load and replay with error 0.
- The live connectome state names the circuit, its dynamics, the rate units and the readout types. Circuit, dynamics and populations are fixed for a run: changing them needs a reset.
- The spiking update is two to three times faster (masked arithmetic, the same values).
- `scripts/evaluate_models.py` runs on the toolkit, covers both circuits and spiking dynamics, and accepts `--workers`.
- Local builds record the download dates when the source hashes match.

## [0.3.0] - 2026-10-13

Version-bump commit `d2dc76f`.

### Added

- **A FlyWire v783 circuit.** `scripts/build_circuit.py` extracts both DNa02 neurons and their presynaptic partners with at least 5 synapses, up to two hops back, capped at 3,000 neurons (78,615 connections, 1,257 cell types), from pinned, hash-checked sources. An offline rebuild reproduces `data/circuits/fafb783-dna02.json` byte for byte. pyarrow is a build-only extra with its own hashed lock.
- **The connectome model** (`connectome_dna02`) next to the unchanged engineered default: leaky rate units on the circuit, signs assumed from predicted transmitters, each sensor driving the visual projection neurons on its side, and turning from the right − left DNa02 difference. Only global parameters are exposed.
- DNa02 and cell-type silencing; model, DNa02 and cell-type comparison conditions; five recorded readouts; exports (schema 3) with the circuit hash and parameters; replay of connectome runs with error 0.
- A connectome interface: a neural-model selector, a live circuit view by cell type with the strongest connections and per-side DNa02 inputs, DNa02 traces, and a DNa02 tint on the female anatomy labeled as model output.
- A one-click first experiment, a note whenever the real-time factor is below 1×, and left/right told apart by line style as well as color.
- `scripts/evaluate_models.py`, a matched-seed evaluation of both models; `scripts/benchmark.py --model`.
- A GitHub Actions workflow on Ubuntu: the non-physics backend tests and the frontend checks, on Node 22.12.0.

### Changed

- FlyGym stepping is 2.4× faster with bitwise-identical results: the body adapter precomputes the upstream controller's lookups and keeps its arithmetic and order. Runs recorded with v0.2 replay with zero error.
- Node 22.12 or newer is enough (Vite 7 needs no more). When no Python 3.12 is found and uv is installed, setup uses a uv-managed Python 3.12.
- On Linux without a display, MuJoCo defaults to EGL.
- SciPy is a declared dependency, with unchanged pins and hashes. The version is read from one place in the backend.
- `App.tsx` is split into focused components, with no behavior change.

## [0.2.0] - 2026-10-12

Version-bump commit `8f60a4d`, the first commit in this repository.

### Added

- A FlyGym / MuJoCo fly body that walks toward a target, steered by an inspectable six-unit engineered circuit with editable parameters and group silencing.
- Geometric sensing or rendered compound-eye input (721 ommatidia per eye) through an engineered green-contrast encoder.
- Timed stimulus protocols, matched-seed condition comparisons, joint, contact and motion measurements, a run library, CSV/JSON/ZIP export and exact replay.
- A male/female anatomy explorer with twelve published neuron skeletons and brain surfaces, and a validated import for small connectivity graphs.
- Graceful Quit and Save current run & quit; a local-only server bound to 127.0.0.1.
- Apache-2.0 `LICENSE` and `NOTICE`, and the third-party data licenses in `data/atlas/LICENSE.md`.

[Unreleased]: https://github.com/Jeevash23/frankenfly/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/Jeevash23/frankenfly/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Jeevash23/frankenfly/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Jeevash23/frankenfly/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Jeevash23/frankenfly/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Jeevash23/frankenfly/releases/tag/v0.2.0
