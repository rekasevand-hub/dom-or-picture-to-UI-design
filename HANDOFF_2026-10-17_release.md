# HANDOFF — Figma_auto_agent 1.1.0 冻结发版

**日期：** 2026-10-17  
**版本：** 1.1.0  
**状态：** 源码冻结发版  
**基线：** 当前工作树（未创建 git commit / tag）  
**版本唯一来源：** 项目根 `VERSION`

---

## 1. 这次发版做了什么

### 1.1 版本与文档

- `VERSION`：`1.0.1` → `1.1.0`
- `setup.py` 描述更新为 DOM/视觉多路线 + SVG/Figma/Axure
- `src/app/version.py` 改为指向本交接文档
- CLI `--help`、交互式工具菜单不再引用已删除的 `docs/` 文件
- 重写根 `README.md`
- 新增本文件 `HANDOFF_2026-10-17_release.md`

### 1.2 冻结清理

以下内容已从项目目录移出，归档到：

```text
D:\LLM-Data\Figma_auto_agent_release_archive\v1.0.1_2026-10-17
```

归档清单：

- `tests/`（约 50 个测试文件、155 个文件）
- `docs/`（旧 API、Axure、Figma 设计与 superpowers 计划）
- 根目录全部旧 `HANDOFF_*.md`
- `DESIGN.md`
- `PLAN.md`
- `pytest.ini`
- `README_v1.0.1.md`（旧 README 副本）
- `ARCHIVE_INFO.txt`（归档说明与回归结果）

冻结后的源码树不再包含 `tests/`、`docs/`、旧 `HANDOFF_*.md`、`DESIGN.md`、`PLAN.md`、`pytest.ini`。

### 1.3 发布内容

发布包是**源码包**，包含：

- `src/`
- `scripts/`
- `figma_bridge/`
- `assets/`（Axure 文档模板，必需）
- `container_pipeline/`（CV 路线必需）
- `samples/`
- `site_profiles/`
- `requirements.txt`
- `requirements-easyocr.txt`
- `.env.example`
- `.gitignore`
- `setup.py`
- `VERSION`
- `README.md`
- `HANDOFF_2026-10-17_release.md`

发布包不包含：

- `.env`
- `.env.test`
- `login_state.json`
- `closeai_state.json`
- `output/`
- `uploads/`
- `.git/`
- `.vscode/`
- `.superpowers/`
- `__pycache__/`
- `.pytest_cache/`
- `OmniParser/`（约 1.1GB，外部模型资源）
- 任何测试缓存、截图产物、发布中间件

---

## 2. 运行环境与入口

### 2.1 本机验收环境

```text
Windows 10/11 + PowerShell
Python: C:\Users\lzq\.conda\envs\omni\python.exe
Conda env: omni
Python 3.11
```

运行前设置：

```powershell
cd D:\LLM-Data\Figma_auto_agent
$env:PYTHONPATH='.'
$env:PYTHONIOENCODING='utf-8'
```

### 2.2 入口

```powershell
python -m src.main --help
```

主要参数：

```text
--url / --image       可重复；多输入 -> 多页（当前仅 Axure）
--route               auto | dom | grounding | cv
--tool                svg | figma | jsdesign | mockingbot | axure
--output-dir          输出目录
--storage-state       复用登录态
--login-state         交互登录并导出登录态
--interactive         交互式向导
--pick-crops          grounding/cv 手工框选
--debug               调试日志
```

### 2.3 最小验证命令

DOM → SVG：

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool svg `
  --output-dir output/_svg_dom
```

DOM → Axure：

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool axure `
  --output-dir output/_axure_dom
```

### 2.4 Figma 启动顺序

1. 终端 A：

```powershell
python -m src.app.services.bridge_server
```

2. Figma → `Plugins` → `Development` → `Import plugin from manifest...` → `figma_bridge/manifest.json`
3. 运行插件，确认状态为“已连接到桥接服务器”
4. 终端 B：

```powershell
python -m src.main `
  --url "https://www.dushu.com/" `
  --route dom `
  --tool figma `
  --output-dir output/_figma_dom
```

