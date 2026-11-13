#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$PROJECT_ROOT/backend/.venv"
# --gpu: run from the GPU environment (./scripts/setup.sh --with gpu), so the torch brain backend is available.
for arg do
  shift
  if [ "$arg" = --gpu ]; then VENV="$PROJECT_ROOT/backend/.venv-gpu"; else set -- "$@" "$arg"; fi
done
if [ ! -x "$VENV/bin/python" ]; then
  if [ "$VENV" = "$PROJECT_ROOT/backend/.venv" ]; then
    echo "Project environment missing. Run ./scripts/setup.sh first; python3 scripts/doctor.py checks everything else."
  else
    echo "GPU environment missing. Run ./scripts/setup.sh --with gpu first."
  fi
  exit 1
fi
export PYTHONPATH="$PROJECT_ROOT/backend/src"
exec "$VENV/bin/python" "$PROJECT_ROOT/scripts/launch.py" "$@"
