# Changelog

All notable changes to DigitalFly are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The version is the one in `backend/pyproject.toml`; every export records it as `application_version`, so a saved run can be matched to the release that produced it. Each release below names its version-bump commit.

Unless an entry says otherwise, a release keeps earlier runs replaying with the same numbers: committed circuits, default parameters and recorded runs are not changed silently.

## [Unreleased]

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

[Unreleased]: https://github.com/Jeevash23/frankenfly/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Jeevash23/frankenfly/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Jeevash23/frankenfly/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Jeevash23/frankenfly/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Jeevash23/frankenfly/releases/tag/v0.2.0
