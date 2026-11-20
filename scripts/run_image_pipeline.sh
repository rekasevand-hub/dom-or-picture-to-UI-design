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

# 默认走阶段二的三路物理分权感知：build_physical_plan（CV 容器 + OCR 文字 +
# OmniParser 图标）-> fixed_canvas_compiler -> Figma Bridge。
#
# GROUNDING_FIDELITY_MODE=high / IMAGE_ENRICHMENT_MODE=apply 是第一阶段的
# 全图 VLM grounding 路线要的开关，默认不再注入：那条路会把 physical_perception
# 与编译器优化整段绕过去，而 CLI 上完全看不出来。真的要走老路线时显式：
#   IMAGE_ROUTE=grounding GROUNDING_FIDELITY_MODE=high IMAGE_ENRICHMENT_MODE=apply #     bash scripts/run_image_pipeline.sh --image ... --truth ... --out ...
ROUTE="${IMAGE_ROUTE:-physical}"

exec "$PY" scripts/image_figma_mvp.py --route "$ROUTE" "$@"
