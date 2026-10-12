#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo "Node.js 22.12 or newer (below 27) with npm is required. Install it before running setup."
  exit 1
fi
node -e 'const [m,n]=process.versions.node.split(".").map(Number); if(m<22 || (m===22 && n<12) || m>=27) {console.error("Need Node >=22.12 and <27, found "+process.versions.node);process.exit(1)}'
is_python312() {
  [ -n "$1" ] && "$1" -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>/dev/null
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
  if ! is_python312 "$DIGITALFLY_PYTHON"; then
    echo "Python 3.12 is required. Install a local Python 3.12 (or uv), then run PYTHON_BIN=/path/to/python3.12 ./scripts/setup.sh. System Python will not be changed."
    exit 1
  fi
  "$DIGITALFLY_PYTHON" -m venv backend/.venv
fi
backend/.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,12), "Project environment requires Python 3.12"'
export PIP_CACHE_DIR="$PROJECT_ROOT/.cache/pip"
export PIP_TOOLS_CACHE_DIR="$PROJECT_ROOT/.cache/pip-tools"
backend/.venv/bin/python -m pip install --disable-pip-version-check pip-tools==7.5.3 setuptools==84.0.0
backend/.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r backend/requirements.lock
backend/.venv/bin/python -m pip install --no-deps --no-build-isolation -e backend
mkdir -p .cache
# Build Matplotlib's font cache now (about 20 s, once) so the first launch and the first
# test run start quickly. This only reads local fonts; nothing is downloaded.
echo "Preparing first-run caches..."
MPLCONFIGDIR="$PROJECT_ROOT/.cache/matplotlib" FLYGYM_ASSET_CACHE_DIR="$PROJECT_ROOT/data/flygym-assets" \
  backend/.venv/bin/python -c 'import matplotlib.font_manager, flygym, flygym_demo.complex_terrain' \
  || echo "Warning: first-run caches were not prepared; the first launch may be slower."
LOCK_HASH=$(node -e 'const fs=require("fs"),crypto=require("crypto");process.stdout.write(crypto.createHash("sha256").update(fs.readFileSync("frontend/package-lock.json")).digest("hex"))')
if [ ! -d frontend/node_modules ] || [ ! -f .cache/frontend-lock.sha256 ] || [ "$(cat .cache/frontend-lock.sha256)" != "$LOCK_HASH" ]; then
  npm --prefix frontend ci --cache "$PROJECT_ROOT/.cache/npm" --no-fund --no-audit
  printf '%s' "$LOCK_HASH" > .cache/frontend-lock.sha256
else
  echo "Frontend dependencies match the lockfile; keeping the existing installation."
fi
npm --prefix frontend run build
echo "Setup complete. Launch with ./scripts/start.sh"
