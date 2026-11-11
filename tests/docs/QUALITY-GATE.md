# 质量门禁定义 · 文档朗读器 v1.0.0

> **铁闸原则**：以下 6 项全绿才允许推送 tag 并触发发版。任何一项未达标，「能不能发」的答案就是「还差哪几项」。

| # | 门禁 | 目标 | 数据来源 | 阻塞发版 |
|---|---|---|---|---|
| G1 | 测试执行率 | 100%（52/52 条 Completed） | `TEST-EXECUTION-TRACKING.csv` | 是 |
| G2 | 通过率 | ≥ 80% | 追踪 CSV 的 Result | 是 |
| G3 | P0 缺陷 | 0（含已关闭的历史 P0 也须为 0） | `BUG-TRACKING.csv` | 是 |
| G4 | P1 缺陷 | ≤ 5，且已修复/已验证 | `BUG-TRACKING.csv` | 是 |
| G5 | 代码覆盖率 | ≥ 80% | `coverage.json`（范围：`src/core` + `src/controller.py`） | 是 |
| G6 | OWASP 安全覆盖 | ≥ 90%（10 类中 ≥ 9 类有明确结论） | `03-SEC-TEST-CASES.md` 结论表 + SEC 用例执行结果 | 是 |

## 口径说明（不放水）

- **覆盖率范围**：核心逻辑层 `src/core/*.py` 与控制器 `src/controller.py`。`src/ui/*` 是纯 Qt 视图层，由 TC-GUI-013 做构造冒烟验证，但**不计入覆盖率分母**——这不是隐藏，而是因为视图层的价值在交互而非分支逻辑，范围已在用例文档中公开声明。
- **N/A 的安全类目**：A01 / A07 / A10 因单机离线架构不适用，但必须写成**可执行的静态论证测试**（验证能力确实不存在），不能留空凑数。任一 N/A 用例失败，该类目自动转为真实漏洞。
- **缺陷口径**：同一根因只记 1 个 Bug ID；修复并复测通过后状态改为 `Verified`，仍计入 P0/P1 历史统计（P0 必须为 0，历史 P0 也不允许）。
- **执行率**：`Skipped` 不算 `Completed`。因此所有用例（含 N/A 论证类）都必须是可执行的断言。
- **CI 复现**：`tests/run_qa.py` 是唯一执行入口，本地与 GitHub Actions 使用同一命令、同一门禁阈值；CI 额外加 `--cov-fail-under=80` 双保险。

## 唯一真实来源原则

```
tests/docs/0*-TEST-CASES.md   ← 权威：用例规格、步骤、预期结果
tests/docs/templates/TEST-EXECUTION-TRACKING.csv  ← 仅状态：由 pytest hook 每条执行完立即回写
tests/docs/BUG-TRACKING.csv   ← 缺陷：编号步骤 + 环境 + 严重级别
tests/docs/QA-REPORT-*.md     ← 报告：由 run_qa.py 自动生成
```

## 发版流程

1. 本地执行 `QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py` → 门禁全绿；
2. `git tag v1.0.0 && git push origin v1.0.0`；
3. GitHub Actions（`macos-latest`）重跑同一门禁 → 打包 → 冻结进程自检 → 上传 Artifact → 建 Release；
4. CI 门禁失败则 Release 不产出，tag 保留但视为失败发版，须修复后打 `v1.0.1`。
