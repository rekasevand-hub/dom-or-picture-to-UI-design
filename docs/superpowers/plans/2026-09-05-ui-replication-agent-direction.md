
# 通用 UI 复刻 Agent 方向修正实施计划（DOM 真值 + 单解释器 + 三结构源）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把项目从"flexweaver/antd 单页复刻脚本"纠正为通用 UI 复刻 Agent：删除 a11y 路线，grounding/cv 保留为可显式调用的独立接口，DOM 真值 + 单解释器（MLLM）为默认语义路径，站点特化收进 Profile，并建立多页回归语料防过拟合。

**Architecture:** 采集层(Playwright 截图+DOM JSON) → 规整层(DOM JSON→PageGraph，零页面知识) → 理解层(唯一的 MLLM Interpreter，SoM+JSON→DesignSpec) → 渲染层(Figma/SVG)。dom/grounding/cv 三条结构源可显式调用，auto 模式按 `dom→grounding→cv` 回退；a11y 全链路删除。特化(antd 图标映射、overlay 调参)以 site Profile 数据存在，核心默认路径不依赖。

**Tech Stack:** Python 3.12，Playwright，OpenAI 兼容视觉模型(qwen3-vl-plus)，Pillow，OpenCV，pytest。

**Spec:** [docs/superpowers/specs/2026-09-05-ui-replication-agent-direction-design.md](../specs/2026-09-05-ui-replication-agent-direction-design.md)

## Global Constraints

- 路线集合收敛为 `auto/dom/grounding/cv`；代码、配置、文档、测试中不再出现 `a11y`/AX/CDP 语义采集。
- `dom`/`grounding`/`cv` 三者都是可直接调用的主处理方向（尤其 `--image` 输入时 grounding/cv 是常规选择）；只有 `auto` 模式把它们当回退链。
- 核心模块（`providers/dom.py`、`router.py`、`direct_design.py`、`llm_service.py`）不得出现页面/框架字面量（antd、flexweaver、`图标: form` 等）；这些只允许存在于 `site_profiles/` 数据与提示词里。
- PageGraph/SoM 的 `element.text` 只存 DOM 可见文本；代码不得把推断语义写入 `text`。语义候选经 `ariaLabel`/`title` 字段透传给模型。
- 保真优先：模型输出的文本与 DOM 可见文本冲突时，以可见文本为准。
- 所有几何坐标保持原图像素整数坐标系。
- 默认不直出 DesignSpec：`DOM_DIRECT_DESIGN` 默认 `false`（route=dom 默认走 Interpreter/VLM）；`--fast` 仅 DOM 路线开启几何直出，无语义回填。
- 每任务必须可独立测试并提交；跑测试用：
  `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\ -q -m "not integration" --ignore=tests\test_omni_init.py`

---


### Task 1: 删除 a11y 路线与 CDP AX 采集

**Files:**
- Delete: `src/app/services/structure/providers/a11y.py`
- Delete: `tests/test_a11y_provider.py`
- Modify: `src/app/services/structure/capture.py`（删 `_ax_bounds`/`_read_ax_style`/`_inject_ax_bounds`、`ax_style` 参数、`00_ax.json` 产物、返回 dict 去 `ax`）
- Modify: `src/app/services/structure/providers/base.py`（`ProviderContext` 删 `ax_path`；新增 `url: str | None = None` 供 Task 5 用）
- Modify: `src/app/services/structure/providers/__init__.py`（删 A11yProvider import 与 `__all__`）
- Modify: `src/app/services/structure/router.py`（valid 集合去 a11y；`requested in ("dom","a11y")` 改 `("dom",)`；报错文案改"DOM"）
- Modify: `src/app/agents/precise_agent.py`（删 A11yProvider 分支；URL 分支去掉 `ax_style=`；ctx 去 `ax_path=`，加 `url=url`）
- Modify: `src/app/agents/route_select.py`（`ALL_ROUTES`/`ROUTE_HINTS`/`route_options`/入口文案去 a11y）
- Modify: `src/app/main.py`（`--route` choices 去 a11y；新增 `--fast` parser 参数，Task 4 才接线）
- Modify: `src/app/services/som/direct_design.py`（`_DIRECT_ROUTES = ("dom",)`；docstring 去 a11y）
- Modify: `tests/test_precise_agent.py`、`tests/test_route_select.py`、`tests/test_direct_design.py`、`tests/test_dom_provider.py`、`tests/test_capture.py`（清理 ax 引用与 a11y 用例）

**Interfaces:**
- Consumes: 现 `capture_page(url, cfg, output_dir, ax_style=False) -> {"image","width","height","dom","ax"}`
- Produces: `capture_page(url, cfg, output_dir) -> {"image","width","height","dom"}`；`ProviderContext(image_path, image_w, image_h, route="", output_dir="", dom_path=None, url=None)`；`route_order` 合法集 `{"dom","grounding","cv"}`

