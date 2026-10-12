# DigitalFly — v0.3 status

DigitalFly is a local research workspace for embodied sensorimotor experiments. See the [quick start](README.md#quick-start) for portable setup and shutdown instructions.

## Implemented

- Real FlyGym / MuJoCo walking and turning with the female-derived NeuroMechFly body, joints, contact and adhesion.
- Selectable geometric sensing or actual rendered compound-eye input, with 721 ommatidia per eye and an explicitly engineered green-contrast encoder.
- Two neural models. The default is the engineered six-unit circuit with editable parameters, group silencing, exact weights and computed rates. The connectome model runs leaky rate units on a 3,000-neuron FlyWire v783 subcircuit around the two DNa02 steering neurons: data-derived wiring, signs assumed from predicted transmitters, engineered dynamics and input/output mapping, global parameters only.
- A reproducible circuit builder (`scripts/build_circuit.py`) with pinned, hash-checked sources, recorded thresholds, hops, cap and license.
- A live circuit view by cell type, DNa02 and cell-type silencing, model and DNa02 conditions in comparisons, and a live DNa02 tint on the female anatomy, labeled as model output.
- Male/female anatomical reference surfaces and twelve published neuron skeletons, with rotation, selection, source IDs and attribution.
- Validated local structural-connectivity import, preserving string IDs and declared provenance. Imported graphs do not replace the walking controller.
- Timed stimulus protocols, a one-click first experiment, matched-seed condition comparisons, sequential trials, pause/resume/cancel and automatic completed-trial exports.
- Joint, contact and motion measurements; a local run library, trajectory overlays, configuration restoration, CSV/JSON/ZIP export and exact replay for both models.
- One authoritative worker with bounded queues/history/recording, explicit error handling and graceful Quit / Save current run & quit.
- A light GitHub Actions workflow on Ubuntu for the non-physics tests and the frontend checks.

## Validation summary

The v0.3 validation covered x86-64 Linux with EGL rendering, Python 3.12, Node 26 and the pinned dependencies. v0.2 was validated on macOS/ARM64; v0.3 has not been re-run there. These describe tested platforms, not a required hardware model.

| Check | v0.3 result |
| --- | --- |
| Full backend suite | 46 passed, including 6 real FlyGym tests: graphics, compound eyes, the fast stepping path's bitwise match with FlyGym's own controller, and the connectome model on the real body |
| Frontend unit tests | 20 passed: plotting, protocol editing, error messages, model selection, comparison rules, the first experiment, the slow-down note and the circuit layout |
| Prettier formatting, TypeScript and production build | Passed |
| Linux rendering | EGL and GLFW passed; OSMesa is not installed on the reference system, so the OSMesa fallback could not be exercised |
| Performance | About 2.4× faster FlyGym stepping (geometric and compound-eye sensing) with bitwise-identical body states |
| Replay | Runs recorded with v0.2 (geometric and compound-eye, with stimulus, intervention and parameter events) replay under v0.3 with maximum absolute error 0; connectome runs replay with error 0 |
| Circuit build | An offline rebuild reproduces `data/circuits/fafb783-dna02.json` byte for byte |
| Refactor | The split of `App.tsx` renders identical HTML on every page (same SHA-256 after removing run ID and memory readout) |
| Browser flow | Both models, the model selector, circuit view and side panel, DNa02 and cell-type silencing, the atlas tint, the first-experiment preset and a four-trial DNa02 comparison exercised on the toy body |

The two models were evaluated with matched seeds on the toy body and, for a smaller set, on headless FlyGym; the tables are in the [research guide](docs/RESEARCH.md#evaluation). The engineered model reaches nearly every target. The connectome model's first turn goes toward lateral targets, but its strong left bias holds the target at its right side and it circles at a fixed distance instead of reaching it. Silencing one DNa02 makes it turn toward the intact side; silencing both stops all turning. These are computational results about this model, not biological validation.

Two upstream TestClient deprecation notices were present in the tests. There is no guarantee of bitwise numerical agreement across devices or dependency versions.

Raw logs, session identifiers and machine-specific measurements are local generated evidence and are excluded from version control. To reproduce the checks and benchmark your own hardware, see [validation commands](docs/evidence/README.md).

## Scientific scope

**Neither model is a whole-brain simulation or a validated fly brain.** The engineered model's six rate units have hand-chosen weights. The connectome model's 3,000 neurons have real FlyWire wiring, but their signs are assumed, their dynamics are a uniform leaky-rate rule with global gains, every visual projection neuron on a side receives the same sensor value, and only DNa02 steers. The fly's other descending neurons, the nerve cord and neuromodulation are absent.

**Both sexes have anatomical data; only the female-derived body is simulated.** The connectome circuit and the body both come from female flies. There is no male body model, fitted sex-specific physiology/behavior, spiking network, flight, feeding, learning, courtship or multi-animal interaction. The visual encoder is an engineered green-object detector. The target is a non-colliding landmark. Long trajectories can overshoot, circle or leave the bounded schematic display.

The next scientific milestone is a circuit whose dynamics and motor mapping are fitted and tested against measured behavior and neural data, including held-out interventions. Methods and dataset-specific licensing are in the [research guide](docs/RESEARCH.md).

## Repository scope

Runtime files stay local. The repository contains instructions, code, dependency locks, examples and attributed scientific assets. Local environments, downloaded datasets, imported data, run records and execution evidence are excluded by [.gitignore](.gitignore). See [sharing the project](docs/SHARING.md).

The code and documentation are Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The scientific data keeps its own licenses, listed in [data/atlas/LICENSE.md](data/atlas/LICENSE.md) and [data/circuits/LICENSE.md](data/circuits/LICENSE.md); all FlyWire-derived data is CC BY-NC 4.0, for non-commercial use only.
