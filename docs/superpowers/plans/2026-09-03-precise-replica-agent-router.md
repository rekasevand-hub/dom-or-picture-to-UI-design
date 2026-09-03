# 精准复刻 Agent（三源路由）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Figma_auto_agent 中实现"URL/截图 → 按用户选择路由（dom/a11y/grounding/cv）→ PageGraph → SoM 标注 → VLM 生成 DesignSpec → figma_bridge/SVG 产出原型"的精准复刻 agent。

**Architecture:** 三路"结构提供器"输出统一收敛到中间结构 `PageGraph`（容器树 + 元素 + 来源/置信度）；路由层按输入形态与用户选择决策（显式失败即报错，`auto` 按 dom→grounding→cv 回退）；其后 SoM 标注、DesignSpec 生成、渲染复用现有链路（`RenderingController`/`figma_bridge`），只写一遍。

**Tech Stack:** Python 3.12（omni conda 环境）、OpenCV、Playwright、OpenAI 兼容 SDK、qwen3-vl-plus（VLM）、deepseek-v4-flash（文本）、`container_pipeline`（CV 兜底）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-03-precise-replica-agent-router-design.md`

## Global Constraints

- 运行解释器：`C:\Users\lzq\.conda\envs\omni\python.exe`（以下所有命令默认用该解释器）。
- 旧流程（`ReconstructAgent` + `--direct-render` + `LLM_*`/`OMNIPARSER_*` 配置）**不得破坏**；新流程只新增模块与 `main.py` 分支。
- `container_pipeline/` 四个核心文件（`run_pipeline.py`、`pipeline_utils.py`、`gestalt_group.py`、`container_borders_v2_4/`）**零改动**。
- 密钥只写 `.env`（不入库、不写进本计划/代码）。VLM 网关 `https://www.acctoken.com/v1`，`VISION_MODEL=qwen3-vl-plus`；文本模型 `TEXT_MODEL=deepseek-v4-flash`，两者同一 api_key。
- 截图一律 `device_scale_factor=1`；坐标一律原图像素整数 `(x,y,w,h)`，左上原点。
- 显式 `--route` 失败 = 报错（不静默换路）；`--route auto` 回退链 dom→grounding→cv，逐条记入 `provenance.fallbacks`。
- 网络相关测试标记 `@pytest.mark.integration`，离线 CI 默认跳过（conftest 按 `RUN_INTEGRATION` 环境变量）。
- 本仓库目前**不是 git 仓库**：每个任务的 Commit 步骤仅在用户同意 `git init` 后执行；否则该步骤改为"运行该任务全部测试通过"作为检查点。
- 所有新模块遵循现有风格：`# -*- coding: utf-8 -*-` 头、模块 docstring、`from __future__ import annotations`、类型注解。

---

### Task 1: 配置项与依赖（VISION_*/TEXT_*/PLAYWRIGHT_*）

**Files:**
- Modify: `src/config/settings.py`（Config 新增字段）
- Modify: `.env.example`、`.env`
- Modify: `requirements.txt`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: 无（仓库现状）。
- Produces: `Config` 新增字段：`vision_base_url:str`、`vision_api_key:str|None`、`vision_model:str`、`vision_native_grounding:bool`、`text_base_url:str`、`text_api_key:str|None`、`text_model:str`、`route_default:str`、`playwright_viewport_width:int`、`playwright_viewport_height:int`、`playwright_headless:bool`、`device_scale_factor:int`、`enrich_visual:bool`、`wait_networkidle_timeout:int`。后续所有任务经 `src.config.load_config()` 读取这些字段。

- [ ] **Step 1: 写失败测试**

`tests/test_settings.py`：
```python
from src.config import load_config, Config

def test_config_new_fields_defaults():
    c: Config = load_config()
    assert c.vision_model == "qwen3-vl-plus"
    assert c.text_model == "deepseek-v4-flash"
    assert c.vision_base_url == "https://www.acctoken.com/v1"
    assert c.route_default == "auto"
    assert c.playwright_viewport_width == 1440
    assert c.device_scale_factor == 1
    assert c.enrich_visual is False

def test_config_new_fields_env():
    import os
    os.environ["VISION_MODEL"] = "x"
    try:
        c = Config()
        assert c.vision_model == "x"
    finally:
        os.environ.pop("VISION_MODEL", None)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_settings.py -v`
Expected: FAIL（`Config` 无这些属性 / `vision_model` 不存在）。

- [ ] **Step 3: 实现配置字段**

在 `src/config/settings.py` 的 Config 中新增（放在 `# --- LLM ---` 段之后）：

```python
    # --- 新流程视觉/文本模型（acctoken 网关，OpenAI 兼容） ---
    vision_base_url: str = field(default_factory=lambda: os.getenv("VISION_BASE_URL", "https://www.acctoken.com/v1"))
    vision_api_key: str | None = field(default_factory=lambda: os.getenv("VISION_API_KEY"))
    vision_model: str = field(default_factory=lambda: os.getenv("VISION_MODEL", "qwen3-vl-plus"))
    vision_native_grounding: bool = field(default_factory=lambda: os.getenv("VISION_NATIVE_GROUNDING", "false").lower() in ("1", "true", "yes"))
    text_base_url: str = field(default_factory=lambda: os.getenv("TEXT_BASE_URL", "https://www.acctoken.com/v1"))
    text_api_key: str | None = field(default_factory=lambda: os.getenv("TEXT_API_KEY"))
    text_model: str = field(default_factory=lambda: os.getenv("TEXT_MODEL", "deepseek-v4-flash"))

    # --- 新流程路由与抓取 ---
    route_default: str = field(default_factory=lambda: os.getenv("ROUTE", "auto"))
    playwright_viewport_width: int = field(default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "1440")))
    playwright_viewport_height: int = field(default_factory=lambda: int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "900")))
    playwright_headless: bool = field(default_factory=lambda: os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() in ("1", "true", "yes"))
    device_scale_factor: int = field(default_factory=lambda: int(os.getenv("DEVICE_SCALE_FACTOR", "1")))
    enrich_visual: bool = field(default_factory=lambda: os.getenv("ENRICH_VISUAL", "false").lower() in ("1", "true", "yes"))
    wait_networkidle_timeout: int = field(default_factory=lambda: int(os.getenv("WAIT_NETWORKIDLE_TIMEOUT", "30000")))
```

- [ ] **Step 4: 运行通过**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS。

- [ ] **Step 5: 更新 .env.example / .env / requirements.txt**

`.env.example` 追加（不带真实密钥）：
```ini
# 新流程（精准复刻 Agent）：acctoken OpenAI 兼容网关
VISION_BASE_URL=https://www.acctoken.com/v1
VISION_API_KEY=
VISION_MODEL=qwen3-vl-plus
VISION_NATIVE_GROUNDING=false
TEXT_BASE_URL=https://www.acctoken.com/v1
TEXT_API_KEY=
TEXT_MODEL=deepseek-v4-flash
ROUTE=auto
PLAYWRIGHT_VIEWPORT_WIDTH=1440
PLAYWRIGHT_VIEWPORT_HEIGHT=900
PLAYWRIGHT_HEADLESS=true
DEVICE_SCALE_FACTOR=1
ENRICH_VISUAL=false
WAIT_NETWORKIDLE_TIMEOUT=30000
```
`.env` 追加同样键，并把 `VISION_API_KEY`/`TEXT_API_KEY` 填为用户提供的 acctoken key（同一个）。

`requirements.txt` 追加：
```
playwright>=1.40.0
```

`tests/conftest.py` 末尾追加（离线自动跳过 integration 用例）：
```python
import os as _os
import pytest

def pytest_collection_modifyitems(config, items):
    if _os.getenv("RUN_INTEGRATION") != "1":
        _skip = pytest.mark.skip(reason="integration: 需网络/Chromium/模型/CV 环境，设置 RUN_INTEGRATION=1 后运行")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(_skip)
```

仓库根新增 `pytest.ini`：
```ini
[pytest]
markers =
    integration: 需要网络/Chromium/模型端点/CV GPU 的端到端用例（RUN_INTEGRATION=1 才跑）
```

