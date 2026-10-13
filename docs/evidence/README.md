# Local validation evidence

This directory is reserved for generated test logs, screenshots, probe results and benchmark measurements. Only this README is included in version control. Other files can contain local paths, operating-system details, timestamps or session identifiers and remain local by default.

The [status summary](../../STATUS.md) records the reference validation without personal paths or raw run identifiers.

## Run the checks

After setup, run these commands from the repository root:

```sh
./scripts/check.sh
backend/.venv/bin/python -m pip check
backend/.venv/bin/python scripts/smoke_flygym.py
backend/.venv/bin/python scripts/benchmark.py
backend/.venv/bin/python scripts/benchmark.py --vision
backend/.venv/bin/python scripts/benchmark.py --model connectome_dna02
backend/.venv/bin/python scripts/evaluate_models.py --engine toy
backend/.venv/bin/python scripts/evaluate_models.py --engine flygym --quick
```

The full tests, smoke test and rendered benchmarks require a working graphics context. The evaluation script writes `evaluation-*.json` here and prints the tables summarized in the [research guide](../RESEARCH.md#evaluation). `./scripts/check.sh --fast` omits the FlyGym integration tests when only the remaining checks are needed.

The smoke script writes a JSON report and PNG here. Benchmark scripts write sensor-specific JSON reports here. To keep console output, redirect it into a local log:

```sh
./scripts/check.sh > docs/evidence/check.log 2>&1
```

## Browser and server checks

Start the app with `./scripts/start.sh --vision --open`. Exercise Run, Pause, Step, target movement, circuit parameters, anatomical selection, a short comparison and Export. Use Quit to shut down the server.

For an automated HTTP/WebSocket probe while the app is running:

```sh
backend/.venv/bin/python scripts/probe_local.py
```

The probe advances and resets that local experiment. It is intended for a test session.

## Replay a local export

```sh
backend/.venv/bin/python scripts/replay.py runs/YOUR_RUN_FOLDER
```

Replace `YOUR_RUN_FOLDER` with a directory created by Export or a completed comparison. Vision replay requires graphics access. Compare runs using the same dependency stack; other hardware or graphics implementations may produce numerical differences.

Benchmark numbers describe the machine and workload that produced them. The repository does not impose a particular device or promise a fixed simulation speed. See [sharing the project](../SHARING.md) before intentionally including generated evidence in a public release.
