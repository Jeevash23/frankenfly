# Examples

Two short scripts that use DigitalFly from Python. Run them from the repository root after `./scripts/setup.sh`. Results describe this simulation, not flies.

| Script | What it shows | Needs |
| --- | --- | --- |
| [`drive_app.py`](drive_app.py) | Drives the running app with `digitalfly.client`: a target on the left, DNa02 silenced on one side and then restored, the net turn in each phase, and a share-safe export | The app running (`./scripts/start.sh`, or `backend/.venv/bin/python scripts/launch.py --toy`) |
| [`batch_seeds.py`](batch_seeds.py) | Runs trials over seeds, two targets and rate or spiking dynamics with `digitalfly.toolkit`, in parallel and without the app; saves each trial as it finishes and prints reaching, first turns, final distance and motor clipping with 95% intervals | Nothing else |

```sh
backend/.venv/bin/python examples/drive_app.py --engine toy --seconds 2
backend/.venv/bin/python examples/batch_seeds.py --seeds 1-10 --workers 4
backend/.venv/bin/python examples/batch_seeds.py --seeds 1-10 --workers 4 --resume  # runs only what is missing
```

`drive_app.py` changes the app's one experiment, so the browser shows it while it runs. `batch_seeds.py` writes `runs/toolkit/batch-seeds.jsonl` and `.csv` (ignored by git; `--out` chooses another stem) and summarizes this batch's trials only, even when the log holds earlier ones. Run it as a script: its parallel workers are new processes that import the file, which an interactive prompt cannot provide.

See [Scripting the app from Python](../docs/USAGE.md#scripting-the-app-from-python) for the client and [the research toolkit](../docs/RESEARCH.md#the-research-toolkit) for the toolkit, its command-line version (`scripts/toolkit.py`) and its statistics. Both scripts are run by the test suite (`backend/tests/test_client.py`), so they stay in step with the code.
