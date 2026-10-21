#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
PY=backend/.venv/bin/python
if [ "${1:-}" = "--fast" ]; then
  $PY -m pytest backend/tests -m 'not flygym' -q
elif [ -z "${MUJOCO_GL:-}" ] && [ "$(uname -s)" = Linux ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] \
  && command -v xvfb-run >/dev/null \
  && ! MUJOCO_GL=egl $PY -c 'import mujoco; c = mujoco.GLContext(16, 16); c.make_current(); c.free()' >/dev/null 2>&1; then
  # Headless without a usable EGL: GLFW on a virtual X display renders the physics tests instead.
  echo "No display and EGL is unavailable; running the tests under xvfb-run with MUJOCO_GL=glfw."
  xvfb-run -a env MUJOCO_GL=glfw $PY -m pytest backend/tests -q
else
  $PY -m pytest backend/tests -q
fi
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