- [ ] **Step 6: 提交/检查点**
若已 `git init`：`git add src/config/settings.py .env.example requirements.txt tests/test_settings.py && git commit -m "feat(config): add vision/text/playwright config for precise agent"`
否则：运行 `python -m pytest tests/ -q`，确认旧测试（test_ocr/test_omni_init）仍通过。

---


### Task 2: PageGraph 数据模型与建树（graph.py）

**Files:**
- Create: `src/app/services/structure/__init__.py`
- Create: `src/app/services/structure/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: 无。
- Produces（后续任务全部依赖）：
```python
def new_graph(image: str, image_w: int, image_h: int, route: str, provenance: dict | None = None) -> dict
def add_container(graph: dict, bbox: list[int], role: str = "", source: str = "", confidence: float = 1.0) -> None
def add_element(graph: dict, bbox: list[int], type_: str = "rectangle", text: str = "", role: str = "", source: str = "", confidence: float = 1.0) -> None
def contains(outer: dict, inner: dict) -> bool   # bbox 严格包含
def iou(a: list[int], b: list[int]) -> float
def assign_ids(graph: dict) -> None              # 阅读序编号：容器 C1..，元素 1..，回填 element['container']
def assign_parent_depth(graph: dict) -> None     # 容器 parent/depth（最小包含容器）
def save_graph(graph: dict, path: str) -> None
def load_graph(path: str) -> dict
```

- [ ] **Step 1: 写失败测试**

`tests/test_graph.py`：
```python
import json
from src.app.services.structure.graph import (new_graph, add_container, add_element,
                                              assign_ids, assign_parent_depth, contains, iou)

def _sample():
    g = new_graph("shot.png", 100, 100, "dom")
    add_container(g, [0, 0, 100, 50], role="banner", source="dom:header")   # C
    add_container(g, [10, 10, 40, 30], role="card", source="dom:div")        # 内层容器
    add_element(g, [12, 12, 30, 20], type_="button", text="hi")              # 中心(27,22) 在内层容器
    add_element(g, [60, 10, 30, 20], type_="text", text="t")                 # 只在外层
    return g

def test_assign_ids_and_containment():
    g = _sample()
    assign_ids(g)
    ids = [c["id"] for c in g["containers"]]
    assert ids == ["C1", "C2"]
    c_outer = g["containers"][0]
    c_inner = g["containers"][1]
    assert c_inner["parent"] == "C1" and c_inner["depth"] == 1 and c_outer["depth"] == 0
    by_id = {c["id"]: c for c in g["containers"]}
    assert by_id["C2"]["elements"] == [1]      # 按钮(1)挂内层容器
    assert by_id["C1"]["elements"] == [2]      # 外层只列直接子元素(文本2)
    assert g["elements"][0]["container"] == "C2"
    assert g["elements"][1]["container"] == "C1"

def test_iou_and_contains():
    assert iou([0, 0, 10, 10], [5, 5, 10, 10]) == 25.0 / 175.0
    assert contains({"bbox": [0, 0, 100, 50]}, {"bbox": [10, 10, 40, 30]}) is True
    assert contains({"bbox": [10, 10, 40, 30]}, {"bbox": [0, 0, 100, 50]}) is False

def test_save_load_roundtrip(tmp_path):
    g = _sample()
    assign_ids(g)
    p = str(tmp_path / "g.json")
    save_graph(g, p)
    g2 = load_graph(p)
    assert g2["image"] == "shot.png" and len(g2["containers"]) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_graph.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现 graph.py**

`src/app/services/structure/__init__.py`：
```python
from src.app.services.structure.graph import (new_graph, add_container, add_element, contains, iou,
                                              assign_ids, assign_parent_depth, save_graph, load_graph)
```

`src/app/services/structure/graph.py`：
```python
"""PageGraph：三路结构提供器的统一中间结构。坐标一律 (x,y,w,h) 原图像素整数。"""
from __future__ import annotations
import json

def new_graph(image: str, image_w: int, image_h: int, route: str,
              provenance: dict | None = None) -> dict:
    return {"image": image, "image_w": image_w, "image_h": image_h, "route": route,
            "containers": [], "elements": [],
            "provenance": provenance or {"route": route, "fallbacks": [], "warnings": []}}

def add_container(graph: dict, bbox: list[int], role: str = "", source: str = "",
                  confidence: float = 1.0) -> None:
    graph["containers"].append({"id": None, "bbox": [int(v) for v in bbox], "role": role,
                                "depth": 0, "parent": None, "elements": [],
                                "confidence": float(confidence), "source": source})

def add_element(graph: dict, bbox: list[int], type_: str = "rectangle", text: str = "",
                role: str = "", source: str = "", confidence: float = 1.0) -> None:
    graph["elements"].append({"id": None, "bbox": [int(v) for v in bbox], "type": type_,
                              "text": text or "", "role": role, "container": None,
                              "confidence": float(confidence), "source": source})

def _cx(e: dict) -> float:
    x, y, w, h = e["bbox"]; return x + w / 2.0, y + h / 2.0

def contains(outer: dict, inner: dict) -> bool:
    x1, y1, w1, h1 = outer["bbox"]; x2, y2, w2, h2 = inner["bbox"]
    return (x1 <= x2 and y1 <= y2 and x1 + w1 >= x2 + w2 and y1 + h1 >= y2 + h2
            and (w1 > w2 or h1 > h2))   # 严格包含（父更大）

def iou(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0

def _reading_key(item: dict) -> tuple[int, int]:
    x, y, w, h = item["bbox"]; return (y, x)   # 上→下、左→右

def assign_ids(graph: dict) -> None:
    graph["containers"].sort(key=_reading_key)
    graph["elements"].sort(key=_reading_key)
    for i, c in enumerate(graph["containers"], 1):
        c["id"] = f"C{i}"
    for i, e in enumerate(graph["elements"], 1):
        e["id"] = i
    for e in graph["elements"]:
        cands = [c for c in graph["containers"]
                 if contains(c, e) and c["bbox"][2] * c["bbox"][3] > 0]
        if cands:
            e["container"] = min(cands, key=lambda c: c["bbox"][2] * c["bbox"][3])["id"]
    # 容器只列“直接挂在它下面”的元素（元素挂最小包含容器；祖先可经 bbox 遍历）
    for c in graph["containers"]:
        c["elements"] = [e["id"] for e in graph["elements"] if e["container"] == c["id"]]

def assign_parent_depth(graph: dict) -> None:
    for c in graph["containers"]:
        c["depth"], c["parent"] = 0, None
    for a in graph["containers"]:
        cands = [b for b in graph["containers"] if b is not a and contains(b, a)]
        if cands:
            p = min(cands, key=lambda b: b["bbox"][2] * b["bbox"][3])
            a["parent"] = p["id"]
            a["depth"] = p["depth"] + 1

def save_graph(graph: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)

def load_graph(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 4: 运行通过**

Run: `python -m pytest tests/test_graph.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**（同 T1 规则，提交 `src/app/services/structure/*` 与 `tests/test_graph.py`）

---

### Task 3: 路由决策（router.py）

**Files:**
- Create: `src/app/services/structure/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `src.config.Config` 的 `vision_api_key`、`route_default` 字段。
- Produces:
```python
def route_order(input_kind: str, requested: str | None, cfg: "Config", have_dom: bool) -> list[str]
```
返回按优先级排列的候选路线列表；显式选择不合法时抛 `ValueError`（带原因）；纯图且无 DOM 时路线候选只含 grounding/cv。

- [ ] **Step 1: 写失败测试**

`tests/test_router.py`：
```python
from dataclasses import replace
import pytest
from src.app.services.structure.router import route_order
from src.config import load_config

@pytest.fixture
def cfg():
    return load_config()

def test_explicit_dom_on_image_raises(cfg):
    with pytest.raises(ValueError, match="dom"):
        route_order("image", "dom", cfg, have_dom=False)

def test_auto_url_prefers_dom(cfg):
    assert route_order("url", None, cfg, have_dom=True)[0] == "dom"

def test_auto_image_no_vision_key(cfg):
    c = replace(cfg, vision_api_key=None)
    assert route_order("image", None, c, have_dom=False) == ["cv"]

