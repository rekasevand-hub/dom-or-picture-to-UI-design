#!/usr/bin/env bash
# 固定运行环境的一键流水线封装（Phase 0 ③环境固化）
# 用法: bash scripts/run_image_pipeline.sh --image <img> --truth <truth> --out <dir> [--acceptance-policy 2.0 ...]
# 其余参数原样透传给 scripts/image_figma_mvp.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${OMNI_PYTHON:-C:/Users/lzq/.conda/envs/omni/python.exe}"

if [ ! -x "$PY" ] && [ ! -f "$PY" ]; then
  echo "[error] python not found: $PY (set OMNI_PYTHON to override)" >&2
  exit 2
fi

cd "$ROOT"
export GROUNDING_FIDELITY_MODE=high
export IMAGE_ENRICHMENT_MODE=apply

exec "$PY" scripts/image_figma_mvp.py "$@"
