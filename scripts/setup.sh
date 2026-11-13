#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
usage() {
  cat <<'EOF'
Usage: ./scripts/setup.sh [--backend-only] [--with builder,flyvis,recording,nwb,mcp] [--check]

  (no options)     Python environment from the hashed locks, then the web interface (needs Node.js)
  --backend-only   skip Node.js and the web interface: the toolkit, replay and tests still work
                   (for clusters and CI)
  --with LIST      also install optional parts, comma-separated:
                     builder    pyarrow (backend/requirements-data.lock), then prepare the FlyWire
                                archive for circuit builds (about 61 MB of downloads)
                     flyvis     FlyVis with CPU-only PyTorch (backend/requirements-vision.lock, about
                                261 MB), then its pretrained networks (3.4 MB)
                     recording  the recorded-fly data in data/recordings/downloads.json (71 MB)
                     nwb        pynwb for NWB export of saved runs (backend/requirements-nwb.lock,
                                about 20 MB)
                     mcp        the MCP Python SDK for scripts/mcp.py, the server agents such as Claude
                                Code use (backend/requirements-mcp.lock, about 2 MB)
  --check          run scripts/doctor.py at the end and fail if it finds a blocking problem

Run it again after every git pull: it reinstalls only what the locks changed. See docs/INSTALL.md.
EOF
}
BACKEND_ONLY=0
CHECK=0
EXTRAS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --backend-only) BACKEND_ONLY=1 ;;
    --check) CHECK=1 ;;
    --with=*) EXTRAS="$EXTRAS ${1#--with=}" ;;
    --with)
      [ $# -gt 1 ] || { echo "--with needs a list, for example --with builder,flyvis,recording"; exit 2; }
      shift
      EXTRAS="$EXTRAS $1" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 2 ;;
  esac
  shift
done
EXTRAS=$(echo "$EXTRAS" | tr ',' ' ')
for extra in $EXTRAS; do
  case "$extra" in
    builder|flyvis|recording|nwb|mcp) ;;
    *) echo "Unknown --with part: $extra (choose from builder, flyvis, recording, nwb, mcp)"; exit 2 ;;
  esac
done
wants() {
  case " $EXTRAS " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
if [ "$BACKEND_ONLY" = 0 ]; then
  if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
    echo "Node.js 22.12 or newer (below 27) with npm is required. Install it before running setup, or run ./scripts/setup.sh --backend-only for the Python side alone."
    exit 1
  fi
  node -e 'const [m,n]=process.versions.node.split(".").map(Number); if(m<22 || (m===22 && n<12) || m>=27) {console.error("Need Node >=22.12 and <27, found "+process.versions.node);process.exit(1)}'
fi
is_python312() {
  [ -n "$1" ] && "$1" -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>/dev/null
}
# 3.12 is the default and the recorded replay stack; PYTHON_BIN may also select 3.13 or 3.14.
is_supported_python() {
  [ -n "$1" ] && "$1" -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,15)' 2>/dev/null
}
if [ ! -x backend/.venv/bin/python ]; then
  if [ -n "${PYTHON_BIN:-}" ]; then
    DIGITALFLY_PYTHON="$PYTHON_BIN"
  elif command -v python3.12 >/dev/null; then
    DIGITALFLY_PYTHON=$(command -v python3.12)
  else
    DIGITALFLY_PYTHON=$(command -v python3 || true)
  fi
  if ! is_python312 "$DIGITALFLY_PYTHON" && [ -z "${PYTHON_BIN:-}" ] && command -v uv >/dev/null; then
    # uv keeps its own Python builds in its data folder; system Python is never changed.
    DIGITALFLY_PYTHON=$(uv python find 3.12 2>/dev/null || true)
    if ! is_python312 "$DIGITALFLY_PYTHON"; then
      echo "No Python 3.12 found. Installing a uv-managed Python 3.12 (about 30 MB download)..."
      uv python install 3.12
      DIGITALFLY_PYTHON=$(uv python find 3.12)
    fi
    echo "Using uv-managed Python: $DIGITALFLY_PYTHON"
  fi
  if [ -n "${PYTHON_BIN:-}" ]; then
    if ! is_supported_python "$DIGITALFLY_PYTHON"; then
      echo "PYTHON_BIN must be Python 3.12, 3.13 or 3.14 (3.12 recommended). System Python will not be changed."
      exit 1
    fi
  elif ! is_python312 "$DIGITALFLY_PYTHON"; then
    echo "Python 3.12 is required. Install a local Python 3.12 (or uv), then run PYTHON_BIN=/path/to/python3.12 ./scripts/setup.sh. System Python will not be changed."
    exit 1
  fi
  "$DIGITALFLY_PYTHON" -m venv backend/.venv