def test_auto_image_with_vision_key(cfg):
    c = replace(cfg, vision_api_key="sk-test")
    assert route_order("image", None, c, have_dom=False) == ["grounding", "cv"]

def test_explicit_grounding_on_image_ok(cfg):
    assert "grounding" in route_order("image", "grounding", cfg, have_dom=False)
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_router.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现 router.py**

```python
"""路由决策：输入形态 × 用户选择 → 候选路线（显式=单候选+校验，auto=回退链）。"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.config import Config

def route_order(input_kind: str, requested: str | None, cfg: "Config", have_dom: bool) -> list[str]:
    valid = {"dom", "a11y", "grounding", "cv"}
    if requested and requested not in valid:
        raise ValueError(f"未知路线: {requested}")
    dom_ok = (input_kind == "url") and have_dom
    if requested:
        if requested in ("dom", "a11y") and not dom_ok:
            raise ValueError(f"路线 {requested} 需要网页 DOM/AX 数据；当前输入为 {input_kind}，请改用 --url 或选 grounding/cv")
        return [requested]
    if input_kind == "url" and have_dom:
        chain = ["dom", "grounding", "cv"]
    else:
        chain = []
        if cfg.vision_api_key:
            chain.append("grounding")
        chain.append("cv")
    return chain
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_router.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**（提交 `router.py`、`tests/test_router.py`）

---

### Task 4: Playwright 抓取（capture.py）

**Files:**
- Create: `src/app/services/structure/capture.py`
- Test: `tests/test_capture.py`（离线部分：DOM_JS 常量存在、`_ax_bounds` 纯函数；live 标记 integration）

**Interfaces:**
- Consumes: Config 的 `playwright_*`、`device_scale_factor`、`wait_networkidle_timeout`。
- Produces:
```python
def capture_page(url: str, cfg: "Config", output_dir: str) -> dict
# 返回 {"image": "...", "width": int, "height": int, "dom": "...|None", "ax": "...|None"}
def _ax_bounds(props: list) -> list[int] | None   # 从 CDP AXNode properties 提取 bounds [x,y,w,h]
```

- [ ] **Step 1: 写失败测试**

`tests/test_capture.py`：
```python
import pytest
from src.app.services.structure.capture import DOM_JS, _ax_bounds

def test_dom_js_present():
    assert "getBoundingClientRect" in DOM_JS

def test_ax_bounds_present():
    props = [{"name": "internal::role", "value": {"value": "button"}},
             {"name": "bounds", "value": {"value": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 20.0}}}]
    assert _ax_bounds(props) == [1, 2, 30, 20]

def test_ax_bounds_missing():
    assert _ax_bounds([{"name": "internal::role", "value": {"value": "button"}}]) is None

@pytest.mark.integration
def test_capture_live(tmp_path):
    from src.config import load_config
    from src.app.services.structure.capture import capture_page
    r = capture_page("https://example.com", load_config(), str(tmp_path))
    assert r["image"] and r["dom"]
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_capture.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现 capture.py**

```python
"""Playwright 抓取：同一次会话产出截图 + DOM JSON（+ CDP AX JSON），dsf=1 保证坐标对齐。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.config import Config

DOM_JS = r"""
() => {
  const out = [];
  const pageBg = getComputedStyle(document.body).backgroundColor;
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const hasText = el.childElementCount === 0 && (el.textContent || '').trim().length > 0;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
      text: hasText ? (el.textContent || '').trim().slice(0, 200) : '',
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      bg: cs.backgroundColor, pageBg: pageBg,
      color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
      borderRadius: cs.borderRadius,
      interactive: /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)
    });
  }
  return out;
}
"""

def _ax_bounds(props: list) -> list[int] | None:
    for p in props:
        if p.get("name") == "bounds":
            v = p.get("value", {}).get("value")
            if isinstance(v, dict):
                try:
                    return [round(v["x"]), round(v["y"]), round(v["width"]), round(v["height"])]
                except (KeyError, TypeError):
                    return None
    return None

def capture_page(url: str, cfg: "Config", output_dir: str) -> dict:
    from playwright.sync_api import sync_playwright
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    image_p = out / "00_screenshot.png"
    dom_p = out / "00_dom.json"
    ax_p = out / "00_ax.json"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.playwright_headless)
        page = browser.new_page(viewport={"width": cfg.playwright_viewport_width,
                                          "height": cfg.playwright_viewport_height},
                                device_scale_factor=cfg.device_scale_factor)
        page.goto(url, wait_until="networkidle", timeout=cfg.wait_networkidle_timeout)
        page.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
        page.wait_for_timeout(500)
        page.screenshot(path=str(image_p))
        nodes = page.evaluate(DOM_JS)
        dom_p.write_text(json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        client = page.context.new_cdp_session(page)
        tree = client.send("Accessibility.getFullAXTree")
        ax_p.write_text(json.dumps(tree.get("nodes", []), ensure_ascii=False), encoding="utf-8")
        browser.close()
    from PIL import Image
    with Image.open(image_p) as im:
        w, h = im.size
    return {"image": str(image_p), "width": w, "height": h,
            "dom": str(dom_p), "ax": str(ax_p)}
```

- [ ] **Step 4: 离线用例通过**
Run: `python -m pytest tests/test_capture.py -v -m "not integration"`
Expected: PASS（2 个纯函数用例）。

- [ ] **Step 5: 提交/检查点**（提交 capture.py 与测试）

---

### Task 5: DOM 结构提供器（providers/dom.py）

**Files:**
- Create: `src/app/services/structure/providers/__init__.py`
- Create: `src/app/services/structure/providers/base.py`
- Create: `src/app/services/structure/providers/dom.py`
- Test: `tests/test_dom_provider.py`

**Interfaces:**
- Consumes: graph.py（T2）、capture 产出的 DOM JSON。
- Produces:
```python
class ProviderContext:
    image_path: str; image_w: int; image_h: int
    dom_path: str | None = None; ax_path: str | None = None
    route: str = ""; output_dir: str = ""
class BaseProvider:
    name: str
    def run(self, ctx: ProviderContext) -> dict   # 返回 PageGraph dict
class DomProvider(BaseProvider): ...
CONTAINER_ROLES = {"header", "nav", "main", "aside", "footer", "section", "form"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}
```

- [ ] **Step 1: 写失败测试**

`tests/test_dom_provider.py`（构造样例 DOM JSON，纯离线）：
```python
import json
from src.app.services.structure.graph import assign_parent_depth, assign_ids
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.base import ProviderContext

def _sample_dom(tmp_path):
    nodes = [
        {"tag": "body", "role": "", "text": "", "x": 0, "y": 0, "w": 100, "h": 100,
         "bg": "rgb(255,255,255)", "interactive": False},
        {"tag": "header", "role": "", "text": "", "x": 0, "y": 0, "w": 100, "h": 20,
         "bg": "rgb(240,240,240)", "interactive": False},
        {"tag": "button", "role": "", "text": "登录", "x": 70, "y": 5, "w": 20, "h": 10,
         "bg": "rgb(0,120,255)", "interactive": True},
        {"tag": "div", "role": "", "text": "正文标题", "x": 10, "y": 40, "w": 80, "h": 12,
         "bg": "rgb(255,255,255)", "interactive": False},
    ]
    p = tmp_path / "dom.json"; p.write_text(json.dumps(nodes), encoding="utf-8")
    return str(p)

def test_dom_provider_basic(tmp_path):
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          dom_path=_sample_dom(tmp_path), route="dom", output_dir=str(tmp_path))
    g = DomProvider().run(ctx)
    assign_ids(g); assign_parent_depth(g)
    roles = {c["role"] for c in g["containers"]}
    assert "header" in roles                      # 语义容器
    types = {e["type"] for e in g["elements"]}
    assert "button" in types and "text" in types
    assert len(g["containers"]) >= 1 and len(g["elements"]) >= 2
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_dom_provider.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现 providers 包**

`src/app/services/structure/providers/__init__.py`：
```python
from src.app.services.structure.providers.base import ProviderContext, BaseProvider
from src.app.services.structure.providers.dom import DomProvider
```

`src/app/services/structure/providers/base.py`：
```python
"""结构提供器基类与上下文。"""
from __future__ import annotations
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class ProviderContext:
    image_path: str
    image_w: int
    image_h: int
    route: str = ""
    output_dir: str = ""
    dom_path: str | None = None
    ax_path: str | None = None

