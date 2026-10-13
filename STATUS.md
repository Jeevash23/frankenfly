# DigitalFly — v0.4 status

DigitalFly is a local research workspace for embodied sensorimotor experiments. See the [quick start](README.md#quick-start) for portable setup and shutdown instructions.

## Implemented

- Real FlyGym / MuJoCo walking and turning with the female-derived NeuroMechFly body, joints, contact and adhesion.
- Selectable geometric sensing or actual rendered compound-eye input, with 721 ommatidia per eye and an explicitly engineered green-contrast encoder.
- Two neural models. The default is the engineered six-unit circuit with editable parameters, group silencing, exact weights and computed rates. The connectome model runs any FlyWire v783 circuit with leaky rate units or the spiking neurons of Shiu et al. 2024: data-derived wiring, signs assumed from predicted transmitters, engineered input and readout, global parameters only. Two circuits ship: the v0.3 DNa02 circuit (3,000 neurons, default) and a steering circuit around DNa01, DNa02 and DNp09 (4,000 neurons).
- Configurable populations by cell type: the steering readout (right − left summed over types), the neurons that receive the sensors and an optional speed drive.
- A reproducible circuit builder (`scripts/build_circuit.py`) with pinned, hash-checked sources, recorded thresholds, hops, cap and license. It builds circuits around any cell types or root IDs, up to the whole brain (134,180 neurons at 5 synapses), from the command line or the app's **Build a circuit** tab, into the git-ignored `data/circuits/local/`.
- A live circuit view by cell type for any circuit, with every readout pair, path tracing to the readout and population editing; DNa02 and cell-type silencing; model and DNa02 conditions in comparisons; a live DNa02 tint on the female anatomy, labeled as model output.
- A research toolkit (`digitalfly.toolkit`, `scripts/toolkit.py`): batch trials and parameter sweeps in parallel processes, open-loop bias curves with a mirror test, ablation scans over every cell type, path tracing, and fits of turning against readout activity in exported runs or fly recordings (`digitalfly.compare`).
- Male/female anatomical reference surfaces and twelve published neuron skeletons, with rotation, selection, source IDs and attribution.
- Validated local structural-connectivity import, preserving string IDs and declared provenance. Imported graphs do not replace the walking controller.
- Timed stimulus protocols, a one-click first experiment, matched-seed condition comparisons, sequential trials, pause/resume/cancel and automatic completed-trial exports.
- Joint, contact and motion measurements; a local run library, trajectory overlays, configuration restoration, CSV/JSON/ZIP export and exact replay for both models.
- One authoritative worker with bounded queues/history/recording, explicit error handling and graceful Quit / Save current run & quit.
- A light GitHub Actions workflow on Ubuntu for the non-physics tests and the frontend checks.

## Validation summary

The v0.4 validation covered x86-64 Linux with EGL rendering, Python 3.12, Node 26 and the pinned dependencies. v0.2 was validated on macOS/ARM64; v0.3 and v0.4 have not been re-run there. These describe tested platforms, not a required hardware model.

| Check | v0.4 result |
| --- | --- |
| Full backend suite | 76 passed, including 6 real FlyGym tests (graphics, compound eyes, the fast stepping path's bitwise match with FlyGym's own controller, and the connectome model on the real body) and new tests of the circuit builder, circuit files and registry, populations, spiking timing (1.8 ms delay, 2.2 ms refractory period, Poisson input), the toolkit, the build endpoints and the fly comparison |
| Frontend unit tests | 27 passed: plotting, protocol editing, error messages, model and circuit selection, comparison rules, readout and trace indexing, the circuit layout for subsets of cell types, the build form and seed suggestions |
| Prettier formatting, TypeScript and production build | Passed |
| Linux rendering | EGL and GLFW passed; OSMesa is not installed on the reference system, so the OSMesa fallback could not be exercised |
| Replay | Connectome runs recorded with v0.3 (toy and FlyGym, with a stimulus change, DNa02 and cell-type silencing and a parameter change) replay under v0.4 with maximum absolute error 0; v0.4 rate and spiking runs replay with error 0 |
| Circuit build | The default rebuild reproduces `fafb783-dna02.json` byte for byte; the general builder reproduces its neurons, connections and cap report and rebuilds `fafb783-steering.json` byte for byte |
| Speed (reference laptop, neural part only) | Wall time per 1 ms neural step: 3,000-neuron circuit 0.05 ms (rate) and 0.3 ms (spiking); whole brain 3.2 ms (rate) and 6.7 ms (spiking) |
| Browser flow | Circuit and dynamics selection, the live view with three readout pairs, path tracing, the population form, and a circuit built and listed from **Build a circuit**, exercised on the toy body with no console errors |

The models were evaluated with matched seeds on the toy body and, for a smaller set, on headless FlyGym; the tables are in the [research guide](docs/RESEARCH.md#evaluation). The engineered model reaches nearly every target. The DNa02 circuit turns toward lateral targets first but, with its strong left bias, circles them instead of reaching them (0/60 toy, 0/18 FlyGym). The steering circuit reaches 57/60 and 18/18; a readout sweep shows that its reaching comes from DNp09, and an ablation scan shows its near-symmetry is partly a balance of uneven visual-neuron samples. With spiking dynamics both circuits keep a strong left bias and reach no targets. These are computational results about these models, not biological validation.

Two upstream TestClient deprecation notices were present in the tests. There is no guarantee of bitwise numerical agreement across devices or dependency versions.

Raw logs, session identifiers and machine-specific measurements are local generated evidence and are excluded from version control. To reproduce the checks and benchmark your own hardware, see [validation commands](docs/evidence/README.md).

## Scientific scope

**Neither model is a validated fly brain.** The engineered model's six rate units have hand-chosen weights. The connectome model's circuits have real FlyWire wiring, but their signs are assumed, the rate dynamics are a uniform rule with global gains, the spiking neurons share one published set of constants, every input neuron on a side receives the same sensor value, and turning is an equal-weight sum over a few readout types. The nerve cord, electrical synapses and neuromodulation are absent. A whole-brain circuit can be built and run, far slower than real time.

**Both sexes have anatomical data; only the female-derived body is simulated.** The connectome circuit and the body both come from female flies. There is no male body model, fitted sex-specific physiology/behavior, flight, feeding, learning, courtship or multi-animal interaction. The visual encoder is an engineered green-object detector. The target is a non-colliding landmark. Long trajectories can overshoot, circle or leave the bounded schematic display.

The next scientific milestone is a circuit whose dynamics and motor mapping are fitted and tested against measured behavior and neural data, including held-out interventions. The comparison tools are in place; the recorded data (a 71 MB DNa02 recording, CC0) has not been downloaded. Methods and dataset-specific licensing are in the [research guide](docs/RESEARCH.md).

## Repository scope

Runtime files stay local. The repository contains instructions, code, dependency locks, examples and attributed scientific assets. Local environments, downloaded datasets, imported data, run records and execution evidence are excluded by [.gitignore](.gitignore). See [sharing the project](docs/SHARING.md).

The code and documentation are Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The scientific data keeps its own licenses, listed in [data/atlas/LICENSE.md](data/atlas/LICENSE.md) and [data/circuits/LICENSE.md](data/circuits/LICENSE.md); all FlyWire-derived data, including circuits you build, is CC BY-NC 4.0, for non-commercial use only.
