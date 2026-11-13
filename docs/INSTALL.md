# Installing and updating DigitalFly

DigitalFly runs on your own computer: a Python server simulates the fly, and your browser shows it. There are four ways to install it:

| Route | Needs | Use it for |
| --- | --- | --- |
| [Native](#native-install) | Python 3.12, Node.js 22.12–26, OpenGL | Everyday use and development on Linux or macOS |
| [Docker](#docker) | Docker (Engine 23+, BuildKit) | Headless servers, a clean environment, Linux without the right Python |
| [Dev container](#dev-container-and-codespaces) | VS Code with Dev Containers, or Codespaces | Contributing without installing anything locally |
| [Windows through WSL2](#windows-through-wsl2) | WSL2 with Ubuntu 24.04 | Windows; there is no native Windows support |

Whatever the route, `python3 scripts/doctor.py` (or `docker run --rm digitalfly python scripts/doctor.py`) checks the result and prints a fix for anything missing.

## Native install

```sh
git clone https://github.com/Jeevash23/frankenfly.git
cd frankenfly
./scripts/setup.sh
./scripts/start.sh --open
```

Setup creates `backend/.venv` with Python 3.12 and installs the pinned, hashed locks (`backend/requirements-tools.lock`, then `backend/requirements.lock`), prepares the first-run caches, installs the frontend packages from `frontend/package-lock.json` and builds the interface. It never uses `sudo` and never changes system Python or system packages. Without Python 3.12 on the PATH it uses a [uv](https://docs.astral.sh/uv/)-managed one when uv is installed; otherwise run `PYTHON_BIN=/path/to/python3.12 ./scripts/setup.sh`.

Options:

| Option | What it does |
| --- | --- |
| `--backend-only` | Skips Node.js and the interface. The toolkit, replay and tests work; `start.sh` needs the interface. For clusters and CI |
| `--with builder` | Installs pyarrow (`backend/requirements-data.lock`) and prepares the FlyWire archive for circuit builds: about 61 MB of downloads, 115 MB in `.cache/circuits/` |
| `--with flyvis` | Installs FlyVis with CPU-only PyTorch (`backend/requirements-vision.lock`, about 261 MB of downloads on Linux) and its pretrained networks (3.4 MB). Python 3.12 only |
| `--with recording` | Downloads the recorded-fly data listed in `data/recordings/downloads.json` (71 MB) into `.cache/recordings/` |
| `--with nwb` | Installs pynwb for NWB export of saved runs (`backend/requirements-nwb.lock`, about 20 MB of downloads) |
| `--with mcp` | Installs the MCP Python SDK for `scripts/mcp.py`, the server that lets agents such as Claude Code drive the app (`backend/requirements-mcp.lock`, under 1 MB of downloads with the FlyVis and NWB locks installed, about 6.5 MB without); see [Agents and the MCP server](USAGE.md#agents-and-the-mcp-server) |
| `--check` | Runs `scripts/doctor.py` at the end and fails if it finds a blocking problem |

Combine parts with commas: `./scripts/setup.sh --with builder,flyvis,recording` replaces the five manual steps in the [research guide](RESEARCH.md#building-your-own-circuits) and [dependency notes](DEPENDENCIES.md#v05-optional-flyvis-vision-and-recorded-fly-data), which still work one by one. Every download is checked against a recorded size and SHA-256 before it is kept, and every Python package against the lock's hashes.

## Updating after `git pull`

```sh
git pull
./scripts/setup.sh            # add the same --with parts you installed before
```

Setup is safe to re-run. pip keeps packages that already match the locks and replaces only the pins that changed; the frontend packages are reinstalled only when `frontend/package-lock.json` changed; the interface is always rebuilt, so the launcher's stale-build check passes. `python3 scripts/doctor.py` confirms that every installed package matches `backend/requirements.lock`.

Start from a clean environment when a release changes the Python version, or removes a package from a lock (pip never uninstalls what a lock no longer lists):

```sh
rm -rf backend/.venv frontend/node_modules
./scripts/setup.sh
```

Saved runs are kept across updates. Replay is exact on the same software and graphics stack: when the [changelog](../CHANGELOG.md) says a lock changed NumPy, SciPy, Numba, MuJoCo or FlyGym, older runs may no longer match within `scripts/replay.py`'s tolerance, and it reports the largest difference.

- **Docker:** `git pull`, then `docker compose up --build` (or `docker build -t digitalfly .`). Runs and caches stay in their volumes.
- **Dev container:** re-run `./scripts/setup.sh` in the container; after a change to the `Dockerfile`, use **Dev Containers: Rebuild Container**.

## Docker

No prebuilt image is published: you build it from your checkout, which pulls the Ubuntu 24.04 and Node 24 base images and installs from the Ubuntu archive, PyPI (hashed locks) and npm (`frontend/package-lock.json`). It holds Python 3.12 with the hashed locks, the built interface and Mesa, which renders the 3D views and compound eyes on the CPU through EGL without a display or GPU (OSMesa as the fallback).

With Docker Compose:

```sh
docker compose up --build     # first build: about 5 minutes and 1.6 GB
```

Open http://localhost:8000. Stop with **Quit** in the app, Ctrl+C, or `docker compose down`. Saved runs, caches and downloads, presets saved in the app, circuits built in the app and imported connectivity are kept in named volumes (`digitalfly_runs`, `digitalfly_cache`, `digitalfly_presets`, `digitalfly_local-circuits`, `digitalfly_connectivity`) and survive `docker compose down`; `docker compose down --volumes` deletes them. Settings go in the environment or a `.env` file next to `docker-compose.yml`:

| Variable | Default | Effect |
| --- | --- | --- |
| `DIGITALFLY_PORT_ON_HOST` | 8000 | Host port to publish; its origins are allowed automatically |
| `DIGITALFLY_EXTRAS` | none | Optional parts built into the image: `flyvis`, `builder`, `recording`, comma-separated |
| `DIGITALFLY_UID` | 1000 | The container user's id, for bind mounts owned by another user (`id -u`) |

With plain Docker:

```sh
docker build -t digitalfly .
docker run --rm --init -p 127.0.0.1:8000:8000 \
  -v digitalfly_runs:/app/runs -v digitalfly_cache:/app/.cache -v digitalfly_presets:/app/configs/local digitalfly
```

Without `-v` for a folder, Docker gives it a new anonymous volume, which `--rm` deletes with the container: name the volumes to keep runs and presets.

Build arguments: `--build-arg EXTRAS=flyvis,builder,recording`, `--build-arg UID=$(id -u)`, and `--build-arg APT_MIRROR=https://...` for another Ubuntu archive. Command-line options go after the image name, for example `docker run ... digitalfly ./scripts/start.sh --toy`. The same image runs the other tools:

```sh
docker run --rm digitalfly python scripts/doctor.py
docker run --rm -v digitalfly_runs:/app/runs digitalfly python scripts/replay.py runs/YOUR_RUN_FOLDER
docker run --rm -v digitalfly_runs:/app/runs digitalfly python scripts/toolkit.py trials --workers 4
```

To see exports in your checkout's `runs/` folder, bind-mount it instead (`-v "$PWD/runs:/app/runs"`, or `./runs:/app/runs` in the compose file). The container user has uid 1000; if your account has another, build with `UID=$(id -u)`.

**Behind a proxy that inspects TLS**, give the build its CA certificate as a secret, which is used only during the build and stored nowhere in the image, and pass the proxy as a build argument (Docker never stores the standard proxy arguments in the image either):

```sh
docker build --secret id=ca,src=/path/to/proxy-ca.crt --build-arg HTTPS_PROXY="$HTTPS_PROXY" -t digitalfly .
```

A proxy that tunnels only HTTPS also needs an HTTPS Ubuntu archive: add `--build-arg APT_MIRROR=https://archive.ubuntu.com/ubuntu`.

**What the image contains.** It is meant to be built and run locally, not published. It includes the repository's data under their own licenses: FlyWire-derived circuits and atlas data are CC BY-NC 4.0 (non-commercial use only) and the anatomical surfaces carry a GPL-3.0 notice (see [ATTRIBUTION](ATTRIBUTION.md)). Optional parts add FlyVis and PyTorch (MIT and BSD), FlyWire downloads (CC BY-NC 4.0) and the recorded fly (CC0). Before pushing an image to a public registry, check that its licenses allow it.

**Replay across builds.** Python packages are pinned and hashed, so rebuilding the same commit installs the same numerical code. System packages, Mesa included, are whatever the Ubuntu 24.04 archive has on the build date; compound-eye inputs come from rendered pixels, so they are the most likely to change slightly in a rebuilt image. Keep the image (`docker save`) if you need bit-identical replay later.

The image was verified on x86-64 Linux with Docker Engine 29: build, the doctor, a FlyGym reset with compound-eye vision, rendered frames, export and exact replay inside the container, and the Host and Origin checks. The `flyvis` and `recording` parts could not be built there (their download hosts were unreachable), and ARM64 hosts (Apple silicon with Docker Desktop, Linux ARM) have not been tried.

### Listening beyond localhost

Natively, the server listens on `127.0.0.1` only, and it accepts only requests whose Host is `127.0.0.1` or `localhost` and browser commands only from its own page. There is no login: anyone who can reach the port can drive the simulation and write to `runs/`.

A published container port has to reach the server through the container's own network interface, so the image starts it with `DIGITALFLY_HOST=0.0.0.0` and the acknowledgement `DIGITALFLY_ALLOW_NETWORK_BIND=1`. The Host, Origin and JSON checks stay on. Publish the port to this computer only, as the compose file and the commands above do (`-p 127.0.0.1:8000:8000`): `-p 8000:8000` would make it reachable from your network.

The same settings work natively, for the rare case that needs them: `DIGITALFLY_ALLOW_NETWORK_BIND=1 ./scripts/start.sh --host 0.0.0.0`. Without the acknowledgement the launcher refuses any address other than `127.0.0.1` or `localhost`, `::1` included (the Host and Origin checks name only those two). When the browser reaches the app under another host name or port, for example a host port other than 8000, add that exact origin; its host name is then accepted as well:

```sh
DIGITALFLY_ALLOWED_ORIGINS=http://localhost:9000,http://127.0.0.1:9000
```

For a remote machine, prefer an SSH tunnel, which needs none of this: `ssh -L 8000:127.0.0.1:8000 server`, then open http://localhost:8000 on your own computer. On a shared machine, remember that other accounts on it can reach its `127.0.0.1` too.

## Dev container and Codespaces

`.devcontainer/devcontainer.json` builds the `Dockerfile`'s `dev` target: Ubuntu 24.04 with Python 3.12, Node 24, Mesa (EGL, OSMesa), Xvfb and git. Open the folder in VS Code and choose **Dev Containers: Reopen in Container**, or create a codespace. After the container is created, `./scripts/setup.sh --check` runs in it. The Python environment and the frontend packages live in volumes, so they never mix with a native install of the same checkout. Ports 8000 (`./scripts/start.sh`) and 5173 (`./scripts/dev.sh`) are forwarded; `./scripts/check.sh` runs every test, physics included, with EGL.

This was verified with the Dev Containers command-line tool 0.89 (post-create setup, doctor and `./scripts/check.sh`), not yet in VS Code itself or in Codespaces. A codespace's forwarded address is not `localhost`; if the app refuses commands there, allow that origin before starting: `export DIGITALFLY_ALLOWED_ORIGINS=https://$CODESPACE_NAME-8000.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`.

## Headless servers

Physics never needs a display; the 3D view and compound-eye sensing need an offscreen OpenGL context. Unless you set `MUJOCO_GL`, DigitalFly tries GLFW when there is a display, then EGL, then OSMesa, and uses the first that renders; `python3 scripts/doctor.py` shows which work. On a server without graphics libraries, install one of them (Debian and Ubuntu):

```sh
sudo apt install libegl1 libgl1-mesa-dri     # EGL on the CPU (Mesa llvmpipe), or a GPU's EGL driver
sudo apt install libosmesa6                  # OSMesa, the fallback; recent Mesa releases no longer build it
sudo apt install xvfb xauth                  # or a virtual display: MUJOCO_GL=glfw xvfb-run -a ./scripts/start.sh
```

Without any of them, physics still runs with the labeled pose map and geometric sensing (`--no-render`), and `--toy` runs the kinematic demo. `./scripts/setup.sh --backend-only` skips Node.js when you only need the toolkit. The Docker image already includes EGL and OSMesa. GPU rendering through NVIDIA's EGL driver (`MUJOCO_GL=egl`) should work but has not been tested.

## Windows through WSL2

There is no native Windows support: the scripts are POSIX shell. WSL2 with Ubuntu 24.04 should work as on Linux, but **this has not been tested**.

1. Install WSL2 with Ubuntu 24.04 (`wsl --install -d Ubuntu-24.04` in an administrator PowerShell).
2. In Ubuntu, install Python and the graphics libraries: `sudo apt install python3.12-venv libegl1 libgl1-mesa-dri`, and Node.js 24 (for example with [nvm](https://github.com/nvm-sh/nvm)).
3. Clone into the Linux file system (`~/frankenfly`, not `/mnt/c/...`, which is much slower), then run `./scripts/setup.sh --check` and `./scripts/start.sh`.
4. Open http://localhost:8000 in a Windows browser; WSL2 forwards `localhost`.

Docker Desktop with its WSL2 backend can run the [Docker image](#docker) instead; that is untested as well.

## Install problems

- **Anything:** `python3 scripts/doctor.py` (in Docker: `docker run --rm digitalfly python scripts/doctor.py`, or `docker exec` into a running container).
- **`Frontend build is stale` after a pull:** run `./scripts/setup.sh`, or just `npm --prefix frontend run build`.
- **The page loads but buttons do nothing, or "Origin is not permitted":** the browser address differs from the published one. Use `http://localhost:PORT`, or add the address to `DIGITALFLY_ALLOWED_ORIGINS`.
- **`Invalid host header`:** the request named a host other than `localhost` or `127.0.0.1`; add its origin to `DIGITALFLY_ALLOWED_ORIGINS`.
- **Permission denied writing `runs/` from a container, or saving a preset fails with "Presets cannot be saved":** a bind-mounted folder belongs to another user; build with `--build-arg UID=$(id -u)` or use the named volumes. `python3 scripts/doctor.py` lists the data folders it cannot write, and `GET /api/capabilities` reports `"presets": {"writable": false}`.
- **Downloads fail behind a proxy:** set `HTTPS_PROXY`, and for a TLS-inspecting proxy point `PIP_CERT`, `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS` at its CA certificate (Docker: the `ca` build secret above).