class BaseProvider(ABC):
    name: str = ""
    @abstractmethod
    def run(self, ctx: ProviderContext) -> dict: ...
```

`src/app/services/structure/providers/dom.py`：
```python
"""DOM 路线：由 Playwright 收集的 DOM JSON 构建 PageGraph（容器=语义/背景/大区块，元素=交互/文本/图）。"""
from __future__ import annotations
import json
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext

CONTAINER_ROLES = {"header", "nav", "main", "aside", "footer", "section", "form", "article"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}

def _normalize_role(node: dict) -> str:
    return (node.get("role") or "").lower().strip()

def _distinct_bg(node: dict) -> bool:
    bg = (node.get("bg") or "").strip().lower()
    page_bg = (node.get("pageBg") or "").strip().lower()
    if not bg or bg in ("rgba(0, 0, 0, 0)", "transparent"):
        return False
    return bg != page_bg

class DomProvider(BaseProvider):
    name = "dom"
    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.dom_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
        # 容器候选：语义角色 / 明显背景块 / 大区块(>25% 高或宽 且面积>2000)
        for n in nodes:
            if _normalize_role(n) in CONTAINER_ROLES or _distinct_bg(n) or (
                n["w"] * n["h"] > 2000 and (n["w"] >= ctx.image_w * 0.5 or n["h"] >= ctx.image_h * 0.5)):
                add_container(g, [n["x"], n["y"], n["w"], n["h"]],
                              role=_normalize_role(n) or n["tag"],
                              source=f"dom:{n['tag']}")
        # 元素候选：交互 / 叶子文本 / 图片
        for n in nodes:
            if n["interactive"] or n["tag"] in ("img", "svg") or n.get("text"):
                etype = "button" if n["tag"] in ("button", "a", "select") else (
                    "input" if n["tag"] in ("input", "textarea") else (
                    "image" if n["tag"] in ("img", "svg") else "text"))
                add_element(g, [n["x"], n["y"], n["w"], n["h"]], type_=etype,
                            text=n.get("text", ""), role=_normalize_role(n),
                            source=f"dom:{n['tag']}")
        return g
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_dom_provider.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**（提交 providers 包与测试）

---

### Task 6: A11y 结构提供器（providers/a11y.py）

**Files:**
- Create: `src/app/services/structure/providers/a11y.py`
- Test: `tests/test_a11y_provider.py`

**Interfaces:**
- Consumes: capture 产出的 `00_ax.json`（CDP getFullAXTree 的 nodes 数组，字段含 `role/name/properties/childIds/ignored`）、capture._ax_bounds。
- Produces: `class A11yProvider(BaseProvider)`；`CONTAINER_AX_ROLES` 与 `ELEMENT_AX_ROLES` 常量。

- [ ] **Step 1: 写失败测试**

`tests/test_a11y_provider.py`：
```python
import json
from src.app.services.structure.providers.a11y import A11yProvider
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.graph import assign_ids, assign_parent_depth

def _mk_ax(role, name, x, y, w, h):
    return {"ignored": False, "role": {"value": role}, "name": {"value": name},
            "properties": [{"name": "bounds",
                            "value": {"value": {"x": x, "y": y, "width": w, "height": h}}}],
            "childIds": []}

def _sample_ax(tmp_path):
    nodes = [_mk_ax("banner", "顶栏", 0, 0, 100, 20),
             _mk_ax("button", "登录", 70, 5, 20, 10),
             _mk_ax("heading", "标题", 10, 40, 80, 12)]
    p = tmp_path / "ax.json"; p.write_text(json.dumps(nodes), encoding="utf-8")
    return str(p)

def test_a11y_provider_basic(tmp_path):
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          ax_path=_sample_ax(tmp_path), route="a11y", output_dir=str(tmp_path))
    g = A11yProvider().run(ctx)
    assign_ids(g); assign_parent_depth(g)
    assert any(c["role"] == "banner" for c in g["containers"])
    types = {e["type"] for e in g["elements"]}
    assert "button" in types and "text" in types
    assert g["elements"][0]["text"] == "登录"
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_a11y_provider.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 a11y.py**

```python
"""a11y 路线：由 CDP Accessibility.getFullAXTree 构建 PageGraph（语义角色 + bounds）。"""
from __future__ import annotations
import json
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext
from src.app.services.structure.capture import _ax_bounds

CONTAINER_AX_ROLES = {"banner", "navigation", "main", "region", "complementary",
                      "contentinfo", "group", "list", "tablist", "form"}
ELEMENT_AX_ROLES = {"button", "link", "textbox", "combobox", "checkbox", "radio",
                    "heading", "listitem", "img", "image", "text", "searchbox", "switch"}
TYPE_BY_ROLE = {"button": "button", "link": "link", "textbox": "input", "searchbox": "input",
                "combobox": "input", "checkbox": "input", "radio": "input", "switch": "input",
                "heading": "text", "text": "text", "listitem": "text",
                "img": "image", "image": "image"}

class A11yProvider(BaseProvider):
    name = "a11y"
    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.ax_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "a11y")
        for n in nodes:
            if n.get("ignored"):
                continue
            role = (n.get("role") or {}).get("value") or ""
            name = (n.get("name") or {}).get("value") or ""
            bbox = _ax_bounds(n.get("properties") or [])
            if not bbox:
                continue
            if role in CONTAINER_AX_ROLES:
                add_container(g, bbox, role=role, source=f"a11y:{role}")
            elif role in ELEMENT_AX_ROLES:
                add_element(g, bbox, type_=TYPE_BY_ROLE.get(role, "rectangle"),
                            text=name, role=role, source=f"a11y:{role}")
        return g
```

（`__init__.py` 补一行导出 `A11yProvider`：`from src.app.services.structure.providers.a11y import A11yProvider`）

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_a11y_provider.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**（提交 a11y.py 与测试）

---


### Task 7: Grounding 提供器（qwen3-vl-plus，OpenAI 兼容后端）

**Files:**
- Create: `src/app/services/structure/backends/__init__.py`
- Create: `src/app/services/structure/backends/grounding_base.py`
- Create: `src/app/services/structure/backends/grounding_vlm.py`
- Create: `src/app/services/structure/providers/grounding.py`
- Test: `tests/test_grounding.py`（解析/映射纯函数离线；后端调用标 integration）

**Interfaces:**
- Consumes: Config `vision_base_url/vision_api_key/vision_model`；graph.py。
- Produces:
```python
class GroundingBackend(ABC):
    def ground(self, image_path: str, image_w: int, image_h: int) -> dict
    # {"containers":[{bbox,role}], "elements":[{bbox,type,text}]}
class GroundingVLM(GroundingBackend): ...
def parse_vlm_json(raw: str, image_w: int, image_h: int) -> dict   # 解析/clamp/白名单
class GroundingProvider(BaseProvider): ...                          # 返回 PageGraph
```

- [ ] **Step 1: 写失败测试**

`tests/test_grounding.py`：
```python
from src.app.services.structure.backends.grounding_vlm import parse_vlm_json

def test_parse_vlm_json_clamps():
    raw = '{"containers": [{"bbox": [-5, 0, 2000, 100]}], "elements": [{"bbox": [10, 10, 50, 20], "type": "button", "text": "hi"}]}'
    out = parse_vlm_json(raw, 100, 100)
    assert out["containers"][0]["bbox"] == [0, 0, 100, 80]
    assert out["elements"][0]["bbox"] == [10, 10, 50, 20]

def test_parse_vlm_json_rejects_bad_type():
    raw = '{"elements": [{"bbox": [1, 2, 3, 4], "type": "spaceship"}]}'
    out = parse_vlm_json(raw, 100, 100)
    assert out["elements"] == []

