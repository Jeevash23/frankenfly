# DigitalFly — v0.7 status

DigitalFly is a local research workspace for embodied sensorimotor experiments. See the [quick start](README.md#quick-start) for setup and shutdown, and [INSTALL](docs/INSTALL.md) for Docker, the dev container and headless servers. Changes by version are in the [changelog](CHANGELOG.md).

## Implemented

- Real FlyGym / MuJoCo walking and turning with the female-derived NeuroMechFly body, joints, contact and adhesion; geometric sensing or rendered compound-eye input (721 ommatidia per eye) through an engineered green-contrast encoder; optional FlyVis eyes (Lappalainen et al. 2024) whose optic-lobe cell types drive each circuit's visual projection neurons through an unsigned FlyWire v783 bridge.
- Two neural models. The default is the engineered six-unit circuit with editable parameters and group silencing. The connectome model runs any FlyWire v783 circuit with leaky rate units or the spiking neurons of Shiu et al. 2024: data-derived wiring, signs assumed from predicted transmitters, engineered input and readout, global parameters only. Four circuits ship: the DNa02 circuit (3,000 neurons, default), a steering circuit around DNa01, DNa02 and DNp09 (4,000 neurons), and side-balanced versions of both (3,000 and 3,999).
- Engineered manipulations of any cell type on the left, the right or both sides (silence, scale its output, or activate it), live, as initial interventions, in protocols and in comparisons; an engineered motor path (readout weights and pooling, a delay and a low-pass) with a motor-clipping diagnostic. With both off, the default, the numbers are v0.5's.
- A reproducible circuit builder with pinned, hash-checked sources, an optional per-side cap (`--balance-sides`), atomic writes, and builds from the command line or the app's **Build a circuit** tab, up to the whole brain (134,180 neurons at 5 synapses).
- A research toolkit (`digitalfly.toolkit`, `scripts/toolkit.py`): parallel trials and sweeps that keep going past failed trials and dead workers, stream and resume, report Wilson and bootstrap intervals and paired differences, and record their provenance; bias curves with a mirror test; ablation scans that silence, scale or activate each cell type; path tracing; the held-target readout table; an assumption-sensitivity analysis (`robustness`); and fits of turning against readout activity in runs and recorded flies.
- A comparison with one recorded fly (Rayshubskiy et al. 2025, CC0), downloaded with size and hash checks and converted as the authors' code does; stimulation epochs are left out of the fits by default, and several recordings and runs can be fitted together with their spread.
- Experiments: timed stimulus protocols, a one-click first experiment, presets, matched-seed comparisons with custom conditions, unpaced runs, per-condition statistics, and a Workbench restored after each comparison.
- Records: a run library with paging, filters, tags, notes and deletion; CSV/JSON/ZIP exports (schema 5, optionally share-safe and with per-cell-type activity) written off the simulation thread; exact replay from the command line or as a background job in the app, which also says whether the installed software still matches the run's.
- Male/female anatomical surfaces and twelve published neuron skeletons, and a validated import of small connectivity graphs, which never drives the body.
- One authoritative simulation worker that survives failing commands, builds a new configuration before replacing the running one, checks commands against the circuit actually loaded, pauses at its recording limits and shuts down gracefully (Quit, or Save current run & quit). A Python client and examples drive the running app from scripts.
- Installation: `scripts/setup.sh` (with `--backend-only`, `--with builder,flyvis,recording,nwb,mcp,gpu` and `--check`), `scripts/doctor.py`, automatic OpenGL backend selection, Python 3.12 (recorded stack) or 3.13 and 3.14 without FlyVis, a Docker image with headless EGL, and a dev container.
- **v0.7, the research-hub foundations** ([roadmap](docs/ROADMAP.md)):
  - A validation scorecard (`scripts/toolkit.py scorecard`, the **Scorecard** page) that scores each model against published perturbation results, with rules fixed in advance ([results and caveats](docs/RESEARCH.md)).
  - A connectivity explorer (the **Explorer** page and the toolkit) over the whole FlyWire v783 brain or any circuit: partners, shortest and strongest routes, a linear influence score and Neuroglancer links. Every result can be silenced, activated or used to seed a circuit.
  - A provenance manifest (RO-Crate) and a drafted methods paragraph with every export (schema 6), and optional NWB export that passes pynwb's validator.
  - An optional GPU brain backend (`connectome_parameters.backend = "torch"`, in its own environment, `./scripts/setup.sh --with gpu`), checked against the CPU backend by an agreement harness. Batched MuJoCo Warp worlds are benchmarked but not yet used by the toolkit.
  - An MCP server (`scripts/mcp.py`) with 32 tools and an append-only audit log, so AI agents can drive the app; and a plugin API (version 1, [PLUGINS.md](docs/PLUGINS.md)) for sensors, stimulus programs, scorecard tests, metrics and toolkit commands.
  - The app is reorganised as a hub: a sidebar, an Overview page, compact page headers, a Ctrl+K command palette, light and dark themes and a phone layout.
- CI on every pull request: backend tests on Python 3.12–3.14, FlyGym physics tests under Xvfb, frontend checks on Node 22 and 24, browser end-to-end tests, a generated-type check and dependency audits; a Docker build and smoke test; a weekly download-link check.

## Validation summary

### v0.7

v0.7 was checked on the reference laptop (x86-64 Linux, CachyOS, Python 3.12, Node 26, an RTX 4050 Laptop GPU) with the prepared FlyWire archive and the FlyVis extra installed:

| Check | v0.7 result |
| --- | --- |
| `./scripts/check.sh` | 442 backend tests passed, 8 skipped (FlyGym physics included); 119 frontend unit tests passed; formatting, TypeScript and the production build passed |
| GPU backend (`backend/.venv-gpu`) | `backend/tests/test_gpu.py`: 17 passed. The agreement harness passes on all five circuits (rate: largest difference 6.1e-16; spiking: per-neuron rate correlation between the backends equal to that between CPU seeds) |
| Browser end to end | 16 Playwright tests passed in headless Chromium, including the new sidebar, redirects, theme, palette and phone drawer |
| MCP server | Started over stdio and drove a short run against a locally started app: tools listed with their annotations, a run reset with a plugin sensor, exported, read back with its manifest, and exported as NWB |

**Speed** (`scripts/benchmark.py --neural --backend both`, measured while another job kept the GPU busy, so pessimistic): spiking dynamics run 3.7–4.8× faster on the GPU for the committed circuits and 14× for the whole brain (17.5 → 1.25 ms per 1 ms step); rate dynamics 7.9× for the whole brain (5.5 → 0.69 ms) and between no gain and 1.9× for the small circuits. Details are in the [research guide](docs/RESEARCH.md).

**Not verified for v0.7:** GitHub Actions has not run on this repository since 13 October 2026, so the CI matrix (Python 3.13 and 3.14, Node 22 and 24, the Docker build, the dependency audits including the new MCP and GPU locks) was not exercised for v0.7; macOS and Docker were not re-run; the GPU environment's packages were reflink-copied from an existing installation, so pip did not hash-check them.

### v0.6

The v0.6 validation ran on x86-64 Linux with Python 3.12, Node 22.22 and the pinned dependencies, in a container without a display, libEGL or OSMesa: `./scripts/check.sh` therefore ran the physics under `xvfb-run` with `MUJOCO_GL=glfw`, and headless EGL was verified in the Docker image instead. The prepared FlyWire archive was present; the FlyVis install and the recorded fly could not be downloaded there. v0.2 was validated on macOS/ARM64; v0.3–v0.6 have not been re-run there. These describe tested platforms, not a required hardware model.

| Check | v0.6 result |
| --- | --- |
| Backend suite (`./scripts/check.sh`) | 353 passed, 3 skipped (FlyVis 2, the downloaded recording 1). This includes the 11 FlyGym physics tests that need no FlyVis (the fast stepping path's bitwise match with FlyGym's own controller, compound eyes, the connectome model on the real body, a replay job on FlyGym, a body replaced by a reset that keeps rendering) and the four tests that rebuild the committed and side-balanced circuits from the prepared archive. Without the archive those 4 skip too; without any OpenGL backend the physics tests fail. See [validation commands](docs/evidence/README.md) |
| Python 3.13 and 3.14 | The fast suite and the physics tests passed on both; FlyVis installs on 3.12 only |
| Frontend | 81 unit tests passed; Prettier formatting, TypeScript and the production build passed |
| Browser end to end | 10 Playwright tests passed in headless Chromium against the toy engine: loading without console errors, run, pause and step, moving the target by click and keyboard, a cell-type manipulation, a comparison at full speed with its statistics, a share-safe export tagged, filtered and verified by replay, presets, URL routing across reloads, the builder's balance option and the Quit dialog. In CI, without the prepared catalog, the builder test skips |
| Replay | Default runs compute exactly what v0.5 did: 130 arrays over 26 toy-body scenarios and the FlyGym pose, rates, motor commands and 66 joint angles, compared with v0.5 output. A spiking run recorded by v0.5 with live parameter edits replays with error 0 through the compatibility path. A FlyGym run on `fafb783-steering-balanced` with a left-side DNp09 scaling and live motor-delay and low-pass edits, exported share-safe, was verified by the app's replay job: 53 samples, maximum absolute error 0, same software |
| Circuit build | With the prepared archive, `fafb783-steering`, `fafb783-dna02-balanced` and `fafb783-steering-balanced` rebuild byte for byte, and the general builder reproduces `fafb783-dna02`'s neurons, connections and cap report |
| Docker image | Built from the repository (Ubuntu 24.04, hashed locks, the built interface): 1.6 GB on disk, 378 MB compressed, running as uid 1000 with no build-time proxy settings or certificates inside. On a port published to 127.0.0.1: healthy; a FlyGym reset with compound eyes and the connectome model; real headless EGL frames from `/api/frame` and `/api/eyes`; presets saved, listed and deleted as the non-root user; a foreign Origin refused (403) and a foreign Host (400); a share-safe export; the doctor with no blocking problem; `scripts/replay.py` in the container replaying the exported FlyGym compound-eye run with error 0; a clean stop |
| Linux rendering | GLFW under Xvfb (reference container) and EGL with Mesa on the CPU (Docker image) passed. OSMesa was not available, so its fallback was not exercised |
| Speed | Not re-measured for v0.6; the default arithmetic is unchanged. v0.5, reference laptop: 0.05 ms (rate) and 0.3 ms (spiking) per 1 ms neural step for the 3,000-neuron circuit, 3.2 and 6.7 ms for the whole brain; FlyVis-eye runs 0.11–0.15× real time (`scripts/benchmark.py --neural`, `--flyvis`). Exporting a full-length run now holds the simulation for 10–40 ms instead of 1–6 s |

**Not verified for v0.6:**

- The FlyVis extra (`--with flyvis`, `EXTRAS=flyvis` in Docker, and the vision lock's next regeneration): its download hosts were unreachable. Its tests, timings and closed-loop results are v0.5's.
- The recorded fly's fit with the stimulation epochs left out, the new default: the recording could not be downloaded. The fly row in the research guide includes them and is labeled so.
- macOS (last validated at v0.2), Windows through WSL2, ARM64 hosts for the Docker image, the dev container in VS Code or Codespaces (it was checked with the Dev Containers command-line tool), and NVIDIA EGL.

Two upstream deprecation notices (Starlette's httpx adapter and an AnyIO alias) appear in the tests; they are not failures. There is no guarantee of bitwise numerical agreement across devices, graphics stacks or dependency versions. Raw logs, session identifiers and machine-specific measurements are local evidence and are excluded from version control; to reproduce the checks, see [validation commands](docs/evidence/README.md).

## Evaluation summary

The models were evaluated with matched seeds on the toy body and, for a smaller set, on headless FlyGym; the tables are in the [research guide](docs/RESEARCH.md#evaluation). The engineered model reaches nearly every target. The DNa02 circuit turns toward lateral targets first but, with its strong left bias, circles them instead of reaching them (0/60 toy, 0/18 FlyGym). The steering circuit reaches 57/60 and 18/18; a readout sweep shows that its reaching comes from DNp09. With spiking dynamics both circuits keep a strong left bias and reach no targets. With FlyVis eyes neither circuit steers toward the target (0/18 and 3/18 on FlyGym).

**Side balance.** Ablation scans showed that the neuron cap sampled some visual projection types unevenly between the sides, and every such neuron on a side receives the same sensor value. The [side-balanced circuits](docs/RESEARCH.md#side-balanced-circuits) keep each cell type's sides in pairs. On the toy body, balancing reduces the DNa02 circuit's equal-input left turn from −0.179 to −0.082 (rate) and from −0.683 to −0.188 (spiking) without removing it; the balanced DNa02 circuit reaches 10/60 targets instead of 0/60 but still orbits most of them, 2.9 mm away instead of 7.5 mm. The balanced steering circuit reaches 60/60, but leans right with equal input (+0.148, from +0.026). A short spiking check (12 trials each) has the balanced DNa02 circuit reach all 12 targets and then circle them, and the balanced steering circuit reach 8 and then walk away. The whole-brain circuit, which has no cap, also turns left with equal input (−0.171), so sampling explains only part of the bias. Balanced circuits were evaluated on the toy body only.

**Assumption sensitivity.** `scripts/toolkit.py robustness` reruns the open-loop analyses over the sign rule, the synapse threshold and the dynamics ([results](docs/RESEARCH.md#how-sensitive-is-a-result-to-the-modelling-assumptions)). The DNa02 circuit's left turns (with equal input, and for targets ahead, to the left and 45° to the right) hold in all 12 variants; its right turn for a target 90° to the right holds in 9. Of the steering circuit's conclusions only one holds in all 12: a target 90° to the left turns it left. With rate dynamics the steering circuit and its balanced version agree on every conclusion, reaching included; with spiking dynamics neither keeps them, so for that circuit the dynamics matter more than the sampling.

These are computational results about these models, not biological validation.

## Scientific scope

**Neither model is a validated fly brain.** The engineered model's six rate units have hand-chosen weights. The connectome model's circuits have real FlyWire wiring, but their signs are assumed, the rate dynamics are a uniform rule with global gains, the spiking neurons share one published set of constants, every input neuron on a side receives the same sensor value, and turning is a sum over a few readout types. The motor path's weights, delay and low-pass, the cell-type manipulations (activation approximates optogenetic activation, uncalibrated) and the per-side cap are engineered choices or sampling assumptions, not fitted values or corrections. The nerve cord, electrical synapses and neuromodulation are absent. A whole-brain circuit can be built and run, far slower than real time.

**Both sexes have anatomical data; only the female-derived body is simulated.** The connectome circuits and the body both come from female flies. There is no male body model, fitted sex-specific physiology or behavior, flight, feeding, learning, courtship or multi-animal interaction. The visual encoder is an engineered green-object detector. The target is a non-colliding landmark. Long trajectories can overshoot, circle or leave the bounded schematic display.

The next scientific milestone is a circuit whose dynamics and motor mapping are fitted and tested against measured behavior and neural data, including held-out interventions; the per-side manipulations and the motor path are the tools for such tests, not their result. The comparison with one recorded fly shows the model turning almost instantly after its DNa02 activity where the fly lags by about 180 ms, and its spiking DNa02 firing tens of times more than the recorded ones; nothing has yet been fitted to recorded data. Methods and dataset-specific licensing are in the [research guide](docs/RESEARCH.md).

## Repository scope

Runtime files stay local. The repository contains instructions, code, dependency locks, presets, examples and attributed scientific assets. Local environments, downloaded datasets, locally built circuits, saved presets, imported data, run records and execution evidence are excluded by [.gitignore](.gitignore). The Docker image is built from the repository and not published. See [sharing the project](docs/SHARING.md).

The code and documentation are Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The scientific data keeps its own licenses, listed in [data/atlas/LICENSE.md](data/atlas/LICENSE.md), [data/circuits/LICENSE.md](data/circuits/LICENSE.md) and [data/recordings/LICENSE.md](data/recordings/LICENSE.md); all FlyWire-derived data, including the balanced circuits, the FlyVis bridges and circuits you build, is CC BY-NC 4.0, for non-commercial use only.