- [ ] **Step 1: 写/改回归测试（先红）**

新建 `tests/test_router_no_a11y.py`：

```python
from dataclasses import replace
from src.config import load_config
from src.app.services.structure.router import route_order

def test_route_set_has_no_a11y():
    cfg = replace(load_config(), vision_api_key=None)
    for chain in (route_order("url", "auto", cfg, have_dom=True),
                  route_order("url", "auto", cfg, have_dom=False)):
        assert "a11y" not in chain

def test_dom_route_requires_url_dom():
    cfg = replace(load_config(), vision_api_key=None)
    try:
        route_order("image", "dom", cfg, have_dom=False)
    except ValueError:
        return
    raise AssertionError("dom 在纯图片输入下应报错")
```

`tests/test_precise_agent.py`：两处 fake `capture_page` 的返回 dict 去掉 `"ax": None` 键，签名改 `def fake_capture(url, cfg, out_dir):`；把断言 `seen["kwargs"] == {"ax_style": False}` 改为 `seen["kwargs"] == {}`。

`tests/test_route_select.py` 替换三个用例：

```python
def test_route_options_url_with_key():
    opts = route_options("url", replace(load_config(), vision_api_key="sk-test"))
    assert opts == ["auto", "dom", "grounding", "cv"]

def test_route_options_url_no_key():
    opts = route_options("url", _no_key_cfg())
    assert opts == ["auto", "dom", "cv"]

def test_select_url_grounding():
    cfg = replace(load_config(), vision_api_key="sk-test")
    req = select_interactive(cfg, ask=_ask_sequence(["1", "https://example.com", "3", "1"]))
    assert req["url"] == "https://example.com"
    assert req["route"] == "grounding" and req["tool"] == "svg"
```

删除：`tests/test_route_select.py` 的 `test_route_options_url_includes_all`、`test_select_url_a11y`；`tests/test_a11y_provider.py` 整个文件；`tests/test_direct_design.py` 中 `test_a11y_provider_passthrough_style`、`test_build_direct_design_a11y_mode`、第 200 行对 `_direct_som("a11y")` 的直出断言；所有 `ax_path=`/`ctx.ax_path` 实参。

- [ ] **Step 2: 跑测试确认失败**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\ -q -m "not integration" --ignore=tests\test_omni_init.py`
Expected: 多个 FAIL（a11y import/枚举残留、`ax_style` kwargs、`ax_path` 不存在）。

- [ ] **Step 3: 实现删除**

`capture.py`：删三个 AX 函数；`capture_page` 去掉 `ax_style` 参数与从 `page_bg = page.evaluate(...)` 到 `ax_p.write_text(...)` 的全部 CDP 代码；删 `ax_p = out / "00_ax.json"`；返回 `{"image":..., "width":..., "height":..., "dom":...}`。

`providers/base.py`：

```python
@dataclass
class ProviderContext:
    image_path: str
    image_w: int
    image_h: int
    route: str = ""
    output_dir: str = ""
    dom_path: str | None = None
    url: str | None = None
```

`router.py`：

```python
    valid = {"dom", "grounding", "cv"}
    if requested:
        if requested in ("dom",) and not dom_ok:
            raise ValueError(f"路线 {requested} 需要网页 DOM 数据；当前输入为 {input_kind}，请改用 --url 或选 grounding/cv")
        return [requested]
```

`providers/__init__.py` 删 A11yProvider 相关两行。`precise_agent.py`：`_build_provider` 删 a11y 分支；URL ctx：

```python
            cap = capture_page(url, self.config, str(out))
            image, w, h = cap["image"], cap["width"], cap["height"]
            ctx = ProviderContext(image_path=image, image_w=w, image_h=h,
                                  route="", output_dir=str(out),
                                  dom_path=cap["dom"], url=url)
```

`route_select.py`：

```python
ALL_ROUTES = ("auto", "dom", "grounding", "cv")
ROUTE_HINTS = {
    "auto":      "自动：URL 优先 DOM，失败逐级回退 grounding/cv",
    "dom":       "网页真实 DOM（几何+样式，坐标最准）—— 仅 URL",
    "grounding": "多模态模型直接看图出容器/元素 bbox（需 VISION_API_KEY）",
    "cv":        "纯像素 CV 管线（OmniParser）—— 可直接作为主处理方向",
}
```

`route_options` URL 分支改 `opts += ["dom", "grounding", "cv"]`；交互文案 `["网页 URL（可 dom/a11y）", "本地截图（grounding/cv）"]` 改 `["网页 URL（可 dom）", "本地截图（grounding/cv）"]` 并同步判断分支。

`main.py` `--route` choices 改 `["auto", "dom", "grounding", "cv"]`，并加：

```python
    parser.add_argument("--fast", action="store_true",
                        help="（实验）DOM 路线用 computed style 几何直出 DesignSpec，跳过 VLM 语义生成")
