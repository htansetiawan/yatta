#!/usr/bin/env bash
# Development: API on :8790 (no render worker) and the Vite dev server on :5173 with hot reload.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && YATTA_WORKER=${YATTA_WORKER:-0} .venv/bin/python -m yatta.app --port 8790) &
trap 'kill %1' EXIT
cd web && npm run dev
