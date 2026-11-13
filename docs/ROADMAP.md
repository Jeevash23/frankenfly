# DigitalFly roadmap: from virtual fly to computational-neuroscience hub

Written 13 November 2026, at v0.6.0. This is a plan, not a promise: each item lands as its own release with the usual changelog, tests and replay guarantees.

## Where DigitalFly stands

v0.6 is a solid research workspace: a FlyGym 2.1 body, the engineered and FlyWire v783 brains (rate or spiking, up to the whole brain), FlyVis eyes, per-side manipulations of any cell type, side-balanced circuits, ablation scans, sweeps, assumption sensitivity, matched-seed comparisons, a run library with exact replay, a fit against one recorded fly, a Python client, Docker and CI.

Its scientific limits are written down in [RESEARCH.md](RESEARCH.md#what-remains-before-biological-simulation-claims): the motor mapping is engineered, nothing is fitted to fly data, vision is the only sense, there is no nerve cord and no learning.

## The landscape in 2026

Embodied connectome flies are no longer rare. Since March 2026:

- **Eon Systems** coupled the whole-brain LIF model of Shiu et al. (2024) to NeuroMechFly for walking, grooming and feeding. They have no nerve cord, and their open code (`eonsystemspbc/fly-brain`) is brain-only, with several simulator backends checked against Brian2.
- **"Embodied Drosophila"** (Rojas Aliaga, a Zenodo preprint) runs the FlyWire brain on a GPU with six senses on FlyGym.
- **`flybrain`** (PyPI, November 2026) simulates the whole male CNS on a laptop GPU, with no body.

Around them sit the query and data tools:

- [FlyWire Codex](https://codex.flywire.ai): paths, influence scores and cross-dataset links.
- [neuPrint](https://neuprint.janelia.org): the male CNS, MANC, the optic lobe and the hemibrain.
- natverse/navis, CAVE, Virtual Fly Brain (which has an MCP server), and FlyVis.

Beyond the fly:

- Simulators: Brian2, NEST, NEURON/NetPyNE, Arbor.
- Standards: SONATA, NeuroML, NWB/DANDI.
- Hubs: Open Source Brain v2, EBRAINS, the Open Brain Institute.
- Viewers: Neuroglancer, napari.

What nobody ships yet:

1. **A closed loop through the brain *and* the nerve cord.** Two whole-CNS connectomes now make this possible: BANC (female, CC BY 4.0) and the male CNS v1.0 (Janelia, CC BY 4.0). A connectome VNC walking model exists (Pugliese et al. 2025) but has no body.
2. **A validation scorecard**: a standing suite of known perturbation → behavior results that any model is scored against. Eon lists it as planned.
3. **A simulation tool that agents can drive** (MCP), and one that links connectivity queries directly to experiments.

DigitalFly's advantage is rigor: matched seeds, exact replay, assumption sensitivity and fits to recordings. The plan is to be the **reproducible, validated hub** for embodied fly neuroscience, open to other models through plugins and standard formats, rather than just another embodied fly.

## Phases

Estimates are our working time (Claude sessions, often several in parallel) plus the waits that don't shrink: downloads on a metered connection, compute runs, and steps only the owner can take.

### v0.7: Hub foundations

These five tracks don't depend on each other and can run in parallel sessions.

| Track | What it adds | Estimate |
|---|---|---|
| **A. Validation scorecard** | `scripts/toolkit.py scorecard` and an app page that score a model on published results: DNa02 → ipsilateral turning (Rayshubskiy 2025), MDN → backward walking, Giant Fiber → escape posture, antennal DNs → grooming, sugar GRNs → MN9 (Shiu 2024). Each test cites its source, gives pass/partial/fail with the measured number, and runs in CI on the toy body. | 1–2 sessions |
| **B. Connectivity explorer** | Upstream/downstream partners, shortest and strongest paths, and a steady-state influence score (BANC-style) over the loaded connectome, each with "silence / activate this in the Workbench". Export any circuit or path as a Neuroglancer link, so neurons stream from public FlyWire buckets with nothing downloaded. | 1–2 sessions |
| **C. Provenance and standard formats** | A provenance manifest for every run (dataset and annotation versions, git SHA, lock hashes, seeds, parameter diff from defaults; RO-Crate shaped), **NWB export** of runs (spikes/rates as `Units`/`TimeSeries`, body kinematics as `Position`/`CompassDirection`), and an auto-drafted methods paragraph. Zenodo upload stays manual (owner's sign-off). | 1–2 sessions |
| **D. Speed** | Enable FlyGym 2.1's MuJoCo Warp backend (`flygym[warp]`) for batched worlds in sweeps, and a GPU brain backend (PyTorch sparse) tested spike-for-spike in distribution against the current Numba path. Sized for a 6 GB laptop GPU. Download: warp-lang and mujoco-warp are small. A CUDA PyTorch wheel is about 2.5 GB, so this track asks first. | 1–2 sessions |
| **E. Interfaces** | An **MCP server** over the existing API (build circuit, run, scan, compare, fetch run), with an audit log, usable next to the Virtual Fly Brain MCP. Plus a **plugin system** (Python entry points) for brains, sensors, stimuli and metrics, so other labs add models without forking. | 1–2 sessions |

Alongside: a **UI refresh**. That means a home dashboard (recent runs, scorecard, jobs), an experiment notebook view that keeps a question, its runs and its conclusion together, a consistent design system, and a docs site. About 1–2 sessions after A–C land, since it presents their output.

### v0.8: More of the fly

| Track | What it adds | Estimate and waits |
|---|---|---|
| **F. Multi-connectome** | Load BANC and the male CNS v1.0 (plus MANC IDs) beside FlyWire v783, with a cell-type crosswalk across them. Pull only subgraphs via neuprint-python / the Codex download API, never the 10 GB synapse tables. | 2 sessions. Needs a free neuPrint token (owner signs in). Each subgraph is tens to a few hundred MB; the full male-CNS weight table is 1.1 GB and needs asking first. |
| **G. More senses** | Olfaction (FlyGym odor arenas → ORN input), taste (leg and proboscis GRNs → feeding), mechanosensation (Johnston's organ, leg contact → grooming). These feed scorecard tests that are blocked today. | 1–2 sessions |
| **H. Fitting** | Fit dynamics and the motor path to many recordings and metrics: Optuna/CMA-ES for point estimates, `sbi` for posteriors, running on the batched worlds from D. Stream NWB recordings from DANDI (for example dandiset 000247) instead of downloading them. | 2 sessions plus compute runs (hours) |

### v0.9: Brain to legs

**I. The nerve cord.** Descending neurons → a connectome VNC rate model (starting from the 4,604-neuron Pugliese et al. circuit, then BANC's own VNC) → leg motor neurons → FlyGym joint targets. The engineered DN → controller path stays as the default and a comparison condition. This closes the field's biggest open gap and is the strongest candidate for a paper. Several sessions plus tuning runs; depends on F and H.

### v1.0: Learning and release

- **J. Plasticity.** Dopamine-gated KC → MBON learning in the mushroom body, in closed loop: odor conditioning, then a choice assay. No embodied fly model learns yet. Needs G.
- **K. Interchange.** SONATA and NeuroML export of circuits, so they run in NEST, BMTK or NetPyNE and can be listed on Open Source Brain.
- **L. Release.** A docs site with tutorials, a software paper (JOSS-style), and a stable plugin and file-format API.

Later, once the fly core is solid: a flight body (flybody), larval or worm connectomes, and shared run links for collaborators.

## Steps only the owner can take

- **GitHub account review.** The account has been hidden from logged-out visitors since about 22 Oct 2026 (support ticket #4890042), and GitHub Actions hasn't run since 13 Oct: the v0.6 pull request (#5) merged without CI. Until that clears, run `scripts/check.sh` locally before merging.
- **neuPrint sign-in** for a token (track F).
- **Approval of downloads over 300 MB** (CUDA PyTorch for D, full connectome tables).
- **Decisions:** whether DigitalFly stays fly-only or grows beyond the fly, and when to submit the software paper.