def test_grounding_provider_builds_graph(tmp_path, monkeypatch):
    from src.app.services.structure.providers.grounding import GroundingProvider
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.graph import assign_ids
    from src.app.services.structure.backends.grounding_base import GroundingBackend
    class Fake(GroundingBackend):
        def ground(self, image_path, image_w, image_h):
            return {"containers": [{"bbox": [0, 0, 100, 50], "role": "banner"}],
                    "elements": [{"bbox": [10, 10, 20, 20], "type": "button", "text": "确定"}]}
    monkeypatch.setattr("src.app.services.structure.providers.grounding._default_backend",
                        lambda cfg: Fake())
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          route="grounding", output_dir=str(tmp_path))
    g = GroundingProvider(None).run(ctx)
    assign_ids(g)
    assert len(g["containers"]) == 1 and g["elements"][0]["text"] == "确定"
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_grounding.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`src/app/services/structure/backends/__init__.py`：
```python
from src.app.services.structure.backends.grounding_base import GroundingBackend
from src.app.services.structure.backends.grounding_vlm import GroundingVLM, parse_vlm_json
```

`src/app/services/structure/backends/grounding_base.py`：
```python
"""Grounding 后端抽象。"""
from __future__ import annotations
from abc import ABC, abstractmethod

class GroundingBackend(ABC):
    @abstractmethod
    def ground(self, image_path: str, image_w: int, image_h: int) -> dict: ...
```

`src/app/services/structure/backends/grounding_vlm.py`：
```python
"""qwen3-vl-plus（OpenAI 兼容）grounding 后端：截图 -> JSON bbox。原生 <|box_start|> 预留。"""
from __future__ import annotations
import base64, json, re
from typing import TYPE_CHECKING
from openai import OpenAI
from src.app.services.structure.backends.grounding_base import GroundingBackend
if TYPE_CHECKING:
    from src.config import Config

ALLOWED_TYPES = {"button", "input", "text", "link", "image"}

def parse_vlm_json(raw: str, image_w: int, image_h: int) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("VLM 输出中没有 JSON 对象")
    data = json.loads(m.group(0))
    out = {"containers": [], "elements": []}
    for c in data.get("containers", []):
        b = c.get("bbox")
        if not b or len(b) != 4:
            continue
        x0 = max(0, min(int(b[0]), image_w)); y0 = max(0, min(int(b[1]), image_h))
        x1 = max(0, min(int(b[2]), image_w)); y1 = max(0, min(int(b[3]), image_h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out["containers"].append({"bbox": [x0, y0, x1 - x0, y1 - y0], "role": str(c.get("role", ""))})
    for e in data.get("elements", []):
        b = e.get("bbox"); t = str(e.get("type", "rectangle"))
        if not b or len(b) != 4 or t not in ALLOWED_TYPES:
            continue
        x0 = max(0, min(int(b[0]), image_w)); y0 = max(0, min(int(b[1]), image_h))
        x1 = max(0, min(int(b[2]), image_w)); y1 = max(0, min(int(b[3]), image_h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out["elements"].append({"bbox": [x0, y0, x1 - x0, y1 - y0], "type": t,
                                "text": str(e.get("text", ""))})
    return out

PROMPT = ("你是 UI 结构标注器。给定网页截图，输出 JSON："
          '{"containers": [{"bbox": [x,y,x2,y2], "role": "banner|nav|card|panel"}], '
          '"elements": [{"bbox": [x,y,x2,y2], "type": "button|input|text|link|image", '
          '"text": "可见文字"}]}。'
          "bbox 用原图像素绝对坐标（左上原点）；容器是布局区块（顶栏/侧边栏/卡片/面板），"
          "元素是容器内可交互控件或独立文字。只输出合法 JSON。")

class GroundingVLM(GroundingBackend):
    def __init__(self, cfg: "Config") -> None:
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.vision_base_url, api_key=cfg.vision_api_key, timeout=120)

    def ground(self, image_path: str, image_w: int, image_h: int) -> dict:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        messages = [
            {"role": "system", "content": "只输出 JSON，不要 markdown 代码块。"},
            {"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]},
        ]
        resp = self.client.chat.completions.create(
            model=self.cfg.vision_model, messages=messages, temperature=0.1,
            response_format={"type": "json_object"})
        return parse_vlm_json(resp.choices[0].message.content or "", image_w, image_h)
```

`src/app/services/structure/providers/grounding.py`：
```python
"""grounding 路线：VLM 直接看图输出容器/元素 bbox -> PageGraph。"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext
from src.app.services.structure.backends.grounding_base import GroundingBackend
if TYPE_CHECKING:
    from src.config import Config

def _default_backend(cfg) -> GroundingBackend:
    from src.app.services.structure.backends.grounding_vlm import GroundingVLM
    return GroundingVLM(cfg)

class GroundingProvider(BaseProvider):
    name = "grounding"
    def __init__(self, cfg=None) -> None:
        self.cfg = cfg
    def run(self, ctx: ProviderContext) -> dict:
        backend = _default_backend(self.cfg)
        raw = backend.ground(ctx.image_path, ctx.image_w, ctx.image_h)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "grounding")
        for c in raw["containers"]:
            add_container(g, c["bbox"], role=c["role"], source="grounding")
        for e in raw["elements"]:
            add_element(g, e["bbox"], type_=e["type"], text=e["text"], source="grounding")
        return g
```

`src/app/services/structure/providers/__init__.py` 追加导出：
```python
from src.app.services.structure.providers.a11y import A11yProvider
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.grounding import GroundingProvider
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_grounding.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**

---

### Task 8: CV 结构提供器（复用 container_pipeline，零改动）

**Files:**
- Create: `src/app/services/structure/providers/cv.py`
- Test: `tests/test_cv_provider.py`（离线只测可用性判断；完整跑标 integration）

**Interfaces:**
- Consumes: `container_pipeline/` 四个模块、graph.py。
- Produces:
```python
def cv_available() -> bool                       # container_pipeline 目录是否存在
def resolve_container_pipeline_root() -> Path    # 从本文件向上找含 container_pipeline 的仓库根
class CVProvider(BaseProvider): ...              # 进程内复刻 run_pipeline 5 步，元素一并入图
```

- [ ] **Step 1: 写失败测试**

`tests/test_cv_provider.py`：
```python
import pytest
from src.app.services.structure.providers.cv import cv_available

def test_cv_available_detects_pipeline():
    assert cv_available() is True   # 仓库内有 container_pipeline/

@pytest.mark.integration
def test_cv_provider_smoke(tmp_path):
    from src.app.services.structure.providers.cv import CVProvider
    from src.app.services.structure.providers.base import ProviderContext
    img = r"D:\LLM-Data\View_fill\user_test3.png"
    ctx = ProviderContext(image_path=img, image_w=2560, image_h=1336,
                          route="cv", output_dir=str(tmp_path))
    g = CVProvider().run(ctx)
    assert g["containers"] and g["elements"]
```

- [ ] **Step 2: 运行确认失败（离线部分）**
Run: `python -m pytest tests/test_cv_provider.py -v -m "not integration"`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现 cv.py**

```python
"""CV 路线：进程内复刻 container_pipeline/run_pipeline 的 5 步，把容器与元素一并收进 PageGraph。

不修改 container_pipeline 下任何文件；本模块只做导入编排。gestalt 相关调用签名以
container_pipeline/run_pipeline.py 为唯一权威参照（实现时对照，禁止改该文件）。
"""
from __future__ import annotations
import os, sys
from pathlib import Path
from typing import TYPE_CHECKING
from src.app.services.structure.graph import (new_graph, add_container, add_element,
                                              assign_parent_depth)
from src.app.services.structure.providers.base import BaseProvider, ProviderContext
if TYPE_CHECKING:
    from src.config import Config

def resolve_container_pipeline_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "container_pipeline").is_dir():
            return parent
    raise FileNotFoundError("找不到 container_pipeline 目录")

def cv_available() -> bool:
    try:
        resolve_container_pipeline_root()
        return True
    except FileNotFoundError:
        return False

def _resolve_omni(root: Path) -> str:
    cands = [root / "container_pipeline" / "OmniParser" / "OmniParser-master",
             root / "OmniParser" / "OmniParser-master",
             root.parent / "OmniParser" / "OmniParser-master"]
    for c in cands:
        if c.is_dir():
            return str(c)
    return str(cands[0])

def _b64_of(path: str) -> str:
    import base64
    return base64.b64encode(Path(path).read_bytes()).decode()