`WinError 10061` 的直接含义：Figma 桥未启动、端口不匹配，或插件未连接。不是 DOM 采集失败。

---

## 3. 核心模块职责

| 模块 | 职责 |
|---|---|
| `src/main.py` | CLI 参数、交互入口、登录态导出、新旧流程分流 |
| `src/app/agents/precise_agent.py` | 主流程：采集 → 路由 → PageGraph → SoM → DesignSpec → 渲染 |
| `src/app/services/structure/` | Playwright DOM 采集、页面图、站点 profile、路由 |
| `src/app/services/structure/providers/` | `dom` / `grounding` / `cv` 三种结构源 |
| `src/app/services/som/` | SoM 标注、直接设计、人工框选 |
| `src/app/services/rendering/adapter_base.py` | DesignSpec 绘制顺序、文字折行、文本行框、多页入口 |
| `src/app/services/rendering/svg_adapter.py` | SVG 输出 |
| `src/app/services/rendering/figma_adapter.py` | WebSocket 调 Figma Plugin API |
| `src/app/services/rendering/axure_adapter.py` | DesignSpec → Axure `.rp` |
| `src/app/services/rendering/axure/` | `.rp` 的 C1 流、Store、控件模型、文档写入、缩略图 |
| `src/app/services/bridge_server.py` | Figma 插件与 Python 适配器之间的本地桥 |
| `figma_bridge/` | Figma 开发插件（`manifest.json` / `code.js` / `ui.html`） |
| `container_pipeline/` | CV 路线的传统容器/元素检测管线 |
| `assets/axure/rp8/` | Axure 文档级原生模板，必须随源码保留 |

---

## 4. Axure「图标压字」修复结论

### 4.1 现象

Axure 发布稿中，按钮右侧图标会盖住标题文字，例如：

- 页头按钮
- “查看更多”按钮

根因不是图标位置错，而是按钮标题面板仍按**控件盒**排版：图标占用了按钮右侧内部空间，标题面板没有消费 DOM 的 `textBox` 偏移，文字从错误的内边距起排，于是被图标压住。

### 4.2 修法

- 按钮标题面板消费 `textBox`：按面板相对按钮的偏移定位，标题对齐改左。
- 标题面板定位使用 `P_PADDING_LEFT`，`P9 = 0`，不再走会引入额外内边距的内嵌控件路径。
- 紧盒按钮：
  - `PADDING_LEFT = dx`
  - `PADDING_RIGHT = -dx`
  - 用左右内边距互补吸收偏移，保持控件原宽度不变。
- 这样既不会把 56px 文字塞进 56px 面板导致折行，也不会把紧盒按钮撑宽。

涉及文件：

- `src/app/services/rendering/axure_adapter.py`
- `src/app/services/rendering/axure/doc.py`

### 4.3 真机证据

`paddingfix` 发布稿：

```text
#u40_text  left: 30px  width: 76px
#u41_text  left: 30px  width: 76px
#u280_text left: 54px  width: 324px
#u325_text left: 54px  width: 324px
```

`tightcase2` 紧盒场景：

```text
#u1       width: 100px
#u1_text  left: 55px  width: 100px
```

结论：

- 标题起点已按 `textBox` 偏移，不再从图标下面起排。
- 紧盒按钮宽度保持 100px，没有被内边距撑大。
- 标题保持单行，没有因 56px 面板 / 56px 文字零余量而折行。

截图证据：

```text
output\_axure_icon\shots2\crop_header.png
output\_axure_icon\shots2\crop_more1.png
output\_axure_icon\shots2\crop_more2.png
output\_axure_icon\shots_tight\crop_tight.png
```

### 4.4 剩余风险

- 多行按钮仍可能回退到 Axure 原生排版。
- 没有 `textBox` 的按钮无法消费真实文字行框，仍按控件盒排版。
- 极端紧盒按钮可能仍有轻微压字，但当前修法不会再引入折行，也不会撑宽控件。
- 如果后续要彻底消除，需要给“无 `textBox` / 多行按钮”单独建一套文本落点策略，并补真机 A/B。

