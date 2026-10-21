# DigitalFly — v0.5 status

DigitalFly is a local research workspace for embodied sensorimotor experiments. See the [quick start](README.md#quick-start) for portable setup and shutdown instructions.

## Implemented

- Real FlyGym / MuJoCo walking and turning with the female-derived NeuroMechFly body, joints, contact and adhesion.
- Selectable geometric sensing or actual rendered compound-eye input, with 721 ommatidia per eye and an explicitly engineered green-contrast encoder.
- Two neural models. The default is the engineered six-unit circuit with editable parameters, group silencing, exact weights and computed rates. The connectome model runs any FlyWire v783 circuit with leaky rate units or the spiking neurons of Shiu et al. 2024: data-derived wiring, signs assumed from predicted transmitters, engineered input and readout, global parameters only. Two circuits ship: the v0.3 DNa02 circuit (3,000 neurons, default) and a steering circuit around DNa01, DNa02 and DNp09 (4,000 neurons).
- Configurable populations by cell type: the steering readout (right − left summed over types), the neurons that receive the sensors and an optional speed drive.
- A reproducible circuit builder (`scripts/build_circuit.py`) with pinned, hash-checked sources, recorded thresholds, hops, cap and license. It builds circuits around any cell types or root IDs, up to the whole brain (134,180 neurons at 5 synapses), from the command line or the app's **Build a circuit** tab, into the git-ignored `data/circuits/local/`.
- A live circuit view by cell type for any circuit, with every readout pair, path tracing to the readout and population editing; DNa02 and cell-type silencing; model and DNa02 conditions in comparisons; a live DNa02 tint on the female anatomy, labeled as model output.
- Optional FlyVis eyes: rendered compound-eye images run through FlyVis (Lappalainen et al. 2024), a connectome-constrained optic-lobe network, whose cell types drive each circuit's visual projection neurons in proportion to their FlyWire v783 synapses from those types (`<circuit>.flyvis.json`). Installed separately with CPU-only PyTorch (`backend/requirements-vision.lock`).
- A comparison with one recorded fly: a verified download of a paired left/right DNa02 recording from Rayshubskiy et al. 2025 (CC0), converted to firing rates and turning as the authors' code does, and fitted against the model's runs.
- A research toolkit (`digitalfly.toolkit`, `scripts/toolkit.py`): batch trials and parameter sweeps in parallel processes, open-loop bias curves with a mirror test, ablation scans over every cell type, path tracing, and fits of turning against readout activity in exported runs or fly recordings (`digitalfly.compare`).
- Male/female anatomical reference surfaces and twelve published neuron skeletons, with rotation, selection, source IDs and attribution.
- Validated local structural-connectivity import, preserving string IDs and declared provenance. Imported graphs do not replace the walking controller.
- Timed stimulus protocols, a one-click first experiment, matched-seed condition comparisons, sequential trials, pause/resume/cancel and automatic completed-trial exports.
- Joint, contact and motion measurements; a local run library, trajectory overlays, configuration restoration, CSV/JSON/ZIP export and exact replay for both models.
- One authoritative worker with bounded queues/history/recording, explicit error handling and graceful Quit / Save current run & quit.
- A light GitHub Actions workflow on Ubuntu for the non-physics tests and the frontend checks.

## Validation summary

The v0.5 validation covered x86-64 Linux with EGL rendering, Python 3.12, Node 26 and the pinned dependencies, with the optional vision lock (FlyVis and CPU-only PyTorch) installed. v0.2 was validated on macOS/ARM64; v0.3–v0.5 have not been re-run there, and the vision lock's macOS entries have not been installed. These describe tested platforms, not a required hardware model.

| Check | v0.5 result |
| --- | --- |
| Full backend suite | 88 passed, including 7 real FlyGym tests (graphics, compound eyes, the fast stepping path's bitwise match with FlyGym's own controller, the connectome model on the real body, and a closed-loop FlyVis-eye run that replays with error 0) and the FlyVis column mapping's T4 direction check. All 88 need: an OpenGL backend for the FlyGym tests (EGL, OSMesa, or Xvfb with `MUJOCO_GL=glfw`; without one they fail); the vision lock and the pretrained networks from `scripts/fetch_flyvis.py` (else 2 tests skip); the prepared FlyWire archive from `scripts/build_circuit.py prepare` (else 2 builder tests skip); and the recording from `scripts/fetch_recording.py` (else 1 test skips). With graphics and none of the optional assets: 83 passed, 5 skipped. See [validation commands](docs/evidence/README.md) |
| Frontend unit tests | 27 passed |
| Prettier formatting, TypeScript and production build | Passed |
| Linux rendering | EGL and GLFW passed; OSMesa is not installed on the reference system, so the OSMesa fallback could not be exercised |
| Replay | Connectome runs recorded with v0.3 replay with maximum absolute error 0 (checked at v0.4; the rate and side-sensor spiking arithmetic is unchanged since); v0.5 rate, spiking and FlyVis-eye runs replay with error 0 |
| Circuit build | The default rebuild reproduces `fafb783-dna02.json` byte for byte; the general builder reproduces its neurons, connections and cap report and rebuilds `fafb783-steering.json` byte for byte |
| Recorded fly | The downloaded file matches Dataverse's size and MD5 and the recorded SHA-256; its conversion is tested against the documented spike counts and fits |
| Speed (reference laptop) | Wall time per 1 ms neural step: 3,000-neuron circuit 0.05 ms (rate) and 0.3 ms (spiking); whole brain 3.2 ms and 6.7 ms. FlyVis: 10 ms per 10 ms step for both eyes; FlyVis-eye runs 0.11–0.15× real time |
| Browser flow | Circuit and dynamics selection, the live view with three readout pairs, path tracing, the population form, a circuit built from **Build a circuit**, and the FlyVis sensor option with its reason when unavailable, with no console errors |

The models were evaluated with matched seeds on the toy body and, for a smaller set, on headless FlyGym; the tables are in the [research guide](docs/RESEARCH.md#evaluation). The engineered model reaches nearly every target. The DNa02 circuit turns toward lateral targets first but, with its strong left bias, circles them instead of reaching them (0/60 toy, 0/18 FlyGym). The steering circuit reaches 57/60 and 18/18; a readout sweep shows that its reaching comes from DNp09, and an ablation scan shows its near-symmetry is partly a balance of uneven visual-neuron samples. With spiking dynamics both circuits keep a strong left bias and reach no targets. With FlyVis eyes neither circuit steers toward the target: each turns to its own side whatever the target does (0/18 and 3/18 on FlyGym). These are computational results about these models, not biological validation.

Two upstream TestClient deprecation notices were present in the tests. There is no guarantee of bitwise numerical agreement across devices or dependency versions.

Raw logs, session identifiers and machine-specific measurements are local generated evidence and are excluded from version control. To reproduce the checks and benchmark your own hardware, see [validation commands](docs/evidence/README.md).

## Scientific scope

**Neither model is a validated fly brain.** The engineered model's six rate units have hand-chosen weights. The connectome model's circuits have real FlyWire wiring, but their signs are assumed, the rate dynamics are a uniform rule with global gains, the spiking neurons share one published set of constants, every input neuron on a side receives the same sensor value, and turning is an equal-weight sum over a few readout types. The nerve cord, electrical synapses and neuromodulation are absent. A whole-brain circuit can be built and run, far slower than real time.

**Both sexes have anatomical data; only the female-derived body is simulated.** The connectome circuit and the body both come from female flies. There is no male body model, fitted sex-specific physiology/behavior, flight, feeding, learning, courtship or multi-animal interaction. The visual encoder is an engineered green-object detector. The target is a non-colliding landmark. Long trajectories can overshoot, circle or leave the bounded schematic display.

The next scientific milestone is a circuit whose dynamics and motor mapping are fitted and tested against measured behavior and neural data, including held-out interventions. The comparison with one recorded fly shows the model turning almost instantly after its DNa02 activity where the fly lags by about 180 ms, and its spiking DNa02 firing tens of times more than the recorded ones; nothing has yet been fitted to recorded data. Methods and dataset-specific licensing are in the [research guide](docs/RESEARCH.md).

## Repository scope

Runtime files stay local. The repository contains instructions, code, dependency locks, examples and attributed scientific assets. Local environments, downloaded datasets, imported data, run records and execution evidence are excluded by [.gitignore](.gitignore). See [sharing the project](docs/SHARING.md).

The code and documentation are Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The scientific data keeps its own licenses, listed in [data/atlas/LICENSE.md](data/atlas/LICENSE.md), [data/circuits/LICENSE.md](data/circuits/LICENSE.md) and [data/recordings/LICENSE.md](data/recordings/LICENSE.md); all FlyWire-derived data, including the FlyVis bridges and circuits you build, is CC BY-NC 4.0, for non-commercial use only. Changes by version are in the [changelog](CHANGELOG.md).
