# Sharing the project

## Portable setup

The project can live in any folder. A new user clones or downloads the source, opens a terminal in its root, and runs:

```sh
./scripts/setup.sh
./scripts/start.sh --vision --open
```

Setup uses Python 3.12 from PATH, an explicit `PYTHON_BIN` or, when uv is installed, a uv-managed Python 3.12, plus Node 22.12–26 and npm. It creates all dependencies inside the checkout. See the [README](../README.md#quick-start) for prerequisites and the [usage guide](USAGE.md) for graphics options and shutdown.

Each checkout has its own local records and imported data. A fresh checkout starts with an empty run library. The published anatomical examples remain available with their original scientific identifiers and source attribution.

## What belongs in version control

| Include | Keep local; ignored by default |
| --- | --- |
| Source code and launch/setup scripts | Python environments, `node_modules`, compiled frontend and caches |
| Dependency manifests and lockfiles | Environment files, private keys and personal editor/assistant settings |
| Generic documentation and configuration examples | Raw logs, screenshots, benchmark reports and session-specific evidence |
| Attributed `data/atlas/`, `data/circuits/` and `data/examples/` assets | Imported connectivity, downloaded connectome data (`.cache/circuits/`), optional asset caches and `runs/` exports |

The exclusions are defined in [.gitignore](../.gitignore). They preserve existing local files; they do not delete experiments or sanitize their contents. Creating a ZIP of the entire working folder bypasses these exclusions, so share a repository checkout/source archive instead of bundling the development environment.

Before a public commit, inspect `git status --short` and `git diff --cached`. Ignore rules do not remove files that were already tracked or erase prior history; any such files need separate review. Force-adding an ignored file also bypasses the exclusions.

Run exports intentionally retain scientific configuration, timestamps, generated run identifiers and software/platform metadata for reproducibility. Local errors and diagnostics can include absolute paths. Review any record you deliberately choose to share.

## Scientific identifiers and attribution

Published neuron IDs, dataset URLs, content hashes and upstream author/license notices are part of the scientific provenance, not personal workstation information. Keep them with the anatomical samples. The datasets and dependencies retain their source-specific licenses; see [attribution](ATTRIBUTION.md) and [research data](RESEARCH.md#licensing-and-attribution).
