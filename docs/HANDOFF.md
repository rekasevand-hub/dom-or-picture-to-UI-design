# HANDOFF —— 怎么接力

`docs/STATE.md` 讲**现在是什么**，这份讲**怎么接着干**，`docs/v2_mentor/` 的日期文档讲**为什么**。
三份不要互相复制：状态会变，理由不会。

---

## 接手（5 分钟）

1. 读 `docs/STATE.md`。一页纸，读完就该知道下一步动哪。
2. 对账：`python scripts/report_state.py`。它从 `acceptance.json` 现算，不读 STATE。
   **对不上，说明产物不是这份代码跑的，先别信任何结论。** 想让它自己盯：
   `pytest tests/v2/test_report_state_native_only.py` —— 红了就是 STATE 过期，或产物换了。
3. 看数字表里的「构建一致」列。不是「是」就先修环境（插件路径 / 版本），再谈分数。
4. 只有需要复查某一项的论证过程时，才去翻日期文档。

## 干活（三条纪律）

- **先取证再改。** 只读探针是标准起手式：`scripts/p1_*_probe.py`、`scripts/audit_structure.py`。先量，再改，改完还能量出来。
- **感知改动必须固定在冻结产物上做 A/B**（`--reuse-prepared`）。全量跑会重新采样 VLM，方差能盖过被测改动。
- **一次只动一件事，四组全跑**（holdout + 三族）。只看一族的好转，八成是另一族在出血。
- 动手前扫一眼 STATE 的禁改项；全表在各日期文档末尾。

## 交出去（20 分钟）

1. `python scripts/report_state.py --write docs/STATE.md` —— **数字一律生成，不手抄**。
   块里有三样：主表、native-only 表、失败维度。prose 只写判断，不复述数字。
2. 日期文档只写三样：**被推翻的假设 / 踩过的坑 / 新增的禁改项**。不复述数字（STATE 有），不复述做了什么（commit 有）。
3. 提交拆两笔：`feat|fix(...)` 代码 + `docs:`。下一个人要能只读代码 diff。
4. 推分支。全部只在本机等于没有。

## 判断一份交接可信不可信

| 检查 | 在哪 |
|---|---|
| `runtime.buildMatches` | `acceptance.json` —— 这批像素是哪版插件渲染的 |
| `gitSha` + `gitDirty` | 同上 —— 是不是脏工作区跑出来的 |
| 测试基线 | 当前 `1550 passed / 8 failed`；那 8 个必须是 axure manifest + p5 探针这批既有环境项 |
| STATE 的块 vs 现算 | `pytest tests/v2/test_report_state_native_only.py` —— 块外有没有手抄的数字表，一测就知道 |
| 数字来源 | 在生成块里（可信）/ 在 prose 里（会漂） |

## 什么时候该写日期文档

只有当天出现**被推翻的假设**或**新的禁改项**时才写。只是把某组多跑了几遍，刷新 `STATE.md` 就够。

反例：11-11 那份 96 KB 文档里，真正改变判断的是四条否证（`minAreaRect` 不行、墨量分字重 AUC 0.62、洪泛填充 tol≥5 漏全图、面积不能当字重判据），其余是过程。
