# Architecture and scientific assumptions

## Closed loop

```text
Python world/body pose
        ↓
selected sensor encoder (geometric or rendered compound eye) ← stimulus
        ↓                          ← sensory channel interventions
six engineered leaky rate units    ← group silencing
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
- Neural circuit: declared two sensor values + silencing mask → six dimensionless continuous rates. No privileged target-coordinate shortcut reaches neural or motor code.
- Motor interface: neural descending rates × 1.4, clipped to `[0,1.4]` → upstream CPG amplitudes. The explicit baseline returns `[1,1]` regardless of rates and is labeled as a bypass.
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

Each control interval samples sensors, advances the neural model for ten substeps with those held observations, computes a motor pair, then advances physics 100 times with that held pair. CSV rows contain the sensor values actually used for that interval and the resulting body pose. They do not retrospectively replace the applied observation with a post-motion reading. While paused, moving a stimulus updates the instantaneous readout without advancing any dynamics.

FlyGym resets its neutral keyframe and seeded CPG, applies the upstream default leg posture, and performs a documented 50 ms body-only settling period. Application time is then set to zero. Reset restores the initial random-generator state, circuit, controller, recorder and clocks; the web Reset supplies the default target/intensity and clears interventions. The API Reset accepts an explicit initial RunConfig, including a custom starting stimulus.

## Ownership, memory, and failures

- One non-daemon Python thread creates, steps, renders and closes the body/context. The FastAPI event loop only handles messages and a shared snapshot.
- One queue, capacity **64**, serializes commands at control boundaries; cancelled pending commands are skipped. HTTP timeouts explicitly warn that an already executing command may finish.
- The display snapshot is replaceable, with **201** decimated history samples, **600** recent path points, **50** recent displayed events, and one JPEG. Full joint geometry exists only in the current sample.
- WebSocket clients have no accumulating application telemetry queues. Slow sends time out after two seconds; server WebSocket input queues are bounded. Disconnect tasks are cancelled and subscribers decremented. Multiple clients do not create bodies.
- Recording retains all samples since reset, limited to **30,000** samples (about 300 simulated seconds) and **10,000** scheduled events. It stops with an actionable error rather than evicting the replay prefix. Export/Reset is required to continue.
- Pydantic rejects unknown fields, nonfinite numbers, out-of-range seeds, target coordinates or speeds. Validation errors exclude raw nonfinite input so they serialize correctly.
- The body checks finite positions/velocities, extreme velocity, and MuJoCo numerical warning counters (MuJoCo can otherwise auto-reset to finite values). A failure enters the explicit error state and refuses Run until Reset.
- Render failure preserves real physics and labels the pose view, with the rendering error exposed. Body failure preserves the error and never switches silently to toy mode.

## Local boundary

Default bind is `127.0.0.1`, one Uvicorn worker, no reload. Trusted hosts are localhost and 127.0.0.1. Browser command and WebSocket origins are restricted to the configured local server and local Vite port. Browser mutations require JSON; cross-origin controls are rejected. Same-origin static assets, fonts, API, JPEG and WebSocket are served in built mode. Unknown `/api/...` paths stay API errors and do not fall through to the SPA.

The v0.2 structural connectivity importer validates and saves bounded graphs through `data/research.py`. IDs remain strings, provenance is mandatory, and counts remain structural counts. The active neural circuit is independent of imported anatomy/connectivity. No synthetic fixture is represented as biological data.


## v0.2 research extensions

`RunConfig` includes sensor selection, bounded neural parameters, initial interventions and an optional finite protocol. A protocol applies events at integer control-step boundaries and automatically pauses at its end. Manual and protocol events carry distinct source labels for replay.

Comparisons reuse the same authoritative worker and body. Each seed/condition pair resets all simulation state, holds its intervention, executes the protocol, exports a result and then begins the next trial. Pause/resume and cancellation are serialized through the command queue. Manual experimental mutations are rejected while a comparison is active. Results retain the batch identifier, condition and seed.

`data/research.py` reads local saved-run metadata and bounded trajectory samples. The browser transforms those samples into display coordinates; scientific metrics remain in Python. `body_signals.jsonl` retains the measured joint/contact/CPG state. Large joint arrays are omitted from display history but remain in the current sample and the recording.

`data/atlas` is static anatomical context: twelve identified neurons and specimen-specific reference surfaces. `scripts/build_atlas.py` validates source hashes and produces display geometry. It neither simulates those neurons nor maps their coordinates into the fly body. Source coordinates and units are retained; camera transforms live in the browser.

The local launcher creates a Uvicorn Server instance and provides its own shutdown callback. `/api/shutdown` requires the current instance ID, JSON and the existing local-origin restrictions, then requests graceful Uvicorn exit. The lifespan closes the owning worker and graphics contexts. It does not signal arbitrary PIDs or other servers.

Complete methods, data licensing and limitations are in [RESEARCH.md](RESEARCH.md).
