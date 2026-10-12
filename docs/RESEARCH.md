# DigitalFly research workspace — v0.3

This is an experimental sensorimotor workbench with explicit modeling assumptions. Its tests establish computational behavior and repeatability, not biological validity. See the [setup instructions](../README.md#quick-start) and [validation summary](../STATUS.md).

## What is now possible

| Area | Implemented | Scope |
| --- | --- | --- |
| Embodied experiment | Actual FlyGym 2.1 / MuJoCo body, joints, contact and adhesion | Female-derived morphology; engineered walking/turning controller |
| Vision | Two actual rendered eye images, upstream fisheye correction and 721 ommatidia per eye | Engineered green-contrast feature encoder; no learned visual network |
| Neural models | The engineered six-unit graph (default), or a connectome-constrained rate model of 3,000 FlyWire v783 neurons around the DNa02 steering neurons; live rates, parameters, silencing and a circuit view for both | Engineered model: explicit rate units, not identified neurons. Connectome model: data-derived wiring, assumed signs, engineered dynamics and input/output mapping; not a whole brain, not biologically validated |
| Anatomy | Rotatable male/female surfaces and twelve published neuron skeletons | Structural anatomy, separate from dynamics |
| Connectivity | The built-in DNa02 subcircuit drives the connectome model. Separately, import, validate, save, search and inspect a small directed graph | Imports: up to 300 neurons / 3,000 edges / 2 MB; imports never drive the body |
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

**Set up the first experiment** on the Experiments page fills in steps 4 and 5 in one click: target reversal over 2 simulated seconds, seeds 42 and 43, and **Neural control** against **Descending units off** (or **Both DNa02 off** with the connectome model). It keeps the current body and sensor, so switch to compound eyes on the Workbench first if you want step 2 as well.

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

## The connectome model

The **connectome_dna02** model steers the fly with a rate model built on real wiring: both DNa02 descending neurons, which predict and influence steering in walking flies, and their presynaptic partners up to two hops back, from the FlyWire reconstruction of one adult female brain (FAFB v783). The engineered six-unit model stays the default and is unchanged. Select the connectome model with **Workbench → Neural model**.

This is a connectome-constrained model, not an uploaded fly brain. It is not biologically validated.

| Part | Status | What it is |
| --- | --- | --- |
| Which neurons, cell types, sides, predicted transmitters, synapse counts | **Data-derived** | FlyWire FAFB v783, through the files below |
| Sign of each connection | **Assumed** | From the presynaptic neuron's predicted transmitter |
| Leaky-rate dynamics, gains, time constant | **Engineered** | One global value each; nothing per neuron or per synapse |
| Sensor → neuron input | **Engineered** | Each sensor drives every visual projection neuron on its side |
| DNa02 → body output | **Engineered**, direction from literature | Turn from the right − left DNa02 difference; constant forward drive |

### Data sources

Both sources are FlyWire v783, the release whose neurons the atlas already shows, from a female fly like the simulated body. Raw downloads stay in the ignored `.cache/circuits/`; `data/circuits/downloads.json` records each one.

| File | Content | Release and provider | Downloaded | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| `fafb_783_meta.feather` ([URL](https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/fafb_783/fafb_783_meta.feather)) | Cell type, super class, side and predicted transmitter for 144,837 neurons | FAFB v783 harmonized metadata, Bates/Lee lab [compilation](https://github.com/sjcabs/fly_connectome_data_tutorial) (GCS generation 1787944265562460) | Whole file, 13,539,866 bytes | `5e248762…` | CC BY-NC 4.0 (FlyWire); compilation code MIT |
| `Connectivity_783.parquet` ([URL](https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/61555bc764aebab90e37a56fa1f312269fa4dde1/Connectivity_783.parquet)) | Synapse counts for all 15,091,983 connected pairs | v783 table shipped with [Shiu et al. 2024](https://github.com/philshiu/Drosophila_brain_model), commit `61555bc`, git blob `d386555d…`, 100,804,642 bytes | Footer and 4 columns by HTTP range requests, 47,365,136 bytes | `95bbc483…` (of the downloaded ranges) | CC BY-NC 4.0 (FlyWire); repository code MIT |

Only the needed columns (presynaptic ID, postsynaptic ID, synapse count, and Shiu et al.'s own sign, kept for comparison) were fetched, so the second hash covers the downloaded byte ranges rather than the whole file; the pinned commit and git blob hash identify the whole upstream file. Full hashes are in `downloads.json`. FlyWire Codex bulk downloads were not used: they require signing in.

FlyWire data is licensed **CC BY-NC 4.0, for non-commercial use only**. Credit the FlyWire Consortium and cite Dorkenwald et al. 2024 and Schlegel et al. 2024 (reconstruction and annotation), Eckstein et al. 2024 (transmitter predictions) and Shiu et al. 2024 (connectivity table). See [data/circuits/LICENSE.md](../data/circuits/LICENSE.md).

### Building the subcircuit

```sh
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock   # pyarrow, build only
backend/.venv/bin/python scripts/build_circuit.py            # add --offline to rebuild from the cache
```

1. **Seeds.** The two DNa02 neurons from the atlas: `720575940629327659` is the **left** one and `720575940604737708` the **right** one, by FlyWire's side annotation in the v783 metadata. Their somata lie on opposite sides of the midline (root-node x of 406 and 654 µm in the atlas skeletons).
2. **Partners.** Hop 1 is every neuron with at least **5 synapses** onto either DNa02; hop 2 is every neuron with at least 5 synapses onto a hop-1 neuron. That gives 685 direct partners and 14,468 hop-2 candidates.
3. **Cap.** At most **3,000 neurons**. Both DNa02 and all hop-1 partners are always kept. The cap binds at hop 2, which keeps the 2,313 neurons with the strongest path to a DNa02; a path's strength multiplies the input fraction of each connection on it (synapses on the connection ÷ all synapses onto the postsynaptic neuron). The weakest kept path strength is 4.63 × 10⁻⁵. The 12,155 dropped neurons are 6,037 central-brain intrinsic, 2,753 optic-lobe intrinsic, 2,057 visual projection, 605 ascending, 460 descending and 243 others; their top types are listed in the file.
4. **Connections.** Every pair of kept neurons connected by at least 5 synapses (the induced subgraph), including lateral and feedback connections.

The result, `data/circuits/fafb783-dna02.json` (1.1 MB), has **3,000 neurons, 78,615 connections, 1,818,869 synapses and 1,257 cell types**. It records its sources, release, hashes, threshold, hops, cap report, counts, license and attribution. An offline rebuild reproduces it byte for byte. The direct inputs match the published circuit: same-side cholinergic DNa03, PFL3 neurons from the central complex, and strong inhibitory PS049 and VES051/052 inputs.

### Signs

| Predicted transmitter | Neurons | Sign |
| --- | --- | --- |
| Acetylcholine | 1,882 | +1, excitatory |
| GABA | 544 | −1, inhibitory |
| Glutamate | 557 | −1, inhibitory |
| Dopamine, serotonin, octopamine, unknown | 8, 3, 5, 1 | **Excluded** by default |

Signs follow Shiu et al. 2024 for acetylcholine, GABA and glutamate. Shiu et al. treat dopamine, serotonin and octopamine as excitatory; here those connections are left out by default, because a fast excitatory synapse is a poor description of neuromodulation. That is an explicit, switchable assumption: **Dopamine, serotonin, octopamine, unknown → Excitatory** restores Shiu et al.'s rule. At default settings 906 of the 78,615 connections are excluded this way. The metadata's per-neuron transmitter agrees with Shiu et al.'s own sign for 2,989 of the 2,999 neurons both describe.

### Dynamics

Every neuron is a leaky rate unit, updated by Euler steps every 1 ms (the existing neural step) with a sparse weight matrix:

```text
r_i ← r_i + dt/τ × [clip(Σ_j W_ij r_j + input_i, 0, 1) − r_i]
W_ij = sign(j) × synapses(j → i) × global gain
```

with τ = 20 ms and rates in [0, 1]. Silenced neurons are clamped to zero before and after every update. There is no spiking, no synaptic delay, no adaptation and no per-neuron parameter.

### Input mapping

Each side's sensor value (geometric or compound-eye) × the input gain is added to the drive of every **visual projection neuron** (FlyWire super class `visual_projection`) on the same side: **250 left and 227 right**. Twenty-nine of them connect to DNa02 directly (31 connections); 448 sit two hops back. The most common types are LC10a, LC10c and LC10d, LT51, LC36, LPLC4 and LC33. This mapping is engineered: these cell types encode different visual features, and here they all receive the same scalar. No cell identities were invented.

### Output mapping

```text
turn = output gain × (DNa02 R − DNa02 L)
motor = 1.4 × clip([tonic drive + turn, tonic drive − turn], 0, 1)    # [left legs, right legs]
```

- **Direction of DNa02 steering.** Rayshubskiy et al. 2025 ([eLife 13:RP102230](https://doi.org/10.7554/eLife.102230)) found the fly's rotational velocity linearly related to the right − left difference in DNa02 firing, a burst in the left DNa02 before a leftward turn, and ipsiversive rotation when one DNa02 is excited. So a more active right DNa02 means a right turn.
- **Which amplitude turns which way.** FlyGym 2.1.0's `HybridTurningController.step` sets the first three CPG amplitudes (legs LF, LM, LH) from `descending_signal[0]` and the last three (RF, RM, RH) from `descending_signal[1]`. A larger left amplitude turns the body right: `[1.2, 0.4]` turns the FlyGym body 146° clockwise in 1 s, and the toy body turns the same way.
- **Forward drive** is the existing tonic term, constant in this model (the engineered model also adds sensory drive).

### Parameters and how the defaults were chosen

Only global parameters exist: synapse threshold (5–100, applied on top of the build threshold), global gain, input gain, output gain, tonic drive, τ, and the transmitter switch. Edit them in **Neural atlas → Live circuit**; changes are recorded and replayed.

| Parameter | Default | Choice |
| --- | --- | --- |
| Global gain | 0.001 | The largest round value that keeps both DNa02 below half saturation for any constant input in [0, 1] on both sides (peak 0.45; 0.0012 reaches 0.63). Chosen before any behavior was measured |
| Input gain | 1 | Sensor values used as they are |
| Output gain | 1 | The turn command equals the DNa02 rate difference |
| Tonic drive, τ, threshold | 0.35, 20 ms, 5 synapses | The engineered model's tonic drive, a 20 ms time constant and the build threshold |

### What the circuit computes

With the target held still, steady-state DNa02 activity after 0.6 s (geometric sensor, target 12 mm away, default parameters):

| Target | DNa02 R − L | Turn command means |
| --- | --- | --- |
| 45° left | −0.238 | Left, toward |
| 90° left | −0.262 | Left, toward |
| Ahead | −0.178 | Left |
| 45° right | −0.056 | Left, away |
| 90° right | +0.060 | Right, toward |

Compared with a target straight ahead, moving it to either side shifts activity toward the DNa02 on that side, as Rayshubskiy et al. describe for attractive stimuli. In a linear count of signed synapses, that comes from two-step pathways; the 31 direct connections from visual projection neurons favor the opposite DNa02. But the circuit is **strongly biased to the left**: equal input on both sides already commands a left turn (−0.18 for a target straight ahead), so a target must be about 90° to the right before the circuit turns right. The circuit's composition is close to balanced (329 left and 353 right hop-1 neurons; 1,163 and 1,146 at hop 2), so the bias emerges from the recurrent, rectified dynamics on this wiring. No global parameter removes it: τ leaves steady states unchanged, a 10- or 20-synapse threshold weakens every response without removing the bias, the transmitter switch changes nothing measurable, and a larger input gain makes the bias stronger. Possible causes include reconstruction or annotation asymmetries, the uniform-gain rate assumption, the sign assumptions, treating all visual projection types alike and the 3,000-neuron cap. This model cannot tell them apart.

### Evaluation

`scripts/evaluate_models.py` runs both models from the default configuration with matched seeds, changing only the target, seed, model and silencing. Targets sit ahead, 45° and 90° to each side and directly behind the starting heading, at 12 and 30 mm. A target counts as reached within 2 mm; the first turn is the direction of the first 10° heading change. All numbers below come from the reports the script saved (`docs/evidence/evaluation-*.json`, kept locally).

**Toy body**, 5 seeds (1–5), 10 simulated seconds per trial:

| Target | Distance | Engineered: reached (median time) | Engineered: first turn toward | Engineered: final distance (mm) | Connectome: reached | Connectome: first turn toward | Connectome: final distance (mm) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ahead | 12 mm | 5/5 (0.7 s) | mixed | 1.4 | 0/5 | left | 7.5 |
| Ahead | 30 mm | 5/5 (2.2 s) | mixed | 1.6 | 0/5 | left | 10.3 |
| 45° left | 12 mm | 5/5 (0.8 s) | 5/5 | 1.6 | 0/5 | 5/5 | 7.5 |
| 45° left | 30 mm | 5/5 (2.3 s) | 5/5 | 1.8 | 0/5 | 5/5 | 9.4 |
| 45° right | 12 mm | 5/5 (0.8 s) | 5/5 | 1.6 | 0/5 | 5/5 | 7.5 |
| 45° right | 30 mm | 5/5 (2.3 s) | 5/5 | 1.8 | 0/5 | 5/5 | 12.7 |
| 90° left | 12 mm | 5/5 (1.0 s) | 5/5 | 1.3 | 0/5 | 5/5 | 7.5 |
| 90° left | 30 mm | 5/5 (2.5 s) | 5/5 | 1.2 | 0/5 | 5/5 | 9.5 |
| 90° right | 12 mm | 5/5 (1.0 s) | 5/5 | 1.3 | 0/5 | 5/5 | 7.6 |
| 90° right | 30 mm | 5/5 (2.5 s) | 5/5 | 1.2 | 0/5 | 5/5 | 20.1 |
| Behind | 12 mm | 5/5 (2.7 s) | mixed | 1.9 | 0/5 | left | 7.6 |
| Behind | 30 mm | 4/5 (6.6 s) | mixed | 21.2 | 0/5 | left | 28.2 |

**Headless FlyGym body**, 3 seeds (1–3), 12 mm targets, 6 simulated seconds per trial:

| Target | Distance | Engineered: reached (median time) | Engineered: first turn toward | Engineered: final distance (mm) | Connectome: reached | Connectome: first turn toward | Connectome: final distance (mm) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ahead | 12 mm | 3/3 (0.7 s) | right | 4.1 | 0/3 | left | 10.5 |
| 45° left | 12 mm | 3/3 (0.8 s) | 3/3 | 1.3 | 0/3 | 3/3 | 11.0 |
| 45° right | 12 mm | 3/3 (0.8 s) | 3/3 | 1.4 | 0/3 | 3/3 | 10.5 |
| 90° left | 12 mm | 3/3 (1.1 s) | 3/3 | 2.2 | 0/3 | 3/3 | 10.8 |
| 90° right | 12 mm | 3/3 (1.0 s) | 3/3 | 1.9 | 0/3 | 3/3 | 11.9 |
| Behind | 12 mm | 3/3 (2.8 s) | right | 3.9 | 0/3 | left | 17.5 |

The real body tells the same story. It walks faster than the toy body at the same drive (8.7 against 5.9 mm/s with the connectome model), so its circles are wider. The engineered model's final distances include walking past the target after reaching it.

**What this shows.** The engineered model reaches almost every target. The connectome model's first turn goes toward every lateral target, but it never comes within 2 mm. It settles into a clockwise orbit around the target, holding it at 90° to its right: in a 12 mm toy trial the orbit radius is 7.5 mm from any starting bearing, and the DNa02 difference there (R − L ≈ +0.07) gives exactly the turn rate that circle needs at the constant tonic forward speed. Its weak response to targets on the right cannot turn it more sharply. The output gain sets the orbit's size, not its shape: in the same toy trials, gains of 2, 4 and 8 shrink the radius to 4.4, 2.3 and 1.5 mm, so a gain of 8 would satisfy the 2 mm criterion while the fly still circles. The defaults were not changed to pass this test.

**Silencing DNa02** (connectome model, toy body, targets 45° and 90° to each side at 12 mm, 5 seeds; positive yaw rate turns left):

| DNa02 silenced | Mean yaw rate, first 2 s: left targets | right targets | Net turn over the trial: left targets | right targets | Reached ≤2 mm | Mean final distance (mm) |
| --- | --- | --- | --- | --- | --- | --- |
| None (intact) | +55 °/s | −23 °/s | −267° | −375° | 0/20 | 7.5 |
| Left | −16 °/s | −74 °/s | −70° | −237° | 0/20 | 55.6 |
| Right | +100 °/s | +37 °/s | +577° | +419° | 0/20 | 41.5 |
| Both | 0 °/s | 0 °/s | 0° | 0° | 0/20 | 55.5 |

On the headless FlyGym body (3 seeds, 6 simulated seconds):

| DNa02 silenced | Mean yaw rate, first 2 s: left targets | right targets | Net turn over the trial: left targets | right targets | Reached ≤2 mm | Mean final distance (mm) |
| --- | --- | --- | --- | --- | --- | --- |
| None (intact) | +57 °/s | −23 °/s | −72° | −195° | 0/12 | 11.0 |
| Left | −7 °/s | −69 °/s | −3° | −139° | 0/12 | 36.5 |
| Right | +97 °/s | +29 °/s | +249° | +61° | 0/12 | 43.3 |
| Both | −0.4 °/s | −0.4 °/s | 0° | 0° | 0/12 | 38.9 |

With both DNa02 silenced, the FlyGym body's turn command is exactly zero; the remaining −0.4 °/s is a drift of the walking gait itself.

Silencing one DNa02 makes the model turn toward the intact side whatever the target does, and silencing both removes all turning, because the readout depends only on these two neurons. Flies differ: Rayshubskiy et al. found that inhibiting DNa02 on both sides left rotational speed unchanged, because other descending neurons such as DNa01 also steer. That is a limit of this model, not a prediction.

### A known quirk of the engineered model

With the target directly behind, the engineered model's left and right inputs are equal, so its steering units cancel. It turns only because each seed starts the fly with a small heading offset (±1.7° at most on the toy body). Starting 40 mm behind with the default seed 42 (offset +0.94°), the toy body first walks away (55 mm from the target after 2.5 s) and is still 15.1 mm away after 10 simulated seconds. Seeds with larger offsets get closer (0.4 and 1.7 mm for seeds 3 and 4), seed 1 (+0.04°) ends 91 mm away, and with no offset at all the fly never turns and ends 100 mm away.

### Limits and assumptions

- **Not a whole brain and not validated.** 3,000 of FlyWire's roughly 140,000 neurons, chosen by synapse paths to DNa02, with 12,155 weaker hop-2 partners dropped by the cap. Behavior was compared between models, not against flies.
- **Signs** come from per-neuron transmitter predictions. Glutamate is treated as inhibitory although it can excite; neuromodulators are left out by default; electrical synapses are absent.
- **Dynamics** are one leaky-rate rule with a single gain, time constant and rectification for every neuron. There are no spikes, delays, adaptation, receptor kinetics or neuromodulation.
- **Input**: every visual projection neuron on a side gets the same scalar, whatever its visual feature. **Output**: only DNa02 steers, and forward drive is a constant. The body's other descending neurons and the nerve cord are not modeled.
- **Sides** follow FlyWire's annotations; FAFB is a single female brain, and individual flies differ.
- **The left bias** is a property of this model on this wiring; it is not known to describe flies.

### Citations

- Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain. *Nature* 634:124–138. [doi:10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y)
- Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of *Drosophila*. *Nature* 634:139–152. [doi:10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5)
- Eckstein N. et al. (2024) Neurotransmitter classification from electron microscopy images at synaptic sites in *Drosophila melanogaster*. *Cell* 187:2574–2594. [doi:10.1016/j.cell.2024.03.016](https://doi.org/10.1016/j.cell.2024.03.016)
- Shiu P.K. et al. (2024) A *Drosophila* computational brain model reveals sensorimotor processing. *Nature* 634:210–219. [doi:10.1038/s41586-024-07763-9](https://doi.org/10.1038/s41586-024-07763-9)
- Rayshubskiy A. et al. (2025) Neural circuit mechanisms for steering control in walking *Drosophila*. *eLife* 13:RP102230. [doi:10.7554/eLife.102230](https://doi.org/10.7554/eLife.102230)
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

Comparison conditions are held for a whole trial, so comparison protocols accept scheduled stimulus changes only. Besides the v0.2 conditions, a comparison can switch the model for a trial (**Engineered model**, **Connectome model**) or, with the connectome model selected, silence the left, right or both DNa02 or one named cell type. Conditions that need a particular model are rejected with the other one. The same distinct seeds are applied to every selected condition. Initial interventions are serialized in each trial’s initial configuration. The worker blocks parameter/stimulus/reset commands while a comparison is active, preventing accidental changes to its controlled conditions. Finished trials are exported before the next trial resets the body.

Limits: 5 seeds, 4 conditions, 30,000 total control intervals. UI durations are 0.1–15 simulated seconds per trial. The API supports longer individual protocols within the existing 30,000-sample recording bound. Runs are CPU-limited; requested speed is a pacing ceiling, not a performance promise.

Replay a saved directory:

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with the name of a run you exported locally. Reference validation reproduced visual-input and timed target-reversal trials with maximum absolute error 0 at a tolerance of 1e-8. Vision rendering and numerical behavior may differ on another graphics/software stack. Personal run records and raw evidence are excluded from the public repository.

## What remains before biological simulation claims

v0.3 adds real connectivity with documented transmitter/sign assumptions, but its dynamics, sensory encoding and motor mapping are engineered, and it steers with a strong left bias. The next scientific step is a **validated circuit**: dynamics fitted to recorded activity, a sensory encoding grounded in the visual projection neurons' measured responses, a descending-to-motor mapping that includes the other steering neurons, and predictions tested against measured fly behavior and neural data, including held-out interventions. A larger neuron count alone does not provide this validation.

The app currently does not simulate a whole CNS, spiking physiology, sex-specific behavior, flight, feeding, learning, courtship or mating. The real body supports walking and turning under the upstream leg controller. Whole-connectome ingestion, FlyVis integration, measured male biomechanics, odor sensing and multi-animal experiments remain future work.

The official MaleCNS download list gives about **1.1 GB** for the full wiring table, **12.7 GB** for synapse locations and **6.8 GB** for partner records. These optional datasets are outside the bundled sample's scope. The published resources linked from the atlas remain available for inspecting broader data externally; the app never downloads them automatically.