fi
backend/.venv/bin/python -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,15), "Project environment requires Python 3.12, 3.13 or 3.14"'
if ! is_python312 backend/.venv/bin/python; then
  echo "Note: Python 3.12 is the recorded stack. On other versions FlyVis is unavailable and exact replay of recorded runs is not guaranteed."
  if wants flyvis; then
    echo "--with flyvis needs Python 3.12 (FlyVis caps it). Recreate the environment: rm -rf backend/.venv, then run setup with Python 3.12."
    exit 1
  fi
fi
export PIP_CACHE_DIR="$PROJECT_ROOT/.cache/pip"
export PIP_TOOLS_CACHE_DIR="$PROJECT_ROOT/.cache/pip-tools"
# pip itself, pip-tools and setuptools come from a hashed lock too, before any other install.
backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-tools.lock
backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements.lock
backend/.venv/bin/python -m pip install --no-deps --no-build-isolation -e backend
mkdir -p .cache
# Build Matplotlib's font cache now (about 20 s, once) so the first launch and the first
# test run start quickly. This only reads local fonts; nothing is downloaded.
echo "Preparing first-run caches..."
MPLCONFIGDIR="$PROJECT_ROOT/.cache/matplotlib" FLYGYM_ASSET_CACHE_DIR="$PROJECT_ROOT/data/flygym-assets" \
  backend/.venv/bin/python -c 'import matplotlib.font_manager, flygym, flygym_demo.complex_terrain' \
  || echo "Warning: first-run caches were not prepared; the first launch may be slower."
# Optional parts: each lock includes the runtime lock's pins, so these never change the app's own packages.
if wants builder; then
  echo "Installing the circuit builder (pyarrow) and preparing the FlyWire archive..."
  backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-data.lock
  backend/.venv/bin/python scripts/build_circuit.py prepare
fi
if wants flyvis; then
  echo "Installing FlyVis with CPU-only PyTorch and fetching its pretrained networks..."
  backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-vision.lock
  backend/.venv/bin/python scripts/fetch_flyvis.py
fi
if wants nwb; then
  echo "Installing pynwb for NWB export..."
  backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-nwb.lock
fi
if wants mcp; then
  echo "Installing the MCP Python SDK for scripts/mcp.py..."
  backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements-mcp.lock
fi
if wants recording; then
  for name in $(backend/.venv/bin/python -c 'import json; print(" ".join(r["name"] for r in json.load(open("data/recordings/downloads.json"))))'); do
    backend/.venv/bin/python scripts/fetch_recording.py "$name"
  done
fi
if [ "$BACKEND_ONLY" = 0 ]; then
  LOCK_HASH=$(node -e 'const fs=require("fs"),crypto=require("crypto");process.stdout.write(crypto.createHash("sha256").update(fs.readFileSync("frontend/package-lock.json")).digest("hex"))')
  if [ ! -d frontend/node_modules ] || [ ! -f .cache/frontend-lock.sha256 ] || [ "$(cat .cache/frontend-lock.sha256)" != "$LOCK_HASH" ]; then
    npm --prefix frontend ci --cache "$PROJECT_ROOT/.cache/npm" --no-fund --no-audit
    printf '%s' "$LOCK_HASH" > .cache/frontend-lock.sha256
  else
    echo "Frontend dependencies match the lockfile; keeping the existing installation."
  fi
  npm --prefix frontend run build
fi
if [ "$CHECK" = 1 ]; then
  echo
  if [ "$BACKEND_ONLY" = 1 ]; then
    backend/.venv/bin/python scripts/doctor.py --backend-only
  else
    backend/.venv/bin/python scripts/doctor.py
  fi
fi
if [ "$BACKEND_ONLY" = 1 ]; then
  echo "Backend setup complete. The toolkit, replay and tests work now; the web interface needs ./scripts/setup.sh without --backend-only."
else
  echo "Setup complete. Launch with ./scripts/start.sh"
fi