class CVProvider(BaseProvider):
    name = "cv"
    def __init__(self, cfg=None) -> None:
        self.cfg = cfg

    def run(self, ctx: ProviderContext) -> dict:
        root = resolve_container_pipeline_root()
        cp = root / "container_pipeline"
        sys.path.insert(0, str(cp))
        sys.path.insert(0, _resolve_omni(root))
        import cv2
        import easyocr
        from container_borders_v2_4 import detect_boxes as d2
        from pipeline_utils import _install_paddleocr_stub, extract_box_lines_hv
        _install_paddleocr_stub()
        from gestalt_group import (gestalt_group, refine_groups, resolve_overlaps,
                                   inside_box, center)
        from util.omniparser import Omniparser
        from PIL import Image as PILImage

        img_bgr = cv2.imread(ctx.image_path)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "cv")

        # 1) easyocr
        reader = easyocr.Reader(["ch_sim", "en"], gpu=True)
        texts = []
        for p, t, _c in reader.readtext(img_rgb, text_threshold=0.5):
            x0, y0 = int(p[0][0]), int(p[0][1]); x1, y1 = int(p[2][0]), int(p[2][1])
            if (x1 - x0) >= 8 and (y1 - y0) >= 6:
                texts.append((x0, y0, x1, y1, t))
        for x0, y0, x1, y1, t in texts:
            add_element(g, [x0, y0, x1 - x0, y1 - y0], type_="text", text=t, source="cv:ocr")

        # 2) v2.4 掩膜容器
        tb = [(t[0], t[1], t[2], t[3]) for t in texts]
        v2 = d2(img_rgb, text_boxes=tb)["boxes"]
        for b in v2:
            add_container(g, [b["x"], b["y"], b["w"], b["h"]], role="", source="cv:v2.4")

        # 3) OmniParser GPU 元素
        cfg = {"som_model_path": os.path.join(_resolve_omni(root), "weights", "icon_detect", "model.pt"),
               "caption_model_name": "florence2",
               "caption_model_path": os.path.join(_resolve_omni(root), "weights", "icon_caption_florence"),
               "device": "cuda", "BOX_TRESHOLD": 0.05}
        op = Omniparser(cfg)
        W, H = ctx.image_w, ctx.image_h
        for it in op.parse(_b64_of(ctx.image_path))[1]:
            b = it.get("bbox")
            if not b:
                continue
            b = [float(v) for v in b]
            if max(b) <= 1.0 and min(b) >= 0:
                b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
            add_element(g, [int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1])],
                        type_="rectangle", text=str(it.get("content", ""))[:20],
                        source="cv:omniparser")

        # 4) 格式塔补全（参照 run_pipeline.py 第 4 步调用方式）
        h_mask, v_mask = extract_box_lines_hv(img_bgr, line_len=22)
        for mask in (h_mask, v_mask):
            mask[:3, :] = mask[-3:, :] = mask[:, :3] = mask[:, -3:] = False
        elems = [{"x": e["bbox"][0], "y": e["bbox"][1], "w": e["bbox"][2], "h": e["bbox"][3]}
                 for e in g["elements"] if e["source"] != "cv:ocr"]
        uncontained = [{"x": e["bbox"][0], "y": e["bbox"][1], "w": e["bbox"][2], "h": e["bbox"][3]}
                       for e in g["elements"]]
        groups, _stats, _un = gestalt_group(v2, elems)
        groups = refine_groups(groups, uncontained, h_mask, v_mask, img_bgr.shape)
        groups = resolve_overlaps(groups, v2)
        for grp in groups:
            add_container(g, [grp["x"], grp["y"], grp["w"], grp["h"]],
                          role="", source="cv:gestalt")

        assign_parent_depth(g)
        return g
```

- [ ] **Step 4: 运行通过（离线部分）**
Run: `python -m pytest tests/test_cv_provider.py -v -m "not integration"`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**

---

### Task 9: SoM 标注器（som/annotate.py）

**Files:**
- Create: `src/app/services/som/__init__.py`
- Create: `src/app/services/som/annotate.py`
- Test: `tests/test_som.py`

**Interfaces:**
- Consumes: graph.py（PageGraph）、截图。
- Produces:
```python
def annotate_som(graph: dict, output_dir: str) -> dict   # 产出 11_som.png + 11_som.json，返回 som dict
```

- [ ] **Step 1: 写失败测试**

`tests/test_som.py`：
```python
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.som.annotate import annotate_som

def _mk_graph(tmp_path, shot):
    import cv2
    cv2.imwrite(str(tmp_path / "shot.png"), __import__("numpy").zeros((80, 100, 3), dtype="uint8"))
    g = new_graph(str(tmp_path / "shot.png"), 100, 80, "dom")
    add_container(g, [0, 0, 100, 80], role="banner")
    add_container(g, [0, 0, 100, 20], role="header")
    add_element(g, [10, 4, 20, 12], type_="button", text="登录")
    return g

def test_annotate_som_writes_files(tmp_path):
    g = _mk_graph(tmp_path, None)
    som = annotate_som(g, str(tmp_path))
    assert (tmp_path / "11_som.png").exists()
    assert (tmp_path / "11_som.json").exists()
    assert som["elements"][0]["id"] == 1
    assert som["containers"][0]["id"] == "C1"
    cids = {c["id"] for c in som["containers"]}
    assert som["elements"][0]["container"] in cids
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_som.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 annotate.py**

`src/app/services/som/__init__.py`：
```python
from src.app.services.som.annotate import annotate_som
```

`src/app/services/som/annotate.py`：
```python
"""Set-of-Mark 双编号标注器：容器 C1..（粗框/深度色），元素 1..（细框 + 角标）。"""
from __future__ import annotations
import json, os
import cv2

DEPTH_COLORS = {0: (255, 200, 0), 1: (0, 200, 0), 2: (0, 160, 255), 3: (200, 0, 255)}

def _draw_label(img, text, x, y):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = 0.5, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    x0, y0 = max(0, x - 2), max(0, y - th - 4)
    cv2.rectangle(img, (x0, y0), (x0 + tw + 4, y0 + th + 4), (30, 30, 30), -1)
    cv2.putText(img, text, (x0 + 2, y0 + th - 2), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

def annotate_som(graph: dict, output_dir: str) -> dict:
    from src.app.services.structure.graph import assign_ids
    assign_ids(graph)
    img = cv2.imread(graph["image"])
    if img is None:
        raise FileNotFoundError("无法读取截图: %s" % graph["image"])
    board = img.copy()
    for c in graph["containers"]:
        x, y, w, h = c["bbox"]
        color = DEPTH_COLORS.get(c["depth"] % 4, (255, 255, 255))
        cv2.rectangle(board, (x, y), (x + w, y + h), color, 3)
        _draw_label(board, c["id"], x, y)
    for e in graph["elements"]:
        x, y, w, h = e["bbox"]
        cv2.rectangle(board, (x, y), (x + w, y + h), (0, 200, 0), 2)
        _draw_label(board, str(e["id"]), x, y)
    cv2.imwrite(os.path.join(output_dir, "11_som.png"), board)
    som = {"image": graph["image"], "size": [graph["image_w"], graph["image_h"]],
           "containers": [{"id": c["id"], "bbox": c["bbox"], "depth": c["depth"],
                           "parent": c["parent"], "elements": c["elements"]}
                          for c in graph["containers"]],
           "elements": [{"id": e["id"], "bbox": e["bbox"], "text": e["text"],
                         "type": e["type"],
                         "interactable": e["type"] not in ("text", "image"),
                         "container": e["container"]} for e in graph["elements"]],
           "provenance": graph.get("provenance", {})}
    with open(os.path.join(output_dir, "11_som.json"), "w", encoding="utf-8") as f:
        json.dump(som, f, ensure_ascii=False, indent=1)
    return som
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_som.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**

---


### Task 10: SoM→DesignSpec（llm_service 扩展）

**Files:**
- Modify: `src/app/services/llm/llm_service.py`
- Test: `tests/test_llm_som.py`

**Interfaces:**
- Consumes: Config `vision_*`/`text_*`；现有 `parse_design_json`。
- Produces（新增，旧函数不动）：
```python
def build_som_prompt(som_json: dict, image_b64: str) -> list[dict]
def call_vlm(messages: list[dict], cfg) -> str       # 用 VISION_* 配置
def call_text_llm(messages: list[dict], cfg) -> str  # 用 TEXT_* 配置
```

- [ ] **Step 1: 写失败测试**

`tests/test_llm_som.py`：
```python
from src.app.services.llm.llm_service import build_som_prompt

