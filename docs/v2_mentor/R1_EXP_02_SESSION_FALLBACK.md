# R1-EXP-02 · URL 三态与真实会话降级回归

> 状态：`completed-for-current-scope`（2026-10-18）。  
> 范围：受控 loopback 页面上的 `content / soft_block / hard_login` 分类、截图保留、soft-block 降级与 hard-login 停止提示。  
> 证据：`output/_r1_experiments/r1_session_fallback_regression.json`、`r1_session_fallback_captures/`、`r1_session_fallback_contact.png`。

## 1. 方法

三个 authored 页面由本地 HTTP 服务提供，并经真实 headless Chromium 调用生产 `_capture_session`：

| 用例 | 页面信号 | 预期 |
|---|---|---|
| `content` | 正文、可见元素充足 | `content` |
| `soft_block` | 可见 CAPTCHA 组件与安全验证文案 | `soft_block` |
| `hard_login` | 登录标题、密码框与登录表单 | `hard_login` |

随后用真实捕获记录驱动 `capture_page_with_fallback`：

- soft-block 初始捕获 → 真实会话候选返回内容页；
- hard-login 初始捕获 → 后续会话只看到 soft-block。

实验没有读取、提交或保存凭据，也没有尝试破解 CAPTCHA。

## 2. 结果

- 三态分类：3/3 正确；`content=0.95`、`soft_block=0.95`、`hard_login=0.95` 置信度。
- 三种页面都保留了截图；soft/hard 页面各为 900×700。
- soft-block 降级后最终 `kind=content`、`screenshot_only=true`、`fallback_used=true`，内容页截图被 promote 为 `00_screenshot.png`。
- hard-login 即使后续会话只看到 soft-block，最终仍保持 `kind=hard_login`，并保留登录页截图。
- hard-login 提示包含 `--login-state`、`--storage-state` 与手动上传入口。
- 显式 `--route dom` 遇到 soft-block 时提示“不会静默切换路线”，并说明 `--route auto` 可自动降级为自主截图。
- 合同检查：10/10。

## 3. 语义

`soft_block` 不是“直接当内容页继续”，而是先保留拦截页截图，再尝试真实会话；只有后续捕获变成 `content` 才允许截图路线继续，并标记 `screenshot_only`。`hard_login` 是终止态，不会被后续 soft-block 覆盖。

## 4. 限制

- 页面是 authored loopback 夹具，真实站点登录墙、CAPTCHA 供应商与反爬变体未覆盖。
- 真实会话候选是确定性测试编排，不是实际登录后的浏览器 profile。
- 本实验只验证分类、截图保留与路线决策，不验证后续 DOM/截图重建质量。
- 没有真实凭据、验证码处理或生产站点的权限链。

## 5. 不得宣称

- 不得写“真实站点登录检测已通用验证”。
- 不得写“验证码可自动处理”；本实验明确没有绕过。
- 不得把 fake real-session 编排写成真实登录会话成功。
- 不得把三态回归写成 screenshot 复刻质量通过。

