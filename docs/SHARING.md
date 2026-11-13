# Sharing the project

## Portable setup

The project can live in any folder. A new user clones or downloads the source, opens a terminal in its root, and runs:

```sh
./scripts/setup.sh
./scripts/start.sh --vision --open
```

`--vision` starts with the rendered compound-eye input, read by an engineered green-object detector; leave it out to start with geometric sensing. It does not install or select FlyVis eyes: those are an optional optic-lobe model, installed separately (see [FlyVis eyes](USAGE.md#flyvis-eyes)) and chosen in the app.

Setup uses Python 3.12 from PATH, an explicit `PYTHON_BIN` or, when uv is installed, a uv-managed Python 3.12, plus Node 22.12–26 and npm. It creates all dependencies inside the checkout. See the [README](../README.md#quick-start) for prerequisites and the [usage guide](USAGE.md) for graphics options and shutdown.

Each checkout has its own local records and imported data. A fresh checkout starts with an empty run library. The published anatomical examples remain available with their original scientific identifiers and source attribution.

## What belongs in version control

| Include | Keep local; ignored by default |
| --- | --- |
| Source code and launch/setup scripts | Python environments, `node_modules`, compiled frontend and caches |
| Dependency manifests and lockfiles | Environment files, private keys and personal editor/assistant settings |
| Generic documentation and configuration examples | Raw logs, screenshots, benchmark reports and session-specific evidence |
| Attributed `data/atlas/`, `data/circuits/` and `data/examples/` assets, and the `data/recordings/` download manifest | Imported connectivity, circuits you build (`data/circuits/local/`), downloads (`.cache/circuits/`, `.cache/recordings/`, `.cache/flyvis/`), optional asset caches and `runs/` exports |

The exclusions are defined in [.gitignore](../.gitignore). They preserve existing local files; they do not delete experiments or sanitize their contents. Creating a ZIP of the entire working folder bypasses these exclusions, so share a repository checkout/source archive instead of bundling the development environment.

Before a public commit, inspect `git status --short` and `git diff --cached`. Ignore rules do not remove files that were already tracked or erase prior history; any such files need separate review. Force-adding an ignored file also bypasses the exclusions. `data/atlas/`, `data/circuits/` and `data/recordings/` are not ignored, so a file copied into them by hand (a downloaded recording, a circuit built with `--committed`) can be committed by accident.

Run exports intentionally retain scientific configuration, timestamps, generated run identifiers and software/platform metadata for reproducibility. Local errors and diagnostics can include absolute paths. For a run you mean to publish, export it share-safe (`POST /api/export` with `{"share_safe": true}`, see [usage](USAGE.md#saved-runs-and-replay)): the export leaves out the operating-system string, makes paths relative to the project or replaces them with `<local>`, and replaces the computer's name in errors and log messages. Review any record you deliberately choose to share.

## Provenance and standard formats

Every export (schema 6, v0.7) carries two more files, also inside its ZIP:

- `ro-crate-metadata.json`, the run's provenance manifest, an [RO-Crate 1.1](https://w3id.org/ro/crate/1.1) (JSON-LD). Its `@graph` holds the run folder (`./`) and each of its files with size and SHA-256; the run as a `CreateAction` with start and end times; DigitalFly as a `SoftwareApplication` with its version and git commit; every installed package and Python, and every `backend/requirements*.lock` with its SHA-256; the connectome release (`#connectome`) with each source file it was built from (URL, release, provider, license, SHA-256, retrieval date) and the circuit file (`#circuit`: name, SHA-256, build settings); the FlyVis checkpoint and bridge hashes for FlyVis-eye runs; and every setting as a `PropertyValue`: the seed, body engine, sensor model, neural model, controller, circuit, dynamics, the initial target, the time steps, the duration, each logged input change (`#change-N`) and each setting that differs from the defaults (`#changed-PATH`, with the default). The root's `license` is CC BY-NC 4.0 whenever the run used FlyWire-derived data; otherwise it says no license has been chosen yet, so choose one before publishing.
- `methods.md`, a methods paragraph drafted only from the manifest, so every statement in it can be checked there. Review and edit it before use: it says what the software did, not what the results mean.

Runs saved before v0.7 get both on demand, built from their `metadata.json` (nothing is written into the saved run): through the run library's export menu, `GET /api/runs/FOLDER/manifest` and `/methods`, or `scripts/toolkit.py manifest RUN` and `methods RUN`. Their manifests say the git commit was not recorded, and list the connectome's source files only when the circuit file on disk still has the run's hash. `GET /api/batches/COMPARISON_ID/methods` and `scripts/toolkit.py methods RUN RUN ...` draft one paragraph for a comparison: what every trial shares, the conditions and their sizes, the settings that vary and the statistics used.

A share-safe export's manifest is built from its share-safe metadata, so it carries no platform string, absolute path or host name either. Uploading a run to Zenodo, DANDI or another archive stays a manual step for you to review and sign off.

**NWB.** With pynwb installed (`./scripts/setup.sh --with nwb`, or `backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-nwb.lock`, about 20 MB), any saved run, of any schema, can be written as a [Neurodata Without Borders](https://nwb.org) 2 file: **NWB** in the run library's export menu, `GET /api/runs/FOLDER/nwb`, or `scripts/toolkit.py nwb RUN [--out FILE]`, which also runs pynwb's validator. The file uses core NWB types only; see [usage](USAGE.md#nwb-export) for where each signal goes. The file is written into the run folder as `FOLDER.nwb` (rewritten on each request) and is not part of the run's ZIP or manifest.

### Provenance manifest terms

Terms schema.org lacks use the `digitalfly:` prefix, which the manifest's `@context` maps to this section: `gitCommit`, `gitDirty` (uncommitted changes to tracked files when the run started), `schemaVersion`, `shareSafe`, `reproducibility`, `manifestBuilt` (set on manifests built after export), `default` (a changed setting's default), `step` and `source` (an input change's control step and origin: manual or protocol), `sources` (how the connectome's sources were found), `file` and `build` (the circuit file's path and build settings), `hashScope`, `retrieved` and the connectome model's counts and equations (`neurons`, `connections_active`, `equation`, `readout`, …).

## Scientific identifiers and attribution

Published neuron IDs, dataset URLs, content hashes and upstream author/license notices are part of the scientific provenance, not personal workstation information. Keep them with the anatomical samples. The datasets and dependencies retain their source-specific licenses; see [attribution](ATTRIBUTION.md) and [research data](RESEARCH.md#licensing-and-attribution).

Anything you share that contains FlyWire-derived data (the circuits, their FlyVis bridges, `data/atlas/female.json` or the female skeletons) is CC BY-NC 4.0: non-commercial use only, with credit to the FlyWire Consortium. The license files in [data/atlas/](../data/atlas/LICENSE.md), [data/circuits/](../data/circuits/LICENSE.md) and [data/recordings/](../data/recordings/LICENSE.md) list what each file needs.