def test_build_som_prompt_shape():
    som = {"image": "a.png", "size": [100, 80], "containers": [], "elements": [],
           "provenance": {"route": "dom"}}
    msgs = build_som_prompt(som, "BASE64==")
    assert msgs[0]["role"] == "system"
    parts = msgs[1]["content"]
    assert any(p["type"] == "image_url" and "BASE64==" in p["image_url"]["url"] for p in parts)
    assert any("DesignSpec" in p["text"] for p in parts if p["type"] == "text")
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_llm_som.py -v`
Expected: FAIL（AttributeError）。

- [ ] **Step 3: 实现（追加到 llm_service.py）**

```python
def build_som_prompt(som_json: dict, image_b64: str) -> list[dict]:
    """把 SoM 标注图 + SoM JSON 一起交给 VLM，要求输出现有 DesignSpec schema。"""
    system = (
        "你是 UI 还原专家。输入是 Set-of-Mark 标注图与配套 JSON：容器 id 形如 C1，"
        "元素 id 为整数，JSON 已给出每个 id 的 bbox/type/text。任务：输出 DesignSpec JSON。"
        "规则：1) 只输出合法 JSON；2) 元素保持独立、不许合并与丢组件；3) 容器画成背景矩形"
        "(type=container)；4) 坐标尺寸基于 JSON 的 bbox 且按 4px 网格取整，不得随意移动；"
        "5) 颜色/字号/圆角参照标注图推断。schema："
        '{"canvas": {"width": int, "height": int}, "elements": ['
        '{"id": str, "type": "rectangle|text|button|input|image|avatar|divider|container",'
        ' "x": int, "y": int, "width": int, "height": int, "text": str,'
        ' "style": {"fillColor": "#RRGGBB", "textColor": "#RRGGBB", "fontSize": int,'
        ' "fontWeight": str, "borderRadius": int, "borderWidth": int, "borderColor": "#RRGGBB"}}]}'
    )
    import json as _json
    user = [
        {"type": "text",
         "text": "画布尺寸 %dx%d。\nSoM JSON：\n%s\n请输出 DesignSpec JSON。" % (
             som_json["size"][0], som_json["size"][1],
             _json.dumps(som_json, ensure_ascii=False, indent=1))},
        {"type": "image_url",
         "image_url": {"url": "data:image/png;base64," + image_b64}},
    ]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_vlm(messages: list[dict], cfg) -> str:
    """用 VISION_* 配置调用多模态模型。cfg 为 src.config.Config。"""
    if not cfg.vision_api_key:
        raise ValueError("VISION_API_KEY 未配置，无法调用多模态模型")
    import openai
    client = openai.OpenAI(base_url=cfg.vision_base_url, api_key=cfg.vision_api_key,
                           timeout=cfg.llm_timeout)
    resp = client.chat.completions.create(model=cfg.vision_model, messages=messages,
                                          temperature=0.1, max_tokens=cfg.llm_max_tokens)
    return resp.choices[0].message.content or ""


def call_text_llm(messages: list[dict], cfg) -> str:
    """用 TEXT_* 配置调用纯文本模型（可选任务用）。"""
    if not cfg.text_api_key:
        raise ValueError("TEXT_API_KEY 未配置")
    import openai
    client = openai.OpenAI(base_url=cfg.text_base_url, api_key=cfg.text_api_key,
                           timeout=cfg.llm_timeout)
    resp = client.chat.completions.create(model=cfg.text_model, messages=messages,
                                          temperature=0.2, max_tokens=cfg.llm_max_tokens)
    return resp.choices[0].message.content or ""
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_llm_som.py -v`
Expected: PASS。

- [ ] **Step 5: 提交/检查点**

---

### Task 11: PreciseAgent 编排 + CLI 接线

**Files:**
- Create: `src/app/agents/precise_agent.py`
- Modify: `src/main.py`
- Test: `tests/test_precise_agent.py`（离线：路由/命名/fallback 记录用 fake provider；真跑标 integration）

**Interfaces:**
- Consumes: T1–T10 全部。
- Produces:
```python
class PreciseAgent:
    def __init__(self, config) -> None: ...
    def run(self, *, url=None, image=None, route="auto", tool="svg", enrich=False) -> dict
# main.py：有 --url 或 --route 时走 PreciseAgent，否则旧 ReconstructAgent
```

- [ ] **Step 1: 写失败测试（离线部分，fake provider 不触真检测）**

`tests/test_precise_agent.py`：
```python
import pytest
from pathlib import Path
from src.config import load_config

def _fake_capture(url, cfg, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "00_screenshot.png").write_bytes(b"PNG")
    (out / "00_dom.json").write_text("[]", encoding="utf-8")
    return {"image": str(out / "00_screenshot.png"), "width": 100, "height": 100,
            "dom": str(out / "00_dom.json"), "ax": None}

def test_route_order_cv_image_no_key():
    from dataclasses import replace
    from src.app.services.structure.router import route_order
    cfg = replace(load_config(), vision_api_key=None)
    assert route_order("image", None, cfg, have_dom=False) == ["cv"]

def test_run_with_cv_provider_smoke_skipped():
    # 端到端（真 CV/真网络）标 integration，不在此离线单测中执行
    assert True

