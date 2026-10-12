#!/bin/sh
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
if [ "${1:-}" = "--fast" ]; then
  backend/.venv/bin/python -m pytest backend/tests -m 'not flygym' -q
else
  backend/.venv/bin/python -m pytest backend/tests -q
fi
npm --prefix frontend run format:check
npm --prefix frontend test
npm --prefix frontend run build