```

`direct_design.py`：`_DIRECT_ROUTES = ("dom",)`；清掉 docstring/注释里 a11y 表述（直出代码保留）。

- [ ] **Step 4: 跑测试确认通过**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\ -q -m "not integration" --ignore=tests\test_omni_init.py`
Expected: 全绿（删 a11y 用例后总数下降约 8–10）。

- [ ] **Step 5: 提交**

```bash
git add -A src tests
git commit -m "refactor: remove a11y route and CDP AX capture; drop ax_path from context"
```


### Task 2: grounding 改为归一化坐标，修 bbox 缩放失真

**Files:**
- Modify: `src/app/services/structure/backends/grounding_vlm.py`
- Create: `tests/test_grounding_parse.py`

**Interfaces:**
- Consumes: `parse_vlm_json(raw: str, image_w: int, image_h: int) -> dict`
- Produces: `parse_vlm_json` 新契约：bbox 为 `[x0,y0,x1,y1]` 归一化浮点(0..1)，按 `image_w/image_h` 还原像素整数框并 clamp。

- [ ] **Step 1: 写失败测试**

```python
import json
from src.app.services.structure.backends.grounding_vlm import parse_vlm_json

def _raw(containers, elements):
    return json.dumps({"containers": containers, "elements": elements})

def test_parse_vlm_normalized_scales_to_pixels():
    raw = _raw(
        [{"bbox": [0.0, 0.0, 0.5, 0.25], "role": "banner"}],
        [{"bbox": [0.1, 0.2, 0.3, 0.4], "type": "button", "text": "保存"}])
    out = parse_vlm_json(raw, 1000, 800)
    assert out["containers"] == [{"bbox": [0, 0, 500, 200], "role": "banner"}]
    assert out["elements"] == [{"bbox": [100, 160, 200, 160], "type": "button", "text": "保存"}]

def test_parse_vlm_normalized_clamps_and_rejects_degenerate():
    raw = _raw([{"bbox": [0.9, 0.9, 1.2, 1.0], "role": "panel"}],
               [{"bbox": [0.0, 0.0, 0.0, 0.5], "type": "text", "text": "x"}])
    out = parse_vlm_json(raw, 100, 100)
    assert out["containers"] == [{"bbox": [90, 90, 10, 10], "role": "panel"}]
    assert out["elements"] == []  # 宽 <2 丢弃
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_grounding_parse.py -q`
Expected: FAIL（当前实现把 0..1 当像素直接 int()）。

- [ ] **Step 3: 实现**

`grounding_vlm.py` 增加坐标解析助手并重写两处解析：

```python
def _norm_box(b, image_w, image_h):
    try:
        f = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    if len(f) != 4:
        return None
    x0 = max(0.0, min(f[0], 1.0)); y0 = max(0.0, min(f[1], 1.0))
    x1 = max(0.0, min(f[2], 1.0)); y1 = max(0.0, min(f[3], 1.0))
    px0, py0 = int(round(x0 * image_w)), int(round(y0 * image_h))
    px1, py1 = int(round(x1 * image_w)), int(round(y1 * image_h))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return None
    return [px0, py0, px1 - px0, py1 - py0]
```

`parse_vlm_json` 中容器/元素统一走 `box = _norm_box(b, image_w, image_h); if box is None: continue`；元素类型校验保持 `ALLOWED_TYPES`。

`PROMPT` 末尾追加："bbox 坐标是 0~1 的归一化比例（相对你实际看到的那张图），禁止使用像素绝对值；左上原点。"

- [ ] **Step 4: 跑测试确认通过**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_grounding_parse.py tests\test_precise_agent.py -q`
Expected: 全绿；如有旧 grounding 用例按新契约改写。

- [ ] **Step 5: 提交**

```bash
git add src/app/services/structure/backends/grounding_vlm.py tests/test_grounding_parse.py
git commit -m "fix(grounding): normalized 0-1 bbox contract to fix gateway-downscale coordinate drift"
```


### Task 3: PageGraph/SoM 语义候选透传 + 核心去除语义回填

**Files:**
- Modify: `src/app/services/structure/capture.py`（DOM_JS 补 `title`）
- Modify: `src/app/services/structure/graph.py`（`add_element` 支持 `aria_label`/`title`）
- Modify: `src/app/services/structure/providers/dom.py`（删常量 `_ICON_ARIA_PREFIXES`、`_ICON_ARIA_LABELS`，函数 `_icon_aria_text`、`_empty_button_fallback_text`，元素循环前的 `text_leaves`/`aria_idxs` 预索引及循环内空按钮回填调用块；`add_element` 传 `aria_label`/`title`；overlay 阈值常量保留为通用默认，注释去 antd 字面量）
- Modify: `src/app/services/som/annotate.py`（SoM element 带出 `ariaLabel`/`title`，非空才写）
- Modify: `src/app/services/llm/llm_service.py`（`_som_entries` 带出 `ariaLabel`/`title`；`_normalize_design_element` 改为可见文本强制优先）
- Modify: `tests/test_dom_provider.py`、`tests/test_direct_design.py`

**Interfaces:**
- Produces: `graph.add_element(g, bbox, type_="rectangle", text="", role="", source="", confidence=1.0, style=None, overlay=False, z_index=0, aria_label="", title="")`；PageGraph 与 SoM element 新增可选键 `ariaLabel`、`title`。

- [ ] **Step 1: 写失败测试**

`tests/test_dom_provider.py` 追加：

```python
def test_dom_provider_passes_aria_and_title_through(tmp_path):
    nodes = [{"tag": "a", "role": "", "ariaLabel": "图标: form", "text": "",
              "title": "编辑表单", "x": 100, "y": 200, "w": 57, "h": 19,
              "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255,255,255)",
              "interactive": True}]
    g = _run_provider(tmp_path, nodes)
    btn = next(e for e in g["elements"] if e["type"] == "button")
    assert btn["text"] == ""                 # 核心不做语义回填
    assert btn["ariaLabel"] == "图标: form"  # 候选原样透传
    assert btn["title"] == "编辑表单"

