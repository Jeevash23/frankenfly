# Using DigitalFly

## Starting and stopping

```sh
./scripts/start.sh --open                      # geometric sensing, opens your browser
./scripts/start.sh --vision --open             # rendered compound-eye input
./scripts/start.sh --no-render                 # real physics without the 3D camera
./scripts/start.sh --toy                       # kinematic toy demo, no physics
./scripts/start.sh --port 8001                 # use another port
./scripts/start.sh --config steering-circuit       # start from a preset (see below) or a configuration file
```

Installing, Docker, the dev container, headless servers and updating after `git pull` are covered in [INSTALL](INSTALL.md).

The app opens paused at http://127.0.0.1:8000. The server listens on this computer only; containers need the explicit option described in [Listening beyond localhost](INSTALL.md#listening-beyond-localhost). To stop the server, click **Quit** in the upper-right corner, optionally saving the current run first, or press **Control+C** in the terminal that started it. Closing the browser tab or pressing Pause does not stop the server.

Extra browser tabs on the same computer share one simulation: Run, Reset, interventions and Quit affect all of them. A copy of the project on another computer runs independently, with its own saved runs.

When the server starts, it removes what an interrupted export, run deletion, replay check or circuit build left behind more than an hour earlier (hidden `runs/.tmp-*`, `runs/.deleting-*` and `.part` files), and names them in the terminal.

### Presets

A preset is a named run configuration. `--config` takes a preset name or the path of a configuration file. These ship with DigitalFly, in `configs/`:

| Preset | Starts |
| --- | --- |
| `default` | The default configuration: FlyGym body, engineered six-unit model, geometric sensing |
| `steering-circuit` | The connectome model on the 4,000-neuron steering circuit, rate dynamics |
| `spiking-dna02` | The DNa02 circuit with spiking neurons |
| `flyvis-eyes` | FlyVis eyes driving the DNa02 circuit; needs the optional FlyVis install and OpenGL |
| `first-experiment` | The engineered model with the 2 s target-reversal protocol of the research guide's first experiment |

On the Workbench, **Presets** lists them: choose one and press **Load preset** to start a fresh run with its configuration (if the current run has advanced, the app asks first, since an unexported run is lost). Presets this computer cannot run are listed but disabled, and **N presets unavailable here** says why. **Save current settings as preset** saves the configuration with the interventions in force now (with a protocol loaded, its starting interventions) under a name you choose, with an optional description; the name is checked as you type. A preset saved on this computer shows **(saved here)** and can be deleted with the bin button next to **Load preset**. When `configs/local/` cannot be written (`presets.writable` is false in `GET /api/capabilities`, for example in a container without a volume there), saving is disabled and the panel says why; shipped presets still load.

Presets you save, in the app or through the API, go to `configs/local/`, which git ignores:

```sh
curl http://127.0.0.1:8000/api/configs                       # every preset, with a description
curl http://127.0.0.1:8000/api/configs/steering-circuit      # one preset's configuration
curl -X POST -H 'Content-Type: application/json' http://127.0.0.1:8000/api/configs \
     -d '{"name": "my-setup", "description": "Steering circuit, seed 7", "config": {"seed": 7, "neural_model": "connectome", "connectome_parameters": {"circuit": "fafb783-steering"}}}'
curl -X DELETE http://127.0.0.1:8000/api/configs/my-setup
```

Names use lowercase letters, digits, `-` and `_` (up to 48 characters); a preset file may be at most 1 MB, as may a configuration sent to `POST /api/reset` or `/api/batch/start`, which holds the largest valid one. Saving checks the configuration in full, circuit included, and replaces a local preset of the same name; the shipped presets cannot be replaced or deleted. Every preset is checked again whenever it is listed or read: one this computer cannot run (FlyVis not installed, a circuit that is not there) is listed with `"available": false` and the reason, and a damaged file is listed with an `error`, never hiding the others. A preset file holds `{"description": "...", "config": {...}}`; a plain configuration file, such as `configs/default.json` or an export's `initial_config` saved on its own, works too.

## Controls

