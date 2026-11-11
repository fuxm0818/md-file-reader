#!/usr/bin/env python3
"""QA 唯一执行入口：本地与 GitHub Actions 使用同一命令、同一门禁阈值。

用法（项目根目录）：
    QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py
退出码 0 = 门禁全绿，可以发版；非 0 = 禁止打 tag。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "qa_conftest_catalog", ROOT / "tests/e2e/conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


CATALOG = _load_conftest()
CASE_CATALOG = CATALOG.CASE_CATALOG
TRACKING_CSV = CATALOG.TRACKING_CSV
BUG_CSV = ROOT / "tests/docs/BUG-TRACKING.csv"
SEC_DOC = ROOT / "tests/docs/03-SEC-TEST-CASES.md"
COVERAGE_JSON = ROOT / ".qa-workspace/coverage.json"
# 版本号跟应用同源，避免报告写着 v1.4.0、.app 里却是别的值。
from src.version import VERSION_TAG  # noqa: E402

VERSION = os.environ.get("QA_VERSION", VERSION_TAG)


def run_pytest() -> tuple[int, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QA_FULL_RUN"] = "1"  # authoritative tracking-CSV writer
    # A unique in-project basetemp keeps repeated runs independent and avoids
    # the host shim's mkdir(exist_ok=True) failure on shared system temp dirs.
    basetemp = ROOT / ".qa-workspace" / (
        "pytest-tmp-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    cmd = [
        sys.executable, "-m", "pytest", "tests/e2e", "-q",
        "--basetemp", str(basetemp),
        "--cov=src.core", "--cov=src.controller",
        "--cov-report=term-missing",
        f"--cov-report=json:{COVERAGE_JSON}",
        "--cov-fail-under=80",
        "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True,
                          capture_output=True, timeout=1800)
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log_path = ROOT / ".qa-workspace/pytest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    print(f"完整 pytest 日志：{log_path}")
    print(output[-6000:])
    return proc.returncode, output


def read_tracking() -> list[dict]:
    with open(TRACKING_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("Test Case ID") in CASE_CATALOG]


def read_bugs() -> list[dict]:
    if not BUG_CSV.exists():
        return []
    with open(BUG_CSV, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("Bug ID")]


def coverage_percent() -> float:
    if not COVERAGE_JSON.exists():
        return 0.0
    try:
        data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
        return float(data["totals"]["percent_covered"])
    except (OSError, ValueError, KeyError):
        return 0.0


def security_coverage(rows: list[dict]) -> tuple[float, str]:
    sec_rows = [r for r in rows if r["Category"] == "Security"]
    passed = [r for r in sec_rows if r["Result"] == "✅ PASSED"]
    rate = len(passed) / len(sec_rows) * 100 if sec_rows else 0.0
    categories = set(re.findall(r"\|\s*(A\d{2})\s", SEC_DOC.read_text(encoding="utf-8"))) if SEC_DOC.exists() else set()
    detail = f"安全用例 {len(passed)}/{len(sec_rows)} 通过，OWASP 类目结论 {len(categories)}/10"
    return rate, detail


def evaluate(pytest_rc: int) -> dict:
    rows = read_tracking()
    total = len(CASE_CATALOG)
    executed = [r for r in rows if r["Status"] == "Completed"]
    passed = [r for r in rows if r["Result"] == "✅ PASSED"]
    failed = [r for r in rows if r["Result"] == "❌ FAILED"]
    bugs = read_bugs()
    p0 = [b for b in bugs if b["Severity"].strip().upper() == "P0"]
    p1 = [b for b in bugs if b["Severity"].strip().upper() == "P1"]
    cov = coverage_percent()
    sec_rate, sec_detail = security_coverage(rows)

    gates = [
        ("G1 测试执行率 100%", len(executed) == total == len(rows), f"{len(executed)}/{total}"),
        ("G2 通过率 ≥80%", bool(executed) and len(passed) / len(executed) * 100 >= 80,
         f"{(len(passed) / len(executed) * 100 if executed else 0):.1f}%"),
        ("G3 P0 缺陷 = 0", len(p0) == 0, f"{len(p0)} 个"),
        ("G4 P1 缺陷 ≤5", len(p1) <= 5, f"{len(p1)} 个"),
        ("G5 代码覆盖率 ≥80%", cov >= 80, f"{cov:.1f}%"),
        ("G6 安全覆盖 ≥90%", sec_rate >= 90 and len(re.findall(r"\|\s*A\d{2}\s", SEC_DOC.read_text(encoding="utf-8"))) >= 9,
         f"{sec_rate:.1f}% · {sec_detail}"),
    ]
    all_green = all(ok for _, ok, _ in gates) and pytest_rc == 0
    return {
        "version": VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_rc": pytest_rc,
        "total": total, "executed": len(executed), "passed": len(passed),
        "failed": len(failed),
        "pass_rate": round(len(passed) / len(executed) * 100, 1) if executed else 0.0,
        "coverage": round(cov, 1),
        "security_rate": round(sec_rate, 1),
        "security_detail": sec_detail,
        "bugs": [{"id": b["Bug ID"], "severity": b["Severity"], "status": b["Status"], "title": b["Title"]} for b in bugs],
        "gates": [{"name": name, "ok": ok, "value": value} for name, ok, value in gates],
        "failed_cases": [{"id": r["Test Case ID"], "note": r["Notes"][:200]} for r in failed],
        "all_green": all_green,
    }


def write_reports(result: dict) -> None:
    docs = ROOT / "tests/docs"
    (docs / "QA-METRICS.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# QA 报告 · {result['version']}",
        "",
        f"- 生成时间：{result['generated_at']}",
        "- 执行方式：`QT_QPA_PLATFORM=offscreen .venv/bin/python tests/run_qa.py`",
        "- 用例权威来源：`tests/docs/0*-TEST-CASES.md`",
        "- 状态追踪：`tests/docs/templates/TEST-EXECUTION-TRACKING.csv`",
        "",
        "## 质量门禁",
        "",
        "| 门禁 | 结果 | 实测 |",
        "|---|---|---|",
    ]
    for gate in result["gates"]:
        lines.append(f"| {gate['name']} | {'✅ 通过' if gate['ok'] else '❌ 未通过'} | {gate['value']} |")
    lines += [
        "",
        f"**结论**：{'✅ 门禁全绿，允许打 tag 发版' if result['all_green'] else '❌ 门禁未过，禁止发版'}",
        "",
        "## 执行概览",
        "",
        f"- 用例：{result['total']} 条，已执行 {result['executed']} 条，通过 {result['passed']} 条，失败 {result['failed']} 条",
        f"- 通过率：{result['pass_rate']}%　代码覆盖率：{result['coverage']}%　安全覆盖：{result['security_rate']}%",
        f"- pytest 退出码：{result['pytest_rc']}（0 表示含 `--cov-fail-under=80` 在内的检查全部通过）",
        "",
        "## 缺陷",
        "",
    ]
    if result["bugs"]:
        lines += ["| ID | 级别 | 状态 | 标题 |", "|---|---|---|---|"]
        for bug in result["bugs"]:
            lines.append(f"| {bug['id']} | {bug['severity']} | {bug['status']} | {bug['title']} |")
    else:
        lines.append("无已登记缺陷。")
    if result["failed_cases"]:
        lines += ["", "## 失败用例", ""]
        for case in result["failed_cases"]:
            lines.append(f"- `{case['id']}`：{case['note']}")
    lines += [
        "",
        "## 门禁口径",
        "",
        "详见 `tests/docs/QUALITY-GATE.md`。覆盖率范围为 `src/core` 与 `src/controller.py`；",
        "OWASP 不适用的类目以可执行的静态论证用例记录，不留空。",
        "",
    ]
    (docs / f"QA-REPORT-{result['version']}.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print("=" * 68)
    print(f"Horizon QA · 文档朗读器 {VERSION} · 全量执行")
    print("=" * 68)
    rc, _ = run_pytest()
    result = evaluate(rc)
    write_reports(result)
    print("\n" + "=" * 68)
    print("质量门禁")
    print("=" * 68)
    for gate in result["gates"]:
        print(f"  {'✅' if gate['ok'] else '❌'} {gate['name']:<24} {gate['value']}")
    print(f"\n  用例 {result['executed']}/{result['total']} 执行 · 通过 {result['passed']} · 失败 {result['failed']}")
    print(f"  覆盖率 {result['coverage']}% · 安全 {result['security_detail']}")
    print(f"  报告：tests/docs/QA-REPORT-{VERSION}.md")
    print("=" * 68)
    print("✅ 门禁全绿，可以发版" if result["all_green"] else "❌ 门禁未过，禁止发版")
    return 0 if result["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