def test_dom_provider_text_never_inferred_from_aria(tmp_path):
    nodes = [
        _a_button(100, 200, 57, 19),
        {"tag": "i", "role": "", "ariaLabel": "图标: form", "text": "",
         "x": 100, "y": 203, "w": 14, "h": 14, "bg": "rgba(0, 0, 0, 0)",
         "pageBg": "rgb(255, 255, 255)", "interactive": False}]
    g = _run_provider(tmp_path, nodes)
    btn = next(e for e in g["elements"] if e["type"] == "button")
    assert btn["text"] == "" and btn["ariaLabel"] == "图标: form"
```

删除 `test_dom_provider_backfills_icon_aria_button_text`；`test_dom_provider_uses_own_non_icon_aria` 改为断言 `btn["text"] == "" and btn["ariaLabel"] == "关闭"`；`test_dom_provider_does_not_backfill_visible_caption` 保留。

`tests/test_direct_design.py` 追加：

```python
def _som_with_aria_element():
    return {"image": "x.png", "size": [800, 600], "containers": [],
            "elements": [{"id": 1, "bbox": [100, 100, 60, 24], "type": "button",
                          "text": "", "ariaLabel": "图标: form", "style": {}}],
            "provenance": {"route": "dom"}}

def test_som_entries_carry_aria_candidates():
    from src.app.services.llm.llm_service import _som_entries
    entries = _som_entries(_som_with_aria_element())
    assert entries[0]["ariaLabel"] == "图标: form"

def test_normalize_design_prefers_visible_text():
    from src.app.services.llm.llm_service import _normalize_design_element
    entry = {"id": "1", "group": "element", "bbox": [100, 100, 60, 24],
             "type": "button", "text": "确定"}
    model = {"id": "1", "text": "删除"}
    out = _normalize_design_element(model, entry)
    assert out["text"] == "确定"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_dom_provider.py tests\test_direct_design.py -q`
Expected: FAIL（无 ariaLabel/title 键、`_som_entries` 未带出、文本仍可被模型覆盖）。

- [ ] **Step 3: 实现**

`capture.py` DOM_JS：`ariaLabel: el.getAttribute('aria-label') || '',` 后加 `title: el.getAttribute('title') || '',`。

`graph.py` `add_element` 签名追加 `aria_label="", title=""`，element dict 在 `"zIndex": int(z_index or 0),` 后加 `"ariaLabel": aria_label or "", "title": title or "",`。

`dom.py`：删除上述常量/函数/预索引/调用块；`add_element(...)` 加 `aria_label=n.get("ariaLabel", ""), title=n.get("title", "")`。overlay 常量与 `_overlay_*` 保留为通用默认；把注释里 "antd 固定列正是 absolute z=1 的整列容器" 改为通用描述（"absolute/sticky 浮层列、吸顶块是常见形态，因此按定位+重叠判定"）。

`annotate.py` elements 推导式 `"text": e["text"],` 后加：

```python
                         "ariaLabel": e.get("ariaLabel", ""),
                         "title": e.get("title", ""),
```

`llm_service.py` `_som_entries` element 分支追加：

```python
        if e.get("ariaLabel"):
            entry["ariaLabel"] = str(e["ariaLabel"])
        if e.get("title"):
            entry["title"] = str(e["title"])
```

`_normalize_design_element` 文本处理改为保真优先：

```python
    if entry.get("text"):
        out["text"] = entry["text"]          # DOM 可见文本为准，防模型改写
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\ -q -m "not integration" --ignore=tests\test_omni_init.py`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add -A src tests
git commit -m "feat(schema): pass ariaLabel/title as semantic candidates; core no longer infers button text"
```


### Task 4: DOM 直出默认关闭，新增 --fast 实验开关

