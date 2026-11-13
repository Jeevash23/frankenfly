# DigitalFly research workspace — v0.6

This is an experimental sensorimotor workbench with explicit modeling assumptions. Its tests establish computational behavior and repeatability, not biological validity. See the [setup instructions](../README.md#quick-start) and [validation summary](../STATUS.md).

## What is now possible

| Area | Implemented | Scope |
| --- | --- | --- |
| Embodied experiment | Actual FlyGym 2.1 / MuJoCo body, joints, contact and adhesion | Female-derived morphology; engineered walking/turning controller |
| Vision | Two actual rendered eye images, upstream fisheye correction and 721 ommatidia per eye; optionally FlyVis eyes, an optic-lobe network wired to the circuits through FlyWire | Default: engineered green-contrast feature encoder. FlyVis: published connectome-constrained network, engineered column mapping and pooling; it does not steer the circuits toward targets |
| Neural models | The engineered six-unit graph (default), or the connectome model on any FlyWire v783 circuit, with rate or spiking (Shiu et al. 2024) dynamics: the 3,000-neuron DNa02 circuit (default), a 4,000-neuron steering circuit around DNa01, DNa02 and DNp09, side-balanced versions of both, or a circuit you build, up to the whole brain; live activity, parameters, populations, path tracing and a circuit view; silencing, scaling or activating any cell type on either side; an engineered motor path (readout weights, delay, low-pass) | Engineered model: explicit rate units, not identified neurons. Connectome model: data-derived wiring, assumed signs, engineered input and readout; not an uploaded brain, not biologically validated |
| Anatomy | Rotatable male/female surfaces and twelve published neuron skeletons | Structural anatomy, separate from dynamics |
| Connectivity | Explore the whole FlyWire v783 brain or any circuit: partners, strongest and shortest paths, and a BANC-style influence score, each row one click from a Workbench manipulation or a circuit build; Neuroglancer links for any selection, path or circuit. Build circuits around any FlyWire v783 cell types or neurons, in the app or with the builder; separately, import, validate, save, search and inspect a small directed graph | Builds need the prepared FlyWire archive (once, from the cached downloads). Imports: up to 300 neurons / 3,000 edges / 2 MB; imports never drive the body |
| Experiments | Timed stimuli, finite protocols, presets, matched-seed comparisons with custom conditions, pause/resume/cancel and automatic trial export | Sequential, one body at a time |
| Analysis | Path length, displacement, mean speed, net turn, final target distance, contact occupancy, trajectory overlays; a research toolkit (Python and command line) for batch trials, parameter sweeps, bias curves, ablation scans, path tracing, assumption-sensitivity analysis and fits of turning against readout activity; one recorded fly (paired DNa02 with ball tracking) to compare against | Descriptive outcomes from one fly and simulations; no significance or biological-effect claims |
| Records | Local run library with filters, tags, notes and per-condition comparison summaries; configuration restoration, CSV/JSON/ZIP, optional per-cell-type activity, and replay | Same pinned software stack; no cross-device guarantee |
| Closing | Quit and Save current run & quit | Requests graceful shutdown of this launcher’s server and its worker |

## A first experiment

1. Start with `./scripts/start.sh --open` from the project directory. It opens paused. Add `--vision` to launch directly with rendered compound-eye input (the engineered encoder below, not FlyVis).
2. In **Workbench → Sensor model**, choose **Rendered compound eyes**. The body resets. Initial eye setup may take several seconds; timing depends on your hardware and graphics environment.
3. Inspect **Through the eyes**, run briefly, and pause. Moving the target changes rendered eye input, neural activity, and motor commands.
4. Open **Experiments**. Choose **Target reversal**, set duration to 0.5 or 2 simulated seconds, seeds to `42, 43`, and conditions to **Neural control** and **Descending units off**.
5. **Run comparison** resets and runs one trial for each seed/condition pair. The target reverses halfway through each trial. Every finished trial saves automatically. Pause freezes the current trial; Cancel stops the remaining trials and saves the unfinished one, marked partial. When the comparison ends, the Workbench returns to the configuration it had before (model, controller, interventions and protocol), so neither it nor the next comparison inherits the last trial's settings.
6. Select saved runs in **Run library** to compare their trajectories and measurements. Save ZIPs for analysis elsewhere. “Restore starting configuration” initializes a fresh paused experiment; it does not replay the old trajectory. The library lists the newest 100 runs and says how many there are; **Load more** shows older ones. The bin icon, then **Delete**, removes a run's folder and ZIP from `runs/`.

**Set up the first experiment** on the Experiments page fills in steps 4 and 5 in one click: target reversal over 2 simulated seconds, seeds 42 and 43, and **Neural control** against **Descending units off** (or **Both DNa02 off** with a connectome circuit that contains DNa02). It keeps the current body and sensor, so switch to compound eyes on the Workbench first if you want step 2 as well.

Longer runs are not automatically more biologically meaningful. The simple attraction controller can overshoot, circle, or leave the ±40 mm display area. The physics ground is unbounded.

## Compound-eye vision and signal definitions

The landmark is a non-colliding, green cylinder of radius 1 mm and height 4 mm. Its position changes the actual rendered scene. It is also visible with geometric sensing; in that mode, neural inputs still use the declared geometric encoder.

With rendered compound eyes (sensor model `vision`, which `--vision` selects):

1. `Simulation.get_raw_vision()` renders the two FlyGym eye cameras with the upstream fisheye correction, using the package’s calibrated 512 × 450 retina.
2. For each pixel, compute `max(G - max(R, B), 0)` from RGB normalized to [0, 1]. This is a deliberately engineered green-object feature, not a model of fly color physiology.
3. Replicate that feature over the RGB channels and use `Retina.raw_image_to_hex_pxls()` to average it into the 721 upstream ommatidia. Combine the disjoint yellow/pale slots to get one feature value per ommatidium.
4. Each neural input is `clip(20 × mean(features), 0, 1)` for its eye. It is held for five control intervals (50 ms of simulation time). Moving a stimulus invalidates the held reading immediately.
5. Sensor silencing is applied after the original readout is retained. The neural and motor code sees only the left/right sensor inputs. Geometric bearing/distance in telemetry is diagnostic and does not drive the neural input.

Intensity changes the rendered green channel: `min(1, 0.08 + 0.67 × intensity)`. Zero intensity hides the landmark. Higher values saturate; this is a rendering control, not a calibrated radiometric stimulus. Other green objects or body parts could contribute to the engineered contrast detector.

Eye images and the current ommatidial features are displayed. Exports retain the applied bilateral input samples and encoder metadata, **not every retinal image or every per-ommatidium frame**. Replaying compound-eye runs requires an offscreen graphics context even when the body-camera renderer is disabled.

## Neural parameters

These apply to the engineered model; the connectome model has [its own global parameters](#parameters-and-how-the-defaults-were-chosen). The original six-unit rate equation remains explicit. Inputs and time constants are bounded and validated:

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

## Exported signals

An export (metadata schema 6) holds `metadata.json`, `telemetry.csv`, `body_signals.jsonl`, the provenance manifest `ro-crate-metadata.json`, the drafted `methods.md` and, when asked for, `activity_types.npz`; spiking runs add `spikes_readout.npz`. The app and its tools read runs of schemas 2–6; older runs lack the columns and fields added since. The manifest, the methods draft and NWB export are described in [sharing](SHARING.md#provenance-and-standard-formats).

With spiking dynamics, `spikes_readout.npz` holds every spike of every readout neuron (each side of each readout cell type): `spike_time_s` (sorted; the start of the 0.1 ms substep whose update crossed the threshold, as Brian2's SpikeMonitor stamps it, from the reset), `spike_unit` (a row of the unit arrays) and, per unit, `unit_neuron_index`, `unit_root_id`, `unit_cell_type` and `unit_side`. Recording stops after 5,000,000 spikes (`metadata.spikes.stopped_at_s` says when); it never changes the simulation. The rate columns are these trains filtered with the exponential `rate_window_ms` window, divided by `rate_scale_hz`.

`telemetry.csv` has one row per recorded control step from the reset. `step`, `time_s`, `x_mm`, `y_mm`, `z_mm`, `yaw_rad` and `speed_mm_s` describe the body after the step; `sensor_l`, `sensor_r` (after sensor silencing) and `raw_sensor_l`, `raw_sensor_r` are the sensor values the step used; the `rate_*` columns are the model's readouts after the step, named after its units (a cell type whose name has a comma, such as `LAL003,LAL044`, gives a quoted header field: read the file as CSV); `motor_l`, `motor_r` is the command applied during the step. Schema 5 appends:

- `target_bearing_deg`: the direction of the target from the row's position, relative to its heading, in degrees within ±180, positive to the left (counterclockwise). The geometric sensor's own bearing was taken at the start of the step, from the previous pose.
- `target_distance_mm`: the distance from the row's position to the target. Its minimum over the rows is `metrics.min_target_distance_mm`; comparison summaries count a trial as reaching the target when it came within 2 mm (the toolkit's `REACH_MM`).
- `stimulus_x_mm`, `stimulus_y_mm`, `stimulus_intensity`: the target in effect for the row. A change at step k applies from row k + 1, as in the event schedule.
- `intervention_code`: the interventions in effect, as `L` and `R` with 1 for a sensor input on and 0 for off, then `;`-separated entries: `units:GROUP` (the engineered model's silenced group), `DNa02:left|right|both`, `TYPE:silence` (a cell type silenced on both sides) and, for interventions on one side or with a mode, `TYPE[:L|:R]:MODE[VALUE]`, for example `L0R1;DNa02:left;DNp09:L:scale0.5`. Spaces, quotes, `;`, `:`, `,` and `#` in cell-type names become `_`.

These columns are derived from each row's pose and the recorded schedule; replay checks the body, rate and motor columns, not them.

With the connectome model, `RunConfig.record_activity = "types"` adds `activity_types.npz`, NumPy arrays that `np.load` reads without pickling:

- `activity`: float32, samples × cell types: each cell type's mean activity over its neurons after each recorded control step, in the units of the rate columns (rate dynamics: the dimensionless rate; spiking: firing rate ÷ `rate_scale_hz`).
- `step` and `time_s`: each sample's control step and simulated time, matching the telemetry rows.
- `type_names` (the column order) and `neurons_per_type`.

Every control step is kept until the activity reaches 128 MB; then every second one (earlier samples are thinned to match), and so on. `metadata.activity.every_steps` gives the final spacing: 128 MB holds about 26,700 steps of the 3,000-neuron DNa02 circuit (1,257 cell types), and fewer of larger circuits. The setting is ignored with the engineered model, recording does not change the simulation, and replay does not check the file.

## The connectome model

The **connectome** model steers the fly with real wiring from the FlyWire reconstruction of one adult female brain (FAFB v783). Pick it in **Workbench → Neural model**, then pick a **circuit** and **dynamics** under it. The engineered six-unit model stays the default and is unchanged.

This is a connectome-constrained model, not an uploaded fly brain. It is not biologically validated.

| Part | Status | What it is |
| --- | --- | --- |
| Which neurons, cell types, sides, predicted transmitters, synapse counts | **Data-derived** | FlyWire FAFB v783, through the files below |
| Sign of each connection | **Assumed** | From the presynaptic neuron's predicted transmitter |
| Rate dynamics: leaky rates, gains, time constant | **Engineered** | One global value each; nothing per neuron or per synapse |
| Spiking dynamics: leaky integrate-and-fire neurons | **Published model** | The neuron model and constants of Shiu et al. 2024, with engineered sensor input and readout |
| Sensor → neuron input | **Engineered** | Each sensor drives the input neurons on its side |
| Readout → body output | **Engineered**, direction from literature | Turn from the right − left difference of the readout cell types; forward drive from a tonic term |

The model was called `connectome_dna02` in v0.3. Runs and configurations that use that name still load and replay.

### Circuits

A circuit is a file of neurons and connections selected from FlyWire v783. Four ship with the repository, two of them side-balanced versions of the other two; you can [build more](#building-your-own-circuits).

| Circuit | Seeds | Neurons | Connections | Cell types | Default readout | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `fafb783-dna02` (default) | DNa02 | 3,000 | 78,615 | 1,257 | DNa02 | The v0.3 circuit, unchanged |
| `fafb783-steering` | DNa01, DNa02, DNp09 | 4,000 | 120,728 | 1,650 | DNa01 + DNa02 + DNp09 | Added in v0.4; see [the steering circuit](#the-steering-circuit) |
| `fafb783-dna02-balanced` | DNa02 | 3,000 | 78,510 | 1,056 | DNa02 | Added in v0.6: the DNa02 circuit's build with the cap applied per cell type and side; see [side-balanced circuits](#side-balanced-circuits) |
| `fafb783-steering-balanced` | DNa01, DNa02, DNp09 | 3,999 | 121,297 | 1,438 | DNa01 + DNa02 + DNp09 | Added in v0.6: the same for the steering circuit |

All hold the seeds and their presynaptic partners up to two hops back, with connections of at least 5 synapses, capped by path strength. Circuits you build yourself go to `data/circuits/local/`, which git ignores, and appear in the circuit list next to the committed ones.

### Data sources

Both sources are FlyWire v783, the release whose neurons the atlas already shows, from a female fly like the simulated body. Raw downloads stay in the ignored `.cache/circuits/`; `data/circuits/downloads.json` records each one.

| File | Content | Release and provider | Downloaded | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| `fafb_783_meta.feather` ([URL](https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/fafb_783/fafb_783_meta.feather)) | Cell type, super class, side and predicted transmitter for 144,837 neurons | FAFB v783 harmonized metadata, Bates/Lee lab [compilation](https://github.com/sjcabs/fly_connectome_data_tutorial) (GCS generation 1787944265562460) | Whole file, 13,539,866 bytes | `5e248762…` | CC BY-NC 4.0 (FlyWire); compilation code MIT |
| `Connectivity_783.parquet` ([URL](https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/61555bc764aebab90e37a56fa1f312269fa4dde1/Connectivity_783.parquet)) | Synapse counts for all 15,091,983 connected pairs | v783 table shipped with [Shiu et al. 2024](https://github.com/philshiu/Drosophila_brain_model), commit `61555bc`, git blob `d386555d…`, 100,804,642 bytes | Footer and 4 columns by HTTP range requests, 47,365,136 bytes | `95bbc483…` (of the downloaded ranges) | CC BY-NC 4.0 (FlyWire); repository code MIT |

Only the needed columns (presynaptic ID, postsynaptic ID, synapse count, and Shiu et al.'s own sign, kept for comparison) were fetched, so the second hash covers the downloaded byte ranges rather than the whole file; the pinned commit and git blob hash identify the whole upstream file. The metadata is requested at its recorded GCS generation (`?generation=1787944265562460`), so a re-harmonised upstream file is not fetched by accident; if that generation is no longer served, the current object is fetched instead and, like every download, must match the recorded SHA-256. Full hashes are in `downloads.json`. FlyWire Codex bulk downloads were not used: they require signing in.

FlyWire data is licensed **CC BY-NC 4.0, for non-commercial use only**. That covers every circuit, including the ones you build. Credit the FlyWire Consortium and cite Dorkenwald et al. 2024 and Schlegel et al. 2024 (reconstruction and annotation), Eckstein et al. 2024 (transmitter predictions) and Shiu et al. 2024 (connectivity table). See [data/circuits/LICENSE.md](../data/circuits/LICENSE.md).

### Building the subcircuit

The default command rebuilds the committed DNa02 circuit from the two downloads:

```sh
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock   # pyarrow, build only
backend/.venv/bin/python scripts/build_circuit.py            # add --offline to rebuild from the cache
```

1. **Seeds.** The two DNa02 neurons from the atlas: `720575940629327659` is the **left** one and `720575940604737708` the **right** one, by FlyWire's side annotation in the v783 metadata. Their somata lie on opposite sides of the midline (root-node x of 406 and 654 µm in the atlas skeletons).
2. **Partners.** Hop 1 is every neuron with at least **5 synapses** onto either DNa02; hop 2 is every neuron with at least 5 synapses onto a hop-1 neuron. That gives 685 direct partners and 14,468 hop-2 candidates.
3. **Cap.** At most **3,000 neurons**. Both DNa02 and all hop-1 partners are always kept. The cap binds at hop 2, which keeps the 2,313 neurons with the strongest path to a DNa02; a path's strength multiplies the input fraction of each connection on it (synapses on the connection ÷ all synapses onto the postsynaptic neuron). The weakest kept path strength is 4.63 × 10⁻⁵. The 12,155 dropped neurons are 6,037 central-brain intrinsic, 2,753 optic-lobe intrinsic, 2,057 visual projection, 605 ascending, 460 descending and 243 others; their top types are listed in the file.
4. **Connections.** Every pair of kept neurons connected by at least 5 synapses (the induced subgraph), including lateral and feedback connections.

The result, `data/circuits/fafb783-dna02.json` (1.1 MB), has **3,000 neurons, 78,615 connections, 1,818,869 synapses and 1,257 cell types**. It records its sources, release, hashes, threshold, hops, cap report, counts, license and attribution. An offline rebuild reproduces it byte for byte. The direct inputs match the published circuit: same-side cholinergic DNa03, PFL3 neurons from the central complex, and strong inhibitory PS049 and VES051/052 inputs.

### Building your own circuits

Any cell types or neurons can seed a circuit. First convert the cached downloads once into a prepared archive (pyarrow is needed for this step only):

```sh
backend/.venv/bin/python scripts/build_circuit.py prepare --offline
```

This writes `.cache/circuits/fafb783-connectome.npz` (50.8 MB: 144,837 neurons and 15,091,902 connections with metadata; the 81 connections whose neurons lack metadata are left out) and a catalog of all 8,841 cell-type labels. Then, with NumPy only:

```sh
backend/.venv/bin/python scripts/build_circuit.py build --name my-circuit --seeds DNa01,DNa02 --hops 2 --threshold 5 --cap 3000
backend/.venv/bin/python scripts/build_circuit.py build --name whole --seed DNa02 --whole-brain
```

- **Seeds** are exact cell-type names (case-sensitive) or FlyWire root IDs. Use `--seed` once per seed for names that contain commas, such as `VES051,VES052`.
- **Selection** follows the same rules as the committed circuit: hops back from the seeds, the synapse threshold, the cap by path strength (every seed and hop-1 neuron is kept), and the induced subgraph.
- **Whole brain** (`--whole-brain`) keeps every neuron with at least one connection at the threshold: 134,180 neurons and 2,700,509 connections at 5 synapses. The seeds only set hop distances; neurons with no path to them get hop −1.
- **Side balance** (`--balance-sides`, v0.6; `balance_sides` in `POST /api/connectome/build`) applies the cap per cell type and side. In the hop the cap trims, each cell type's left and right candidates are ranked by path strength. The strongest candidates on the type's short side that even out its neurons already kept at earlier hops come first, one by one; the rest are paired by rank, strongest left with strongest right. A type's surplus on one side has no partner and is not kept, so a type found on one side only is left out of that hop. Neurons on neither side (center, unknown) are ranked alone. The pairs and single neurons are kept in order of their weakest member's path strength (ties: lower FlyWire ID) until the next one would exceed the cap, so a balanced circuit can end one neuron short of it. Seeds, direct partners and any hop the cap does not trim are kept as they are, so the data's own asymmetries there remain; without a binding cap the option changes nothing, and it is refused with `--whole-brain`. The header records `"balance_sides": true` in `provenance.build` (unbalanced builds leave the key out, so they still rebuild byte for byte) and a `side_balance` report: the rule, how many unpaired neurons were dropped, and the cell types still uneven, with their counts. A dropped unpaired neuron can be stronger than kept ones, so the cap report's strongest dropped path can exceed its weakest kept path.
- **Default readout**: the seed cell types that have seed neurons on both sides. You can change it later.
- **Output**: format 2, as JSON up to 200,000 connections and as a compressed NumPy archive above that, in `data/circuits/local/`, with the same provenance, cap report, transmitter counts, license and attribution as the committed files. The general builder reproduces the committed DNa02 circuit's neurons, connections and cap report, and rebuilds `fafb783-steering.json` byte for byte (both tested when the prepared archive is present).
- **Rebuilding** a name writes the new file in full to a hidden temporary file and then renames it into place, so a failed or cancelled build keeps the previous circuit. Only that name's other format (`NAME.json` or `NAME.npz`) is removed; other circuits such as `NAME.v2` and the FlyVis bridge `NAME.flyvis.json` are kept (a bridge built for the old file refuses to load until you rebuild it). Names ending in `.flyvis` are refused. The cap report's weakest kept path strength comes from the deepest hop that kept neurons, so it is reported whenever neurons were dropped.
- **Options** such as `--hops`, `--threshold`, `--cap` and `--offline` work before or after the subcommand; given in both places, the subcommand's value wins.

The same builder runs from **Neural atlas → Build a circuit**: type seeds with autocomplete from the catalog, set hops, threshold and cap, and follow the build log. One build runs at a time, as a separate process with validated arguments; nothing is downloaded. **Use this circuit** starts a fresh run on it.

### The connectivity explorer

`digitalfly.explore` answers structural questions without simulating anything: who connects to a cell type, how two cell types are linked, and what a cell type reaches through many steps. It reads the whole brain from the prepared archive (`.cache/circuits/fafb783-connectome.npz`: 144,837 neurons with metadata and the 15,091,902 connections between them, 2,700,509 of them with at least 5 synapses) or any circuit file, and it is available in the app (**Neural atlas → Connectivity explorer**), over the API (`/api/explore/*`), from the Python client and as `scripts/toolkit.py partners`, `route`, `influence` and `neuroglancer` ([usage](USAGE.md#exploring-connectivity)). Every query first keeps the connections of at least a threshold of synapses (default 5, as in the circuits). The structure is data-derived; the signs are the model's assumption (acetylcholine +1, GABA and glutamate −1, the other transmitters 0 unless counted excitatory, as in [Signs](#signs)); the path weights and the influence model are engineered definitions, stated here.

**Partners.** A query is one or more cell types or FlyWire root IDs, optionally one side. A partner row adds the synapses between the partner (a cell type, or a neuron) and the query neurons. Its share is those synapses ÷ every synapse onto the query (upstream) or from it (downstream) in the kept connections. Its sign is the presynaptic neuron's: the partner's for inputs, the query neuron's for outputs. For example, at 5 synapses the two DNa02 neurons receive 23,990 synapses from 285 cell types; the largest single share is PS049's (731 synapses, 3.0%, GABAergic).

**Paths.** A step u → v carries f = synapses(u → v) ÷ all of v's input synapses: the fraction of v's input that u supplies (for cell types, from type A onto type B ÷ all of B's input; the same rule as the live circuit's path tracing). A path's strength multiplies its steps' f; its net sign multiplies their signs. **Strongest** minimises Σ −ln f with Dijkstra's algorithm, so it is the exact maximum of the product; **shortest** minimises the number of steps, ties broken by strength (weights 1 + 0.001 × −ln f). Alternatives are found by computing, for every kept connection, the best path that passes through it, and listing the distinct simple paths in order: the first row is the optimum, the others are good, different routes, but not an exhaustive list of the k best. In the whole brain at 5 synapses the strongest cell-type path from LC10a to DNa02 is LC10a → AOTU025 → DNa02 (strength 0.0031, both steps cholinergic).

**Influence.** After the steady-state influence of the BANC brain-and-nerve-cord connectome (Bates et al. 2025; the ConnectomeInfluenceCalculator, [github.com/DrugowitschLab/ConnectomeInfluenceCalculator](https://github.com/DrugowitschLab/ConnectomeInfluenceCalculator)): a linear rate model τ dr/dt = (W̃ − I) r + s with

```text
W_ij = sign(j) × synapses(j → i)          connections of at least the threshold, signed counts
W̃    = 0.99 W ÷ λ                         λ = the largest real part of W's eigenvalues
r    = (I − W̃)⁻¹ s                        s = 1 on every query neuron, 0 elsewhere ("from")
x    = (I − W̃)⁻ᵀ e                        e = 1 on every query neuron ("onto")
```

`r_i` is neuron i's steady-state activity when the query neurons get constant input; a cell type's row sums its neurons (the query neurons themselves are reported apart). In the "onto" direction `x_j` is the summed activity of the query neurons when neuron j alone is stimulated, so a cell type's row is the effect of stimulating the whole type. Rescaling by λ makes the dynamics stable, and 0.99 is BANC's default: long polysynaptic chains count for a lot (the leading mode is amplified about 100×). The system is solved with BiCGSTAB (a sparse direct solver for graphs of up to 5,000 neurons), and each result reports λ, the solver and its relative residual (below 10⁻⁹ on the whole brain). Should W have no positive real eigenvalue (an acyclic or inhibition-dominated graph), the spectral radius of |W| is used instead, and failing that its largest row sum; the result says which. Unsigned influence counts every connection as excitatory. On the whole brain at 5 synapses, λ = 1,086; the strongest influences onto DNa02 are VES051,VES052 (−0.79), PS049 (−0.64) and CB0757 (−0.55), all inhibitory under the sign rule, then DNa03 (+0.50).

What influence is not: it has no rectification, thresholds, gains or time, so it is not what the simulation's rate or spiking dynamics would do, and it is neither BANC's published numbers (which come from the BANC dataset, report a log-transformed "adjusted influence" and use their own transmitter sets) nor a measured effect. Use it to rank candidates for a manipulation, then test them in the model, where one click on a row silences or activates the cell type in the running circuit.

**Neuroglancer.** Any selection, path or circuit becomes a Neuroglancer link (`neuroglancer-demo.appspot.com`) whose state names FlyWire's public v783 segmentation (`precomputed://gs://flywire_v141_m783`), a faint brain outline (`gs://flywire_neuropil_meshes/whole_neuropil/brain_mesh_v141.surf`) and, switched off, the FAFB EM images (`gs://flywire_em/aligned/v1`), with one coloured layer per group. Meshes stream from these public buckets when the link is opened; DigitalFly downloads nothing. The link records only root IDs, so it works for every v783 circuit, and links hold at most 5,000 neurons by default (20,000 at most). A synthetic or non-FlyWire graph is refused, since its IDs are not in the segmentation. The views show FlyWire data under CC BY-NC 4.0; credit the FlyWire Consortium.

**Performance.** On the reference laptop the archive loads in 0.5 s and the threshold's sparse matrices take 0.3 s; partner queries take under 0.05 s, paths 0.1–0.4 s, and influence 0.4–1.4 s (the first one computes λ, then it is cached per threshold and sign rule). The whole brain then holds about 0.4 GB of memory in the app, and the two most recently used thresholds are kept.

### Signs

| Predicted transmitter | Neurons (DNa02 circuit) | Sign |
| --- | --- | --- |
| Acetylcholine | 1,882 | +1, excitatory |
| GABA | 544 | −1, inhibitory |
| Glutamate | 557 | −1, inhibitory |
| Dopamine, serotonin, octopamine, unknown | 8, 3, 5, 1 | **Excluded** by default |

Signs follow Shiu et al. 2024 for acetylcholine, GABA and glutamate. Shiu et al. treat dopamine, serotonin and octopamine as excitatory; here those connections are left out by default, because a fast excitatory synapse is a poor description of neuromodulation. That is an explicit, switchable assumption: **Dopamine, serotonin, octopamine, unknown → Excitatory** restores Shiu et al.'s rule. At default settings 906 of the DNa02 circuit's 78,615 connections are excluded this way. The metadata's per-neuron transmitter agrees with Shiu et al.'s own sign for 2,989 of the 2,999 neurons both describe.

### Rate dynamics

Every neuron is a leaky rate unit, updated by Euler steps every 1 ms (the existing neural step) with a sparse weight matrix:

```text
r_i ← r_i + dt/τ × [clip(Σ_j W_ij r_j + input_i, 0, 1) − r_i]
W_ij = sign(j) × synapses(j → i) × global gain
```

with τ = 20 ms and rates in [0, 1]. Silenced neurons are clamped to zero before and after every update. There is no synaptic delay, adaptation or per-neuron parameter. This is the default and is numerically identical to v0.3.

### Spiking dynamics

**Dynamics → Spiking** replaces the rate units with the leaky integrate-and-fire network of Shiu et al. 2024 (Methods and their `model.py`), on the same wiring and signs:

```text
dv/dt = (v_rest − v + g) / τ_m      dg/dt = −g / τ_s      (both frozen while refractory)
spike when v > v_th: v → v_reset, g → 0; 1.8 ms later each target gets g += sign × synapses × w_syn
```

| Constant | Value | Constant | Value |
| --- | --- | --- | --- |
| Resting and reset potential | −52 mV | Threshold | −45 mV |
| Membrane time constant | 20 ms | Synaptic time constant | 5 ms |
| Refractory period | 2.2 ms | Synaptic delay | 1.8 ms |
| Weight per synapse, w_syn | 0.275 mV | Poisson input kick | 250 × w_syn |

Each 1 ms neural step runs ten 0.1 ms forward-Euler substeps in Brian2's schedule order, which Shiu et al.'s code uses: state update, threshold, delayed synaptic and Poisson input, reset. A neuron is frozen until 22 substeps after its spike, as in Brian2. The sensor input is engineered: each sensor value × input gain × 150 Hz (Shiu et al.'s default rate) is the Poisson rate of every input neuron on its side, and those neurons have no refractory period, as Poisson targets in Shiu et al.'s code. The readout is each neuron's firing rate, an exponential average over 50 ms, divided by a rate scale of 100 Hz, so 100 spikes/s count like a rate-model activity of 1. Spike trains depend on the run's seed, so a spiking run repeats exactly for its seed and replays with error 0. A parameter edit during a run takes effect from the next step on the running network: membrane potentials, conductances, spikes in transit, rates and the random generator carry over (in v0.5 every edit restarted the network from rest and replayed the run's first input noise; `scripts/replay.py` does the same for runs exported by v0.5 or earlier, schema 3, so they still replay exactly).

Speed on the reference laptop: the 3,000-neuron circuit spends about 0.3 ms of wall time per 1 ms neural step (about 3× faster than real time for the neural part) and the 134,180-neuron whole brain about 6.7 ms (0.15×). With rate dynamics the same circuits take 0.05 ms and 3.2 ms. The FlyGym body adds its own cost. The [GPU backend](#gpu-backend) runs the whole brain at about 1.25 ms per step with spiking dynamics and 0.7 ms with rate dynamics.

### GPU backend

**Brain backend → GPU (PyTorch CUDA)** in the Workbench, or `connectome_parameters.backend = "torch"` in a configuration, runs the connectome model's rate or spiking dynamics on an NVIDIA GPU (`neural/gpu.py`; how it works: [ARCHITECTURE](ARCHITECTURE.md#gpu-brain-backend-and-batched-worlds-roadmap-track-d)). The default stays **CPU (NumPy)**, which computes exactly what it did before, so defaults and recorded runs replay bit for bit. The GPU backend needs the separate GPU environment (`./scripts/setup.sh --with gpu`, then `./scripts/start.sh --gpu` or `backend/.venv-gpu/bin/python` for scripts); elsewhere choosing it is refused with the reason. It is fixed for a run, like the dynamics, and exports record it.

**What agrees with the CPU path.** Rate dynamics are the same arithmetic in the same order except for the order of terms in each sparse sum, so every neuron's rate matches within float rounding. Spiking dynamics are the same model, constants and substep schedule, but the Poisson input comes from another random generator, so spike trains differ for the same seed and only their statistics can be compared. `neural/agreement.py` (`scripts/benchmark.py --check`) does both, in the style of the Eon Systems fly-brain harness, which checks each of its simulator backends against Brian2:

- rate: both backends side by side through a changing input, with a readout type's left side scaled by 0.5 from the middle on; the largest difference in any neuron's rate or readout must be below 10⁻⁹;
- spiking: eight seeds per backend, 2 s at constant input (left 0.6, right 0.4). The correlation across neurons of the per-neuron firing rates between a CPU run and a GPU run must reach that between two CPU runs with different seeds, less 0.03; the mean firing rate of all neurons and of the recurrent ones (not driven by the sensors, so their rates follow the weights), and each readout type's spike count per side, must agree between the backends within Welch's t (99.9 %, two-sided) times the standard error over seeds, plus 1 %.

Measured on the reference laptop (RTX 4050 Laptop GPU, 6 GB), all circuits pass:

| Circuit | Neurons | Rate: largest \|GPU − CPU\| | Spiking: rate correlation, CPU–CPU / CPU–GPU | Mean rate, all neurons (Hz), CPU / GPU | Recurrent neurons (Hz), CPU / GPU (bound) | Readout spike counts within bounds |
| --- | ---: | ---: | --- | --- | --- | --- |
| fafb783-dna02 | 3,000 | 3.3 × 10⁻¹⁶ | 0.9935 / 0.9939 | 18.09 / 18.06 | 7.029 / 7.034 (±0.195) | 2 of 2 (DNa02 L 395.5 / 392.0, R 250.5 / 250.6) |
| fafb783-dna02-balanced | 3,000 | 3.3 × 10⁻¹⁶ | 0.9938 / 0.9940 | 20.29 / 20.28 | 7.856 / 7.872 (±0.213) | 2 of 2 |
| fafb783-steering | 4,000 | 3.3 × 10⁻¹⁶ | 0.9949 / 0.9948 | 20.62 / 20.59 | 9.437 / 9.414 (±0.280) | 6 of 6 |
| fafb783-steering-balanced | 3,999 | 2.2 × 10⁻¹⁶ | 0.9953 / 0.9953 | 21.71 / 21.62 | 10.430 / 10.342 (±0.346) | 6 of 6 |
| whole brain (local build) | 134,180 | 6.1 × 10⁻¹⁶ | 0.9959 / 0.9959 | 6.076 / 6.076 | 1.826 / 1.829 (±0.029) | 2 of 2 (DNa02 L 483.5 / 486.2, R 1.2 / 1.6) |

The harness is sensitive enough to matter: on the DNa02 circuit, a weight per synapse 5 % too large in the GPU runs fails (the recurrent rate rises by 0.34 Hz against a bound of 0.20 Hz), while 2 % too large passes (+0.15 Hz); the population and readout tests alone miss both, because the input neurons' rates follow the Poisson drive. A first version with four seeds per backend failed a correct backend once in five circuits (the balanced steering circuit, 10.50 vs 10.31 Hz); twenty seeds each gave 10.41 ± 0.02 and 10.37 ± 0.03 Hz, so the default is now eight seeds and a t bound. A GPU spiking run repeats exactly for its seed on the same GPU and software (its delay queue sums in fixed point and its random numbers are counter-based), and a GPU run exported from the app replays on the GPU: spiking with error 0, rate within replay's tolerance.

**Speed.** Wall time per 1 ms neural step, `scripts/benchmark.py --neural --backend both`, 1,000 steps after 100 warm-up steps, both sensors at 0.5, seed 0. The GPU time includes waiting for the device at the end, as the app reads the readouts once per 10 ms:

| Circuit | Neurons | Rate, CPU | Rate, GPU | Spiking, CPU | Spiking, GPU | Spiking speed-up |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fafb783-dna02 | 3,000 | 0.116 ms | 0.117 ms | 0.860 ms | 0.216 ms | 4.0× |
| fafb783-dna02-balanced | 3,000 | 0.104 ms | 0.119 ms | 0.841 ms | 0.226 ms | 3.7× |
| fafb783-steering | 4,000 | 0.223 ms | 0.115 ms | 0.942 ms | 0.197 ms | 4.8× |
| fafb783-steering-balanced | 3,999 | 0.158 ms | 0.116 ms | 1.030 ms | 0.247 ms | 4.2× |
| whole brain (local build) | 134,180 | 5.455 ms | 0.692 ms | 17.472 ms | 1.252 ms | 14.0× |

These were measured while another project's training job kept the GPU at 100 % and other work loaded the CPU (the CPU numbers are slower than the 0.3 ms and 6.7 ms measured for the spiking circuits on an idle laptop), so both columns are conservative and the ratios approximate. On a 3,000–4,000-neuron circuit, GPU rate dynamics are no faster (launching the kernels costs as much as the CPU's whole step), while spiking dynamics run about four times faster. On the whole brain the GPU is about 8× faster for rate dynamics (0.69 ms, faster than real time) and about 14× for spiking dynamics (1.25 ms per ms: the whole brain at 0.8× real time). Device memory stays small: at most 92 MB of tensors for the whole brain with spiking dynamics (49 MB with rate dynamics), plus the CUDA context (about 0.3–0.5 GB), well inside the 6 GB of a laptop GPU. The FlyGym body, at about 7,000–9,000 physics steps per second on one CPU core, then dominates a closed-loop run.

**Limits.** The GPU environment does not include FlyVis, so FlyVis eyes need the CPU environment. Sweeps and scans work with `--set connectome_parameters.backend=torch` (trials) or `--set backend=torch` (bias, ablation), from `backend/.venv-gpu/bin/python`; keep `--workers` at 1–2, because each worker process opens its own CUDA context on the one GPU. A non-finite network state stops a GPU run at the next readout (at most 100 steps later) rather than at the step that produced it.

### Input mapping

Each side's sensor value (geometric or compound-eye) × the input gain drives every **visual projection neuron** (FlyWire super class `visual_projection`) on the same side: **250 left and 227 right** in the DNa02 circuit, 345 and 304 in the steering circuit. In the DNa02 circuit, 29 of them connect to DNa02 directly (31 connections) and 448 sit two hops back; the most common types are LC10a, LC10c and LC10d, LT51, LC36, LPLC4 and LC33. This mapping is engineered: these cell types encode different visual features, and here they all receive the same value. **Populations → Sensor input** restricts the input to named cell types (they need neurons on both sides). A circuit whose default input lacks visual projection neurons on one side, as a small local build can, is refused until you name input types.

### Output mapping

```text
turn = output gain × Σ over readout types (mean right − mean left)
forward = tonic drive (+ speed gain × mean of the speed cell types, if any)
motor = 1.4 × clip([forward + turn, forward − turn], 0, 1)    # [left legs, right legs]
```

- **Direction.** Rayshubskiy et al. 2025 ([eLife 13:RP102230](https://doi.org/10.7554/eLife.102230)) found the fly's rotational velocity linearly related to the right − left difference in DNa02 firing, and the same relation in a paired DNa01 recording, with DNa02 predicting large, transient turns and DNa01 smaller, slower ones. Bidaye et al. 2020 ([Neuron 108:469](https://doi.org/10.1016/j.neuron.2020.07.032)) found that P9 (DNp09) drives forward walking with turning toward its own side and receives input from visual projection neurons. So a more active right neuron of any of these types means a right turn.
- **Weights.** By default readout types are summed with equal weights. That is an assumption: the measured gains differ between DNa01 and DNa02. `readout_weights` (−5 to 5 per type, 1 when not given) and `readout_pool` (`sum`, or `mean`, which divides by the number of readout types) change that; both are engineered.
- **Delay and smoothing.** `motor_delay_ms` (0–500) delays the command `[forward + turn, forward − turn]` by whole 1 ms neural steps, and `motor_tau_ms` (0–1000) then low-passes it, `c += (1 − exp(−dt/τ)) × (delayed − c)` every neural step, before the clip. Both are 0 by default, which leaves the v0.5 output unchanged. They are engineered stand-ins for the nerve cord and leg dynamics the model lacks, not fitted values; the exact rules are in [ARCHITECTURE.md](ARCHITECTURE.md#connectome-motor-path).
- **Which amplitude turns which way.** FlyGym 2.1.0's `HybridTurningController.step` sets the first three CPG amplitudes (legs LF, LM, LH) from `descending_signal[0]` and the last three (RF, RM, RH) from `descending_signal[1]`. A larger left amplitude turns the body right: `[1.2, 0.4]` turns the FlyGym body 146° clockwise in 1 s, and the toy body turns the same way.
- **Forward drive** is the tonic term. **Populations → Speed drive** adds the mean activity of named cell types (for example DNp09) × the speed gain. It is off by default.

Readout, input and speed populations are set by cell type in **Neural atlas → Live circuit → Populations**. They decide which rates are recorded, so changing them starts a fresh run.

### Interventions

Besides silencing DNa02 and whole cell types, `Interventions.cell_types` manipulates any cell type on the left, the right or both sides (up to 32 entries, one per side of a type):

| Mode | Value | Rate dynamics | Spiking dynamics |
| --- | --- | --- | --- |
| `silence` | ignored | activity held at 0 | held at rest, never fires |
| `scale` | 0–2 | what the neurons send (to their targets and the readout) × value | each spike's synaptic effect × value |
| `activate` | rate above 0, up to 1 (rate) or Hz above 0, up to 500 (spiking) | rate clamped to the value | independent Poisson input at the value in Hz, the sensor input's kick, no refractory period |

All three are **engineered manipulations**. Activation approximates optogenetic activation and is not calibrated to any opsin, light level or recorded firing rate; scaling is graded inhibition (< 1) or a boost (> 1) of transmission without a single biological counterpart. With no `cell_types` the model computes exactly what v0.5 did. The equations are in [ARCHITECTURE.md](ARCHITECTURE.md#connectome-interventions).

They apply through `POST /api/interventions`, as a configuration's `initial_interventions`, as protocol events ("activate at step 100, restore at step 200" is two events) and as comparison conditions; every change is a step-stamped event, and runs replay exactly. For example, with spiking dynamics (rate dynamics would take an activation above 0, up to 1; to hold a type at rest, silence it):

```json
{"cell_types": [{"name": "DNa02", "side": "left", "mode": "silence"},
                {"name": "LC10a", "side": "right", "mode": "scale", "value": 0.5},
                {"name": "DNp09", "mode": "activate", "value": 80}]}
```

An export's `metadata.neural.interventions` lists those in force at its end, with neuron counts; the live view counts silenced, scaled and activated neurons. A comparison's `custom_conditions` run labelled conditions of your own: interventions and/or changes to the live-editable connectome parameters (gains, tonic drive, threshold, time constant, motor path, readout weights and pooling, spiking settings), as `{"label": "gain 3", "connectome_parameters": {"output_gain": 3}}`.

### Parameters and how the defaults were chosen

Only global parameters exist: synapse threshold (1–1000, applied on top of the circuit's build threshold), global gain, input gain, output gain, tonic drive, τ, the transmitter switch, the speed gain and, for spiking, the weight per synapse, the input rate, the rate window and the rate scale. Edit them in **Neural atlas → Live circuit**; changes are recorded and replayed. The motor path's readout weights, pooling, delay and low-pass are set in the same place (under **Motor path**), through the API (`POST /api/connectome/parameters`) or with the toolkit (for example `--set connectome_parameters.motor_delay_ms=180`), and are live-editable and replayed in the same way. Circuit, dynamics and populations are fixed for a run.

| Parameter | Default | Choice |
| --- | --- | --- |
| Global gain | 0.001 | The largest round value that keeps both DNa02 below half saturation for any constant input in [0, 1] on both sides (peak 0.45; 0.0012 reaches 0.63). Chosen before any behavior was measured |
| Input gain | 1 | Sensor values used as they are |
| Output gain | 1 | The turn command equals the summed readout difference |
| Tonic drive, τ, threshold | 0.35, 20 ms, 5 synapses | The engineered model's tonic drive, a 20 ms time constant and the build threshold |
| Spiking constants | Shiu et al. 2024 | Not tuned; the 100 Hz rate scale and 50 ms window are engineered readout choices |

### What the circuits compute

With the target held still, steady-state DNa02 activity in the DNa02 circuit after 0.6 s (geometric sensor, target 12 mm away, default parameters):

| Target | DNa02 R − L | Turn command means |
| --- | --- | --- |
| 45° left | −0.238 | Left, toward |
| 90° left | −0.262 | Left, toward |
| Ahead | −0.178 | Left |
| 45° right | −0.056 | Left, away |
| 90° right | +0.060 | Right, toward |

`scripts/toolkit.py readouts` prints this table (the fly is held at the origin facing ahead, the geometric sensor's two values are clamped for 600 ms, then each readout type's right − left activity and the turn command are read; `--set circuit=…` for another circuit, `--bearings`, `--distance` and `--ms` to change the geometry).

Compared with a target straight ahead, moving it to either side shifts activity toward the DNa02 on that side, as Rayshubskiy et al. describe for attractive stimuli. But the DNa02 circuit is **strongly biased to the left**: equal input on both sides already commands a left turn, so a target must be about 90° to the right before the circuit turns right. No global parameter removes the bias: τ leaves steady states unchanged, a 10- or 20-synapse threshold weakens every response without removing it, the transmitter switch changes nothing measurable, and a larger input gain makes it stronger.

`scripts/toolkit.py bias` measures the same thing directly: it clamps both sensors for 500 ms over a grid of inputs and reports the turn command, plus a **mirror test** (a left-right symmetric circuit gives turn(a, b) = −turn(b, a); the asymmetry is 0 for such a circuit and grows with the bias):

| Circuit and dynamics | Turn with equal input 0.5 / 0.5 | Turn, input 0.3 / 0.7 (target right) | Turn, input 0.7 / 0.3 (target left) | Mirror asymmetry |
| --- | --- | --- | --- | --- |
| DNa02 circuit, rate | −0.179 (left) | −0.025 (left) | −0.240 (left) | 1.07 |
| Steering circuit, rate | +0.026 | +0.440 (right) | −0.368 (left) | 0.15 |
| Steering circuit, spiking | −2.02 (left) | −0.40 (left) | −1.91 (left) | 1.07 |

Positive turns are rightward. The spiking values are averaged over the last 400 ms of 800 ms (seed 1).

**The clip, and how to read `motor_clipped_fraction`.** Once the turn command's size exceeds min(forward, 1 − forward), 0.35 with the default tonic drive, one side of `[forward + turn, forward − turn]` leaves [0, 1], and the clip in the motor equation pins that side's legs at amplitude 0 or 1.4. The spiking turns above (−2.02, −1.91) are far past that, so with the default spiking calibration the steering is mostly saturated: the sign of the turn reaches the legs, its size does not. Each run reports the share of control intervals (10 ms) whose command was clipped on either side as `motor_clipped_fraction`, an engineered diagnostic, in exports (`metadata.neural.motor_clipped_fraction`) and in the live connectome block. Near 0, the legs follow the circuit's graded output; near 1, turning speed is set by the clip, so input differences that change only the size of the turn cannot be told apart, and slope fits of turning against the readout (such as the turning-per-spike numbers below) measure the clip as much as the circuit. Results that depend only on the turn's sign (first turn, reaching) are less affected. Over the first 5 s of a default toy-body run (seed 1), it is 0 for the DNa02 circuit and 0.12 for the steering circuit with rate dynamics, and 0.57 and 0.67 with spiking dynamics. The default spiking calibration was not changed; lowering the output gain or raising the rate scale reduces the clipping.

### Where the side bias comes from

`scripts/toolkit.py ablation` silences each cell type in turn (both sides, all of its neurons) with equal input on both sides and ranks the types by how much the turn command changes. In the DNa02 circuit (rate dynamics, intact turn −0.179):

| Silenced type | Neurons in the circuit (left / right) | Turn with it silenced | Change |
| --- | --- | --- | --- |
| AOTU025 | 1 / 1 | −0.080 | +0.099 |
| LC10c | 35 / 19 | −0.118 | +0.061 |
| LC10a | 51 / 29 | −0.123 | +0.056 |
| LC33 | 8 / 7 | −0.220 | −0.041 |
| LT51 | 11 / 11 | −0.214 | −0.035 |

A positive change means the type was pushing the fly to the left. Two of the strongest contributors are visual projection types that the 3,000-neuron cap sampled unevenly: it kept 51 left and 29 right LC10a neurons and 35 left and 19 right LC10c neurons, because the cap ranks neurons by their path to the seeds, not by side. Every visual projection neuron on a side receives the same sensor value, so a lopsided sample turns into a lopsided drive. The bias is not only a sampling effect: in the whole-brain circuit (built locally with `--whole-brain`, no cap), equal input still commands a left turn of −0.171 through DNa02, with a mirror asymmetry of 0.75.

In the steering circuit the same scan finds larger effects that cancel: silencing LC9 (63 left, 77 right) shifts the turn by −0.144, while LC10a (19 left, 3 right), PVLP020, AOTU025 and LC11 (42 left, 7 right) each push left by +0.045 to +0.126. Its near-symmetric output is partly a balance of opposite sampling asymmetries, not a symmetric circuit. [Side-balanced circuits](#side-balanced-circuits) test this.

### Side-balanced circuits

`fafb783-dna02-balanced` and `fafb783-steering-balanced` (v0.6) rebuild the two committed circuits with the same seeds, hops, threshold and cap, but with `--balance-sides`, which applies the cap per cell type and side ([the rule](#building-your-own-circuits)): `build --name fafb783-dna02-balanced --seeds DNa02 --cap 3000 --balance-sides --committed`, and the steering seeds with `--cap 4000`. They answer one question about these models: how much of each circuit's side bias comes from the cap sampling cell types unevenly? The original circuits are unchanged and remain the defaults.

| | DNa02 circuit | Balanced | Steering circuit | Balanced |
| --- | --- | --- | --- | --- |
| Neurons | 3,000 | 3,000 | 4,000 | 3,999 |
| Cell types | 1,257 | 1,056 | 1,650 | 1,438 |
| Visual projection inputs, left / right | 250 / 227 | 274 / 276 | 345 / 304 | 335 / 338 |
| Cell types with neurons on a side, and how many of them are uneven | 1,252; 458 | 1,048; 37 | 1,636; 597 | 1,414; 87 |
| LC10a, LC10c, left / right | 51 / 29, 35 / 19 | 43 / 43, 23 / 23 | 19 / 3, 12 / 7 | 12 / 12, 10 / 10 |
| Unpaired neurons dropped at hop 2 | — | 2,769 | — | 4,469 |

Every cell type still uneven in a balanced circuit has neurons among the seeds' direct partners, which are always kept. Balancing drops types found on one side only from the trimmed hop, so the balanced circuits have fewer cell types; a balanced sample is a different assumption about which neurons matter, not a more complete one. In the whole brain these visual projection types are close to even (LC10a 115 / 119, LC10c 101 / 102), so the uneven counts of the original circuits come from the cap.

Open loop (`scripts/toolkit.py bias`; rate: 500 ms; spiking: 800 ms, averaged over the last 400 ms, seed 1; positive turns are rightward):

| Circuit and dynamics | Turn with equal input 0.5 / 0.5 | Turn, input 0.3 / 0.7 (target right) | Turn, input 0.7 / 0.3 (target left) | Mirror asymmetry |
| --- | --- | --- | --- | --- |
| DNa02 circuit, rate | −0.179 | −0.025 | −0.240 | 1.07 |
| DNa02 balanced, rate | −0.082 | +0.093 | −0.206 | 0.62 |
| Steering circuit, rate | +0.026 | +0.440 | −0.368 | 0.15 |
| Steering balanced, rate | +0.148 | +0.554 | −0.223 | 0.56 |
| DNa02 circuit, spiking | −0.683 | −0.483 | −0.929 | 1.24 |
| DNa02 balanced, spiking | −0.188 | +0.192 | −0.399 | 0.45 |
| Steering circuit, spiking | −2.02 | −0.40 | −1.91 | 1.07 |
| Steering balanced, spiking | −0.917 | +0.569 | −0.689 | 0.57 |

With the target held at each bearing (`scripts/toolkit.py readouts --set circuit=fafb783-dna02-balanced`), the balanced DNa02 circuit's DNa02 R − L is −0.198 (45° left), −0.247 (90° left), −0.071 (ahead), +0.065 (45° right) and +0.168 (90° right): it now turns toward the target at all four lateral bearings, where the original turned away from a target 45° to the right, but still turns left with the target ahead.

What this shows about these models:

- **The DNa02 circuit's left bias is partly the cap's sampling.** Balancing reduces its equal-input turn from −0.179 to −0.082 (rate dynamics) and its mirror asymmetry from 1.07 to 0.62, and with input 0.3 / 0.7 and 0.7 / 0.3 it then turns toward the stronger side. It does not remove the bias: equal input still turns left at every level, and at a mean input of 0.75 even 0.55 / 0.95 gives no right turn (−0.001). Run on the balanced circuit, `scripts/toolkit.py ablation` ranks the same types first, now with equal numbers on both sides: AOTU025 (1 / 1, +0.048), LC10c (23 / 23, +0.023) and LC10a (43 / 43, +0.022) still push the turn left, because their left and right neurons connect differently. The whole-brain circuit, which has no cap at all, turns left with equal input too (−0.171).
- **The steering circuit's near-symmetry was a cancellation.** Balanced, it turns right with equal input (+0.148) and its mirror asymmetry rises from 0.15 to 0.56. With spiking dynamics, both balanced circuits turn toward the stronger side for inputs 0.3 / 0.7 and 0.7 / 0.3, which neither original does ([how robust that is](#how-sensitive-is-a-result-to-the-modelling-assumptions)).

Closed loop, toy body, the evaluation's targets (6 bearings × 12 and 30 mm × seeds 1–5, 10 simulated seconds, rate dynamics; `scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.circuit=…`):

| Circuit | Reached ≤2 mm (95% CI) | First turn toward lateral targets | Median final distance | Mean final distance, 12 mm targets | Mean speed |
| --- | --- | --- | --- | --- | --- |
| DNa02 circuit | 0/60 (0–6%) | 40/40 | 8.5 mm | 7.5 mm | 5.9 mm/s |
| DNa02 balanced | 10/60 (9–28%) | 40/40 | 2.9 mm | 2.9 mm | 5.9 mm/s |
| Steering circuit | 57/60 (86–98%) | 40/40 | 3.8 mm | 3.8 mm | 6.1 mm/s |
| Steering balanced | 60/60 (94–100%) | 40/40 | 1.9 mm | 1.8 mm | 6.0 mm/s |

Paired over the same seeds and targets, balancing changes reaching by +0.17 (95% bootstrap interval +0.08 to +0.27) and the final distance by −3.7 mm (−6.2 to −0.5) for the DNa02 circuit, and by +0.05 (0.00 to +0.12) and −2.4 mm (−4.0 to −1.3) for the steering circuit. The balanced DNa02 circuit still settles into a clockwise orbit with the target about 90° to its right, 2.9 mm from it instead of the original's 7.5 mm; it counts as reaching only the 12 mm targets 45° and 90° to the left (5 seeds each), which it passes within 2 mm of on the way into that orbit.

With spiking dynamics, a shorter check (targets 45° and 90° to each side at 12 mm, seeds 1–3, 10 simulated seconds, 12 trials per circuit) gives: the balanced DNa02 circuit reaches all 12 targets within 1.9–2.3 s and then circles them 1.0–2.6 mm away (the original reaches none; mean final distance 22.9 mm); the balanced steering circuit reaches 8 of 12 within 1.6–1.8 s and then walks away from them (final distances 35–56 mm), where the original reaches none (16.5 mm). With 12 trials each the intervals are wide (reaching 76–100% and 39–86%).

These are properties of two samplings of one female brain's wiring under this model's assumed signs and engineered input and output. That balancing improves reaching here says that the cap's uneven sampling hurt these circuits; it says nothing about whether flies' steering circuits are symmetric.

### The steering circuit

The steering circuit adds two descending types to DNa02: DNa01, the other steering neuron Rayshubskiy et al. recorded, and DNp09 (P9), which drives object-directed walking with turning to its own side (Bidaye et al. 2020). It was built with the general builder (`build --name fafb783-steering --seeds DNa01,DNa02,DNp09 --cap 4000 --committed`): 6 seed neurons, 1,306 direct partners and 2,688 of 21,656 hop-2 candidates.

How it was chosen, in order: DNa01 and DNa02 were added for their documented steering roles, and DNp09 for object-directed walking. An open-loop check on this 4,000-neuron circuit showed the turn command stayed left-biased with DNa01 and DNa02 as readout (−0.130 with equal input, and a left turn even for a target on the right), and became nearly symmetric once DNp09 was read out too (+0.026). The three-type readout is the builder's default rule (seed types with neurons on both sides), not a parameter fitted to behavior. No gain was changed. The sweep below then compares the four readouts on the same circuit (`scripts/toolkit.py trials --set connectome_parameters.circuit=fafb783-steering --vary 'connectome_parameters.readout_types=…'`, toy body, the evaluation's 60 trials each):

| Readout | Reached ≤2 mm | First turn toward lateral targets | Median final distance |
| --- | --- | --- | --- |
| DNa02 | 0/60 | 20/40 | 63.9 mm |
| DNa01 + DNa02 | 0/60 | 10/40 | 68.8 mm |
| DNa01 + DNa02 + DNp09 (default) | 57/60 | 40/40 | 3.8 mm |
| DNp09 | 60/60 | 40/40 | 2.2 mm |

So in this model the reaching comes from DNp09. Read out alone, DNa01 and DNa02 turn the fly the wrong way at first in this larger circuit, and it walks away. That is a property of this circuit and readout, not evidence about which neurons flies use.

### Evaluation

`scripts/evaluate_models.py` runs the engineered model and three connectome configurations (DNa02 circuit; steering circuit; steering circuit with spiking dynamics) from the default configuration with matched seeds, changing only the target, seed, model, circuit, dynamics and silencing. Targets sit ahead, 45° and 90° to each side and directly behind the starting heading, at 12 and 30 mm. A target counts as reached within 2 mm; the first turn is the direction of the first 10° heading change. All numbers below come from the reports the script saved (`docs/evidence/evaluation-*.json`, kept locally; a run of only some models or at another duration saves under a name that says so, such as `evaluation-toy-engineered.json`, and never replaces a full report). The engineered and DNa02-circuit results are identical to v0.3's.

**Toy body**, 5 seeds (1–5), 10 simulated seconds per trial, 60 trials per model:

| Model | Reached ≤2 mm | First turn toward lateral targets | Median time to reach | Mean final distance, 12 mm targets | Mean speed |
| --- | --- | --- | --- | --- | --- |
| Engineered | 59/60 | 40/40 | 2.25 s | 1.5 mm | 9.5 mm/s |
| Connectome, DNa02 circuit | 0/60 | 40/40 | — | 7.5 mm | 5.9 mm/s |
| Connectome, steering circuit | 57/60 | 40/40 | 4.7 s | 3.8 mm | 6.1 mm/s |
| Connectome, steering circuit, spiking | 0/60 | 22/40 | — | 15.5 mm | 7.1 mm/s |

The steering circuit misses only three of the five 30 mm targets behind the fly. After reaching a target it keeps circling it at about 4 mm, because nothing tells it to stop. The engineered model misses one 30 mm target behind.

**Headless FlyGym body**, 3 seeds (1–3), 12 mm targets, 6 simulated seconds per trial, 18 trials per model:

| Model | Reached ≤2 mm | First turn toward lateral targets | Median time to reach | Mean final distance | Mean speed |
| --- | --- | --- | --- | --- | --- |
| Engineered | 18/18 | 12/12 | 0.9 s | 2.5 mm | 14.6 mm/s |
| Connectome, DNa02 circuit | 0/18 | 12/12 | — | 12.0 mm | 8.7 mm/s |
| Connectome, steering circuit | 18/18 | 12/12 | 1.6 s | 9.4 mm | 9.0 mm/s |
| Connectome, steering circuit, spiking | 0/18 | 7/12 | — | 13.2 mm | 11.6 mm/s |

On the real body the steering circuit reaches every target within 1.4–3.9 s and then walks past it: the final distances include that. With spiking dynamics both circuits keep a strong left bias (the table in [What the circuits compute](#what-the-circuits-compute)), so the fly circles away from targets on its right.

**The DNa02 circuit's orbit.** Its first turn goes toward every lateral target, but it never comes within 2 mm. It settles into a clockwise orbit around the target, holding it at 90° to its right: in a 12 mm toy trial the orbit radius is 7.5 mm from any starting bearing. The output gain sets the orbit's size, not its shape: gains of 2, 4 and 8 shrink the radius to 4.4, 2.3 and 1.5 mm, so a gain of 8 would satisfy the 2 mm criterion while the fly still circles. The defaults were not changed to pass this test.

**Silencing DNa02** (toy body, targets 45° and 90° to each side at 12 mm, 5 seeds; positive yaw rate turns left):

| Circuit | DNa02 silenced | Mean yaw rate, first 2 s: left targets | right targets | Net turn: left targets | right targets | Reached ≤2 mm | Mean final distance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DNa02 | None | +55 °/s | −23 °/s | −267° | −375° | 0/20 | 7.5 mm |
| DNa02 | Left | −16 °/s | −74 °/s | −70° | −237° | 0/20 | 55.6 mm |
| DNa02 | Right | +100 °/s | +37 °/s | +577° | +419° | 0/20 | 41.5 mm |
| DNa02 | Both | 0 °/s | 0 °/s | 0° | 0° | 0/20 | 55.5 mm |
| Steering | None | +40 °/s | −34 °/s | +1431° | +1293° | 20/20 | 3.9 mm |
| Steering | Left | +46 °/s | −25 °/s | +1253° | +1123° | 20/20 | 3.9 mm |
| Steering | Right | +38 °/s | −37 °/s | +1273° | +1136° | 20/20 | 4.0 mm |
| Steering | Both | +46 °/s | −25 °/s | +1526° | +1394° | 20/20 | 2.5 mm |

On the headless FlyGym body (3 seeds, 6 simulated seconds) the pattern is the same: the DNa02 circuit turns toward the intact side with one DNa02 off and stops turning with both off (−0.4 °/s, a drift of the walking gait itself), while the steering circuit reaches all 12 targets in every condition.

With DNa02 as its only readout, the DNa02 circuit cannot turn without it. The steering circuit keeps steering with both DNa02 silenced, because DNp09 carries its turning. Flies also keep turning when both DNa02 are inhibited (Rayshubskiy et al. 2025), but here that robustness follows from the readout we chose. It is consistent with the fly result, not evidence for it.

### The research toolkit

`digitalfly.toolkit` (Python) and `scripts/toolkit.py` (command line) run the analyses above without the web app. Every trial is built from a validated configuration and seed, so it can be repeated; results go to the ignored `runs/toolkit/` as CSV and JSON.

```sh
backend/.venv/bin/python scripts/toolkit.py trials --set neural_model=connectome \
    --vary connectome_parameters.circuit=fafb783-dna02,fafb783-steering --workers 8
backend/.venv/bin/python scripts/toolkit.py bias --set circuit=fafb783-steering
backend/.venv/bin/python scripts/toolkit.py ablation --set circuit=fafb783-dna02 --workers 8 --top 20
backend/.venv/bin/python scripts/toolkit.py ablation --side left --workers 8               # left neurons only
backend/.venv/bin/python scripts/toolkit.py ablation --mode scale --value .5 --workers 8   # halve each type's output
backend/.venv/bin/python scripts/toolkit.py ablation --mode activate --value 80 --side right \
    --set dynamics=spiking --average-ms 200 --workers 8                                  # 80 Hz Poisson drive
backend/.venv/bin/python scripts/toolkit.py paths --source LC10a --target DNa02
backend/.venv/bin/python scripts/toolkit.py jump --set neural_model=connectome --set seed=3 --duration 60 --jump-seed 11
backend/.venv/bin/python scripts/toolkit.py circuits
```

```python
from digitalfly import toolkit
base = toolkit.configure({"engine": "toy", "neural_model": "connectome"})
configs = toolkit.grid(base, seed=[1, 2, 3], stimulus=[toolkit.target(45, 12), toolkit.target(-90, 12)],
                       **{"connectome_parameters.output_gain": [1, 2, 4]})
log = toolkit.TrialLog("runs/toolkit/gain-sweep", resume=True)   # .jsonl and .csv, written as trials finish
hashes = [toolkit.config_hash(c, duration_s=10) for c in configs]
todo = [c for c, h in zip(configs, hashes) if h not in log.saved]
toolkit.run_trials(todo, workers=4, duration_s=10, on_result=lambda index, row: log.add(row))  # any worker count
summary = toolkit.summarize(log.rows_for(hashes), ["output_gain"])  # this sweep's rows: intervals, paired differences
toolkit.ablation_scan(toolkit.ConnectomeParameters(circuit="fafb783-steering"), left=.5, right=.5)
toolkit.ablation_scan(toolkit.ConnectomeParameters(), mode="activate", value=.6, side="left")   # rate clamped at 0.6
```

- **trials** runs closed-loop trials over target bearings, distances and seeds, with `--set` for fixed settings and `--vary` for grid axes (dotted names reach nested settings, and fill an unset group such as `connectome_parameters.readout_weights.DNa02=1,2`). `--vary` splits its values at commas, unless they are one JSON list of lists, objects or null: `--vary 'stimulus=[{"x":5,"y":5},{"x":5,"y":-5}]'` is two targets. A setting out of range stops the command with one line naming it. It reports reaching, the first turn, final distance, the target's final bearing (about −90° while circling clockwise), net turn and speed. `seed` and the target position (`stimulus`, `stimulus.x`, `stimulus.y`) can come from `--set`/`--vary` instead of `--seeds`, `--bearings` and `--distances`, but not from both (the command stops and says which to drop); `stimulus.intensity` is kept for every target.
- **bias** clamps the sensors and reports turn commands and the mirror test. **ablation** silences each cell type in turn; `--types A,B` or a repeated `--type` (for names with commas, such as `--type "AOTU018,AOTU031"`) limits the scan, and unknown names, or the readout types (the turn is read from them, so they are never scanned), are refused before it starts. `--mode scale --value S` multiplies each type's output by S (0–2) instead, and `--mode activate --value V` drives it: V Hz of Poisson input per neuron in spiking dynamics, a rate clamped at V (above 0, up to 1) in rate dynamics; V must be above 0 (see [Interventions](#interventions)). `--side left` or `right` manipulates one side only and skips types with no neurons there (a named type without them is refused). For these modes the change is reported as a shift of the turn command (positive = rightward); the default scan's numbers are unchanged. A type whose run fails becomes a row with an `error` text, the rest of the scan goes on, and the command exits with an error after saving. Both accept `--average-ms` to average spiking output.
- **paths** lists the strongest cell-type paths between two types. A step's strength is the share of the target type's input synapses that comes from the source type; a path multiplies its steps, and its sign multiplies the assumed signs. The same tracing is in the live circuit view.
- **jump** records and exports a run whose target jumps to a random side every `--every` seconds (`toolkit.jumping_target_run`), for **compare**, which fits turning to readout activity in a recording or a run; see below.
- **readouts** prints [what the circuits compute](#what-the-circuits-compute): each readout type's right − left activity and the turn command for a target held still at fixed bearings (`robustness.readout_table` in Python). **robustness** reruns the open-loop analyses, and optionally short reach trials, under several modelling assumptions; see the next section.

**Failures, resuming and provenance.** A trial that raises (for example a FlyGym body that becomes numerically unstable) becomes a row with its settings, its whole configuration and an `error` text; the other trials carry on. A worker process that dies (killed, or out of memory) takes down only the trials it and the other workers were running: each of them runs again on its own in a fresh process, the rest go on in a new pool, and only a trial whose process dies again becomes an error row (`robustness` does the same for variants). `trials` appends every finished trial to `<out>.jsonl` and `<out>.csv` as it completes, then rewrites the CSV in trial order and writes the JSON report at the end, exiting with an error if any trial failed. `--resume` with the same `--out` skips the trials already saved without an error, matched by a hash of the validated configuration, `run_trial`'s settings and the circuit file's SHA-256 (so a rebuilt circuit runs again). A line cut short by an interrupted write is skipped with a warning. Each `.jsonl` line also records the code that computed it (`code`: the digitalfly version, git commit and whether tracked files had changes); the hash covers the settings and the circuit but not the code, so `--resume` reuses rows from other code, and says how many and from which version, so you can rerun without `--resume` when the change matters. `toolkit.TrialLog` does the same from Python (example above; it makes the output folder, and `log.rows_for(hashes)` picks one sweep's rows when the log also holds other seeds or durations), and `scripts/evaluate_models.py` streams its trials to the report's `.jsonl` and `.csv` the same way and takes `--resume`. Every saved report (`trials`, `bias`, `ablation`, `paths`, `jump`, `compare`, and `scripts/evaluate_models.py`) has a `provenance` block: git commit and whether the working tree had changes, the command line, each circuit's name and SHA-256, Python, the platform and package versions. Trial rows also carry `circuit_sha256`. Dots in `--out` names are kept: `--out runs/toolkit/gain-1.5` writes `gain-1.5.json`, `.csv` and `.jsonl`.

**Statistics.** `trials` reports, per condition (the `--vary` values; seeds are replicates and are pooled), how many trials reached the target and turned toward lateral targets with 95% Wilson score intervals, and the median and mean final distance with a 95% percentile-bootstrap interval of the mean (2,000 resamples from a generator seeded with 0, so the same rows always give the same interval). With more than one condition it adds paired differences from the first condition over trials with the same seed, bearing and distance (reaching counted as 1 or 0), with bootstrap intervals. Failed trials are counted but left out of every statistic. `toolkit.summarize`, `toolkit.wilson_interval` and `toolkit.bootstrap_interval` do the same from Python. These intervals describe variation over seeds and targets in this simulation, not uncertainty about flies.

Parallel workers use separate processes (`spawn`), so call the Python functions with `workers > 1` from a script file, not an interactive prompt. Each worker is limited to (CPU cores ÷ workers) OpenMP, MKL and OpenBLAS threads, set before the workers start so that NumPy and PyTorch pick the limit up; `ablation_scan` uses the same limit.

**Long trials.** Trials keep no per-sample recording (`Experiment(config, render=False, record=False)` from `digitalfly.simulation.experiment`), so they have no length limit: the app's recording limit (30,000 samples, 300 simulated seconds) does not apply. Recording does not feed back into the simulation, so the numbers are identical to a recorded run's. An experiment you pass to `run_trial` yourself keeps its own setting, and a recording one is checked against the limit before the trial starts. `jumping_target_run` (and `jump`) exports its run, so it needs the recording: it accepts at most 299.99 s and says so before running.

**Motor clipping.** Connectome trial rows carry `motor_clipped_fraction`, the fraction of control intervals whose motor command left [0, 1] and was clipped (an engineered diagnostic; see [Output mapping](#output-mapping)). `trials` prints its mean over the connectome trials. A clipped command no longer follows the readout, so a large fraction means the output gain or the spiking calibration saturates the body's turning.

### Batched worlds (experimental)

FlyGym 2.1 can step many copies of a world at once on a GPU with MuJoCo Warp (`flygym.warp.GPUSimulation`, the `flygym[warp]` extra, installed by the GPU environment). `digitalfly.simulation.batched` builds the app's own FlyGym body in it (the same fly, adhesion, flat ground and tibia/tarsus contacts as `FlyGymBody`) and `scripts/benchmark.py --worlds` measures it. Because the closed loop cannot run there yet (below), it records 0.5 s of the app's body walking under a constant command (descending command [1.2, 1.0], a right turn; 6.5 mm of path), then replays the recorded joint targets and adhesion step by step: in CPU MuJoCo (FlyGym's `Simulation`, the app's engine) and in N MuJoCo Warp worlds, each 10 ms of 100 physics steps captured once as a CUDA graph. The CPU replay ends within 4 × 10⁻⁷ mm of the closed-loop run it came from, so replaying commands is faithful on the CPU.

| Engine | Worlds | Wall time for 0.5 s | World steps per second | World 0's thorax vs CPU at 0.5 s | GPU memory (Warp pool) |
| --- | ---: | ---: | ---: | ---: | ---: |
| CPU MuJoCo, one core | 1 | 0.45 s | 11,107 | — | — |
| MuJoCo Warp | 1 | 7.7 s | 651 | 0.061 mm | 5 MB |
| MuJoCo Warp | 16 | 11.2 s | 7,131 | 0.059 mm | 9 MB |
| MuJoCo Warp | 64 | 17.3 s | 18,467 | 0.075 mm | 20 MB |
| MuJoCo Warp | 256 | 43.4 s | 29,485 | 0.065 mm | 63 MB |
| MuJoCo Warp | 1,024 | 155.2 s | 32,997 | 0.061 mm | 235 MB |

Measured on the reference laptop (RTX 4050 Laptop GPU; 12 CPU threads) while another project's training job kept the GPU at 100 %, so the GPU rows are pessimistic. Even so, the conclusion is clear for this hardware: 1,024 worlds give about three CPU cores' worth of physics steps, which the toolkit's process pool already uses, and one world is 17× slower than the CPU. Every world received the same commands; MuJoCo Warp's trajectory differs from CPU MuJoCo's by about 0.06 mm (1 % of the path) after 0.5 s, from float32 arithmetic and the noslip solver it lacks (FlyGym switches noslip off for it; the CPU model uses 5 iterations).

**Why the toolkit's trials do not use it.** Every DigitalFly trial is a closed loop at 10 kHz: at each physics step FlyGym's hybrid turning controller reads the legs' ground-contact forces (its stumbling and retraction corrections), the tarsus heights and the heading, and every 10 ms the brain reads the body. `GPUSimulation` gives joint, body and actuator state as GPU arrays but no contact forces, and the controller (a CPG network with per-leg corrections) exists only per world in Python on the CPU, so a closed loop would copy every world's state to the CPU and back 10,000 times per simulated second, slower than the CPU engine. Its trajectories also differ from the CPU engine's, on which recorded runs, replay and the scorecard's thresholds depend, so batched results would not be comparable with saved ones. Making it useful needs the contact readout and the hybrid controller ported to batched GPU arrays, and a check of how far the drift moves the toolkit's measures (reaching, turning, final distance); until then it stays a measurement.

### How sensitive is a result to the modelling assumptions?

Every number in this guide comes from one choice of assumptions that the data do not settle: the sign rule, the synapse threshold, how readout types are pooled and weighted, rate or spiking dynamics, which neurons the cap kept, the random seed. `scripts/toolkit.py robustness` (v0.6) reruns an analysis under every combination of chosen values and reports which qualitative conclusions survive:

```sh
backend/.venv/bin/python scripts/toolkit.py robustness --set circuit=fafb783-dna02 --analyses bias,readouts
backend/.venv/bin/python scripts/toolkit.py robustness --set circuit=fafb783-steering --vary readout_pool=sum,mean \
    --vary 'readout_weights=[null,{"DNa02":2},{"DNp09":0.5}]' --analyses bias,readouts
backend/.venv/bin/python scripts/toolkit.py robustness --vary circuit=fafb783-steering,fafb783-steering-balanced \
    --vary dynamics=rate,spiking --analyses bias,readouts,reach --workers 2
```

- **Assumptions.** `--vary NAME=V1,V2` takes any `ConnectomeParameters` field (dotted for spiking constants, such as `spiking.rate_scale_hz`; a JSON list for lists and objects), including `circuit`, for example a circuit and its balanced version, plus `seed`. Without `--vary` the grid is the transmitter rule (`other_transmitters`: excluded, excitatory) × synapse threshold (5, 10, 20) × dynamics (rate, spiking): 12 variants. The first value of every axis makes up the baseline, variant 0, so list the default first. `--set` fixes other parameters.
- **Analyses** (`--analyses`, default `bias`): `bias`, the bias curve and mirror test (clamped 500 ms; spiking 800 ms averaged over the last 400 ms); `readouts`, the turn for a target held 12 mm away at 45° and 90° to each side and ahead (600 ms; spiking as for `bias`); `reach`, toy-body trials toward targets 45° and 90° to each side at 12 mm, seeds 1–3 (`--reach-seeds`), 5 simulated seconds each (`--reach-duration`). `--seed` (default 0) seeds the open-loop spiking analyses; a `seed` axis does that per variant and is then that variant's only reach seed.
- **Conclusions** are categories: the direction of each turn command (left, right, or none within ±0.01, `--tolerance`), whether moving the target off the midline shifts the turn toward the target's side, and for `reach` the share of trials that end within 2 mm and of first turns toward the target (none, some for at most half, most, all). Each is compared with the baseline's: the survival table gives the number of variants that agree, the ones that differ and, when exactly the variants with one axis value differ, that value.
- **Output and failures** work as for `trials`: a Markdown table of every variant's numbers and the survival table; JSON with provenance, CSV, and a JSONL file appended as each variant finishes. A variant that fails becomes an error row, is left out of the comparison and makes the command exit with an error; `--resume` with the same `--out` reruns only the missing or failed variants. `--workers` evaluates variants in parallel processes. From Python: `robustness.variants`, `robustness.run`, `robustness.survival`.

What it found (the commands above and in [docs/evidence](evidence/README.md#toolkit-analyses); spiking variants use seed 0 unless seeds are varied):

| Circuit and assumptions varied | Variants | Survive in every variant | Do not survive |
| --- | --- | --- | --- |
| DNa02 circuit; sign rule × threshold × dynamics | 12 | Left turn with equal input, and with the target on either side (0.3 / 0.7 and 0.7 / 0.3); left turn for targets 45° and 90° left, ahead and 45° right | Right turn for a target 90° right (9 of 12: two spiking variants turn left, one is within the tolerance); the shift toward the target's side (8 of 12) |
| Steering circuit; sign rule × threshold × dynamics | 12 | Left turn for a target 90° left | Right turn with equal input (8 of 12: spiking at thresholds 5 and 10 turns left); right turn with the target on the right (9 of 12: three spiking variants turn left); left turn with the target on the left (10 of 12: spiking at threshold 20 turns right); left turn for a target 45° left (8 of 12: not at threshold 20); the shift toward the target's side (7 of 12) |
| Steering circuit, spiking; seeds 1–5 | 5 | Left turn with equal input and with the target on either side (with the target on the right, seed 5 gives −0.010, at the edge of the tolerance); left turn for targets 45° and 90° left, ahead and 90° right; no shift toward the target's side | Left turn for a target 45° right (4 of 5: seed 5 gives +0.056) |
| Steering circuit; readout pooling (sum, mean) × weights (equal, DNa02 × 2, DNp09 × 0.5) | 6 | Turns toward targets on either side, in both the bias test and the held-target test; the shift toward the target's side | Right turn with equal input (1 of 6) and with the target ahead (2 of 6): doubling DNa02 or halving DNp09 turns it left, and mean pooling divides the equal-input +0.026 by three, to +0.009, inside the tolerance |
| DNa02 circuit and its balanced version × rate, spiking; with reach trials | 4 | Left turn with equal input and with the target on the left; left turn for targets 45° and 90° left and ahead; the shift toward the target's side | Left turn with the target on the right (2 of 4: both balanced variants turn right, toward it); left turn for a target 45° right (3 of 4: the balanced circuit with rate dynamics turns right); right turn for a target 90° right (3 of 4: the original with spiking dynamics is within the tolerance); reaching no target (2 of 4: in 5 s the balanced circuit reaches 6 of 12 with rate and 12 of 12 with spiking dynamics); a first turn toward every lateral target (3 of 4: the original with spiking dynamics, 9 of 12) |
| Steering circuit and its balanced version × rate, spiking; with reach trials | 4 | Left turn with the target on the left; left turn for a target 45° left | With spiking dynamics, in both versions: left turn with equal input, with the target ahead and for a target 90° right; no shift toward the target's side; fewer targets reached (0 and 8 of 12, against 12 of 12 for both with rate dynamics) and fewer first turns toward them (6 and 11 of 12). Only the original with spiking dynamics turns left with the target on the right and for a target 45° right; only the balanced one turns right for a target 90° left |

With rate dynamics the steering circuit and its balanced version agree on every conclusion, reaching included; with spiking dynamics neither keeps them, so for that circuit the dynamics matter more than the sampling. For the DNa02 circuit, balancing is what makes it turn right with input 0.3 / 0.7, under both dynamics. In the open-loop bias test both balanced circuits turn toward a target on either side with spiking dynamics at seeds 0 and 1, but with the target held 90° to either side the balanced steering circuit with spiking dynamics turns away from it (seed 0).

With rate dynamics the transmitter rule changes these turn commands by at most 0.008; with spiking dynamics it changes the spike trains too, and the turns by up to 0.21 (DNa02 circuit) and 0.47 (steering circuit). The threshold and the dynamics matter most. Two cautions follow from the tables. A category near zero depends on the tolerance as much as on the model, as mean pooling shows. And "survives" means only that the conclusion held under the assumptions varied, on the same wiring and the same engineered input and output: it is a statement about this model's stability, not evidence about flies. A result that changes under one of these assumptions should be reported with the assumption it needs.

### Validation scorecard

`scripts/toolkit.py scorecard` (and `digitalfly.scorecard`, and the **Validation scorecard** panel on the Experiments page) scores a model against published perturbation → behavior results. It is a standing test suite, not a fit: nothing is tuned to pass it. Each test cites its source, manipulates cell types with the ordinary [interventions](#interventions) on matched-seed closed-loop trials, measures the body's behavior and gives **pass**, **partial** or **fail** by a rule that was written down before any model was scored (`scorecard.TESTS`; the rules are listed with `scorecard --list`). Two further results keep a test on the list without a score: **not testable**, when the circuit has none of the needed cell types (or the model has no cell types at all, like the engineered six-unit model), and **blocked**, when the fly lacks the sense or the motor program the result needs. A result that follows from how the readout is wired rather than from the connectome is flagged **by construction**, with the reason.

| Test | Source | Manipulation | Measure | Rule |
| --- | --- | --- | --- | --- |
| DNa02 one side → ipsilateral turning | Rayshubskiy et al. 2025, Fig. 8B: unilateral ReaChR gave a small but significant ipsilateral steering bias | Darkness (target intensity 0); DNa02 activated on the left, then the right | Yaw-rate shift toward the activated side vs matched controls, from 0.2 s | pass: > 5 °/s on each side; partial: mean of both > 5 °/s, or both > 0 |
| DNa02 both sides silenced → rotational speed unchanged | Rayshubskiy et al. 2025, Fig. 8E: GtACR1 on both DNa02 left rotational speed unchanged | Targets at ±45° and ±90°, 12 mm; DNa02 silenced on both sides | Rotational speed silenced ÷ control (|heading change| over 0.25 s bins) | pass: 0.75–1.33; partial: 0.5–2 |
| DNp09 (P9) one side → ipsilateral turning | Bidaye et al. 2020: unilateral P9 activation starts ipsilateral forward turns | As for DNa02 | As for DNa02 | As for DNa02 |
| MDN → backward walking | Bidaye et al. 2014 | Darkness; MDN activated on both sides | Forward velocity along the body axis | pass: < −0.5 mm/s; partial: at most half the control's |
| Giant Fiber (DNp01) → takeoff | von Reyn et al. 2014 | — | — | blocked: the body cannot take off |
| aDN1 (DNg62) / aDN2 (DNge078) → antennal grooming | Hampel et al. 2015; FlyWire names from Shiu et al. 2024 and Virtual Fly Brain | — | — | blocked: no grooming motor program |
| Left-right symmetry | Buchanan et al. 2015: single flies have a handedness, the population mean is unbiased | None: control trials at ±45° and ±90° | Bias index Σ(yaw(+b) + yaw(−b)) ÷ Σ(|yaw(+b)| + |yaw(−b)|) from 0.2 to 1 s; positive = leftward | pass: |index| ≤ 0.1; partial: ≤ 0.3 |
| Sugar GRNs → MN9 | Shiu et al. 2024 | — | — | blocked: no taste input, no proboscis |

Activation clamps the rate at 1 (rate dynamics) or drives 150 Hz Poisson input (spiking, Shiu et al.'s input rate). A test whose control does not turn (below 2 °/s) or walk (below 0.5 mm/s) is **inconclusive** instead of scored.

**Results** (toy body: seeds 1–3, 3 s trials; FlyGym body: seeds 1–2, 2 s trials; code at commits `c43fc79` and `7eb4238`, which differ only in documentation). Rate dynamics unless marked. “BC” = by construction.

| Model | Body | DNa02 one side (°/s) | DNa02 both silenced (ratio) | DNp09 one side (°/s) | MDN (mm/s, control) | Symmetry index | Score |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Engineered six-unit | toy | not testable | not testable | not testable | not testable | +0.02 pass (BC) | 1 pass of 1 |
| Engineered six-unit | FlyGym | not testable | not testable | not testable | not testable | +0.14 partial (BC) | 1 partial of 1 |
| DNa02 circuit | toy | +321 pass (BC) | 0.00 fail (BC) | +23.7 pass | +5.88 (+5.88) fail | +0.71 fail | 2 pass, 3 fail |
| DNa02 circuit | FlyGym | +271 pass (BC) | 0.05 fail (BC) | +11.2 pass | +6.99 (+6.99) fail | +0.77 fail | 2 pass, 3 fail |
| DNa02 circuit, spiking | toy | +321 pass (BC) | 0.00 fail (BC) | +187 pass | +5.88 (+5.88) fail | +1.00 fail | 2 pass, 3 fail |
| DNa02 balanced | toy | +321 pass (BC) | 0.00 fail (BC) | +23.7 pass | +5.88 (+5.88) fail | +0.29 partial | 2 pass, 1 partial, 2 fail |
| DNa02 balanced | FlyGym | +271 pass (BC) | 0.05 fail (BC) | +11.3 pass | +6.99 (+6.99) fail | +0.35 fail | 2 pass, 3 fail |
| DNa02 balanced, spiking | toy | +321 pass (BC) | 0.00 fail (BC) | +188 pass | +5.88 (+5.88) fail | +0.24 partial | 2 pass, 1 partial, 2 fail |
| Steering circuit | toy | +321 pass (BC) | 1.19 pass | +321 pass (BC) | +5.88 (+5.88) fail | +0.11 partial | 3 pass, 1 partial, 1 fail |
| Steering circuit | FlyGym | +271 pass (BC) | 1.50 partial | +271 pass (BC) | +6.98 (+6.99) fail | +0.18 partial | 2 pass, 2 partial, 1 fail |
| Steering circuit, spiking | toy | +321 pass (BC) | 0.46 fail | +321 pass (BC) | +5.88 (+5.88) fail | +1.00 fail | 2 pass, 3 fail |
| Steering balanced | toy | +321 pass (BC) | 1.13 pass | +321 pass (BC) | +5.88 (+5.88) fail | +0.06 pass | 4 pass, 1 fail |
| Steering balanced | FlyGym | +271 pass (BC) | 1.03 pass | +271 pass (BC) | +6.99 (+6.99) fail | +0.07 pass | 4 pass, 1 fail |
| Steering balanced, spiking | toy | +321 pass (BC) | 0.91 pass | +321 pass (BC) | +5.88 (+5.88) fail | −0.56 fail | 3 pass, 2 fail |

In every circuit the Giant Fiber is not testable (no DNp01 neurons) and sugar → MN9 is blocked. The antennal grooming test is not testable in the DNa02 circuits (no DNg62 or DNge078) and blocked in the steering circuits, which contain both aDNs but no grooming motor program. FlyGym scorecards with spiking dynamics were not run.

What the scorecard shows, read with its flags:

- **The unilateral activation passes are mostly the readout, not the wiring.** Wherever the activated type is a readout type (DNa02 everywhere, DNp09 in the steering circuits), the engineered motor mapping turns the fly toward the more active side, so activation turns it there whatever the connectome says; the turn saturates the motor command (+321 °/s on the toy body for every circuit). The flies' effect was small; the model's is as large as the body allows.
- **One pass comes from the wiring: DNp09 steers the DNa02 circuits.** DNp09 is in the DNa02 circuits but not read out there, and activating it on one side turns the fly toward that side through its connections to DNa02 (+23.7 °/s rate, +187 °/s spiking on the toy body; +11.2 °/s on FlyGym). The balanced and unbalanced circuits give the same rate-dynamics numbers, which suggests that in darkness only DNp09's path to DNa02 is active and that balancing left that path's neurons unchanged (not checked neuron by neuron). This agrees in direction with Bidaye et al. (2020); its size is not calibrated.
- **Silencing DNa02 separates the circuits.** The DNa02 circuits read turning from DNa02 alone, so silencing it removes every turn: a fail by construction, and it is what the flies did not do. The steering circuits keep turning through DNa01 and DNp09 (ratio 1.03–1.50 with rate dynamics, a pass or a partial), consistent with the flies' unchanged rotational speed; with spiking dynamics the unbalanced steering circuit loses half its rotation (0.46, a fail) and the balanced one keeps it (0.91).
- **MDN does nothing to the body,** in every circuit: forward velocity is unchanged to 0.01 mm/s. MDN is not a readout type and its connections inside these circuits do not reach the readout. The body could not have walked backward anyway: the motor interface clips the descending drive at zero and has no backward channel, so this test can at best be partial until the motor path changes (the nerve cord, roadmap v0.9).
- **Symmetry restates the known side biases,** measured in closed loop. The DNa02 circuit's left bias fails (+0.71 toy, +0.77 FlyGym), balancing halves it (+0.29, +0.35), and the balanced steering circuit is the only connectome model that passes (+0.06, +0.07). The closed-loop index and the open-loop equal-input turn ([bias tables](#where-the-side-bias-comes-from); also stored, unscored, with each scorecard) need not agree in sign: the balanced steering circuit turns slightly right with equal input held (+0.148) but slightly left in its first second toward mirrored targets. With spiking dynamics every circuit fails or nearly fails it, as the bias tables found.
- **The FlyGym body is not perfectly symmetric either.** The engineered model, whose weights are mirror symmetric, scores +0.14 on FlyGym (partial) and +0.02 on the toy body. With two seeds this is a small sample, but it means a symmetry index near ±0.1 on FlyGym is within what the body alone produces.

**Caveats.** A pass means this model reproduces the direction of one published effect under an engineered manipulation; it does not validate the model as a fly. The fly experiments manipulated neurons optogenetically or genetically with their own timing (500 ms light pulses for DNa02 activation, 2 min epochs for silencing), in flies walking on a ball or in an arena without a visual target; the scorecard holds the manipulation for the whole trial, and its turning is driven by a target. Activation strengths are not calibrated to any opsin or firing rate. The rules test direction and rough size, not effect sizes, and seeds are few (the toy body is deterministic apart from a small starting-heading offset). The tests that matter most for a nerve cord or new senses (Giant Fiber, grooming, feeding) cannot be scored yet; they stay on the list so that the scorecard shows what is out of reach.

**A measure corrected after the first FlyGym scores.** The rules above were fixed before any model was scored. One measure changed afterwards, before this release, and its thresholds did not: rotational speed for the silencing test was first the mean |yaw rate| over 10 ms samples. On FlyGym that is dominated by the body's yaw wobble at the 12 Hz stride, and the DNa02 circuit with both DNa02 silenced, which has no turn command at all, still rotated at 113 °/s and passed (ratio 0.89). Rotational speed is now read from heading changes over 0.25 s bins (three strides), which gives 2.4 °/s for that circuit, so it fails as it must; toy-body numbers did not change, since the toy body has no stride. The unscored open-loop equal-input turn and the inconclusive outcome were added in the same change.

### Comparing with real flies

`digitalfly.compare` fits rotational velocity to the right − left firing rate of a readout pair, choosing the lag (0–0.5 s) with the best r²: the relation Rayshubskiy et al. measured for DNa02. It reads a recording in one documented CSV (or NumPy) format, with columns `t_s`, `rate_left_hz`, `rate_right_hz`, `rotational_velocity_deg_s` (rightward positive) and optionally `forward_velocity_mm_s`, and it reads exported DigitalFly runs directly, converting spiking activity back to spikes/s:

```sh
backend/.venv/bin/python scripts/toolkit.py compare --recording fly.csv --run runs/YOUR_RUN_FOLDER
```

It reports each fit's sign, lag, gain, offset and r², side by side, and each source's left and right rate (mean, median and 99th percentile). `--recording` and `--run` can be repeated: each fly and run then gets its own row (`fly 1`, `fly 2`, …), and an "Across" table gives, for the flies and for the runs, the mean, standard deviation and range of the best lag, and the mean and standard deviation of the gain (pooled only when all share one unit), r² and held-out r²; the saved report holds them under `across` (`compare.summarize_fits` in Python). With one recording and one run the output is as before. A recording can mark samples as not valid (an optional `valid` column of 1 or 0); the fits then use only pairs of valid samples. Gains only compare directly when both are in spikes/s; the model's turning follows its readout by construction, so a matching fit is not validation. A steering curve (mean turning rate by the target's bearing) is also available for trajectories toward targets. The fitting is tested on labeled synthetic recordings with a known gain, lag and offset.

#### One recorded fly

`scripts/fetch_recording.py rayshubskiy2025-a2_d_13.mat` downloads one recording from Rayshubskiy et al. 2025 (Harvard Dataverse [doi:10.7910/DVN/0NCLP1](https://doi.org/10.7910/DVN/0NCLP1), version 1.2, CC0 1.0; 71,381,032 bytes, MD5 and SHA-256 checked; the raw file stays in the ignored cache). It holds a simultaneous whole-cell recording of the left and the right DNa02 in one walking fly, 575 s at 10 kHz, with ball-tracked forward, rotational and sideways velocity at 100 Hz; an optogenetic stimulus channel was on for 4.3% of the time. `compare.rayshubskiy_recording` converts it as the authors' MIT-licensed analysis code does (their channel assignment, spike detection and parameters for this fly, 12.5 ms bins smoothed with a 25 ms Gaussian, and their yaw calibration). It finds 571 spikes on the left DNa02 and 1,888 on the right: 1.0 and 3.3 spikes/s on average, a median of 0 and a 99th percentile of 36 spikes/s.

**Stimulation epochs are left out by default (v0.6).** While the optogenetic stimulus is on, turning and firing may be driven by the experiment rather than by spontaneous steering, and light artifacts could reach the spike detector. `compare` therefore marks the ball samples with the stimulus on, or on within the preceding 0.5 s (the fits' longest lag; an engineered choice), as not valid, and fits only the rest; `--include-stimulus` (`exclude_stimulus=False` in Python) keeps them, as v0.5 did. The conversion summary reports the fraction excluded.

**The sign of yaw is an inference.** The files do not document it. One of the authors' MATLAB scripts, working from their raw data, labels positive yaw as left turns; in this file, positive yaw follows right − left DNa02 firing, which the paper's central result (the left DNa02 bursts, then the fly turns left) makes rightward. The converter defaults to that reading and takes `--positive-yaw left` for the other. The direction of the fit below therefore cannot test the paper's result; its lag, size and shape can.

Fits of rightward turning to the right − left DNa02 rate (`scripts/toolkit.py compare`, saved under `runs/toolkit/`). The fly's row was computed in v0.5, before the stimulation mask existed, so it **includes** the 4.3% of stimulated samples; `--include-stimulus` reproduces it:

| Source | Best single lag | Turning per spike/s of R − L | r² at that lag | Linear filter: held-out r² (5-fold) |
| --- | --- | --- | --- | --- |
| Fly (575 s, stimulation epochs included) | 180 ms | 3.36 °/s | 0.044 | 0.097 |
| Model, DNa02 circuit, spiking, FlyGym (30 s) | 20 ms | 2.70 °/s | 0.375 | 0.419 |
| Model, steering circuit, spiking, FlyGym (30 s) | 10 ms | 1.18 °/s | 0.086 | 0.074 |
| Model, DNa02 circuit, spiking, toy body (60 s) | 0 ms | 4.18 °/s | 0.858 | 0.711 |
| Model, steering circuit, spiking, toy body (60 s) | 0 ms | 1.79 °/s | 0.325 | 0.273 |

**Not yet re-run:** the fly's fit with the stimulation epochs left out, the default since v0.6. `scripts/toolkit.py compare --recording .cache/recordings/rayshubskiy2025-a2_d_13.mat` computes it; until it is added here, read the fly row as including stimulated walking. The model rows are unaffected (runs have no stimulation channel).

The model runs come from `toolkit.jumping_target_run`, which `scripts/toolkit.py jump` runs and exports (the target jumps to a random side every 2 s, `--jump-seed 11`, model `--set seed=3`). The fly's filter is biphasic, as the paper reports for DNa02: turning one way about 150–180 ms after the right − left difference, after a smaller opposite lobe at short lags.

What this says about the model:

- **Turning per spike.** On the FlyGym body the DNa02 circuit turns 2.7 °/s per spike/s of DNa02 difference, near the fly's 3.4 °/s (single-lag fits; noise in the fly's rate estimate lowers its value).
- **Timing.** The fly turns about 180 ms after its DNa02 difference; the model within 10–20 ms. By default the model has no delay between descending neurons and the legs beyond the body's own; `motor_delay_ms` and `motor_tau_ms` add one, but no value has been fitted.
- **How much DNa02 explains.** In the fly, DNa02 predicts about 10% of held-out turning. In the DNa02 circuit it predicts 42% on FlyGym and 71% on the toy body, because the model's turning is wired to DNa02 by construction. In the steering circuit, where DNp09 does most of the steering, DNa02 predicts 7%, close to the fly, for that reason rather than a biological one.
- **Firing rates.** The spiking model's DNa02 fire far more than the recorded ones: means of 52–143 spikes/s against 1–3, and 99th percentiles of 212–230 spikes/s against 36 (v0.5 figures over every sample; `scripts/toolkit.py compare` now prints these rates for each source, over the samples its fits use). The Poisson input (150 Hz at full sensor value, Shiu et al.'s default) drives the network much harder than walking drives this fly.

One fly is one sample: none of these numbers has been checked on other recordings. The dataset holds four paired DNa02 recordings and more single ones (5.5 GB of electrophysiology in all). Only this one is in the download manifest so far, because each file is listed only once its size and hashes have been checked; `compare` already accepts several recordings, converted the same way, and reports their spread.

Other public datasets checked from their metadata:

| Dataset | What it holds | License | Smallest useful download |
| --- | --- | --- | --- |
| Rayshubskiy et al. 2025, other files | Paired and single DNa01 and DNa02 recordings with ball tracking; 380 files, 157.9 GB in all, mostly central-complex imaging | CC0 1.0 | 63–873 MB per recording |
| Mussells Pires et al. 2024 ([Nature 626:808](https://doi.org/10.1038/s41586-023-07006-3)), Zenodo [doi:10.5281/zenodo.10145317](https://doi.org/10.5281/zenodo.10145317) | Tethered walking flies orienting to a closed-loop visual landmark, with landmark jumps that provoke corrective turns | CC BY 4.0 | Figure source data, 526,695 bytes |

### FlyVis eyes

FlyVis (Lappalainen et al. 2024, [Nature 634:1132](https://doi.org/10.1038/s41586-024-07939-3), MIT) is a connectome-constrained network of 64 optic-lobe cell types, from photoreceptors to T4/T5 and the Tm/TmY layer: 45,669 neurons per eye on a hexagonal lattice of 721 columns, the same count as FlyGym's ommatidia. Its connectivity comes from the FIB-25 and FIB-19 medulla reconstructions, not FlyWire, and its unknown neuron and synapse parameters were trained on a motion-detection task. It sees luminance only. With the optional FlyVis install (`./scripts/setup.sh --with flyvis`, or `backend/requirements-vision.lock` then `scripts/fetch_flyvis.py` for the pretrained networks), **Sensor model → FlyVis eyes** puts it between the rendered eyes and the connectome circuits.

| Part | Status | What it is |
| --- | --- | --- |
| FlyVis network | Published model | The best-ranked of FlyVis's 50 pretrained networks (`flow/0000/000`), stepped every 10 ms; 0.5 s of adaptation to the starting scene |
| Eye images → FlyVis columns | Engineered | Each ommatidium's mean RGB luminance; FlyGym ommatidia matched to FlyVis columns by nearest centroid after an anchored affine fit (after FlyGym 1.x's RetinaMapper) |
| Eye orientation | Checked against biology | The right eye is mirrored onto FlyVis's layout, chosen so that T4a and T5a prefer front-to-back and T4c upward motion, as in flies (Maisak et al. 2013). Tested with bright moving edges for T4a/T4b and T4c/T4d in the right eye only; T5 (the OFF pathway) and the left eye's mapping are not tested |
| FlyVis → circuit | Data-derived wiring, engineered pooling and signs | Each cell type's strongest rectified response in each eye (above its grey steady state) drives each visual projection neuron in proportion to its FlyWire v783 synapses from that type and eye (`<circuit>.flyvis.json`, built by `build_circuit.py flyvis-bridge`). The bridge is **unsigned**: every FlyVis type counts as excitatory, including GABAergic (Mi4, C3) and glutamatergic (Mi9) ones, which the circuits' own sign rule would make inhibitory. Exports label it so; a signed bridge is future work |

The bridge maps 51 of FlyVis's 65 node types to FlyWire names (CT1's lobula compartment to CT1; Mi3, Mi11, Mi12, Tm28, Tm30, Tm5Y, TmY13 and the photoreceptors have no direct match or no synapses onto these neurons). It feeds 464 of the DNa02 circuit's 477 visual projection neurons and 641 of the steering circuit's 649; FlyVis types supply a median 12% and 15% of those neurons' input synapses. The steering circuit's strongest such inputs are T2a and T3, the small-object pathway into LC10 and LC11.

**What FlyVis sees.** With the target appearing 45° to one side, FlyVis's OFF-pathway types respond more in the eye that sees it (Tm9, Mi9 and Tm2 by up to 0.13, mirror-symmetric for the two sides, and still visible with the target 25 mm away). In closed loop with the fly held still, the target raises its side's mean drive to the circuit by 0.003–0.004, while the scene itself drives both sides at about 0.22 and already pushes the left side 0.027 harder than the right.

**Closed loop: FlyVis eyes do not steer these circuits toward the target.** Headless FlyGym, 3 seeds, 12 mm targets at the six bearings, 6 simulated seconds (`scripts/toolkit.py trials --engine flygym --set sensor_model=flyvis …`, saved in `runs/toolkit/eval-flyvis.json`):

| Circuit | Reached ≤2 mm | First turn toward lateral targets | Turning over the first 2 s, any target | Median final distance |
| --- | --- | --- | --- | --- |
| DNa02 circuit | 0/18 | 6/12 | +14 to +20 °/s (always left) | 33.5 mm |
| Steering circuit | 3/18 (the three targets 45° to the right) | 6/12 | −20 to −45 °/s (always right) | 24.5 mm |

Each circuit turns to its own side whatever the target does; a first turn goes toward the target only when the target happens to lie on that side. The target changes turning only slightly (steering circuit: −40 °/s with the target 45° to the right against −36 °/s with it 45° to the left, averaged over seeds). With FlyVis, the circuits' side biases decide the turn; with the geometric sensor, which reports nothing but the target's bearing and distance, the steering circuit reached 18/18 on the same body. FlyVis would need to tell the circuit where in the eye something is, through a retinotopic bridge (which columns each visual projection neuron sees) or object-selective visual projection neurons, to steer here; neither is modeled. These defaults were not changed to make FlyVis steer.

FlyVis runs at about the speed of real time on its own (10 ms of computing per 10 ms step for both eyes); with rendering and physics, FlyVis-eye runs take 0.11–0.15× real time. They replay exactly.

### A known quirk of the engineered model

With the target directly behind, the engineered model's left and right inputs are equal, so its steering units cancel. It turns only because each seed starts the fly with a small heading offset (±1.7° at most on the toy body). Starting 40 mm behind with the default seed 42 (offset +0.94°), the toy body first walks away (55 mm from the target after 2.5 s) and is still 15.1 mm away after 10 simulated seconds. Seeds with larger offsets get closer (0.4 and 1.7 mm for seeds 3 and 4), seed 1 (+0.04°) ends 91 mm away, and with no offset at all the fly never turns and ends 100 mm away.

### Limits and assumptions

- **Not a whole brain in the closed loop by default, and not validated.** The committed circuits hold 3,000 and 4,000 of FlyWire's roughly 140,000 neurons, chosen by synapse paths to their seeds. The whole brain can be built and run, slowly. Behavior was compared between models, not against flies.
- **Signs** come from per-neuron transmitter predictions. Glutamate is treated as inhibitory although it can excite; neuromodulators are left out by default; electrical synapses are absent.
- **Dynamics.** The rate model is one leaky-rate rule with a single gain, time constant and rectification. The spiking model uses Shiu et al.'s single set of constants for every neuron, with no adaptation, receptor kinetics or neuromodulation, and forward-Euler integration rather than Brian2's exact linear integration.
- **Input and output.** Every input neuron on a side gets the same value, whatever its visual feature (with FlyVis eyes, an unsigned drive through the bridge). Turning is an equal-weight sum over the readout types unless weights are set, and forward drive is a tonic term. The nerve cord and the body's other descending neurons are not modeled.
- **Sampling.** The cap keeps neurons by path strength, which can sample a cell type unevenly between the sides. `--balance-sides` keeps a type's two sides in pairs instead; that is another sampling assumption, not a correction (see [side-balanced circuits](#side-balanced-circuits)), and `scripts/toolkit.py robustness` shows which results depend on such choices.
- **Sides** follow FlyWire's annotations; FAFB is a single female brain, and individual flies differ.
- **The side biases** are properties of these models on this wiring; they are not known to describe flies.

### Citations

- Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain. *Nature* 634:124–138. [doi:10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y)
- Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of *Drosophila*. *Nature* 634:139–152. [doi:10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5)
- Eckstein N. et al. (2024) Neurotransmitter classification from electron microscopy images at synaptic sites in *Drosophila melanogaster*. *Cell* 187:2574–2594. [doi:10.1016/j.cell.2024.03.016](https://doi.org/10.1016/j.cell.2024.03.016)
- Shiu P.K. et al. (2024) A *Drosophila* computational brain model reveals sensorimotor processing. *Nature* 634:210–219. [doi:10.1038/s41586-024-07763-9](https://doi.org/10.1038/s41586-024-07763-9)
- Bates A.S., Phelps J.S., Kim M., Yang H.H. et al. (2025) Distributed control circuits across a brain-and-cord connectome. *bioRxiv*; the influence calculator is [github.com/DrugowitschLab/ConnectomeInfluenceCalculator](https://github.com/DrugowitschLab/ConnectomeInfluenceCalculator).
- Rayshubskiy A. et al. (2025) Neural circuit mechanisms for steering control in walking *Drosophila*. *eLife* 13:RP102230. [doi:10.7554/eLife.102230](https://doi.org/10.7554/eLife.102230)
- Bidaye S.S., Machacek C., Wu Y., Dickson B.J. (2014) Neuronal control of *Drosophila* walking direction. *Science* 344:97–101. [doi:10.1126/science.1249964](https://doi.org/10.1126/science.1249964)
- Bidaye S.S. et al. (2020) Two brain pathways initiate distinct forward walking programs in *Drosophila*. *Neuron* 108:469–485. [doi:10.1016/j.neuron.2020.07.032](https://doi.org/10.1016/j.neuron.2020.07.032)
- von Reyn C.R. et al. (2014) A spike-timing mechanism for action selection. *Nature Neuroscience* 17:962–970. [doi:10.1038/nn.3741](https://doi.org/10.1038/nn.3741)
- Hampel S., Franconville R., Simpson J.H., Seeds A.M. (2015) A neural command circuit for grooming movement control. *eLife* 4:e08758. [doi:10.7554/eLife.08758](https://doi.org/10.7554/eLife.08758)
- Buchanan S.M., Kain J.S., de Bivort B.L. (2015) Neuronal control of locomotor handedness in *Drosophila*. *PNAS* 112:6700–6705. [doi:10.1073/pnas.1500804112](https://doi.org/10.1073/pnas.1500804112)
- Lappalainen J.K. et al. (2024) Connectome-constrained networks predict neural activity across the fly visual system. *Nature* 634:1132–1140. [doi:10.1038/s41586-024-07939-3](https://doi.org/10.1038/s41586-024-07939-3)
- Maisak M.S. et al. (2013) A directional tuning map of *Drosophila* elementary motion detectors. *Nature* 500:212–216. [doi:10.1038/nature12320](https://doi.org/10.1038/nature12320)
- Mussells Pires P. et al. (2024) Converting an allocentric goal into an egocentric steering signal. *Nature* 626:808–818. [doi:10.1038/s41586-023-07006-3](https://doi.org/10.1038/s41586-023-07006-3)
- Zheng Z. et al. (2018) A complete electron microscopy volume of the brain of adult *Drosophila melanogaster*. *Cell* 174:730–743. [doi:10.1016/j.cell.2018.06.019](https://doi.org/10.1016/j.cell.2018.06.019)
- Lobato-Rios V. et al. (2022) NeuroMechFly, a neuromechanical model of adult *Drosophila melanogaster*. *Nature Methods* 19:620–627. [doi:10.1038/s41592-022-01466-7](https://doi.org/10.1038/s41592-022-01466-7)
- Wang-Chen S. et al. (2024) NeuroMechFly v2: simulating embodied sensorimotor control in adult *Drosophila*. *Nature Methods* 21:2353–2362. [doi:10.1038/s41592-024-02497-y](https://doi.org/10.1038/s41592-024-02497-y)

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

Comparison conditions are held for a whole trial, so comparison protocols accept scheduled stimulus changes only. Besides the v0.2 conditions, a comparison can switch the model for a trial (**Engineered model**, **Connectome model**) or, with the connectome model selected, silence the left, right or both DNa02 or one named cell type. Custom conditions (**Experiments → Compare conditions**, or `custom_conditions` in the API) add labelled conditions with their own interventions (any of the above, including per-side scaling and activation of cell types) and, with the connectome model, changes to its live-editable parameters; trial records carry the label as their condition. Conditions that need a particular model are rejected with the other one, and **Engineered model** is rejected with FlyVis eyes, which drive only the connectome model. Every trial's configuration is validated in full before the first trial starts, so a combination that could not be replayed fails up front. The same distinct seeds are applied to every selected condition. Initial interventions are serialized in each trial’s initial configuration. The worker blocks parameter/stimulus/reset commands while a comparison is active, preventing accidental changes to its controlled conditions; speed is allowed, since it only paces the run. Finished trials are exported before the next trial resets the body.

`GET /api/batches/COMPARISON_ID/summary` (or the run library's `batch` filter) gathers a comparison's saved trials. For each condition it gives the mean, the sample standard deviation and a 95% interval of final target distance, path length, net turn, mean speed and, for trials saved since v0.6, reaching within 2 mm; then, for every other condition, the mean difference from the first condition over trials with the same seed, with its interval. The statistics are the toolkit's (`toolkit.summarize`): percentile bootstrap intervals (2,000 resamples, generator seed 0) for means and differences, Wilson score intervals for the reached fraction, none below two trials. Only trials that ran their protocol to the end count, once per condition and seed: trials saved unfinished (cancelled, failed, or exported by hand during the comparison, which marks them partial) and repeats of a condition and seed are left out and counted (`partial_trials`, `duplicate_trials`). `?format=csv` gives the same as one table.

Limits: 5 seeds, 4 built-in conditions and 6 conditions in all with custom ones, 30,000 total control intervals. UI durations are 0.1–15 simulated seconds per trial. The API supports longer individual protocols within the existing 30,000-sample recording bound. Runs are CPU-limited; requested speed is a pacing ceiling, not a performance promise. `POST /api/batch/start` with `"max_speed": true` runs the trials unpaced, as fast as the computer allows; the results are the same, since speed never changes the computation.

Replay a saved directory:

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with the name of a run you exported locally. The running app does the same check in the background (`POST /api/runs/YOUR_RUN_FOLDER/replay`) and shows the verdict, with whether the software still matches the run's recorded versions and lockfiles, as the run's `verified` field (see the [usage guide](USAGE.md#saved-runs-and-replay)). Reference validation reproduced visual-input and timed target-reversal trials with maximum absolute error 0 at a tolerance of 1e-8. Compound-eye rendering and numerical behavior may differ on another graphics/software stack. Personal run records and raw evidence are excluded from the public repository.

## What remains before biological simulation claims

v0.3 added real connectivity with documented transmitter/sign assumptions; v0.4 added any circuit up to the whole brain, published spiking dynamics, a steering circuit that reaches targets and tools to analyze them; v0.5 added FlyVis eyes and a comparison with one recorded fly; v0.6 adds per-side manipulations of any cell type, an engineered motor path, side-balanced circuits and an analysis of which results survive changes to the modelling assumptions; v0.7 adds a [validation scorecard](#validation-scorecard) of published perturbation results, which the current models mostly pass only by construction or fail. The motor readout is still engineered (its delay and low-pass are not fitted), the side biases are only partly explained by the sampling effects above, FlyVis does not yet tell the circuits where a target is, and nothing has been fitted to fly data: one recording shows the model's turning following its DNa02 activity far faster, and its spiking DNa02 firing far more, than in the fly. The next scientific step is a **validated circuit**: dynamics fitted to recorded activity, a sensory encoding grounded in the visual projection neurons' measured responses, a descending-to-motor mapping that includes the other steering neurons, and predictions tested against measured fly behavior and neural data, including held-out interventions. A larger neuron count alone does not provide this validation.

The app does not simulate the nerve cord, sex-specific behavior, flight, feeding, learning, courtship or mating. The real body supports walking and turning under the upstream leg controller. A retinotopic FlyVis bridge, fits to more recordings, measured male biomechanics, odor sensing and multi-animal experiments remain future work.

The official MaleCNS download list gives about **1.1 GB** for the full wiring table, **12.7 GB** for synapse locations and **6.8 GB** for partner records. These optional datasets are outside the bundled sample's scope. The published resources linked from the atlas remain available for inspecting broader data externally; the app never downloads them automatically.
