# DigitalFly research workspace — v0.2

This is an experimental sensorimotor workbench with explicit modeling assumptions. Its tests establish computational behavior and repeatability, not biological validity. See the [setup instructions](../README.md#quick-start) and [validation summary](../STATUS.md).

## What is now possible

| Area | Implemented | Scope |
| --- | --- | --- |
| Embodied experiment | Actual FlyGym 2.1 / MuJoCo body, joints, contact and adhesion | Female-derived morphology; engineered walking/turning controller |
| Vision | Two actual rendered eye images, upstream fisheye correction and 721 ommatidia per eye | Engineered green-contrast feature encoder; no learned visual network |
| Neural model | Live six-unit directed graph, computed rates, incoming weights, time constants, parameter controls and group silencing | Explicit rate model, not identified biological neurons |
| Anatomy | Rotatable male/female surfaces and twelve published neuron skeletons | Structural anatomy, separate from dynamics |
| Connectivity | Import, validate, save, search and inspect a small directed graph | Up to 300 neurons / 3,000 edges / 2 MB; not connected to the motor controller |
| Experiments | Timed stimuli, finite protocols, matched-seed comparisons, pause/resume/cancel and automatic trial export | Sequential, one body at a time |
| Analysis | Path length, displacement, mean speed, net turn, final target distance, contact occupancy, trajectory overlays | Descriptive outcomes; no significance or biological-effect claims |
| Records | Local run library, configuration restoration, CSV/JSON/ZIP and replay | Same pinned software stack; no cross-device guarantee |
| Closing | Quit and Save current run & quit | Requests graceful shutdown of this launcher’s server and its worker |

## A first experiment

1. Start with `./scripts/start.sh --open` from the project directory. It opens paused. Add `--vision` to launch directly with eye inputs.
2. In **Workbench → Sensor model**, choose **Rendered compound eyes**. The body resets. Initial eye setup may take several seconds; timing depends on your hardware and graphics environment.
3. Inspect **Through the eyes**, run briefly, and pause. Moving the target changes rendered eye input, neural activity, and motor commands.
4. Open **Experiments**. Choose **Target reversal**, set duration to 0.5 or 2 simulated seconds, seeds to `42, 43`, and conditions to **Neural control** and **Descending units off**.
5. **Run comparison** resets and runs one trial for each seed/condition pair. The target reverses halfway through each trial. Every finished trial saves automatically. Pause freezes the current trial; Cancel retains the current partial trial for manual export and stops remaining trials.
6. Select saved runs in **Run library** to compare their trajectories and measurements. Save ZIPs for analysis elsewhere. “Restore starting configuration” initializes a fresh paused experiment; it does not replay the old trajectory.

Longer runs are not automatically more biologically meaningful. The simple attraction controller can overshoot, circle, or leave the ±40 mm display area. The physics ground is unbounded.

## Vision and signal definitions

The landmark is a non-colliding, green cylinder of radius 1 mm and height 4 mm. Its position changes the actual rendered scene. It is also visible with geometric sensing; in that mode, neural inputs still use the declared geometric encoder.

In vision mode:

1. `Simulation.get_raw_vision()` renders the two FlyGym eye cameras with the upstream fisheye correction, using the package’s calibrated 512 × 450 retina.
2. For each pixel, compute `max(G - max(R, B), 0)` from RGB normalized to [0, 1]. This is a deliberately engineered green-object feature, not a model of fly color physiology.
3. Replicate that feature over the RGB channels and use `Retina.raw_image_to_hex_pxls()` to average it into the 721 upstream ommatidia. Combine the disjoint yellow/pale slots to get one feature value per ommatidium.
4. Each neural input is `clip(20 × mean(features), 0, 1)` for its eye. It is held for five control intervals (50 ms of simulation time). Moving a stimulus invalidates the held reading immediately.
5. Sensor silencing is applied after the original readout is retained. The neural and motor code sees only the left/right sensor inputs. Geometric bearing/distance in telemetry is diagnostic and does not drive the vision controller.

Intensity changes the rendered green channel: `min(1, 0.08 + 0.67 × intensity)`. Zero intensity hides the landmark. Higher values saturate; this is a rendering control, not a calibrated radiometric stimulus. Other green objects or body parts could contribute to the engineered contrast detector.

Eye images and the current ommatidial features are displayed. Exports retain the applied bilateral input samples and encoder metadata, **not every retinal image or every per-ommatidium frame**. Replaying vision requires an offscreen graphics context even when the body-camera renderer is disabled.

## Neural parameters

The original six-unit rate equation remains explicit. Inputs and time constants are bounded and validated:

- Sensory gain: 0–3, multiplies the input matrix.
- Steering gain: 0–3, multiplies the two opponent-steering matrix rows.
- Tonic drive: 0–1, sets the two descending biases.
- Time-constant multiplier: 0.25–4, scales all six time constants.

Changing a parameter affects the real update equation and records an event. Circuit rates are retained across a parameter change; Reset zeros them. Export records the initial configuration, parameter events and final matrices. Baseline commands are always `[1, 1]`, bypassing the neural output.

## Body measurements

Positions are millimeters and joint angles are radians. `get_joint_angles()` follows the fly’s skeleton order. Six leg records are ordered LF, LM, LH, RF, RM, RH.

- Ground-contact force is the norm of the vector sum of MuJoCo ground-contact forces on each leg’s tibia and five tarsal segments, in µN. Vector cancellation is possible; this is not the sum of scalar force magnitudes.
- A leg is marked in contact when this magnitude exceeds 0.01 µN. The contact plot shows sampled binary contacts, and contact occupancy is the fraction of control samples meeting the threshold. It is not a separately fitted stance classifier.
- Walking phase comes from the upstream engineered central-pattern-generator oscillators. It is not a neural recording.
- Path length sums planar displacement over control intervals. Displacement is the straight-line distance from the settled starting pose. Mean speed is the mean of the measured interval speeds. Net turn sums wrapped yaw differences; it can exceed 360°.
- Final target distance refers to the **current** target, which may have moved during a protocol.

Export metadata includes `body_joint_order` so each joint position can be identified. `body_signals.jsonl` retains joint positions, leg force/contact values and oscillator phases for every recorded sample. Display history omits the large joint-angle arrays while retaining current joint state and bounded gait history.

## Male and female anatomical data

The body is based on a micro-CT scan of an adult **female**, as documented by [NeuroMechFly](https://neuromechfly.org/). There is no separate male body, sex-specific biomechanics, or fitted male/female behavior controller in this application.

The anatomical explorer contains **three cross-matched types, two neurons per type, per sex**: DNa02, DNp01, DNp09. The twelve identities are retained as strings. The cell-type assignments come from the authors’ [male/female mapping](https://github.com/flyconnectome/2025malecns). A selected excerpt and the full source file’s SHA-256 are in `data/atlas/type-mapping-excerpt.json`.

| Sex | Sample source | Surface | Display units |
| --- | --- | --- | --- |
| Female | FAFB v783 skeletons in the authors’ [compiled data](https://github.com/sjcabs/fly_connectome_data_tutorial/blob/main/data/dataset_documentation/fafb_data.md) | FAFB14 neuropil surface from navis-flybrains | Native nm converted to µm |
| Male | [MaleCNS v1.0 SWC files](https://male-cns.janelia.org/download/) | MaleCNS brain and VNC surfaces from navis-flybrains | SWC 8 nm voxel units converted to µm; surfaces nm converted to µm |

No inter-specimen registration or pointwise male/female shape comparison is performed. Each specimen is independently fit to the viewer. Selecting male anatomy does not change the simulated body. The female dataset covers the brain; the male data includes nerve cord. Differences in coverage, preparation, registration and skeletonization make direct cable-length or shape comparisons inappropriate without further analysis.

The viewer preserves source coordinates under a camera rotation/projection. For display, degree-two SWC chains are contracted at approximately 2 µm of cable while retaining all branch/end points. Surface vertices are clustered at 4 µm and sampled as a point cloud. The original geometry, source URL, hash and download size remain under `data/atlas/`. Source cable length is computed before display simplification. Use the original source files, not the display geometry, for quantitative morphology work.

Rebuild the display assets offline:

```sh
backend/.venv/bin/python scripts/build_atlas.py
```

The atlas includes about 10.6 MB of retained upstream files plus approximately 6.5 MB of display JSON. The mapping download was 6.7 MB and stays in the ignored cache; its selected excerpt is retained. No full connectivity graph, synapse-position volume or pretrained neural model was downloaded.

### Licensing and attribution

- Female FlyWire data follows [CC BY-NC 4.0 public-release terms](https://home.flywire.ai/guidelines). Attribute the FlyWire Consortium and the original datasets/publications. The downloaded skeletons are distributed through the Bates/Lee lab compilation; the source URLs and hashes are retained.
- MaleCNS data is [CC BY 4.0](https://male-cns.janelia.org/download/), from the FlyEM/Janelia, Cambridge, MRC LMB and Google collaboration. Cite Berg and colleagues’ MaleCNS work and the specific release.
- Anatomical surfaces are distributed by [navis-flybrains](https://github.com/navis-org/navis-flybrains), whose GPL-3.0 notice is retained at `data/atlas/sources/flybrains-LICENSE`. Original dataset attribution still applies. The surfaces' upstream URLs and hashes are in `data/atlas/downloads.json`.
- Every data file's license is listed in [data/atlas/LICENSE.md](../data/atlas/LICENSE.md). The project's Apache-2.0 license does not cover them, and the FlyWire-derived files are for non-commercial use only.
- Synthetic format fixtures are explicitly labeled and stored in `data/examples/`. They are not biological measurements.

## Connectivity import format

Use **Neural atlas → Imported connectivity → Import connectivity JSON**. The downloadable format example is synthetic. Supply:

- Provenance: biological/synthetic kind, dataset, release, specimen, sex, source URL, license, coverage and weight assumption.
- Nodes: strict string `id`, label, cell type and side.
- Edges: strict string `pre_id`, `post_id` and positive integer `synapse_count`.

IDs must be unique; every endpoint must exist. Combine duplicate directed edges before import. The limit is 300 neurons, 3,000 edges, and 2 MB per file. Imports are content-addressed and saved under ignored `data/connectivity/`. No arbitrary paths or remote-fetch endpoints are exposed. User-supplied biological provenance is retained as a declaration, not independently authenticated.

Statistics cover only the imported subset: total nodes, directed edges, synapses, incoming/outgoing synapse counts and reciprocal non-self pairs. The circular layout is not anatomy. Synapse counts do not establish excitation/inhibition, delays, time constants, physiological weights or neuron dynamics. Importing a graph does not replace the active walking circuit.

## Protocol and comparison reproducibility

Events use integer control-step boundaries. Durations and target/intervention values are validated; event indices must be unique, ascending and before the protocol’s end. Manual workbench edits, timed events and parameter changes are distinguished in the event schedule. The replay tool applies manual edits and lets the saved protocol reproduce its own timed events.

Comparison conditions are held for a whole trial, so comparison protocols accept scheduled stimulus changes only. The same distinct seeds are applied to every selected condition. Initial interventions are serialized in each trial’s initial configuration. The worker blocks parameter/stimulus/reset commands while a comparison is active, preventing accidental changes to its controlled conditions. Finished trials are exported before the next trial resets the body.

Limits: 5 seeds, 4 conditions, 30,000 total control intervals. UI durations are 0.1–15 simulated seconds per trial. The API supports longer individual protocols within the existing 30,000-sample recording bound. Runs are CPU-limited; requested speed is a pacing ceiling, not a performance promise.

Replay a saved directory:

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with the name of a run you exported locally. Reference validation reproduced visual-input and timed target-reversal trials with maximum absolute error 0 at a tolerance of 1e-8. Vision rendering and numerical behavior may differ on another graphics/software stack. Personal run records and raw evidence are excluded from the public repository.

## What remains before biological simulation claims

The next scientific step is a **specified, validated circuit**, with a documented sensory encoding, real connectivity, transmitter/sign assumptions, fitted dynamics, and a defensible descending-to-motor mapping. Validate its predictions against measured fly behavior and neural data, including held-out interventions. A larger neuron count alone does not provide this validation.

The app currently does not simulate a whole CNS, spiking physiology, sex-specific behavior, flight, feeding, learning, courtship or mating. The real body supports walking and turning under the upstream leg controller. Whole-connectome ingestion, FlyVis integration, measured male biomechanics, odor sensing and multi-animal experiments remain future work.

The official MaleCNS download list gives about **1.1 GB** for the full wiring table, **12.7 GB** for synapse locations and **6.8 GB** for partner records. These optional datasets are outside the bundled sample's scope. The published resources linked from the atlas remain available for inspecting broader data externally; the app never downloads them automatically.
