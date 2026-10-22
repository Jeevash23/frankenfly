# Local validation evidence

This directory is reserved for generated test logs, screenshots, probe results, benchmark measurements and evaluation reports. Only this README is included in version control. Other files can contain local paths, operating-system details, timestamps or session identifiers and remain local by default.

The [status summary](../../STATUS.md) records the reference validation without personal paths or raw run identifiers. This page lists the commands that reproduce each published number. Run them from the repository root after `./scripts/setup.sh`. Speeds depend on your hardware; counts, fits and evaluation tables should match exactly on the same software stack.

## Before you start

**Graphics.** FlyGym physics tests, the smoke test, the benchmarks, FlyGym evaluations and replay of eye-input runs need an OpenGL backend. On a desktop session the default works. Unless `MUJOCO_GL` is set, DigitalFly uses the first backend that renders: GLFW when there is a display, then EGL, then OSMesa (`python3 scripts/doctor.py` shows which work). On Linux without a display or a working EGL, `./scripts/check.sh` runs the tests under `xvfb-run` with `MUJOCO_GL=glfw` when it is installed, which is how the v0.6 reference ran. Set `MUJOCO_GL` to choose:

```sh
MUJOCO_GL=egl ./scripts/check.sh                   # needs libEGL (for example Ubuntu's libegl1)
MUJOCO_GL=osmesa ./scripts/check.sh                # needs libOSMesa, which recent Mesa releases no longer ship
xvfb-run -a env MUJOCO_GL=glfw ./scripts/check.sh  # any machine with Xvfb and Mesa's libGL
```

Any command below that needs graphics can be prefixed the same way. Even FlyGym tests that render nothing fail without a backend, because importing FlyGym loads MuJoCo's GL bindings.

**Optional assets.** Several tests and numbers need downloads that setup does not make:

```sh
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-vision.lock  # FlyVis 1.2.0, CPU-only PyTorch
backend/.venv/bin/python scripts/fetch_flyvis.py                                              # pretrained FlyVis networks, 3.4 MB
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock    # pyarrow, for circuit builds only
backend/.venv/bin/python scripts/build_circuit.py prepare                                      # about 61 MB of FlyWire v783 data, then the prepared archive
backend/.venv/bin/python scripts/fetch_recording.py rayshubskiy2025-a2_d_13.mat               # one recorded fly, 71 MB
```

`./scripts/setup.sh --with builder,flyvis,recording` does all five in one step. The locks install into `backend/.venv`; downloads land in the ignored `.cache/`. The download commands retry network errors, resume an interrupted download when run again, and check every file against its recorded hashes. The FlyWire data, and every circuit and bridge built from it, is CC BY-NC 4.0, non-commercial; the recording is CC0.

## Tests and checks (STATUS validation table)

```sh
./scripts/check.sh                       # backend tests, formatting, frontend tests and production build
backend/.venv/bin/python -m pip check
backend/.venv/bin/python scripts/gen_types.py --check
backend/.venv/bin/python scripts/smoke_flygym.py
```

