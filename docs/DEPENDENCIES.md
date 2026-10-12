# Dependencies and platform requirements

## Requirements

- A POSIX shell for the launch/setup scripts.
- Python **3.12**, selected from PATH or supplied explicitly through `PYTHON_BIN`.
- Node.js **24–26** and npm for installing/building the frontend.
- An offscreen OpenGL context for the body camera and compound-eye sensing. Geometric sensing with `--no-render` can run without those images.

No GPU or CUDA installation is required. Setup creates a project-local `backend/.venv`; it does not install drivers or change system settings. Each checkout should create its own environment and frontend dependencies.

Reference validation covers macOS/ARM64. Linux/EGL and other environments have not been validated by this project. Use the commands below to check a new environment rather than treating one platform's results as a compatibility guarantee.

## Chosen stack

**FlyGym distribution `flygym==2.1.0`**, with the current v2 composition/simulation API. No `flygym-gymnasium` distribution is installed. The paper's NeuroMechFly v2 body model and the Python package's 2.x API are distinct version labels.

| Dependency | Tested version |
| --- | --- |
| Python requirement | `>=3.12,<3.13` |
| FlyGym | 2.1.0 |
| MuJoCo | 3.9.0 |
| NumPy | 2.5.3 |
| SciPy | 1.18.1 |
| Numba | 0.67.0 |
| Pillow | 12.3.0 |
| FastAPI / Starlette | 0.141.1 / 1.6.0 |
| Uvicorn | 0.53.0 |
| Pydantic | 2.13.5 |
| websockets | 17.1 |
| psutil | 7.2.2 |
| pytest / httpx | 9.1.1 / 0.28.1 |
| pip-tools | 7.5.3 |
| Node requirement | 24–26 |
| React / React DOM | 19.3.0 |
| Vite / React plugin | 7.3.6 / 5.2.0 |
| TypeScript | 5.9.3 |
| Prettier (formatting) | 3.9.9 |

Full transitive versions and hashes: `backend/requirements.lock`, generated from `backend/pyproject.toml` with pip-tools. The lock includes the test extra. Frontend versions/integrity hashes: `frontend/package-lock.json`. All direct frontend imports are local packages. No PyTorch, JAX, Brian2, CUDA or Warp stack is installed. `jaxtyping`, IPython, imageio, ffmpeg and Matplotlib are upstream FlyGym transitives; they are not speculative extra model stacks.

To deliberately regenerate the Python lock after editing the project specification:

```sh
PIP_CACHE_DIR="$PWD/.cache/pip" PIP_TOOLS_CACHE_DIR="$PWD/.cache/pip-tools" \
  backend/.venv/bin/pip-compile --extra test --generate-hashes \
  --output-file backend/requirements.lock backend/pyproject.toml
```

Do not hand-maintain an additional requirements file. Setup installs from the lock using `--require-hashes`, then installs the local source without resolving dependencies again.

## Official references checked

- [FlyGym installation](https://neuromechfly.org/installation/)
- [API migration: 1.x versus 2.x](https://neuromechfly.org/migration/)
- [FlyGym source](https://github.com/NeLy-EPFL/flygym)
- [Pinned 2.1.0 source](https://github.com/NeLy-EPFL/flygym/tree/v2.1.0)
- [Turning-controller tutorial](https://neuromechfly.org/tutorials/4d_turning_controller/)
- [Model composition](https://neuromechfly.org/tutorials/1a_basic_model_composition/)
- [Simulation API](https://neuromechfly.org/api_reference/flygym/simulation/)
- [Legacy Gymnasium documentation](https://gymnasium.neuromechfly.org/), identified as a separate API; not mixed into this implementation
- [FastAPI](https://fastapi.tiangolo.com/)
- [Vite setup](https://vite.dev/guide/)

Actual installed Python source was inspected for `make_locomotion_fly`, `HybridTurningController`, `HybridControllerObservation`, `LocomotionAction`, `apply_locomotion_action`, reset/warmup and renderer ownership. Installed package APIs were then executed.

## Reproducing validation

After setup, run from the repository root:

```sh
./scripts/check.sh
backend/.venv/bin/python -m pip check
backend/.venv/bin/python scripts/smoke_flygym.py
backend/.venv/bin/python scripts/benchmark.py
backend/.venv/bin/python scripts/benchmark.py --vision
```

The full checks and benchmarks require graphics access. `./scripts/check.sh --fast` intentionally omits FlyGym integration tests and does not establish graphics/body compatibility. To test a running local server, use `backend/.venv/bin/python scripts/probe_local.py`; it advances and resets that server's experiment.

The [status summary](../STATUS.md) records the reference results. [Evidence instructions](evidence/README.md) explain generated outputs, replay and the version-control boundary. Raw logs and device-specific measurements stay local. Benchmark throughput and memory vary with hardware, graphics setup and load.

The reference test stack emitted two upstream deprecation notices (Starlette's httpx adapter and an AnyIO alias); they were not test failures.

## Assets and optional FlyVis review

The FlyGym 2.1.0 wheel was approximately **3.16 MB** and includes simplified NeuroMechFly meshes (at most 2,000 faces per segment), rigging, poses and the walking data used here. Normal startup requires **no extra asset download**. The package supports optional high-resolution meshes from EPFL, but those were not requested or downloaded. If added later, its cache is configured to `data/flygym-assets`, not a global personal directory.

Environment, package-cache and asset sizes vary by platform. They are excluded from the public repository and recreated locally during setup.

Stretch investigation checked [FlyVis's official implementation](https://github.com/TuragaLab/flyvis), [installation instructions](https://turagalab.github.io/flyvis/install/), and its current package/downloader source. It adds PyTorch, TorchVision and a separate scientific stack; the upstream downloader uses Google Drive pretrained ZIP archives and an API-key workflow. No verified drop-in FlyGym 2.1 bridge was found in the installed release; the published NeuroMechFly integration referenced the older API. Archive sizes were not established from unauthenticated metadata, so **no optional model archive was downloaded**. Integration is deferred, not passed or silently replaced with invented wiring.


## v0.2 research dependencies

The research features use the existing pinned runtime packages; no extra GPU framework or pretrained model is required. The verified FlyGym 2.1 APIs used are `BaseFly.add_vision`, `Simulation.get_raw_vision`, `Retina.raw_image_to_hex_pxls`, `Simulation.get_joint_angles` and `Simulation.get_bodysegment_contact_forces`. The actual installed Python source was inspected before integration. Eye cameras use the upstream 512×450 fisheye retina and 721 ommatidia per eye.

Anatomy data was downloaded from the official MaleCNS v1.0 bucket and the Bates/Lee lab FAFB v783 compilation. Small surface files came from navis-flybrains; no navis, trimesh, PyTorch, JAX or new graphics dependency was installed. A narrow NumPy reader handles the retained, hash-verified PLY assets. Details, sizes, coordinate assumptions and licensing: [RESEARCH.md](RESEARCH.md).

Reproduce these checks using the commands above. Generated results belong in the ignored evidence directory; the public repository retains generic instructions and the validation summary.
