# QA 报告 · v1.0.0

- 生成时间：2026-11-11 13:00:18
- 执行方式：`QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py`
- 用例权威来源：`tests/docs/0*-TEST-CASES.md`
- 状态追踪：`tests/docs/templates/TEST-EXECUTION-TRACKING.csv`

## 质量门禁

| 门禁 | 结果 | 实测 |
|---|---|---|
| G1 测试执行率 100% | ✅ 通过 | 52/52 |
| G2 通过率 ≥80% | ✅ 通过 | 100.0% |
| G3 P0 缺陷 = 0 | ✅ 通过 | 0 个 |
| G4 P1 缺陷 ≤5 | ✅ 通过 | 1 个 |
| G5 代码覆盖率 ≥80% | ✅ 通过 | 86.2% |
| G6 安全覆盖 ≥90% | ✅ 通过 | 100.0% · 安全用例 12/12 通过，OWASP 类目结论 10/10 |

**结论**：✅ 门禁全绿，允许打 tag 发版

## 执行概览

- 用例：52 条，已执行 52 条，通过 52 条，失败 0 条
- 通过率：100.0%　代码覆盖率：86.2%　安全覆盖：100.0%
- pytest 退出码：0（0 表示含 `--cov-fail-under=80` 在内的检查全部通过）

## 缺陷

| ID | 级别 | 状态 | 标题 |
|---|---|---|---|
| BUG-001 | P1 | Verified | 无中文音色时打包后自检直接失败，未降级到可用音色 |
| BUG-002 | P2 | Verified | PDF 兼容表意文字未归一化，正文与朗读出现异体字 |

## 门禁口径

详见 `tests/docs/QUALITY-GATE.md`。覆盖率范围为 `src/core` 与 `src/controller.py`；
OWASP 不适用的类目以可执行的静态论证用例记录，不留空。