**Files:**
- Modify: `src/config/settings.py`（`DOM_DIRECT_DESIGN` 默认 `false`）
- Modify: `src/app/agents/precise_agent.py`（`run()` 增 `fast=False`；fast 且 route∈(auto,dom) 时 `cfg = replace(self.config, dom_direct_design=True)`，run 内后续统一用本地 `cfg`）
- Modify: `src/app/main.py`（把 `--fast` 透传给 `agent.run(..., fast=args.fast)`）
- Modify: `.env.example`（默认 false 与 --fast 说明）
- Modify: `tests/test_direct_design.py`、`tests/test_precise_agent.py`

**Interfaces:**
- Consumes: Task 1 的 `--fast` parser 参数
- Produces: `PreciseAgent(config).run(*, url=None, image=None, route="auto", tool="svg", enrich=False, fast=False) -> dict`；`try_build_direct_design` 保持"cfg.dom_direct_design=True 且 route=dom 才直出，否则 None"。

- [ ] **Step 1: 写失败测试**

`tests/test_direct_design.py`（沿用 `_direct_som`、`_fast_cfg`）：

```python
def _fast_cfg():
    from dataclasses import replace
    return replace(load_config(), dom_direct_design=True)

def test_direct_design_gated_off_by_default():
    from src.config import load_config
    assert not load_config().dom_direct_design
    assert try_build_direct_design(_direct_som("dom"), load_config()) is None

def test_direct_design_enabled_via_flag_cfg():
    assert try_build_direct_design(_direct_som("dom"), _fast_cfg()) is not None
```

`tests/test_precise_agent.py` 追加：

```python
def test_run_fast_flips_dom_direct_design(tmp_path, monkeypatch):
    from dataclasses import replace
    import cv2, numpy as np
    from pathlib import Path
    from src.config import load_config
    from src.app.agents.precise_agent import PreciseAgent

    seen = {}
    def fake_capture(url, cfg, out_dir):
        out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / "00_screenshot.png"), np.zeros((100, 100, 3), dtype=np.uint8))
        (out / "00_dom.json").write_text("[]", encoding="utf-8")
        return {"image": str(out / "00_screenshot.png"), "width": 100,
                "height": 100, "dom": str(out / "00_dom.json")}
    class _OkProvider:
        def run(self, ctx):
            from src.app.services.structure.graph import new_graph
            return new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
    def fake_build(cfg, route):
        assert route == "dom"
        return _OkProvider()
    def fake_try(som_json, cfg):
        seen["direct_cfg"] = cfg
        return {"canvas": {}, "elements": []}
    class _NoopRenderer:
        def __init__(self, cfg): pass
        def render(self, design, tool): pass
    monkeypatch.setattr("src.app.services.structure.capture.capture_page", fake_capture)
    monkeypatch.setattr("src.app.agents.precise_agent._build_provider", fake_build)
    monkeypatch.setattr("src.app.services.som.direct_design.try_build_direct_design", fake_try)
    monkeypatch.setattr("src.app.controllers.rendering_controller.RenderingController", _NoopRenderer)
    cfg = replace(load_config(), vision_api_key="sk-test", output_dir=tmp_path)
    PreciseAgent(cfg).run(url="https://example.invalid", route="dom", tool="svg", fast=True)
    assert seen["direct_cfg"].dom_direct_design is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_direct_design.py tests\test_precise_agent.py -q`
Expected: FAIL（默认仍 true / `run` 无 `fast` 参数）。

- [ ] **Step 3: 实现**

`settings.py` 该行默认值改 `"false"`：

```python
    dom_direct_design: bool = field(default_factory=lambda: os.getenv("DOM_DIRECT_DESIGN", "false").lower() in ("1", "true", "yes"))
```

`precise_agent.py`：文件头 import 区加一行 `from dataclasses import replace`；把 `def run` 的签名与其后 cfg 初始化改为：

```python
    def run(self, *, url=None, image=None, route="auto", tool="svg",
            enrich=False, fast=False) -> dict:
        cfg = (replace(self.config, dom_direct_design=True)
               if (fast and route in ("auto", "dom")) else self.config)
        out = cfg.output_dir
```

`run` 体内所有 `self.config` 改为 `cfg`（capture、ProviderContext、`_build_provider(cfg, r)`、`try_build_direct_design(som_json, cfg)`、`generate_som_design(som_json, b64, cfg, ...)`、`RenderingController(cfg)`）。

`main.py` 调用处加 `fast=args.fast`。

`.env.example`：