| Control | What it changes |
| --- | --- |
| Run / Pause, or Space | Starts or freezes the Python simulation |
| Step | Advances exactly **10 ms** of simulation while paused |
| Reset | Restores the body, controller, neural state, seed, target `(12, 8)` mm at intensity 1, interventions, clock, history and recording. Keeps the selected parameters and any loaded protocol |
| Remove protocol (free run) | On the protocol banner: starts a fresh run without the loaded protocol, so it runs until you pause it |
| Seed | Applied on the next Reset; makes the walking-rhythm initialization repeatable |
| Speed | Requests 0.05–2× simulated time per wall time; your hardware may run slower |
| Specimen | Live 640×288 MuJoCo rendering; the camera follows the body |
| Arena | Labeled top-down map from the simulated body poses; click to place the target, or focus the map (Tab) and use the arrow keys to move it 1 mm (5 mm with Shift) |
| Target X/Y, intensity | Moves the stimulus and its rendered landmark; press Enter or leave the field to apply coordinates. Dragging the intensity slider updates the target a few times a second and once more on release |
| Sensor model | Geometric bearing, rendered compound eyes, or FlyVis eyes (the optional optic-lobe network; needs FlyGym, the connectome model and a circuit with a FlyVis bridge); switching starts a fresh experiment |
| Neural model | The engineered six-unit loop (default) or the connectome circuit; switching starts a fresh experiment. FlyVis eyes drive only the connectome model, so switching to the engineered loop with them selected also switches to rendered compound eyes, with a note |
| Circuit, Dynamics | With the connectome model: which FlyWire circuit (committed or built on this computer) and whether its neurons are rate units or spiking neurons (Shiu et al. 2024). Either change starts a fresh experiment |
| Sensor switches | Zero the corresponding input to the neural circuit |
| Neural silencing | Engineered model: clamps a group of units to zero |
| Cell-type manipulations | Connectome model: choose a cell type, the side (both, left or right) and **Silence**, **Scale output** (× 0 to 2) or **Activate** (a clamped rate from 0 to 1 with rate dynamics, Poisson input from 0 to 500 Hz with spiking dynamics; the unit is shown), then **Apply**. The list below shows each manipulation in force with a remove button, and how many neurons are silenced, scaled and activated. Each side of a type takes one manipulation: a new one replaces what acted on the same side (the other side of a two-sided one is kept) instead of adding a second. These are engineered manipulations: activation approximates optogenetic activation, and none of them is calibrated |
| Body engine | Starts a new experiment with FlyGym physics or the separately labeled toy demo |
| Control mode | Neural loop, or the controller-only `[1, 1]` baseline that bypasses the neurons; starts a fresh experiment |
| Export | Saves a folder and ZIP with CSV telemetry, configuration, provenance and the input schedule. **Share-safe export** leaves out the operating-system string and replaces absolute paths and the computer's name, for runs you publish |
| Presets | Loads, saves and deletes named configurations (see [Presets](#presets)) |

## Reading the displays

The **geometric** sensor uses the target's bearing and distance. The **compound-eye** mode computes its neural input from the actual eye-camera pixels, through an engineered green-contrast encoder. Behavior always comes from the Python simulation; the browser never animates it.

Neural traces show continuous firing rates, not spikes. Silencing the descending units does not stop the body instantly, because the walking controller and the body keep their own dynamics.

**Driving the fly**, under the world view, names the model that currently drives the body. With the connectome model, **Inside the loop** shows each readout cell type's left and right neurons, the mean input on each side, or the five most active cell types. With spiking dynamics the traces show firing rate ÷ the rate scale (100 spikes/s by default), so they can exceed 1.

**Neural atlas → Live circuit** shows the circuit by cell type: layers are hop distance to the circuit's seeds (not anatomy), node size is the number of neurons, fill is the live mean activity, solid lines are excitatory and dashed, capped lines inhibitory connections, and the readout neurons sit on the right. Click a type, or find it by name, to see its transmitter, partners and activity, trace its strongest paths to a readout type, or manipulate it on either side or both (the same controls as on the Workbench); manipulated types have a dashed outline, and the list under the inspector shows every manipulation in force. From the keyboard the diagram is a single Tab stop: arrow keys move between cell types and Enter inspects one. Large circuits show the 1,500 cell types nearest the readout. Changing a gain, the tonic drive or a time constant keeps the diagram, the selected type and its traced paths; another circuit, or a rebuilt one, starts the view afresh. Below the diagram, **Global parameters** change the running model from the next step without restarting it (recorded for replay). They include the engineered **motor path**: the motor delay and low-pass time constant, whether readout types are summed or averaged, and a weight per readout type (empty means 1). When the motor command has been clipped to its range in more than half of the control intervals since the run started, a warning says that turning is saturated (the legs follow the sign of the turn, not its size); see "The clip, and how to read `motor_clipped_fraction`" in [the research guide](RESEARCH.md#output-mapping). If the circuit file was rebuilt while a run uses it, the view says so and offers **Reset**, which loads the new build. **Populations by cell type** choose the steering readout, the neurons that receive the sensors and an optional speed drive; names are separated by semicolons, and applying them starts a fresh run.

In **Male & female anatomy**, the two female DNa02 skeletons are tinted by the model's computed DNa02 activity when DNa02 is a readout. That tint is model output, not recorded neural data.

## Comparisons in the app

**Experiments** runs comparisons: the same stimulus protocol for each seed and condition, one trial at a time, each trial saved to the run library as it finishes. Choose up to four built-in conditions and add **custom conditions** of your own, up to six conditions in all. A custom condition has a label (up to 40 characters, not the name of a built-in condition, different from the others) and holds its interventions for the whole trial: sensors off and, with the engineered model, a silenced group or, with the connectome model, cell-type manipulations; with the connectome model it can also change the output gain, input gain, tonic drive, motor delay or motor low-pass. Its trials carry the label as their condition. Problems are explained under the conditions as you edit, and a refusal from the server is shown there as a sentence. **Run as fast as possible** runs the trials unpaced instead of at the Workbench speed. **Cancel remaining** saves the unfinished trial too, marked **partial** in the run library. When a comparison ends, the Workbench returns to the configuration it had before, and the progress panel says so (or why it could not).

Below the progress panel of a finished comparison, **Comparison statistics** shows what `GET /api/batches/COMPARISON_ID/summary` computes from its saved trials ([below](#saved-runs-and-replay)): for each condition the number of trials `n` and, for each metric, the mean ± standard deviation with its 95% interval; then each condition's paired difference from the first condition (trials with the same seed) with its interval; and a chart of one metric at a time, each condition's mean with its interval on an axis that includes zero. Partial and duplicate trials, which the statistics leave out, are counted above the table. Fewer than five trials or pairs are marked **small n**, and the panel then says that the intervals are approximate: a bootstrap interval of a mean from a handful of trials tends to be too narrow, so read the differences as descriptive and add seeds to narrow them. An interval wider than its own estimate is marked **wide** (dashed in the chart). **Download CSV** saves the same numbers, **Show these trials in the library** filters the run library to them, and **How these numbers are computed** lists the methods. Any trial in the run library opens its comparison's statistics with **Comparison statistics**.

## Pages, keyboard and drafts

The page and the Neural atlas tab are part of the address (`#/workbench`, `#/atlas/circuit`, `#/experiments`), so Back, Forward, bookmarks and reloading keep your place. Unsent edits are kept in this browser until you submit them: the Experiments protocol, seeds, conditions and custom conditions (until a comparison starts), the **Build a circuit** form (until a build starts) and, in **Imported connectivity**, the dataset on screen with its search and threshold. They live in the browser's local storage, per browser and computer; a private window or blocked site data simply starts without them. Every control shows a focus ring when reached with the keyboard.

## Building a circuit

**Neural atlas → Build a circuit** selects a new circuit from FlyWire v783 on your computer. Name it, add seeds (cell types, with suggestions from the full catalog, or FlyWire root IDs), and set the hops back from the seeds, the minimum synapses per connection and the neuron cap, or tick **Whole brain**. **Balance left and right** (`balance_sides`) applies the cap per cell type and side, so each type keeps equal left and right counts where the data allow ([the rule](RESEARCH.md#building-your-own-circuits)); it is a sampling assumption, not a correction, and a whole-brain build, which has no cap, cannot use it. Circuits built that way, such as the committed `fafb783-dna02-balanced` and `fafb783-steering-balanced`, say **left/right balanced** in the list of available circuits and the Workbench's circuit menu, and **LEFT-RIGHT BALANCED** on the live circuit. **Build circuit** runs the builder in the background and shows its log; a 3,000-neuron circuit takes a few seconds. **Use this circuit** (or **Use** in the list of available circuits) starts a fresh run on it. Built circuits are saved in `data/circuits/local/`, which git ignores, and keep the FlyWire license: non-commercial use only.

The builder needs the FlyWire data prepared once (see [the research guide](RESEARCH.md#building-your-own-circuits)); until then the tab shows the command to run. Building never downloads anything. The same builder runs from the command line as `scripts/build_circuit.py build`. Rebuilding a name replaces only that circuit (its file is written in full before it replaces the old one), never other circuits whose names start the same way.

## FlyVis eyes

With the optional FlyVis install (`./scripts/setup.sh --with flyvis`; see [dependencies](DEPENDENCIES.md#v05-optional-flyvis-vision-and-recorded-fly-data)), **Sensor model → FlyVis eyes** runs the rendered eye images through FlyVis, a connectome-constrained network of the fly's optic lobe, and lets its cell types drive the circuit's visual neurons through FlyWire wiring. It needs the FlyGym body and the connectome model, and the circuit needs a FlyVis bridge: the committed circuits have one; for a circuit you build, run `backend/.venv/bin/python scripts/build_circuit.py flyvis-bridge --circuit NAME`. The bridge reaches only visual projection neurons, so a sensor input of other cell types is refused with FlyVis eyes. The first start builds FlyVis's network cache (about 10 seconds). Runs are slow, about 0.1–0.15× real time, and replay exactly. **Through the eyes** then shows the luminance FlyVis receives.

## Batch experiments and analysis

`scripts/toolkit.py` runs experiments without the web app, in parallel processes, and saves CSV and JSON under `runs/toolkit/`:

```sh
backend/.venv/bin/python scripts/toolkit.py trials --set neural_model=connectome --workers 8
backend/.venv/bin/python scripts/toolkit.py bias --set circuit=fafb783-steering
backend/.venv/bin/python scripts/toolkit.py ablation --workers 8
backend/.venv/bin/python scripts/toolkit.py jump --set neural_model=connectome --duration 60
backend/.venv/bin/python scripts/toolkit.py compare --run runs/YOUR_RUN_FOLDER
```

`trials` writes each trial to a `.jsonl` file and the CSV as soon as it finishes. A trial that fails (for example a FlyGym body that becomes numerically unstable) is saved as a row with an `error` column and the others carry on; the command then exits with an error. A worker process that dies (for example out of memory) costs no trials: the ones it took down run again on their own. Rerun the same command with `--resume` and the same `--out` to run only the trials that are missing or failed; it warns when saved trials were computed by another version of the code. Trials keep no per-sample recording, so `--duration` has no 300-second limit. Every saved report records the git commit, the command line, the circuits with their SHA-256 and the package versions.

`readouts` prints the turn command for a target held still at fixed bearings (the research guide's table "What the circuits compute"). `robustness` reruns the bias and readout analyses, and optionally short reach trials, under several modelling assumptions (sign rule, synapse threshold, readout pooling and weights, dynamics, circuit, seed) and reports which conclusions hold in every variant; it saves and resumes like `trials`. See [How sensitive is a result to the modelling assumptions?](RESEARCH.md#how-sensitive-is-a-result-to-the-modelling-assumptions)

To compare with a real fly, fetch the recorded DNa02 data once (71 MB; `./scripts/setup.sh --with recording` does the same) and compare it with an exported run:

```sh
backend/.venv/bin/python scripts/fetch_recording.py rayshubskiy2025-a2_d_13.mat
backend/.venv/bin/python scripts/toolkit.py compare --recording .cache/recordings/rayshubskiy2025-a2_d_13.mat --run runs/YOUR_RUN_FOLDER
```

A download that is interrupted resumes where it stopped when you run the same command again; network errors are retried a few times first, and a failure ends with a one-line message. `compare` takes `--recording` and `--run` more than once, and then also reports the mean and spread of each fit across the recordings.

Run `scripts/toolkit.py COMMAND --help` for every option, and see the [research guide](RESEARCH.md#the-research-toolkit) for what each analysis measures and for the Python API.

When the real-time factor drops below 1×, a note under the controls says how long one simulated second takes and whether that is the speed you requested or more than the computer can keep up with.

Charts use simulated time and freeze during Pause. Sensor readouts can update while paused when you move the target. Active wall time excludes paused time, and the real-time factor is simulated time divided by active wall time, including rendering. These are measurements, not guarantees of real-time speed.

## Validation scorecard

The scorecard scores a model against published perturbation → behavior results: DNa02 and DNp09 activated on one side, DNa02 silenced on both sides, MDN activated, the Giant Fiber, the antennal grooming neurons, left-right symmetry and sugar taste neurons. Each test cites its source, manipulates cell types with the ordinary interventions on matched-seed trials, and gives **pass**, **partial** or **fail** by a rule written down before any model was scored. A test is **not testable** when the circuit lacks its cell types (or the model has none, like the engineered one) and **blocked** when it needs a sense or a motor program this fly does not have. Results marked *by construction* follow from the engineered readout, not from the wiring. The [research guide](RESEARCH.md#validation-scorecard) has the rules, the measured results and their caveats.

In the app, the **Validation scorecard** panel on the Experiments page shows the latest scorecard of each model scored so far. **Score the Workbench model** scores the model, circuit and dynamics loaded on the Workbench as a background job, on the toy body (under a minute for rate dynamics) or the FlyGym body (several minutes); the panel updates when the job finishes, and the job appears under Background jobs. Open a test's title for its finding, citation, rule and caveats.

From the command line:

```sh
backend/.venv/bin/python scripts/toolkit.py scorecard --list                     # the tests, sources and rules
backend/.venv/bin/python scripts/toolkit.py scorecard --model engineered
backend/.venv/bin/python scripts/toolkit.py scorecard --circuit fafb783-steering --set dynamics=spiking
backend/.venv/bin/python scripts/toolkit.py scorecard --all --engine flygym --workers 3   # engineered + 4 circuits
```

The defaults are the toy body with seeds 1–3 and 3 s trials (FlyGym: seeds 1–2, 2 s). Each run prints a Markdown table, saves the scorecard and its per-trial rows under `runs/toolkit/` (JSON and CSV, with provenance), and replaces the app's latest card for that model in `runs/scorecards/` (`--no-publish` keeps it; a partial run with `--tests` never replaces it). Other connectome settings (`--set output_gain=2`) give the card a name of their own.

## Saved runs and replay

Exports are written only inside `runs/`; the app never accepts a destination path. Every export includes the initial configuration, final state, dependency versions and the SHA-256 of each `backend/requirements*.lock`, neural weights, units, time steps, and every event stamped with its control step; FlyVis-eye runs add the FlyVis release, network and checkpoint hash, and the bridge file with its hash. An export is written into a hidden folder in `runs/` and renamed into place only when complete, so an interrupted export never appears in the run library.

Recording keeps every sample from Reset, up to 30,000 (about 300 simulated seconds), rather than silently dropping the start of a run. At that limit the run pauses with a note in the session log; it stays valid and exports normally, and Reset starts a new one. Up to 10,000 manual input changes (target, interventions and parameters) are recorded; after that, further changes are refused until you export and reset. Run, Pause, Step, speed changes and exports never count; the session log keeps the first 10,000 of those per run and then one note that later ones are left out, which never affects replay. Repeated target moves (or engineered-model parameter changes) within the same 10 ms step, such as a target dragged while paused, are saved as one event holding the final value, which is the only one the simulation used. Interventions and connectome parameter changes are saved one by one, even within one step, because each takes effect as it is applied (silencing puts neurons at rest at once).

To publish a run, tick **Share-safe export** under **Export this run**, or through the API, `POST /api/export` with the body `{"share_safe": true}` leaves out the operating-system string and replaces absolute paths with paths relative to the project (or `<local>`) and the computer's name with `<local>` in errors and log messages:

```sh
curl -X POST -H 'Content-Type: application/json' -d '{"share_safe": true}' http://127.0.0.1:8000/api/export
```

The API also lists saved runs page by page (`GET /api/runs?offset=0&limit=100&include_empty=true`; the `X-Total-Count` header gives the total) and deletes one with `DELETE /api/runs/FOLDER_NAME`, which removes its folder and ZIP. The run being recorded cannot be deleted until you Reset, nor a run while a replay check of it waits or runs (409).

The list takes filters, all optional and combined: `model=engineered` or `connectome`, `circuit=NAME` (connectome runs on that circuit), `batch=COMPARISON_ID`, `tag=TAG` and `q=TEXT` (found, ignoring case, in the run's folder name, notes or comparison condition); `X-Total-Count` then counts the matching runs. Each run lists its `tags`, `notes`, `batch_id` and `condition`. To tag a run or write notes on it:

```sh
curl -X PATCH -H 'Content-Type: application/json' -d '{"tags": ["pilot"], "notes": "Target hidden at 2 s"}' \
  http://127.0.0.1:8000/api/runs/YOUR_RUN_FOLDER
```

Up to 10 tags of up to 24 letters, digits, spaces, `_` or `-` each, and up to 2,000 characters of notes; a field you leave out keeps its value. They are saved in the run's `annotations.json`; its `metadata.json` never changes. In the app, the run library on the Experiments page has the same filters above its table (**Model**, **Circuit**, **Comparison ID**, **Tag** and **Search**; typed ones apply once you pause, and one the server would refuse is explained instead of sent), and its count then says how many runs match. A run's tags show as chips in its **Tags & notes** column; clicking one lists the runs with that tag. **Add tags or notes** (or **Edit**) opens a form under the row: tags separated by commas, and notes. Tags and notes are checked against the rules above as you type, and a refusal from the server is shown as a sentence. `GET /api/batches/COMPARISON_ID/summary` summarizes a comparison's saved trials: for each condition, the mean, standard deviation and 95% interval of final target distance, path length, net turn and mean speed and, for runs saved since v0.6, the fraction that came within 2 mm of the target; then the differences from the first condition over trials with the same seed. Add `?format=csv` for a table. Only trials that ran their protocol to the end count, once per condition and seed: trials saved unfinished (a cancelled or failed comparison's last trial, or one exported by hand during the comparison, which is saved marked partial) and repeats are left out and counted (`partial_trials`, `duplicate_trials`).

Exporting runs beside the simulation, so the fly, the display and other commands keep going while a long run is written; the export answers once its files are complete. With the connectome model, `"record_activity": "types"` in the configuration you reset with (`POST /api/reset`) also saves `activity_types.npz`, every cell type's mean activity at each control step ([signal definitions](RESEARCH.md#exported-signals)).

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with a folder created by Export or by a completed comparison. Replay re-runs the recorded schedule and checks body position, yaw, neural rates and motor outputs against the saved telemetry, at a tolerance of `1e-8`. It reports the largest difference in each column and, when they differ, the first sample with the largest one; a damaged `telemetry.csv` (a value that is not a number, missing rows or columns) fails the check. Results match on the same software and graphics stack; other devices or dependency versions may differ slightly. A connectome run records the SHA-256 of its circuit file; if that circuit has since been rebuilt or edited, replay stops and says so (`--allow-circuit-mismatch` tries anyway). `--save` also writes the verdict to the run's `replay.json`.

The running app verifies a saved run the same way, in a separate process, so the simulation never waits for it. In the run library on the Experiments page, **Verify replay** starts a check; the row then shows its progress (with **Cancel**) and, when it is done, **✓ verified** or **✗ mismatch** with the largest error, plus **software differs** when the installed versions are not the ones the run recorded (hover for the message). **Background jobs** on the same page lists checks and circuit builds, with **Cancel** while they wait or run; the page asks the server for them every 1.5 seconds only while one does. Through the API, `POST /api/runs/FOLDER_NAME/replay` (body `{}`) queues the check and answers 202 with the job. One check runs at a time; others wait their turn, and a FlyGym run is replayed with the OpenGL backend the server chose. The verdict is saved in the run's `replay.json` and appears as `verified` on the run in `GET /api/runs` and `GET /api/runs/FOLDER_NAME`: `ok`, `max_abs_error`, `tolerance`, when it was `checked`, a `message`, and `same_software`, which says whether the Python version, the package versions and the lockfile hashes the run recorded match the installed ones (when they do not, the message lists the differences). A check that cannot run at all, for example because the circuit changed, fails its job with the reason and leaves the previous verdict in place.

```sh
curl -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/runs/YOUR_RUN_FOLDER/replay
curl http://127.0.0.1:8000/api/jobs                                   # replay checks and circuit builds, newest first
curl -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/jobs/JOB_ID/cancel
```

`GET /api/jobs` lists the last 50 jobs (circuit builds from **Build a circuit** included) with their status (`queued`, `running`, `done`, `failed` or `cancelled`), progress, the last 200 lines of output, the result and any error. Cancelling stops the job's process and everything it started. Quitting the server stops running jobs.

To measure throughput on your machine:

```sh
backend/.venv/bin/python scripts/benchmark.py            # the app's worker: real-time factor and memory
backend/.venv/bin/python scripts/benchmark.py --vision   # with rendered compound-eye input
backend/.venv/bin/python scripts/benchmark.py --neural   # wall time per 1 ms neural step, per circuit and dynamics
backend/.venv/bin/python scripts/benchmark.py --flyvis   # FlyVis eyes, when FlyVis is installed
```

## Scripting the app from Python

`digitalfly.client` drives the running app with the same commands as the browser. It uses only the Python standard library (plus `websockets`, installed with the app, for live telemetry), so it also works from another environment such as a notebook's, when you copy `backend/src/digitalfly/client.py` there:

```python
from digitalfly.client import Client      # PYTHONPATH=backend/src, or a copy of client.py
fly = Client("http://127.0.0.1:8000")
fly.reset({"engine": "toy", "neural_model": "connectome", "seed": 3})
fly.stimulus(0, 12)                        # target 12 mm to the left
fly.run()
fly.wait_until(lambda state: state["sample"]["t"] >= 2)
fly.interventions(silence_dna02="left")    # merged into the current interventions
fly.connectome_parameters(output_gain=2)   # likewise merged into the current parameters
for state in fly.stream(10):               # live telemetry, about 10 states a second while running
    print(state["sample"]["t"], state["metrics"]["net_turn_deg"])
fly.pause()
saved = fly.export(share_safe=True)        # {run_id, samples, path, download_url}
print(fly.runs(limit=5)["total"])
```

Every call returns the server's JSON; commands return the new state, the same object as `fly.status()`. `reset()` without a configuration restarts from the current one, and `reset(seed=4, **{"connectome_parameters.dynamics": "spiking"})` changes single values. `step(n)` advances n control intervals while paused. A refused command raises `ClientError` with the HTTP status and the server's reason, for example 409 for Step while running or 422 for an unknown cell type. Requests carry the `Origin` header of the app's own address, which the server accepts (a foreign origin gets 403), and never go through a proxy.

The app runs a single experiment, so the browser shows what the script does, and a command from either changes it for both. For many trials, use the [research toolkit](RESEARCH.md#the-research-toolkit) instead: it runs without the app, in parallel. [`examples/`](../examples/README.md) has a script for each: a short protocol driven through the client, and a batch over seeds with the toolkit.

## Troubleshooting

**Not sure what is wrong:** run `python3 scripts/doctor.py`. It checks Python and the project environment, that installed packages match `backend/requirements.lock`, Node and npm against `frontend/package.json`, whether the built interface is current, which OpenGL backends render, the optional FlyVis and circuit-builder installs, the cache folders, free disk space and port 8000. It prints one line per check with the command that fixes it, and changes nothing. After `./scripts/setup.sh --backend-only`, add `--backend-only` so that it does not expect Node.js or the interface; inside the Docker image it points its fixes at rebuilding the image. For install and update problems, see [INSTALL](INSTALL.md#install-problems).

**Port occupied:** the launcher stops with a message and never kills other processes. Stop your previous server with Ctrl+C, or start on another port with `--port 8001`. The development launcher needs both 8000 and 5173.

**Stale or missing frontend:** run `npm --prefix frontend run build`. The launcher refuses to serve a build older than the frontend source. Restart the server after Python changes.

**Slow first start:** Matplotlib builds a font cache in `.cache/matplotlib` the first time it runs. Setup builds it for you; if you delete `.cache/`, the next start rebuilds it, which takes about 20 seconds.

**macOS `invalid CoreGraphics connection`:** the process has no access to a graphics context, for example inside a restricted sandbox. Start from a normal terminal, or use geometric sensing with `--no-render`.

**No usable renderer:** compound-eye vision needs a graphics context. Without one, physics still runs with the labeled pose map and geometric sensing; `python3 scripts/doctor.py` shows which OpenGL backends work.

**Body viewport disabled:** `--no-render` keeps the real physics and shows the labeled pose map instead. If the body itself fails to initialize, the app shows the error and keeps FlyGym selected; it never switches to the toy demo silently. The toy demo is always labeled **"Toy demo: a kinematic body, not FlyGym physics."**

**Linux rendering:** unless you set `MUJOCO_GL`, DigitalFly tries MuJoCo's default GLFW when there is a display, then EGL, then OSMesa, each in a short test process, and uses the first that renders. A `MUJOCO_GL` you set is never overridden. When none works (a server or container without graphics libraries), physics still runs without the 3D view, compound-eye vision is unavailable, and the message says what to do: start with `--toy`; run under a virtual display with `MUJOCO_GL=glfw xvfb-run -a ./scripts/start.sh`; or install EGL or OSMesa (Debian/Ubuntu: `sudo apt install libegl1`, or `libosmesa6`; recent Mesa releases no longer ship OSMesa). Setup never installs drivers or system packages; the Docker image includes EGL and OSMesa. See [headless servers](INSTALL.md#headless-servers).

**Scripting the running app:** use the Python client ([Scripting the app from Python](#scripting-the-app-from-python)). The REST schema is at http://127.0.0.1:8000/api/openapi.json (OpenAPI 3.1). Open it in the browser, or save it with `curl -o openapi.json http://127.0.0.1:8000/api/openapi.json` and load the file in any OpenAPI viewer or client generator. The app serves no interactive documentation page: one would need scripts from a CDN, which its security policy blocks. The state that `/api/ws` and `/api/status` send is described by `GET /api/schema/state` (JSON Schema); `backend/.venv/bin/python scripts/gen_types.py` turns both schemas into the frontend's TypeScript types (`frontend/src/api.gen.ts`), and `--check` fails when they are out of date.

**Connectome circuit unavailable:** the committed circuits are `data/circuits/fafb783-dna02.json` and `fafb783-steering.json`, and their side-balanced versions `fafb783-dna02-balanced.json` and `fafb783-steering-balanced.json`. If one is missing or edited, restore it from version control or rebuild it with `scripts/build_circuit.py` (see the [research guide](RESEARCH.md#building-the-subcircuit)). A local circuit that no longer loads appears in the circuit list with its error; delete or rebuild it. The app refuses to rebuild the circuit the running experiment uses; if `build_circuit.py` rewrites it anyway, the run keeps its loaded wiring and asks you to Reset before parameter edits.

**"The simulation has stopped … Restart DigitalFly":** the simulation thread ended, which a failing command or display update should no longer cause. Stop the server with Ctrl+C and start it again; please report what you did before it happened.

**Builder not ready:** the **Build a circuit** tab and `build_circuit.py build` need the prepared FlyWire archive in `.cache/circuits/`. Run `./scripts/setup.sh --with builder` once, which installs the build-only data lock and runs `scripts/build_circuit.py prepare` (see the research guide).

**Spiking or whole-brain runs are slow:** the spiking 3,000-neuron circuit runs faster than real time on the reference laptop, but the whole brain takes about 7 ms of computing per 1 ms of neural time with spiking neurons and 3 ms with rate units, before the body's own cost. Use the toy body or the toolkit's parallel workers for long experiments.

**Connection lost:** controls disable, the last received state stays on screen with a label, and the page reconnects automatically. The app talks only to your own computer, fonts and meshes included; there are no analytics, accounts or cloud services.
