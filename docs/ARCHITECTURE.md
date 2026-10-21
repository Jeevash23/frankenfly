# Architecture and scientific assumptions

## Closed loop

```text
Python world/body pose
        ↓
selected sensor encoder ← stimulus
  (geometric, rendered compound eye, or FlyVis eyes → FlyWire bridge)
        ↓                          ← sensory channel interventions
selected neural model              ← silencing (groups, or DNa02 / cell types)
  · engineered: six leaky rate units (default)
  · connectome: a FlyWire v783 circuit (committed or built locally),
    rate units or Shiu et al. 2024 spiking neurons
        ↓
left/right descending command
        ↓
upstream FlyGym hybrid turning controller (joint + adhesion targets)
        ↓
MuJoCo physics → updated body/world
```

The browser sends validated commands and plots Python samples. It never integrates neural or body dynamics. Its arena converts coordinates for drawing; that is a view transform, not a behavior model. Joint polylines use actual simulated segment positions. The toy body uses a fixed glyph without fabricated leg motion.

## Interfaces and units

- Body pose: world position `[x,y,z]` in **mm**, yaw in **radians**, speed in **mm/s**. Right-handed frame, `+z` upward, yaw counterclockwise from `+x`. The thorax's local `+x` determines forward heading.
- Sensor encoder: geometric pose/stimulus features or rendered eye pixels → dimensionless bilateral intensities in `[0,1]`, followed by input interventions. Raw intensities, geometric bearing and distance are retained as diagnostics. Neural and motor code receive no target coordinates.
- Neural circuit: declared two sensor values + silencing mask → dimensionless continuous rates (six for the engineered model; one per neuron for the connectome model, of which the readout pairs, the mean input per side, the circuit mean and an optional speed drive are recorded; spiking activity is firing rate ÷ the rate scale). No privileged target-coordinate shortcut reaches neural or motor code.
- Motor interface: engineered descending rates × 1.4, clipped to `[0,1.4]`, or for the connectome model `1.4 × clip([forward + turn, forward − turn], 0, 1)` with `turn = output gain × Σ (readout R − readout L)` over the readout cell types and `forward = tonic (+ speed gain × speed population)`, optionally weighted, delayed and low-passed (the [motor path](#connectome-motor-path) below) → upstream CPG amplitudes `[left legs, right legs]`. The explicit baseline returns `[1,1]` regardless of rates and is labeled as a bypass.
- Body adapter: descending command → 100 upstream controller/physics updates per control interval → finite body state. Controller proprioception uses FlyGym's supported `HybridControllerObservation.from_sim`.
- The target also appears as a non-colliding green landmark in the MuJoCo world. The optional vision adapter pools actual eye-camera pixels through the upstream retina and an engineered contrast encoder. See `RESEARCH.md` for exact rates, units and assumptions.

## Engineered equations

In geometric sensing mode, for target distance `d` and bearing `θ` relative to heading:

```text
I = target_intensity / (1 + (d / 20 mm)^2)
sL = clip(I × (0.5 + 0.5 cos(θ − π/4)), 0, 1)
sR = clip(I × (0.5 + 0.5 cos(θ + π/4)), 0, 1)
```

Input interventions zero `sL` or `sR` after retaining the raw readout for inspection/export. Generic unit order: sensory L/R, steering L/R, descending L/R.

```text
r(t+dt) = r(t) + dt/τ × [clip(W r(t) + B s(t) + b, 0, 1) − r(t)]
τ = [25, 25, 50, 50, 80, 80] ms
b = [0, 0, 0, 0, 0.35, 0.35]
```

`B` injects left/right signals into their sensory units. Steering uses a hand-chosen opponent difference (`±1.7`). Descending units receive sensory sum (`0.45` each) and opposing steering terms (`±0.85`). Exact matrices live in `backend/src/digitalfly/neural/model.py` and each export. They are not synapse counts or inferred biological weights. Silenced rates are clamped before and after every neural update and immediately at intervention boundaries.

The connectome model's equations, data and assumptions are in [RESEARCH.md](RESEARCH.md#the-connectome-model): `r += dt/τ × (clip(W r + input, 0, 1) − r)` with `W_ij = sign(j) × synapses(j→i) × global gain`, a CSR sparse matrix rebuilt only when parameters change.

### Connectome motor path

Everything between the readout and the legs is **engineered**. With `w_t` = `readout_weights[t]` (1 when not set), `K` readout types and neural step `k` (dt = 1 ms):

```text
turn_k = output_gain × P_t w_t × (mean_R(t) − mean_L(t))       P = Σ ("sum", default) or Σ/K ("mean")
c_k    = [forward_k + turn_k, forward_k − turn_k]                after the network update of step k
d_k    = c_{k−D},  D = round(motor_delay_ms / dt)                delay line; c_j = c_s for j < s, s = when the path came on
y_k    = y_{k−1} + (1 − exp(−dt / motor_tau_ms)) × (d_k − y_{k−1}),  y_s = c_s;  y_k = d_k when motor_tau_ms = 0
motor  = 1.4 × clip(y, 0, 1)                                     read at the end of each 10 ms control interval
```

With `motor_delay_ms = motor_tau_ms = 0` (the defaults) the path is off and `motor = 1.4 × clip(c, 0, 1)` is computed from the current activity, exactly as in v0.5. The path comes on at a reset or a live edit (`POST /api/connectome/parameters`), with the delay line and `y` full of the command at that moment; later edits keep both. A longer delay keeps the newest commands and repeats the oldest to fill the line (the output holds for the difference), a shorter one drops the oldest; switching the path off drops it. `turn()` and the recorded readouts stay instantaneous.

`motor_clipped_fraction` is an engineered diagnostic: the fraction of control intervals since the reset whose command `y` (or `c`) left `[0, 1]` on either side, counted once per interval on the command sent to the body (observations between steps and baseline intervals are not counted). `ConnectomeCircuit.description()` reports it, so exports carry it in `metadata.neural`.

The toy adapter uses speed `12 × mean(motor)` mm/s and yaw rate `4 × (right − left)` rad/s. It has no collision or leg physics. Seed initializes a small heading offset. The FlyGym model instead resolves MuJoCo contact, actuated joints and adhesion.

## Timing

| Stage | Deterministic interval |
| --- | --- |
| MuJoCo and upstream locomotion controller | 0.0001 s |
| Neural Euler update | 0.001 s |
| Bilateral input application / descending-command update | 0.01 s |
| Rendered-eye feature refresh, when selected | 0.05 s; stimulus edits invalidate the held reading |
| Step command | One 0.01 s control interval |
| Telemetry/rendering | Target approximately 10 Hz wall time, capacity-dependent |

Each control interval samples sensors, advances the neural model for ten substeps with those held observations, computes a motor pair, then advances physics 100 times with that held pair. Each physics step builds the controller observation and runs the hybrid turning controller through precomputed lookups (`ContactForces`, `fast_turning_controller` in `engines.py`); the arithmetic is FlyGym 2.1.0's, in the same order, and a FlyGym test keeps the body state bitwise identical to FlyGym's own code path (`FlyGymBody(upstream=True)`). CSV rows contain the sensor values actually used for that interval and the resulting body pose. They do not retrospectively replace the applied observation with a post-motion reading. While paused, moving a stimulus updates the instantaneous readout without advancing any dynamics.

FlyGym resets its neutral keyframe and seeded CPG, applies the upstream default leg posture, and performs a documented 50 ms body-only settling period. Application time is then set to zero. Reset restores the initial random-generator state, circuit, controller, recorder and clocks; the web Reset supplies the default target/intensity and clears interventions. The API Reset accepts an explicit initial RunConfig, including a custom starting stimulus.

## Ownership, memory, and failures

- One non-daemon Python thread creates, steps, renders and closes the body/context. The FastAPI event loop only handles messages and a shared snapshot.
- One queue, capacity **64**, serializes commands at control boundaries; cancelled pending commands are skipped. HTTP timeouts explicitly warn that an already executing command may finish.
- The thread outlives failures. A failing command answers its caller and the loop continues; a state that cannot be published puts the run into the error state instead of ending the thread. Should the thread still exit, every command returns 503 at once, asking for a restart, and `/api/health` reports `worker_alive: false`.
- The display snapshot is replaceable, with **201** decimated history samples, **600** recent path points, **50** recent displayed events, and one JPEG. Full joint geometry exists only in the current sample. Its `revision` increases only when something in it changes (the memory reading aside). It is rebuilt about 10 times a second while running; otherwise after each command and at most once a second.
- WebSocket clients have no accumulating application telemetry queues. Each revision is JSON-encoded once and the same text goes to every client, which receives only revisions it does not have. Slow sends time out after two seconds; server WebSocket input queues are bounded. Disconnect tasks are cancelled and subscribers decremented. Multiple clients do not create bodies.
- Recording retains all samples since reset, limited to **30,000** samples (about 300 simulated seconds), rather than evicting the replay prefix. When it fills, the run pauses with a `limit` event instead of entering the error state; a further Step or Run, like Step after a protocol's end, is refused (`RunLimit`, 409) and leaves the run valid. It exports normally, and Reset starts a new one. `Experiment(record=False)` keeps no samples, for programmatic trials of any length.
- The input schedule (manual stimulus, intervention and parameter events) is limited to **10,000** events; further manual changes are refused (409) before they are applied, so the schedule always replays. Protocol and bookkeeping events (reset, run, pause, step, speed, export, trial, error, limit) never count. A repeat of the same input or speed change within one control step replaces the previous event, since only its last value ever reaches the simulation.
- Exports (metadata schema 4) are written into a hidden `runs/.tmp-*` folder and renamed into place, ZIP first, only when complete; a failed export removes its partial files, and the run library lists only folders named like a run. `share_safe` exports omit `platform` and replace absolute paths and the host name in free text. `DELETE /api/runs/{key}` renames the folder to a hidden name before removing it. Run and connectivity listings are paged (`offset`, `limit`, `X-Total-Count`) and cached by each file's modification time.
- MuJoCo's OpenGL backend is chosen once per process, before MuJoCo is first imported, by rendering a tiny scene in a child process for each candidate (GLFW when a display exists, then EGL, then OSMesa); an explicit `MUJOCO_GL` is never changed. With none, the body runs without a renderer and vision sensors refuse to start, with the fixes in the message.
- Pydantic rejects unknown fields, nonfinite numbers, out-of-range seeds, target coordinates or speeds. Validation errors exclude raw nonfinite input so they serialize correctly. Checks that read circuit files are skipped while FastAPI parses a request on the event loop; the worker validates every configuration again, in full, and its errors return 422 in the same format.
- Reset builds the new circuit, and the body when the engine or sensor changes, before replacing anything. A configuration that cannot be built returns 409 and leaves the current run untouched; a failure after that leaves the new run in the error state. The configuration, circuit and body always belong together, and provenance describes the circuit actually loaded.
- The body checks finite positions/velocities, extreme velocity, and MuJoCo numerical warning counters (MuJoCo can otherwise auto-reset to finite values). A failure enters the explicit error state and refuses Run until Reset.
- Render failure preserves real physics and labels the pose view, with the rendering error exposed. Body failure preserves the error and never switches silently to toy mode.

## Local boundary

Default bind is `127.0.0.1`, one Uvicorn worker, no reload. Trusted hosts are localhost and 127.0.0.1. Browser command and WebSocket origins are restricted to the configured local server and local Vite port. Another bind address (`--host`, or `DIGITALFLY_HOST`, as the container image uses) is refused unless `DIGITALFLY_ALLOW_NETWORK_BIND=1` acknowledges that the API has no login; `DIGITALFLY_ALLOWED_ORIGINS` adds exact origins, whose host names become trusted hosts and WebSocket sources in the content security policy too. Neither changes the checks themselves ([INSTALL](INSTALL.md#listening-beyond-localhost)). Browser mutations require JSON (a DELETE may have no body; browsers always preflight a cross-origin DELETE); cross-origin controls are rejected. The OpenAPI schema is served at `/api/openapi.json`; there are no Swagger or ReDoc pages, which would need a CDN and inline scripts that the content security policy blocks. Same-origin static assets, fonts, API, JPEG and WebSocket are served in built mode. Unknown `/api/...` paths stay API errors and do not fall through to the SPA.

The v0.2 structural connectivity importer validates and saves bounded graphs through `data/research.py`. IDs remain strings, provenance is mandatory, and counts remain structural counts. The active neural circuit is independent of imported anatomy/connectivity. No synthetic fixture is represented as biological data.


## v0.2 research extensions

`RunConfig` includes sensor selection, bounded neural parameters, initial interventions and an optional finite protocol. A protocol applies events at integer control-step boundaries and automatically pauses at its end. Manual and protocol events carry distinct source labels for replay.

Comparisons reuse the same authoritative worker and body. Every trial's configuration is built and validated as a `RunConfig` before the first trial starts. Each seed/condition pair resets all simulation state, holds its intervention, executes the protocol, exports a result and then begins the next trial. Pause/resume, speed and cancellation are serialized through the command queue; `BatchRequest.max_speed` runs the trials unpaced. Manual experimental mutations are rejected while a comparison is active. Results retain the batch identifier, condition and seed. When a comparison completes, is cancelled or fails, an unfinished trial is saved with `trial.partial` set, and the worker resets to the configuration and interventions it had before the comparison.

`data/research.py` reads local saved-run metadata and bounded trajectory samples. The browser transforms those samples into display coordinates; scientific metrics remain in Python. `body_signals.jsonl` retains the measured joint/contact/CPG state. Large joint arrays are omitted from display history but remain in the current sample and the recording.

`data/atlas` is static anatomical context: twelve identified neurons and specimen-specific reference surfaces. `scripts/build_atlas.py` validates source hashes and produces display geometry. It neither simulates those neurons nor maps their coordinates into the fly body. Source coordinates and units are retained; camera transforms live in the browser.

The local launcher creates a Uvicorn Server instance and provides its own shutdown callback. `/api/shutdown` requires the current instance ID, JSON and the existing local-origin restrictions, then requests graceful Uvicorn exit. The lifespan closes the owning worker and graphics contexts. It does not signal arbitrary PIDs or other servers.

Complete methods, data licensing and limitations are in [RESEARCH.md](RESEARCH.md).


## v0.3 connectome model

`RunConfig.neural_model` selects `engineered` (default) or `connectome_dna02`; `connectome_parameters` holds the latter's global settings. Switching models resets the experiment. `neural/connectome.py` loads and validates the committed circuit once per process (`load_circuit`, cached by file and modification time) and implements the same interface as the engineered `RateCircuit`: `configure`, `reset`, `advance`, `apply_silencing`, `motor`, `readout`, `description`.

- **Interventions.** `silence` (engineered groups) and `silence_dna02` / `silence_types` (connectome) are each rejected with a 409 when the other model is active. Cell-type names are validated in the worker against the circuit the run has loaded, not the file of that name (422), and interventions replace the current ones only once they apply. Silenced neurons are clamped like the engineered units.
- **API.** `POST /api/connectome/parameters` records a `connectome_parameters` event; `GET /api/connectome/circuit` returns a cell-type view for the current parameters (types with counts, hop layer, transmitters and sides; type-to-type connections aggregated by sign; per-side DNa02 inputs). `/api/capabilities` lists both models and the circuit's hash and coverage.
- **State.** Samples record five readouts for the connectome model (DNa02 L/R, mean visual input L/R, circuit mean); the circuit mean makes replay sensitive to the whole hidden state. The snapshot adds a display-only `connectome` block at the 10 Hz publish rate: per-type mean rates, the turn command and the traces of the five most active types, from a 201-sample buffer aligned with `history`. Per-neuron rates never leave the worker.
- **Exports.** Schema 3. `metadata.neural` carries the circuit file, its SHA-256, the parameters, sign rules, input and output mapping and the data/assumed/engineered labels; telemetry rate columns follow the model's readout names. `replay.py` compares whichever rate columns a run recorded and re-applies connectome parameter events; it first checks the circuit file's SHA-256 against the recorded one and refuses a changed circuit unless given `--allow-circuit-mismatch`.
- **Comparisons.** Conditions add `engineered_model` and `connectome_model` (switch the model for that trial), `dna02_left_off`, `dna02_right_off`, `dna02_both_off` and `cell_type_off` (with `BatchRequest.cell_type`). Model-specific conditions are validated against the configuration's model.
- **Data.** `scripts/build_circuit.py` and its pyarrow dependency are build-only; the app reads only the committed 1.1 MB JSON and needs nothing beyond the runtime lock (SciPy was already installed with FlyGym and is now declared).

The connectome view in the browser lays cell types out by hop distance to DNa02 and laterality, never anatomy; it draws the 140 strongest type-to-type connections plus every connection of the selected type. The browser caches each circuit summary by circuit name, the SHA-256 of the loaded file (from the live snapshot) and the structural parameters (synapse threshold, sign of other transmitters, populations), never gains or time constants, and drops the cache when a build finishes. In the atlas, the two female DNa02 skeletons are tinted with the live readout, labeled as model output.

## v0.4 circuits, spiking dynamics and research tools

`neural_model` is now `connectome` (`connectome_dna02` is accepted as an alias). `ConnectomeParameters` adds `circuit` (a name), `dynamics` (`rate` or `spiking`), the `readout_types`, `input_types` and `speed_types` populations, `speed_gain` and the `spiking` settings. Circuit, dynamics and populations are fixed for a run: they decide which rates are recorded, so changing them through `/api/connectome/parameters` returns 409 and needs a Reset.

- **Circuits.** `connectome.circuit_path` resolves a name to `data/circuits/` first and `data/circuits/local/` second, accepting only plain files with names matching `[a-z0-9][a-z0-9._-]{0,63}`. `CircuitData` reads format 1 (v0.3) and format 2 (JSON, or an NPZ archive with a JSON header and `neuron_*`/`edge_*` arrays), validates array lengths, unique neuron IDs, every lookup index and edge endpoint (whole numbers in range) and synapse counts (finite, at least 1), raising a `ValueError` that names the field (a 422 from the API), and is cached by path and modification time. `list_circuits` reads only headers.
- **Spiking.** `SpikingState` keeps membrane potential, synaptic conductance, a refractory countdown and a ring buffer of 19 delayed-input slots for every neuron, with the weights as a CSC matrix so each spike adds its column to the slot due 1.8 ms later. Ten 0.1 ms substeps per neural step follow Brian2's schedule (update, threshold, delayed and Poisson input, reset). The random generator is seeded from the run seed, so spiking runs repeat and replay exactly. Updates use masked arithmetic rather than boolean indexing. The neural step's `dt` sets the number of substeps (it must be a multiple of 0.1 ms). A live parameter edit rebuilds only the weights and constants (`SpikingState.configure`) and keeps v, g, the refractory countdown, the delay queue, the rates, the step count and the random generator; only a reset, or a new circuit or input population, starts the network afresh.
- **Builds.** `data/builds.py` runs `scripts/build_circuit.py build` as one subprocess at a time, with arguments validated by `BuildRequest` and passed as a list (never a shell), in its own session; a reader thread keeps the last 200 log lines and parses the final JSON line as the result. Building needs the prepared archive in the ignored cache and no network; built-in names and the circuit the running experiment (or an active comparison) uses are refused with 409, and a circuit cannot be loaded while it is being built; the lifespan terminates a running build on shutdown. The builder writes every file to a hidden `.NAME.<pid>.part` next to it and renames it into place, and then deletes only the same name's other format, so a terminated build leaves the previous circuit intact.
- **API.** `GET /api/connectome/circuits` (list and active circuit), `GET /api/connectome/paths` (strongest cell-type paths, 1–6 hops), `GET /api/connectome/catalog` (the FlyWire cell-type catalog, 404 until prepared), `GET`/`POST /api/connectome/build`. `/api/connectome/circuit` is cached by parameters and the circuit's hash, includes each readout's sided inputs, and sends at most 1,500 cell types (those nearest the readout) with their circuit indices; while the connectome model runs, its `sha256` is that of the loaded circuit, and it returns 409 if the file has since been rebuilt (as do live parameter edits). `/api/capabilities` reports the active dynamics, the circuit summary, whether it is a whole-brain build and whether the builder is ready; its timesteps and limits are the code's own constants. `/api/health` reports the application version.
- **State and exports.** The live `connectome` block adds the circuit name and `circuit_sha256`, dynamics, unit names and readout types. Exports record the circuit name, file and hash, dynamics, populations, spiking constants and labels; rate columns follow the unit names. Replay handles both dynamics.
- **Toolkit.** `digitalfly/toolkit.py` builds trials from validated `RunConfig`s and runs them serially or in spawned processes, each worker keeping one `Experiment` per body engine and resetting it for every trial, so results do not depend on the worker count. A trial that raises returns an error row (and its worker drops that `Experiment`); results stream back through `as_completed` to an `on_result` callback, which the CLI uses to append JSONL/CSV rows, and are returned in input order. The parent sets the OpenMP/MKL/OpenBLAS thread variables before spawning workers (`thread_limit`), for trials and `ablation_scan` alike. `config_hash`, `summarize` (Wilson and seeded bootstrap intervals, matched-seed paired differences) and `provenance` support resuming and reporting. Open-loop analyses (`hold`, `bias_curve`, `ablation_scan`) drive a `ConnectomeCircuit` directly. `digitalfly/compare.py` resamples recordings and runs to 10 ms bins and fits turning to the readout difference. `scripts/toolkit.py` is the command line for both; outputs go to the ignored `runs/toolkit/`.
- **Interface.** The Workbench adds circuit and dynamics selectors; the live circuit view is keyed by circuit type index, draws every readout pair, traces paths and edits populations; **Build a circuit** drives the build endpoints.

## v0.5 FlyVis eyes and recorded flies

- **FlyVis eyes.** `vision/flyvis_eyes.py` wraps one FlyVis network (batch of two eyes) built from its config and weights-only checkpoint. Sensor model `flyvis` makes `FlyGymBody` render the eyes every five control intervals, convert them to per-ommatidium luminance, and step FlyVis by 10 ms after every control interval with the latest frame; on the first observation after a reset it adapts for 0.5 s to the scene. `Experiment.sense()` passes the pooled responses (eyes × 65 types, with sensor silencing applied per eye) to `ConnectomeCircuit.set_visual`, which multiplies them by the circuit's bridge (a sparse neurons × 130 matrix) to give each input neuron its own drive in place of the side's sensor value, in rate and spiking dynamics. The bridge is unsigned (every FlyVis type drives as if excitatory) and labeled engineered in `description()`, whose `input_mapping` then describes the bridge instead of the sensor values; `check_flyvis_inputs` refuses (`ValueError`, in `set_visual` and in `configure` while FlyVis drives) an input population that the bridge does not reach on both sides. Samples record the mean drive per side as the sensor values. FlyVis is imported lazily; without it the app works and the option is unavailable.
- **Bridges.** `<circuit>.flyvis.json`, next to its circuit, holds FlyWire v783 synapse fractions from FlyVis-modelled types onto the circuit's visual projection neurons, by eye, and the circuit's hash; `load_bridge` refuses a bridge built for another version of the circuit. Bridge files never appear as circuits. `RunConfig` rejects FlyVis eyes (422) when the bridge reaches none of the input neurons on a side, for example with non-visual `input_types`, which would otherwise leave the circuit silently without input.
- **Recorded flies.** `compare.rayshubskiy_recording` converts the Rayshubskiy et al. dual recordings (spike detection, firing rates, yaw calibration and an explicit yaw-sign setting) and by default marks samples during and 0.5 s after the optogenetic stimulus as not valid; `Recording.valid` keeps those samples out of `fit_turning` and `compare.fit_filter` (a cross-validated linear filter); `toolkit.jumping_target_run` (CLI `jump`) records comparison runs. `scripts/fetch_recording.py` and `scripts/fetch_flyvis.py` download into the ignored cache and verify hashes.
