#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$PROJECT_ROOT/backend/.venv/bin/python" ]; then
  echo "Project environment missing. Run ./scripts/setup.sh first."
  exit 1
fi
export PYTHONPATH="$PROJECT_ROOT/backend/src"
exec "$PROJECT_ROOT/backend/.venv/bin/python" "$PROJECT_ROOT/scripts/launch.py" "$@"
