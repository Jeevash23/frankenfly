# Using DigitalFly

## Starting and stopping

```sh
./scripts/start.sh --open                      # geometric sensing, opens your browser
./scripts/start.sh --vision --open             # rendered compound-eye input
./scripts/start.sh --no-render                 # real physics without the 3D camera
./scripts/start.sh --toy                       # kinematic toy demo, no physics
./scripts/start.sh --port 8001                 # use another port
./scripts/start.sh --config configs/default.json
```

The app opens paused at http://127.0.0.1:8000. To stop the server, click **Quit** in the upper-right corner, optionally saving the current run first, or press **Control+C** in the terminal that started it. Closing the browser tab or pressing Pause does not stop the server.

Extra browser tabs on the same computer share one simulation: Run, Reset, interventions and Quit affect all of them. A copy of the project on another computer runs independently, with its own saved runs.

## Controls

| Control | What it changes |
| --- | --- |
| Run / Pause, or Space | Starts or freezes the Python simulation |
| Step | Advances exactly **10 ms** of simulation while paused |
| Reset | Restores the body, controller, neural state, seed, target `(12, 8)` mm at intensity 1, interventions, clock, history and recording. Keeps the selected parameters and protocol |
| Seed | Applied on the next Reset; makes the walking-rhythm initialization repeatable |
| Speed | Requests 0.05–2× simulated time per wall time; your hardware may run slower |
| Specimen | Live 640×288 MuJoCo rendering; the camera follows the body |
| Arena | Labeled top-down map from the simulated body poses; click to place the target |
| Target X/Y, intensity | Moves the stimulus and its rendered landmark; press Enter or leave the field to apply coordinates |
| Sensor model | Geometric bearing or rendered compound eyes; switching starts a fresh experiment |
| Neural model | The engineered six-unit loop (default) or the connectome DNa02 circuit; switching starts a fresh experiment |
| Sensor switches | Zero the corresponding input to the neural circuit |
| Neural silencing | Engineered model: clamps a group of units to zero. Connectome model: silences the left, right or both DNa02 neurons, or any cell type in the circuit |
| Body engine | Starts a new experiment with FlyGym physics or the separately labeled toy demo |
| Control mode | Neural loop, or the controller-only `[1, 1]` baseline that bypasses the neurons; starts a fresh experiment |
| Export | Saves a folder and ZIP with CSV telemetry, configuration, provenance and the input schedule |

## Reading the displays

The **geometric** sensor uses the target's bearing and distance. The **compound-eye** mode computes its neural input from the actual eye-camera pixels, through an engineered green-contrast encoder. Behavior always comes from the Python simulation; the browser never animates it.

Neural traces show continuous firing rates, not spikes. Silencing the descending units does not stop the body instantly, because the walking controller and the body keep their own dynamics.

**Driving the fly**, under the world view, names the model that currently drives the body. With the connectome model, **Inside the loop** shows DNa02 left and right, the mean visual input on each side, or the five most active cell types, and **Neural atlas → Live circuit** shows the circuit by cell type: layers are hop distance to DNa02 (not anatomy), node size is the number of neurons, fill is the live mean rate, solid lines are excitatory and dashed, capped lines inhibitory connections. Click a type, or find it by name, to see its transmitter, partners and activity, or to silence it. In **Male & female anatomy**, the two female DNa02 skeletons are then tinted by the model's computed activity. That tint is model output, not recorded neural data.

When the real-time factor drops below 1×, a note under the controls says how long one simulated second takes and whether that is the speed you requested or more than the computer can keep up with.

Charts use simulated time and freeze during Pause. Sensor readouts can update while paused when you move the target. Active wall time excludes paused time, and the real-time factor is simulated time divided by active wall time, including rendering. These are measurements, not guarantees of real-time speed.

## Saved runs and replay

Exports are written only inside `runs/`; the app never accepts a destination path. Every export includes the initial configuration, final state, dependency versions, neural weights, units, time steps, and every event stamped with its control step. Recording stops at 30,000 samples (about 300 simulated seconds) or 10,000 events rather than silently dropping the start of a run.

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with a folder created by Export or by a completed comparison. Replay re-runs the recorded schedule and checks body position, yaw, neural rates and motor outputs against the saved telemetry, at a tolerance of `1e-8`. Results match on the same software and graphics stack; other devices or dependency versions may differ slightly.

To measure throughput on your machine:

```sh
backend/.venv/bin/python scripts/benchmark.py
backend/.venv/bin/python scripts/benchmark.py --vision
```

## Troubleshooting

**Port occupied:** the launcher stops with a message and never kills other processes. Stop your previous server with Ctrl+C, or start on another port with `--port 8001`. The development launcher needs both 8000 and 5173.

**Stale or missing frontend:** run `npm --prefix frontend run build`. The launcher refuses to serve a build older than the frontend source. Restart the server after Python changes.

**Slow first start:** Matplotlib builds a font cache in `.cache/matplotlib` the first time it runs. Setup builds it for you; if you delete `.cache/`, the next start rebuilds it, which takes about 20 seconds.

**macOS `invalid CoreGraphics connection`:** the process has no access to a graphics context, for example inside a restricted sandbox. Start from a normal terminal, or use geometric sensing with `--no-render`.

**No usable renderer:** compound-eye vision needs a graphics context. Use geometric sensing with `--no-render` if graphics are unavailable.

**Body viewport disabled:** `--no-render` keeps the real physics and shows the labeled pose map instead. If the body itself fails to initialize, the app shows the error and keeps FlyGym selected; it never switches to the toy demo silently. The toy demo is always labeled **"Toy demo: a kinematic body, not FlyGym physics."**

**Linux rendering:** in a desktop session MuJoCo's default GLFW context works. Without a display (SSH, containers), DigitalFly selects EGL automatically. To choose explicitly, start with `MUJOCO_GL=egl ./scripts/start.sh`, or `MUJOCO_GL=osmesa` if your system still ships OSMesa (recent Mesa releases do not). Setup never installs drivers or system packages.

**Connectome circuit unavailable:** the connectome model reads `data/circuits/fafb783-dna02.json`, which ships with the repository. If it is missing or edited, restore it from version control or rebuild it with `scripts/build_circuit.py` (see the [research guide](RESEARCH.md#building-the-subcircuit)).

**Connection lost:** controls disable, the last received state stays on screen with a label, and the page reconnects automatically. The app talks only to your own computer, fonts and meshes included; there are no analytics, accounts or cloud services.