---

## 5. 冻结验证结果

### 5.1 冻结前回归

执行：

```powershell
& 'C:\Users\lzq\.conda\envs\omni\python.exe' -m pytest -q --ignore=tests/test_omni_init.py
```

结果：

```text
522 passed, 22 skipped in 9.31s
```

说明：

- `tests/test_omni_init.py` 被排除，原因是本机 PaddleOCR 版本不兼容；这是环境问题，不是本次发版改动。
- 该结果对应删除 `tests/` 前的最后一版源码。

### 5.2 冻结后编译

```powershell
python -m compileall -q src scripts
```

结果：

```text
compileall: OK
```

### 5.3 冻结后 CLI

```powershell
python -m src.main --help
```

结果：正常输出，`--help` 不再引用已删除文档。

### 5.4 冻结后 Axure 渲染冒烟

使用既有：

```text
output/_axure_dom/12_design.json
```

执行：

```powershell
$env:OUTPUT_DIR='output/_release_smoke'
python scripts/render_design.py --design output/_axure_dom/12_design.json --tool axure
```

结果：

```text
已渲染 333 个元素到 axure
prototype.rp = 634,914 bytes
```

未启动 Axure，未执行发布脚本。

---

## 6. 历史文档说明

旧 `docs/` 与旧 `HANDOFF_*.md` 已整体移出项目。代码里仍保留少量“归档文档 axure_rp8_*.md / 归档文档 api.md / 归档交接 HANDOFF_2026-*”的实现依据注释，这些文件在：

```text
D:\LLM-Data\Figma_auto_agent_release_archive\v1.0.1_2026-10-17
```

它们不是本发布包的运行时依赖。

---

## 7. 已知限制

- `jsdesign` / `mockingbot` 仍是桩，不可用于正式交付。
- `grounding` / `cv` 需要 `VISION_API_KEY`；`cv` 还需要本地 OmniParser 权重。
- 发布包不含 `OmniParser/`，CV 路线需自行放入：

```text
OmniParser/OmniParser-master/
```

- 多输入多页目前只支持 Axure；SVG / Figma 会明确拒绝。
- Figma 输出依赖 bridge server + 插件同时在线。
- `TEXT_ALIGN` 仅对 SVG 生效；Figma / Axure 不使用 SVG 的 ±1px 位移。
- `scripts/axure_publish_html.ps1` 会结束本机所有 `AxureRP8` 进程并删除目标 Tag 目录；运行前必须存盘。
- Axure 多行按钮、无 `textBox` 按钮仍是剩余压字风险点。
- 站点 profile 是经验阈值，站点改版后需重新采集和复核。

---

## 8. 后续建议

1. 为 Axure 多行按钮 / 无 `textBox` 按钮补文本落点策略和真机 A/B。
2. 决定是否为 SVG / Figma 增加真正的多页输出。
3. 接入即时设计 / 墨刀正式 API，或从 CLI 中移除桩选项。
4. 为 CV 路线增加 OmniParser 权重的可选下载/校验脚本，避免 1.1GB 资源进源码包。
5. 在 CI 中恢复归档测试，并固定 PaddleOCR 版本，消除 `test_omni_init.py` 的环境性跳过。
6. 为 Figma 桥增加“未启动/插件未连接”的启动前自检和更友好的错误提示。

---

## 9. 发布包校验

发布包路径：

```text
D:\LLM-Data\Figma_auto_agent_release\figma-auto-agent-1.1.0-2026-10-17.zip
```

SHA256 不在包内写死（避免自引用），最终值以发布目录中的外部校验文件为准：

```text
D:\LLM-Data\Figma_auto_agent_release\RELEASE_SHA256_1.1.0.txt
```

包内文件数：144（含 `RELEASE_INFO.txt` / `RELEASE_MANIFEST.txt`）  
校验副本：同目录 `RELEASE_SHA256_1.1.0.txt`（ZIP 字节数以实际文件为准）

**冻结约定：** 发布包生成后不再改源码；如需修复，应升版本并重新打包。