`./scripts/check.sh --fast` omits the FlyGym tests and does not establish graphics or body compatibility. The v0.6 backend suite has **356 tests**, 12 of them FlyGym physics tests. Without graphics the FlyGym tests fail; without each optional asset its tests skip: FlyVis 2 (one of them a physics test), the prepared archive 4 (the general builder's check against the DNa02 circuit, the steering circuit's rebuild and the two balanced circuits' rebuilds), the recording 1. One test checks what `benchmark.py --flyvis` reports without FlyVis, so it skips when FlyVis is installed. That gives:

| Graphics and assets | Backend result |
| --- | --- |
| All optional assets | 355 passed, 1 skipped (expected; not run for v0.6, where FlyVis and the recording were unavailable) |
| The prepared archive only (the v0.6 reference) | 353 passed, 3 skipped |
| No optional assets | 349 passed, 7 skipped |
| No optional assets, `./scripts/check.sh --fast` | 338 passed, 6 skipped (the 12 physics tests deselected) |

Run `pytest -rs` to see the reason for each skip:

```sh
backend/.venv/bin/python -m pytest backend/tests -q -rs
```

| STATUS row | Command |
| --- | --- |
| Python 3.13 and 3.14 | In a separate checkout: `PYTHON_BIN=/path/to/python3.13 ./scripts/setup.sh`, then `./scripts/check.sh` (the same with 3.14) |
| Frontend unit tests, formatting, TypeScript and build | `./scripts/check.sh` (or `npm --prefix frontend test`, `run format:check`, `run typecheck`, `run build`) |
| Browser end to end | Once: `cd frontend && npx playwright install chromium`. Then `npm --prefix frontend run build` and `npm --prefix frontend run e2e` (10 tests; the builder test skips without the prepared archive's catalog) |
| Linux rendering | `scripts/smoke_flygym.py` and `./scripts/check.sh`, once with each `MUJOCO_GL` value above |
| Replay | `backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER` on runs exported from the app or by `toolkit.jumping_target_run` (below); in the running app, **Verify replay** in the run library, or `POST /api/runs/YOUR_RUN_FOLDER/replay` |
| Docker image | `docker build -t digitalfly .`, then the smoke steps of `.github/workflows/docker.yml` (the doctor in the image; a container on `-p 127.0.0.1:8001:8000`; a FlyGym reset with `"sensor_model": "vision"`; `/api/frame`; a preset; the Origin and Host checks; the health check and a clean stop), plus an export and `docker exec CONTAINER python scripts/replay.py runs/YOUR_RUN_FOLDER` |
| Circuit build | With the prepared archive, `pytest backend/tests/test_build_circuit.py backend/tests/test_balance_sides.py` rebuilds both committed circuits and their two side-balanced versions in a temporary folder and compares them. For the default DNa02 rebuild in place: `backend/.venv/bin/python scripts/build_circuit.py --offline`, then `git diff --exit-code data/circuits/fafb783-dna02.json` |
| Recorded fly | With the recording, `pytest backend/tests/test_compare.py` checks the conversion against the documented spike counts and fit |

The smoke script writes a JSON report and PNG here. To keep console output, redirect it into a local log:

```sh
./scripts/check.sh > docs/evidence/check.log 2>&1
```

## Speed (STATUS and the research guide)

`scripts/benchmark.py` runs the application worker for 2 simulated seconds with the body camera rendering and reports the real-time factor and memory; it writes `research-performance-*.json` here:

```sh
backend/.venv/bin/python scripts/benchmark.py                          # geometric sensing, engineered model
backend/.venv/bin/python scripts/benchmark.py --vision                 # rendered compound-eye input (not FlyVis)
backend/.venv/bin/python scripts/benchmark.py --model connectome_dna02 # the connectome model on the DNa02 circuit, rate dynamics
```

The same script times the neural step alone and the FlyVis sensor. The wall time per 1 ms neural step (0.05 and 0.3 ms for the 3,000-neuron circuit with rate and spiking dynamics; 3.2 and 6.7 ms for the whole brain) needs no graphics; it times every committed circuit with both dynamics, plus any local whole-brain build, after 100 warm-up steps, and writes `neural-step.json`. Build the whole brain first to include it (needs the prepared archive):

```sh
backend/.venv/bin/python scripts/build_circuit.py build --name whole --seed DNa02 --whole-brain
backend/.venv/bin/python scripts/benchmark.py --neural                    # committed circuits and local whole-brain builds
backend/.venv/bin/python scripts/benchmark.py --neural --circuit whole    # or only the circuits named
```

FlyVis (10 ms of computing per 10 ms step for both eyes, and 0.11–0.15× real time for FlyVis-eye runs, without the body camera) needs the vision lock, the pretrained networks and graphics. Without them the report says why it was skipped:

```sh
backend/.venv/bin/python scripts/benchmark.py --flyvis   # writes flyvis-timing.json
```

The app's own real-time readout, under the controls, shows the same factor with the body camera on.

## Evaluation (research guide)

### Matched-seed evaluation

```sh
backend/.venv/bin/python scripts/evaluate_models.py --engine toy --workers 8           # 400 trials, 360 distinct (each run once); writes evaluation-toy.json
backend/.venv/bin/python scripts/evaluate_models.py --engine flygym --quick --workers 4 # needs graphics; writes evaluation-flygym-quick.json
```

The script prints one row per target and model. `--models` runs a subset and `--duration` changes the trial length; such a partial report is named after them (for example `evaluation-toy-engineered.json`), so it never replaces the full one. Each finished trial is appended to the report's `.jsonl` and `.csv` while the evaluation runs; after an interruption or a failed trial, rerun the same command with `--resume` to run only what is missing. The summary and silencing tables in the research guide are aggregated from the report:

```sh
backend/.venv/bin/python - docs/evidence/evaluation-toy.json <<'EOF'
import json, sys
import numpy as np
report = json.load(open(sys.argv[1]))
print("| Model | Reached ≤2 mm | First turn toward lateral targets | Median time to reach | Mean final distance, 12 mm targets | Mean speed |")
for model, (label, _) in report["models"].items():
    rows = [r for r in report["trials"] if r["model"] == model]
    lateral = [r for r in rows if r["bearing_deg"] not in (0, 180)]
    times = [r["reach_time_s"] for r in rows if r["reached"]]
    print(f"| {label} | {sum(r['reached'] for r in rows)}/{len(rows)} | "
          f"{sum(r['first_turn_toward'] is True for r in lateral)}/{len(lateral)} | "
          f"{f'{np.median(times):.2f} s' if times else '—'} | "
          f"{np.mean([r['final_distance_mm'] for r in rows if r['distance_mm'] == 12]):.1f} mm | "
          f"{np.mean([r['mean_speed_mm_s'] for r in rows]):.1f} mm/s |")
print("\n| Model | DNa02 silenced | Yaw rate, first 2 s: left / right targets | Net turn: left / right targets | Reached | Mean final distance |")
for model, (label, _) in report["models"].items():
    for silence in ["none", "left", "right", "both"]:
        rows = [r for r in report["silencing"] if r["model"] == model and r["silence_dna02"] == silence]
        if not rows:
            continue
        side = lambda key, left: np.mean([r[key] for r in rows if (r["bearing_deg"] > 0) == left])
        print(f"| {label} | {silence} | {side('mean_yaw_rate_first_2s_deg_s', True):+.0f} / "
              f"{side('mean_yaw_rate_first_2s_deg_s', False):+.0f} °/s | {side('net_turn_deg', True):+.0f}° / "
              f"{side('net_turn_deg', False):+.0f}° | {sum(r['reached'] for r in rows)}/{len(rows)} | "
              f"{np.mean([r['final_distance_mm'] for r in rows]):.1f} mm |")
EOF
```

Use the same lines with `evaluation-flygym-quick.json` for the FlyGym tables. Positive yaw rates are leftward turns.

### Toolkit analyses

Results are printed as Markdown and saved under the ignored `runs/toolkit/` (or `--out`):

| Published result | Command |
| --- | --- |
| What the circuits compute (DNa02 R − L at 0.6 s for each bearing) | `scripts/toolkit.py readouts` (add `--set circuit=fafb783-dna02-balanced` and so on for the other circuits) |
| Bias table, DNa02 circuit | `scripts/toolkit.py bias --set circuit=fafb783-dna02` |
| Bias table, steering circuit, rate | `scripts/toolkit.py bias --set circuit=fafb783-steering` |
| Bias table, steering circuit, spiking | `scripts/toolkit.py bias --set circuit=fafb783-steering --set dynamics=spiking --ms 800 --average-ms 400 --seed 1` |
| Ablation, DNa02 circuit | `scripts/toolkit.py ablation --set circuit=fafb783-dna02 --workers 8 --top 20` |
| Ablation, steering circuit | `scripts/toolkit.py ablation --set circuit=fafb783-steering --workers 8 --top 20` |
| Whole-brain bias (−0.171, asymmetry 0.75) | `scripts/toolkit.py bias --set circuit=whole`, after building `whole` as above |
| Steering-circuit readout sweep | `scripts/toolkit.py trials --set neural_model=connectome --set connectome_parameters.circuit=fafb783-steering --vary 'connectome_parameters.readout_types=[["DNa02"],["DNa01","DNa02"],["DNa01","DNa02","DNp09"],["DNp09"]]' --workers 8` |
| DNa02 orbit radius against output gain | `scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.output_gain=1,2,4,8 --distances 12 --workers 8` (median final distance) |
| FlyVis closed loop (needs FlyVis and graphics) | `scripts/toolkit.py trials --engine flygym --duration 6 --distances 12 --seeds 1-3 --set neural_model=connectome --set sensor_model=flyvis --vary connectome_parameters.circuit=fafb783-dna02,fafb783-steering --workers 3 --out runs/toolkit/eval-flyvis` |
| Path tracing | `scripts/toolkit.py paths --source LC10a --target DNa02` |
| Side-balanced circuits: bias tables | `scripts/toolkit.py bias --set circuit=fafb783-dna02-balanced` and `--set circuit=fafb783-steering-balanced`; spiking rows add `--set dynamics=spiking --ms 800 --average-ms 400 --seed 1` |
| Side-balanced circuits: closed loop | `scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.circuit=fafb783-dna02,fafb783-dna02-balanced,fafb783-steering,fafb783-steering-balanced --workers 3` (spiking: add `--set connectome_parameters.dynamics=spiking --bearings=45,-45,90,-90 --distances 12 --seeds 1-3`) |
| Assumption sensitivity, DNa02 and steering circuits | `scripts/toolkit.py robustness --set circuit=fafb783-dna02 --analyses bias,readouts`, the same with `circuit=fafb783-steering` |
| Assumption sensitivity: seeds, readout, balance | `scripts/toolkit.py robustness --set circuit=fafb783-steering --set dynamics=spiking --vary seed=1,2,3,4,5 --analyses bias,readouts`; `… --set circuit=fafb783-steering --vary readout_pool=sum,mean --vary 'readout_weights=[null,{"DNa02":2},{"DNp09":0.5}]' --analyses bias,readouts`; `… --vary circuit=fafb783-dna02,fafb783-dna02-balanced --vary dynamics=rate,spiking --analyses bias,readouts,reach` and the same for the steering pair |

Prefix each with `backend/.venv/bin/python`. Positive turn commands are rightward.

### Fly and model fits

The fly row of the fit table, after fetching the recording. The published row includes the stimulation epochs (`--include-stimulus`); without that option `compare` leaves them out, the default since v0.6, which gives the fit the research guide still lists as not yet re-run:

```sh
backend/.venv/bin/python scripts/toolkit.py compare --include-stimulus --recording .cache/recordings/rayshubskiy2025-a2_d_13.mat --out runs/toolkit/compare-fly
backend/.venv/bin/python scripts/toolkit.py compare --recording .cache/recordings/rayshubskiy2025-a2_d_13.mat --out runs/toolkit/compare-fly-masked
```

The four model rows use runs whose target jumps to a random side every 2 s (target seed 11, model seed 3): 30 simulated seconds on FlyGym (needs graphics) and 60 on the toy body. Record them with `jump`, which prints each exported run's folder:

```sh
for circuit in fafb783-dna02 fafb783-steering; do
  for engine_duration in flygym:30 toy:60; do
    backend/.venv/bin/python scripts/toolkit.py jump --engine ${engine_duration%:*} --duration ${engine_duration#*:} \
        --jump-seed 11 --set seed=3 --set neural_model=connectome \
        --set connectome_parameters.circuit=$circuit --set connectome_parameters.dynamics=spiking
  done
done
```

Then fit them all next to the fly in one command (the fly row of the table includes the stimulation epochs, hence `--include-stimulus`). It prints one fit row per run (`model 1` to `model 4`, in the order given), the spread across the runs, and each source's left and right DNa02 rate (mean, median and 99th percentile, over the samples the fits use):

```sh
backend/.venv/bin/python scripts/toolkit.py compare --include-stimulus \
    --recording .cache/recordings/rayshubskiy2025-a2_d_13.mat \
    --run runs/RUN_1 --run runs/RUN_2 --run runs/RUN_3 --run runs/RUN_4 --out runs/toolkit/compare-models
```

The original firing-rate summary file was not kept, so how it pooled the two sides is not recorded; this prints each side separately.

## Browser and server checks

Start the app with `./scripts/start.sh --vision --open` (rendered compound-eye input; FlyVis eyes are chosen in the app). Exercise Run, Pause, Step, target movement, circuit parameters, anatomical selection, a short comparison and Export. Use Quit to shut down the server.

For an automated HTTP/WebSocket probe while the app is running:

```sh
backend/.venv/bin/python scripts/probe_local.py
```

The probe advances and resets that local experiment. It is intended for a test session.

## Replay a local export

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with a directory created by Export or a completed comparison. Replaying runs with compound-eye or FlyVis input requires graphics access, and FlyVis runs need the vision lock. Compare runs using the same dependency stack; other hardware or graphics implementations may produce numerical differences.

Benchmark numbers describe the machine and workload that produced them. The repository does not impose a particular device or promise a fixed simulation speed. See [sharing the project](../SHARING.md) before intentionally including generated evidence in a public release.
