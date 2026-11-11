# QA 报告 · v1.4.0

- 生成时间：2026-11-11 23:00:27
- 执行方式：`QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py`
- 用例权威来源：`tests/docs/0*-TEST-CASES.md`
- 状态追踪：`tests/docs/templates/TEST-EXECUTION-TRACKING.csv`

## 质量门禁

| 门禁 | 结果 | 实测 |
|---|---|---|
| G1 测试执行率 100% | ✅ 通过 | 82/82 |
| G2 通过率 ≥80% | ✅ 通过 | 100.0% |
| G3 P0 缺陷 = 0 | ✅ 通过 | 0 个 |
| G4 P1 缺陷 ≤5 | ✅ 通过 | 3 个 |
| G5 代码覆盖率 ≥80% | ✅ 通过 | 85.7% |
| G6 安全覆盖 ≥90% | ✅ 通过 | 100.0% · 安全用例 12/12 通过，OWASP 类目结论 10/10 |

**结论**：✅ 门禁全绿，允许打 tag 发版

## 执行概览

- 用例：82 条，已执行 82 条，通过 82 条，失败 0 条
- 通过率：100.0%　代码覆盖率：85.7%　安全覆盖：100.0%
- pytest 退出码：0（0 表示含 `--cov-fail-under=80` 在内的检查全部通过）

## 缺陷

| ID | 级别 | 状态 | 标题 |
|---|---|---|---|
| BUG-001 | P1 | Verified | 无中文音色时打包后自检直接失败，未降级到可用音色 |
| BUG-002 | P2 | Verified | PDF 兼容表意文字未归一化，正文与朗读出现异体字 |
| BUG-003 | P2 | Verified | 打包产物版本号恒为 0.0.0，界面不显示版本 |
| BUG-004 | P1 | Verified | 系统切换深浅色后界面不跟随，深色下句级高亮撞色 |
| BUG-005 | P1 | Verified | 音频缓存「上限 500 MB」未生效，只增不减 |

## 门禁口径

详见 `tests/docs/QUALITY-GATE.md`。覆盖率范围为 `src/core` 与 `src/controller.py`；
OWASP 不适用的类目以可执行的静态论证用例记录，不留空。