```ini
# DOM 路线默认走 Interpreter（VLM 语义生成）；true（或 CLI --fast）退回 computed style 几何直出，无语义推断
DOM_DIRECT_DESIGN=false
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\ -q -m "not integration" --ignore=tests\test_omni_init.py`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add src tests .env.example
git commit -m "feat(cli): DOM direct design off by default; add --fast experimental switch"
```


### Task 5: Site Profile（特化数据化，核心零页面字面量）

**Files:**
- Create: `src/app/services/structure/site_profiles.py`
- Create: `site_profiles/flexweaver.rtdsoft.com.json`
- Modify: `src/app/services/structure/providers/dom.py`（overlay 判定支持可选参数覆盖）
- Modify: `src/app/agents/precise_agent.py`（读取 profile，向 `som_json["_profile_hints"]` 注入提示）
- Modify: `src/app/services/llm/llm_service.py`（`build_som_prompt`/`build_som_batch_prompt` 在存在 `_profile_hints` 时追加提示段）
- Create: `tests/test_site_profiles.py`
- Modify: `tests/test_precise_agent.py`

**Interfaces:**
- Consumes: `ProviderContext.url`（Task 1）
- Produces: `load_profile(url: str | None) -> SiteProfile | None`；`SiteProfile(domains, icon_aria_labels, overlay)` 带 `.matches(url) -> bool`、`.hint_text() -> str`。

- [ ] **Step 1: 写失败测试**

```python
from dataclasses import replace
from src.config import load_config
from src.app.services.structure.site_profiles import load_profile

def test_mom_profile_loads_by_domain():
    prof = load_profile("http://flexweaver.rtdsoft.com:6016/index#/production/mfg_order_query")
    assert prof is not None
    assert prof.icon_aria_labels["form"] == "编辑"
    assert "form" in prof.hint_text() and "编辑" in prof.hint_text()

def test_profile_only_matches_its_domain():
    prof = load_profile("http://flexweaver.rtdsoft.com:6016/")
    assert prof is not None and int(prof.overlay["min_area"]) == 800
    assert load_profile("https://example.com") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_site_profiles.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

`src/app/services/structure/site_profiles.py`（完整文件，不含页面字面量）：

```python
# -*- coding: utf-8 -*-
"""站点 Profile：页面/框架级特化以数据形式存在，核心默认路径不依赖。

Profile 只允许影响：1) 给 Interpreter 的提示词；2) DOM overlay 判定的可选参数覆盖。
本模块不承载任何核心逻辑分支；文件位于仓库根 site_profiles/<host>.json。
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]          # 仓库根
_PROFILES_DIR = _ROOT / "site_profiles"


@dataclass
class SiteProfile:
    domains: list[str]
    icon_aria_labels: dict[str, str] = field(default_factory=dict)
    overlay: dict | None = None

    def matches(self, url: str) -> bool:
        if not url:
            return False
        host = (url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]).lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def hint_text(self) -> str:
        if not self.icon_aria_labels:
            return ""
        lines = ["站点图标语义（仅当条目 aria-label 以图标前缀开头时参考）："]
        for token, label in self.icon_aria_labels.items():
            lines.append("  " + token + " -> " + label)
        return "\n".join(lines)


def load_profile(url: str | None) -> SiteProfile | None:
    """按 URL 主机名加载 site_profiles/<host>.json；无匹配返回 None。"""
    if not url:
        return None
    host = (url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]).lower()
    fp = _PROFILES_DIR / (host + ".json")
    if not fp.is_file():
        return None
    data = json.loads(fp.read_text(encoding="utf-8"))
    return SiteProfile(
        domains=[str(d) for d in data.get("domains", [host])],
        icon_aria_labels={str(k): str(v)
                          for k, v in data.get("icon_aria_labels", {}).items()},
        overlay=data.get("overlay"))
```

`site_profiles/flexweaver.rtdsoft.com.json`：

```json
{
  "domains": ["flexweaver.rtdsoft.com"],
  "icon_aria_labels": {
    "form": "编辑", "edit": "编辑", "delete": "删除",
    "search": "搜索", "plus": "新增", "download": "下载",
    "upload": "上传", "setting": "设置", "close": "关闭"
  },
  "overlay": {"min_area": 800, "min_overlap_px": 1500,
              "min_overlap_w": 30, "min_overlap_h": 15}
}
```

`dom.py`：`_overlay_flags(nodes, rects, params=None)`，把四个阈值取值改为 `(params or {}).get("min_area", _OVERLAY_MIN_AREA)` 等；`DomProvider.run`：

```python
        from src.app.services.structure.site_profiles import load_profile
        prof = load_profile(ctx.url)
        ov = (prof.overlay or {}) if prof else None
        overlay_ctx = _overlay_context(nodes, rects, _overlay_flags(nodes, rects, ov))
```

`precise_agent.py` 在读取 `som_json` 后、进入 design 生成前：

```python
        if url:
            from src.app.services.structure.site_profiles import load_profile
            prof = load_profile(url)
            if prof and prof.icon_aria_labels:
                som_json["_profile_hints"] = prof.hint_text()
```

`llm_service.py` 两个 build 函数在 system 拼好后追加：

