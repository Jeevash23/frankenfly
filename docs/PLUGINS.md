# Plugins

**Plugin API version 1** (DigitalFly 0.7, `digitalfly.plugins.API_VERSION`). This page is the reference for writing a plugin. A change that breaks a plugin written against it raises the version, and DigitalFly lists plugins written for another version as incompatible instead of loading them.

A plugin adds things to DigitalFly without forking it:

- **sensors**: replace the geometric encoder's two values;
- **stimulus programs**: write target and intervention schedules;
- **scorecard tests**: add tests to the validation scorecard;
- **metrics**: compute numbers on saved runs;
- **toolkit commands**: add commands to `scripts/toolkit.py`.

Brain models are not part of API 1 (see [Not yet pluggable](#not-yet-pluggable)).

[`examples/plugins/digitalfly-example-plugin`](../examples/plugins/digitalfly-example-plugin) is a complete plugin with one of each. Copy it to start your own.

## The ground rules

- **Nothing runs until it is named.** A plugin's code is imported when DigitalFly lists the installed plugins, but no contribution runs unless a run, a scorecard, a metric request or a command names it as `plugin:name`.
- **Defaults never change.** Installing a plugin changes no default setting and no built-in scorecard test. It doesn't change the numbers, hashes, exports or replay of any run made without it.
  - `RunConfig.plugins` is left out of every serialized configuration when it is unset, so configuration hashes and exported metadata stay byte for byte the same.
  - Scorecards that include plugin tests are never published as the app's latest card for a model.
- **Runs record what they used.** A run that uses a plugin records each contribution in its export: the plugin, its distribution, version, kind and the API version.
  - In `metadata.json` (`plugins`).
  - In the RO-Crate manifest (a `SoftwareApplication` per contribution, linked from the run).
  - In the methods draft.
  - Scorecards record their plugin tests in `plugins` and on each test. Metric results name their plugin and version.
- **Broken plugins are listed, not fatal.** A plugin that fails to import, gives the wrong object, or has an invalid contribution is listed with its error and never used. So is one written for another API version, or one whose name another plugin also uses.
- **A plugin is code with your permissions.** Install only plugins you trust, as with any Python package.
- **Turning plugins off.** `DIGITALFLY_PLUGINS=0` stops discovery.

## Packaging

A plugin is an installed Python distribution with one entry point in the `digitalfly.plugins` group:

```toml
# pyproject.toml
[project]
name = "my-fly-plugin"
version = "0.1.0"
dependencies = []          # DigitalFly itself is not declared: the plugin runs in DigitalFly's environment

[project.entry-points."digitalfly.plugins"]
myplugin = "my_fly_plugin:plugin"
```

The entry point's name (`myplugin`) is the plugin's name. It must match `[a-z0-9][a-z0-9_.-]{0,63}`, and it is the prefix of every contribution: `myplugin:crossed`. The plugin's version is its distribution's version.

The object the entry point names is a `digitalfly.plugins.Plugin`, or a function without arguments that returns one.

Install the plugin into DigitalFly's environment:

```sh
backend/.venv/bin/python -m pip install --no-deps -e path/to/my-fly-plugin
backend/.venv/bin/python scripts/toolkit.py plugins          # what is installed, and any errors
```

The app lists installed plugins on the Experiments page (**Plugins**), at `GET /api/plugins`, through `Client.plugins()`, and through the MCP tool `list_plugins`. Restart the app after installing or updating a plugin: each process discovers plugins once.

## `Plugin`

```python
from digitalfly.plugins import Plugin

plugin = Plugin(
    api_version=1,                 # required: the API this plugin was written for
    title="My fly plugin", description="...", url="https://...", license="MIT",
    sensors=(...), stimuli=(...), scorecard_tests=(...), metrics=(...), commands=(...),
)
```

Every contribution has a `name` (an `id` for scorecard tests) that is unique within its plugin and kind, and matches the same pattern as plugin names.

## Sensors

```python
from digitalfly.plugins import Sensor

def crossed(reading):               # reading: digitalfly.plugins.SensorReading
    return reading.geometric_right, reading.geometric_left

Sensor("crossed", "Crossed eyes", crossed, description="...")
```

A sensor replaces the two values (left, right) that the geometric encoder gives the neural model, once per 10 ms control interval. It works with either brain, either body, the geometric sensor model, and in the app, the toolkit and comparisons.

**What the sensor gets.** `SensorReading` holds:

- `t` (s) and `step`;
- the pose: `x`, `y` (mm), `yaw` (rad), `velocity` (mm/s);
- the target: `target_x`, `target_y`, `intensity`;
- the built-in encoder's values: `geometric_left` and `geometric_right`;
- the target's `bearing_rad` (positive = left) and `distance_mm`.

**What DigitalFly does with the result.** It must be two finite numbers, which DigitalFly clips to `[0, 1]`. It is recorded as `raw_left` and `raw_right`. Input interventions (`zero_left`, `zero_right`) still apply after the sensor.

**Determinism.** A sensor must be a deterministic function of its reading: no clocks, no global random state and no state carried between calls. Otherwise its runs do not replay.

**Using one.** Name the sensor in the configuration:

```python
RunConfig(engine="toy", plugins={"sensor": "myplugin:crossed"})
```

The sensor model must be `geometric`. A run that uses a sensor needs the plugin to be installed, at the same version, to replay. Its metadata says which plugin and version that is.

## Stimulus programs

```python
from digitalfly.plugins import StimulusProgram

def zigzag(every_steps=100, jumps=4):
    return {"name": "Zigzag", "duration_steps": jumps * every_steps,
            "events": [{"step": k * every_steps, "stimulus": {"x": 10, "y": 6 if k % 2 == 0 else -6}}
                       for k in range(jumps)]}

StimulusProgram("zigzag", "Zigzag target", zigzag, parameters={"every_steps": 100, "jumps": 4})
```

A program returns a `Protocol` (or its dict). Events are at control steps, and each can carry a `stimulus` and/or `interventions`. `parameters` lists the program's parameters with their defaults (numbers, text or booleans).

`digitalfly.plugins.stimulus_protocol("myplugin:zigzag", jumps=6)` runs the program and validates the result. Put the result in the configuration, and name the program in `plugins` so the run records it:

```python
protocol = plugins.stimulus_protocol("myplugin:zigzag", jumps=6)
RunConfig(protocol=protocol, plugins={"stimulus": "myplugin:zigzag", "stimulus_parameters": {"jumps": 6}})
```

The run keeps the schedule itself, so it replays without the plugin. The program is attribution only.

## Scorecard tests

A scorecard test is written like the built-in tests in `digitalfly/scorecard.py`. It gives the matched-seed conditions to run, then scores their trials by a rule fixed in advance.

```python
from digitalfly.plugins import ScorecardTest

ScorecardTest(
    id="target_side", title="Target 45° to one side → turning toward it",
    source={"citation": "...", "doi": "...", "finding": "..."},
    manipulation="...", measure="...", rule="pass: ...; partial: ...; fail: ...",
    cell_types=[["DNa02"]],          # groups of accepted names; the first found in each group is used
    needs=["walk", "turn"],          # capabilities (scorecard.CAPABILITY_TEXT); others make the test "blocked"
    conditions=conditions,           # (names, dynamics) -> [(label, Stimulus, Interventions), ...]
    score=score,                     # (names, trials) -> (status, measured)
    caveats=["..."],
)
```

**Before any trial runs.** Cell types missing from the circuit make the test `not_testable`, and so does the engineered model whenever `cell_types` is not empty. Missing capabilities make it `blocked`.

**`conditions`.** It gets the resolved cell-type names and the dynamics (`rate` or `spiking`), and returns the conditions to run. Labels need only be unique within the test.

**`score`.** It gets the trial rows, each with:

- `condition` (your label) and `seed`;
- the measures of `scorecard.trial_metrics`: `yaw_rate_deg_s`, `early_yaw_rate_deg_s`, `rotational_speed_deg_s` and `forward_velocity_mm_s`;
- `mean_speed_mm_s`.

It returns a status (`pass`, `partial`, `fail` or `inconclusive`) and a dict with at least `value`, `unit` and `text`.

**Running plugin tests.** They run only when asked for:

```sh
scripts/toolkit.py scorecard --model engineered --plugin-tests myplugin:target_side   # or --plugin-tests all
```

```python
scorecard.run(Target("engineered"), tests=[], plugins=["myplugin:target_side"])     # tests=[]: no built-in tests
```

Cards that include plugin tests are saved under `runs/toolkit/`, never published as the app's latest card.

## Metrics

```python
from digitalfly.plugins import Metric

def straightness(run):              # run: digitalfly.plugins.ExportedRun
    x, y = run.columns["x_mm"], run.columns["y_mm"]
    ...
    return {"straightness": ..., "path_mm": ...}

Metric("straightness", "Path straightness", straightness, unit="ratio", description="...")
```

A metric reads a saved run as an `ExportedRun`:

- `path`: the run folder;
- `metadata`: `metadata.json`;
- `columns`: every numeric column of `telemetry.csv` as a list of floats (`time_s`, `x_mm`, `y_mm`, `yaw_rad`, `speed_mm_s`, `sensor_l`, the rate and motor columns, and so on).

It returns a number, a flat dict of numbers, or `None` when it does not apply.

A metric that raises gives an error entry, and the other metrics still run. Metrics never change the run folder.

Ways to compute metrics:

- `scripts/toolkit.py metrics runs/<run> [--metric myplugin:straightness]`
- `GET /api/runs/KEY/metrics[?metric=myplugin:straightness]`
- `Client.run_metrics(key)`
- the MCP tool `run_metrics`

## Toolkit commands

```python
from digitalfly.plugins import Command

def add_arguments(parser):          # an argparse parser
    parser.add_argument("runs", nargs="+")

def run(args):
    ...

Command("straightness", "Print the path straightness of saved runs", run, add_arguments)
```

Commands appear as `scripts/toolkit.py myplugin:straightness`. The prefix means a plugin can never replace or shadow a built-in command. Save results under `runs/toolkit/` as the built-in commands do. The MCP server's `run_toolkit` tool can run plugin commands too.

## Not yet pluggable

**Brain models.** The neural interface is not stable enough to publish yet. A circuit takes sensor values and interventions, steps on the 1 ms neural clock, gives readouts and a motor command, describes itself for exports, and is replayed bit for bit. GPU backends are being added to it now, and every part of that contract is tested against the built-in models. Plugin brains are planned for a later API version, once that interface settles.

**Senses other than the two-channel visual input.** Olfaction, taste and mechanosensation (roadmap track G) will extend `SensorReading`. That will be API version 2.

## Versioning

- `API_VERSION` changes only when a published name, signature or behaviour on this page changes incompatibly.
- Additions, such as new optional fields on `SensorReading` or new contribution kinds, keep the version.
- A plugin declares the version it was written for. DigitalFly loads only plugins whose version matches its own, and lists the others with the reason.