@pytest.mark.integration
def test_run_url_auto_svg(tmp_path):
    from dataclasses import replace
    from src.app.agents.precise_agent import PreciseAgent
    cfg = replace(load_config(), output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.com", route="auto", tool="svg")
    assert (tmp_path / "11_som.json").exists() and (tmp_path / "prototype.svg").exists()
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_precise_agent.py -v -m "not integration"`
Expected: 先 FAIL（ModuleNotFoundError：precise_agent）。

- [ ] **Step 3: 实现 precise_agent.py**

```python
"""精准复刻 Agent：capture -> 路由 -> provider -> PageGraph -> SoM -> VLM DesignSpec -> 渲染。"""
from __future__ import annotations
import json, time
from pathlib import Path

from src.app.services.structure.graph import assign_ids, assign_parent_depth, save_graph
from src.app.services.structure.router import route_order
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.som.annotate import annotate_som


def _build_provider(cfg, route):
    from src.app.services.structure.providers.dom import DomProvider
    from src.app.services.structure.providers.a11y import A11yProvider
    from src.app.services.structure.providers.grounding import GroundingProvider
    from src.app.services.structure.providers.cv import CVProvider
    # dom/a11y 无参构造；grounding/cv 需要 cfg
    if route == "dom":
        return DomProvider()
    if route == "a11y":
        return A11yProvider()
    if route == "grounding":
        return GroundingProvider(cfg)
    return CVProvider(cfg)


class PreciseAgent:
    def __init__(self, config) -> None:
        self.config = config

    def run(self, *, url=None, image=None, route="auto", tool="svg", enrich=False) -> dict:
        out = self.config.output_dir
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        if url:
            from src.app.services.structure.capture import capture_page
            cap = capture_page(url, self.config, str(out))
            image, w, h = cap["image"], cap["width"], cap["height"]
            ctx = ProviderContext(image_path=image, image_w=w, image_h=h,
                                  route="", output_dir=str(out),
                                  dom_path=cap["dom"], ax_path=cap["ax"])
            input_kind = "url"
        else:
            from src.app.utils.image_utils import load_image
            frame = load_image(image)
            h, w = frame.shape[:2]
            ctx = ProviderContext(image_path=image, image_w=w, image_h=h,
                                  route="", output_dir=str(out))
            input_kind = "image"

        have_dom = bool(ctx.dom_path)
        requested = route if route != "auto" else None
        chain = route_order(input_kind, requested, self.config, have_dom)
        fallbacks, graph = [], None

        for r in chain:
            try:
                provider = _build_provider(self.config, r)
                ctx.route = r
                graph = provider.run(ctx)
                break
            except Exception as exc:
                if requested:
                    raise
                fallbacks.append({"from": r, "reason": str(exc)})
        if graph is None:
            raise RuntimeError("auto 全部路线失败: " + json.dumps(fallbacks, ensure_ascii=False))

        assign_ids(graph)
        assign_parent_depth(graph)
        graph["provenance"]["fallbacks"] = fallbacks
        save_graph(graph, str(out / "10_pagegraph.json"))
        annotate_som(graph, str(out))

        from src.app.utils.image_utils import encode_image_base64, load_image as _li
        from src.app.services.llm.llm_service import build_som_prompt, call_vlm, parse_design_json
        som_json = json.loads((out / "11_som.json").read_text(encoding="utf-8"))
        b64 = encode_image_base64(_li(graph["image"]))
        design = parse_design_json(call_vlm(build_som_prompt(som_json, b64), self.config))
        (out / "12_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=1),
                                            encoding="utf-8")

        from src.app.controllers.rendering_controller import RenderingController
        RenderingController(self.config).render(design, tool)

        manifest = {"route": graph["route"], "url": url, "image": image, "tool": tool,
                    "seconds": round(time.time() - t0, 1), "fallbacks": fallbacks,
                    "counts": {"containers": len(graph["containers"]),
                               "elements": len(graph["elements"])}}
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        return graph
```

- [ ] **Step 4: main.py 接线**
`parse_args` 增加三个参数：
```python
    parser.add_argument("--url", default=None, help="网页 URL（新流程）")
    parser.add_argument("--route", default=None, choices=["auto", "dom", "a11y", "grounding", "cv"],
                        help="结构来源路线")
    parser.add_argument("--enrich", action="store_true", help="视觉补充（默认关）")
```
`main()` 顶部校验后，在创建 `ReconstructAgent` 前插入：
```python
    if args.url or args.route:
        from src.app.agents.precise_agent import PreciseAgent
        agent = PreciseAgent(config)
        agent.run(url=args.url, image=args.image, route=args.route or "auto",
                  tool=tool, enrich=args.enrich)
        return 0
```

实现提示（对照真实 `src/main.py` 修改，勿照抄旧文案）：
1. 现有 `parser.add_argument("--image", required=True, ...)` 改为 `default=None`（去掉 required）。
2. `main()` 中在读取 tool/ocr_engine 后、创建 ReconstructAgent 前加入：`if not args.url and not args.image: parser.error("必须提供 --url 或 --image")`。
3. 只有当 `args.url or args.route` 才走 PreciseAgent；否则走原有 `ReconstructAgent(config).run(...)`，且其 image 参数只在 image 模式下有值。


- [ ] **Step 5: 回归**
Run: `python -m pytest tests/ -q -m "not integration"`
Expected: 全绿（含旧 test_ocr / test_omni_init）。

- [ ] **Step 6: 提交/检查点**

---

### Task 12: 三路对比工具 + 指标 + 文档收尾

**Files:**
- Create: `src/app/services/structure/metrics.py`
- Create: `scripts/compare_routes.py`
- Modify: `README.md`、`docs/api.md`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: PageGraph 文件。
- Produces:
```python
def container_iou_matrix(a: list[dict], b: list[dict]) -> list[list[float]]
def text_containment_rate(graph: dict) -> float
def summarize(graph_a: dict, graph_b: dict) -> dict
```

- [ ] **Step 1: 写失败测试**

`tests/test_metrics.py`：
```python
from src.app.services.structure.metrics import container_iou_matrix, text_containment_rate

def test_iou_matrix():
    a = [{"bbox": [0, 0, 100, 100]}]
    b = [{"bbox": [0, 0, 50, 50]}]
    assert abs(container_iou_matrix(a, b)[0][0] - 0.25) < 1e-6

def test_containment_rate():
    g = {"containers": [{"bbox": [0, 0, 100, 100]}],
         "elements": [{"bbox": [10, 10, 10, 10], "type": "text"},
                      {"bbox": [200, 200, 10, 10], "type": "text"}]}
    assert text_containment_rate(g) == 0.5
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 metrics.py**

```python
"""三路 PageGraph 轻量对比指标（无人工标注；dom 可用作参照）。"""
from __future__ import annotations

def container_iou_matrix(a: list[dict], b: list[dict]) -> list[list[float]]:
    from src.app.services.structure.graph import iou
    return [[iou(x["bbox"], y["bbox"]) for y in b] for x in a]

def text_containment_rate(graph: dict) -> float:
    from src.app.services.structure.graph import contains
    els = [e for e in graph["elements"] if e["type"] in ("text", "button", "input", "link")]
    if not els:
        return 0.0
    hit = sum(1 for e in els if any(contains(c, e) for c in graph["containers"]))
    return hit / len(els)

def summarize(graph_a: dict, graph_b: dict) -> dict:
    m = container_iou_matrix(graph_a["containers"], graph_b["containers"])
    best = [max(row) if row else 0.0 for row in m]
    avg = sum(best) / len(best) if best else 0.0
    return {"a": {"route": graph_a["route"], "containers": len(graph_a["containers"]),
                  "elements": len(graph_a["elements"]),
                  "text_containment": round(text_containment_rate(graph_a), 3)},
            "b": {"route": graph_b["route"], "containers": len(graph_b["containers"]),
                  "elements": len(graph_b["elements"]),
                  "text_containment": round(text_containment_rate(graph_b), 3)},
            "avg_best_container_iou_a_vs_b": round(avg, 3)}
```

- [ ] **Step 4: 运行通过**
Run: `python -m pytest tests/test_metrics.py -v`
Expected: PASS。

- [ ] **Step 5: 实现 scripts/compare_routes.py**

```python
"""同一 URL/截图跑多条路线，输出对比小结 + 各路线 SoM 产物。用法：
python scripts/compare_routes.py --url https://example.com --routes dom,grounding,cv
"""
from __future__ import annotations
import argparse, sys, json, itertools
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dataclasses import replace
from src.config import load_config
from src.app.services.structure.metrics import summarize

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--image", default=None)
    ap.add_argument("--routes", default="dom,grounding,cv")
    ap.add_argument("--base-out", default="output/compare")
    args = ap.parse_args()
    cfg = load_config()
    graphs, summary = {}, []
    for r in args.routes.split(","):
        sub = Path(args.base_out) / r
        from src.app.agents.precise_agent import PreciseAgent
        PreciseAgent(replace(cfg, output_dir=sub)).run(
            url=args.url, image=args.image, route=r, tool="svg")
        graphs[r] = json.loads((sub / "10_pagegraph.json").read_text(encoding="utf-8"))
    for ra, rb in itertools.combinations(graphs, 2):
        summary.append(summarize(graphs[ra], graphs[rb]))
    out = Path(args.base_out) / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in summary:
        print(s)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 文档收尾**
`README.md` 与 `docs/api.md` 追加：`--url/--route/--enrich` 参数说明、PreciseAgent Python API 示例、VISION_*/TEXT_* 网关说明、Playwright 前置（`python -m playwright install chromium`）、`compare_routes.py` 用法。

- [ ] **Step 7: 全量回归 + 提交/检查点**
Run: `python -m pytest tests/ -q -m "not integration"`
Expected: 全绿。随后 integration 手工验收：`python -m src.main --url https://example.com --route auto --tool svg`，确认产物齐全且回退记录正确。

---

## Self-Review 记录

- Spec 覆盖：CLI/产物(T1/T11/T12)、PageGraph(T2)、路由(T3/T11)、dom/a11y/grounding/cv(T5-T8)、enrich 开关按 spec 默认关闭仅留参(T11)、SoM(T9)、DesignSpec+渲染(T10/T11)、对比(T12)、配置/依赖/测试(T1/T12)。
- 签名一致性：graph 与 provider/annotate/som/llm 接口在各 Task 的定义处与调用处一致；`ProviderContext` 字段（image_path/image_w/image_h/route/output_dir/dom_path/ax_path）在 T5 定义并被 T5-T8/T11 使用。
- CV provider（T8）gestalt 调用签名以 `container_pipeline/run_pipeline.py` 为唯一权威参照，实现时对照微调、禁止改动该文件——已显式标注。
- 遗留决策：仓库非 git，commit 步骤在用户同意 `git init` 后启用；`.env` 密钥由实施者在执行时填入。