```python
    hints = som_json.get("_profile_hints")
    if hints:
        system = system + "\n站点提示（仅供参考，不得编造不在画面/列表中的内容）：\n" + hints
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_site_profiles.py tests\test_dom_provider.py tests\test_direct_design.py -q`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add -A src site_profiles tests
git commit -m "feat(profile): site profiles as data; overlay overrides optional; hints feed Interpreter prompts"
```


### Task 6: samples 多页回归语料与断言入口

**Files:**
- Create: `scripts/capture_samples.py`
- Create: `tests/fixtures/pages/simple_backend.html`
- Create: `tests/fixtures/pages/action_column_aria.html`
- Create: `samples/mom-antd-query/{00_screenshot.png,00_dom.json,expected.json}`
- Create: `samples/simple-backend/{...}`、`samples/action-column-aria/{...}`（由脚本抓取）
- Create: `tests/test_samples_regression.py`

**Interfaces:**
- Produces: `python scripts/capture_samples.py --html <file.html> --out <dir>`；`samples/<name>/expected.json` 形如 `{"min_containers": int, "min_elements": int, "max_elements": int}`；`pytest tests/test_samples_regression.py` 对每个 sample 离线跑 `DomProvider`。

- [ ] **Step 1: 写采集脚本与语料**

`scripts/capture_samples.py`：

```python
"""抓本地 HTML 页面成回归语料：00_screenshot.png + 00_dom.json。"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.structure.capture import DOM_JS

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(Path(args.html).resolve().as_uri(), wait_until="load")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "00_screenshot.png"), full_page=True)
        nodes = page.evaluate(DOM_JS)
        (out / "00_dom.json").write_text(
            json.dumps(nodes, ensure_ascii=False), encoding="utf-8")
        browser.close()
    from PIL import Image
    from src.app.services.structure.providers.dom import DomProvider
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.graph import assign_ids, assign_parent_depth
    im = Image.open(out / "00_screenshot.png")
    ctx = ProviderContext(image_path=str(out / "00_screenshot.png"),
                          image_w=im.width, image_h=im.height, route="dom",
                          output_dir=str(out), dom_path=str(out / "00_dom.json"))
    g = DomProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    nc, ne = len(g["containers"]), len(g["elements"])
    (out / "expected.json").write_text(json.dumps(
        {"min_containers": max(1, int(nc * 0.7)),
         "min_elements": max(1, int(ne * 0.7)),
         "max_elements": int(ne * 1.3) + 1}, indent=1), encoding="utf-8")
    print("captured", out, "counts", nc, ne)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

`tests/fixtures/pages/simple_backend.html`：

```html
<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:sans-serif;margin:0;background:#f4f5f7}
.hd{height:48px;background:#2b3643;color:#fff;line-height:48px;padding:0 16px}
.sb{position:fixed;left:0;top:48px;bottom:0;width:200px;background:#364150;color:#ddd;padding-top:12px}
.main{margin:48px 0 0 200px;padding:16px}
.card{background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:16px;margin:12px;width:300px;display:inline-block;vertical-align:top}
button{background:#1890ff;color:#fff;border:0;border-radius:4px;padding:6px 14px}
input{padding:6px 10px;border:1px solid #ccc;border-radius:4px;width:240px}
</style></head><body>
<div class="hd">Simple Admin</div>
<div class="sb"><div>菜单A</div><div>菜单B</div></div>
<div class="main">
 <input placeholder="输入搜索词"/>
 <div class="card"><h3>卡片一</h3><p>这里是第一张卡片的描述文字</p><button>确定</button></div>
 <div class="card"><h3>卡片二</h3><p>第二张卡片的内容说明</p><button>取消</button></div>
</div></body></html>
```

`tests/fixtures/pages/action_column_aria.html`（sticky 操作列 + 图标 aria，i 内是空文本 svg）：

```html
<!doctype html><html><head><meta charset="utf-8"><style>
body{font-family:sans-serif;margin:0;background:#fff}
table{border-collapse:collapse;width:100%;margin-top:60px}
th,td{border-bottom:1px solid #eee;padding:10px;text-align:left;white-space:nowrap}
.ops{position:sticky;right:0;background:#fff;box-shadow:-4px 0 6px -6px #999}
a{color:#1890ff;text-decoration:none;margin-right:8px;display:inline-block}
</style></head><body>
<table><tr><th>生产单号</th><th>状态</th><th class="ops">操作</th></tr>
<tr><td>PO-0001</td><td>进行中</td>
 <td class="ops"><a href="#"><i aria-label="图标: form"><svg width="14" height="14"><path d="M0 0h14v14H0z"/></svg></i></a>
     <a href="#"><i aria-label="图标: delete"><svg width="14" height="14"><path d="M0 0h14v14H0z"/></svg></i></a></td></tr>
<tr><td>PO-0002</td><td>已完成</td>
 <td class="ops"><a href="#"><i aria-label="图标: form"><svg width="14" height="14"><path d="M0 0h14v14H0z"/></svg></i></a>
     <a href="#"><i aria-label="图标: delete"><svg width="14" height="14"><path d="M0 0h14v14H0z"/></svg></i></a></td></tr>
</table></body></html>
```

执行抓取：

```bash
mkdir samples 2>$null
Copy-Item output\00_screenshot.png samples\mom-antd-query\00_screenshot.png
Copy-Item output\00_dom.json samples\mom-antd-query\00_dom.json
python scripts/capture_samples.py --html tests\fixtures\pages\simple_backend.html --out samples\simple-backend
python scripts/capture_samples.py --html tests\fixtures\pages\action_column_aria.html --out samples\action-column-aria
```

`tests/test_samples_regression.py`：

```python
import json
from pathlib import Path
import pytest
from PIL import Image
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.graph import assign_ids, assign_parent_depth

SAMPLES = [p for p in (Path(__file__).resolve().parents[1] / "samples").glob("*")
           if (p / "00_dom.json").exists()]

@pytest.mark.parametrize("sample", sorted(SAMPLES, key=lambda p: p.name),
                         ids=lambda p: p.name)
def test_sample_dom_pagegraph(sample):
    dom = json.loads((sample / "00_dom.json").read_text(encoding="utf-8"))
    im = Image.open(sample / "00_screenshot.png")
    ctx = ProviderContext(image_path=str(sample / "00_screenshot.png"),
                          image_w=im.width, image_h=im.height, route="dom",
                          output_dir=str(sample), dom_path=str(sample / "00_dom.json"))
    g = DomProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    exp = json.loads((sample / "expected.json").read_text(encoding="utf-8"))
    assert len(g["containers"]) >= exp["min_containers"]
    assert exp["min_elements"] <= len(g["elements"]) <= exp["max_elements"]
    for e in g["elements"] + g["containers"]:
        x, y, w, h = e["bbox"]
        assert x >= 0 and y >= 0 and x + w <= im.width + 1 and y + h <= im.height + 1
```

mom 快照用已知数量（离线实测 containers=117、elements=188）直接提交宽松界 `samples/mom-antd-query/expected.json`：

```json
{"min_containers": 80, "min_elements": 130, "max_elements": 260}
```

两个合成页由脚本在抓取时**自动生成** `expected.json`（±30% 界，见脚本第 3 步）；若改动后回归超界，先人工核对该页是否语义性变化，再决定调整期望还是修代码。

- [ ] **Step 2: 跑回归测试确认入口可用**

Run: `C:\Users\lzq\.conda\envs\omni\python.exe -m pytest tests\test_samples_regression.py -q`
Expected: PASS（三个 sample 全过；数量界不符就按实际值修正 expected.json 后重跑）。

- [ ] **Step 3: 提交**

```bash
git add scripts samples tests/fixtures tests/test_samples_regression.py
git commit -m "test(samples): multi-page DOM regression corpus against overfitting"
```

---

### Task 7: 文档与示例配置同步

**Files:**
- Modify: `README.md`、`docs/api.md`、`.env.example`

**Steps**
- [ ] **Step 1: 文本替换**
  - `README.md`：route 表 `--route` 值改 `auto / dom / grounding / cv`；删 a11y 相关段落与示例命令；补 `--fast` 行与“默认 DOM 走 Interpreter，`--fast` 退回 computed style 直出（仅 DOM、无语义推断）”说明；交互式选择段落同步。
  - `docs/api.md`：把 "dom / a11y 路线：样式直出" 小节改写为 "DOM 路线设计生成（默认 Interpreter / 可选 --fast 直出）"；参数表与示例命令删 a11y、补 --fast；`DOM_DIRECT_DESIGN` 默认值 `true`→`false`；`manifest.design.mode` 说明改为仅 `--fast` 时 `dom-direct`，默认走 VLM 时无该模式。
  - `.env.example`：DOM_DIRECT_DESIGN 注释与默认值按 Task 4 成品核对。
- [ ] **Step 2: 残留检查**

Run: `rg -n "a11y|00_ax|ax_style|ax_path|A11y" src tests README.md docs .env.example --glob '!**/__pycache__/**'`
Expected: 无输出（本计划与历史 spec 说明性提及除外）。

- [ ] **Step 3: 提交**

```bash
git add README.md docs .env.example
git commit -m "docs: sync route set, --fast, and Interpreter-default design flow"
```

---

## Self-Review 对照（spec §10 → Task）

| spec 落地项 | Task |
|---|---|
| 删除 a11y（代码/配置/路由/测试/文档/产物） | T1 + T7 |
| dom 语义特判迁出核心、ariaLabel/title 透传 | T3 + T5 |
| DOM 默认走 Interpreter、`--fast` 保留 | T4 |
| grounding bbox 缩放对齐 + 单测 | T2 |
| `samples/` 多页语料与断言 | T6 |
| 文档同步 | T7 |
