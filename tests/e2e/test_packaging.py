"""TC-PKG-* — 打包与发布流水线契约。规格见 tests/docs/04-PKG-TEST-CASES.md。"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import QA_CACHE, ROOT

WORKFLOW = ROOT / ".github/workflows/build-macos.yml"


@pytest.mark.case("TC-PKG-001")
def test_build_script_contract():
    script = ROOT / "build.sh"
    text = script.read_text(encoding="utf-8")
    assert os.access(script, os.X_OK)
    for token in ("--onedir", "--windowed", "--name \"文档朗读器\"",
                  "--paths \"$ROOT\"", "--distpath", "--workpath",
                  "PySide6.QtMultimedia", "pymupdf", "docx",
                  "--osx-bundle-identifier", "codesign"):
        assert token in text, f"build.sh 缺少: {token}"
    assert "mv \"$target\"" in text or "mv " in text
    assert "--clean" not in text  # bulk-delete protection in this environment
    assert ".venv/bin/pyinstaller" in text


@pytest.mark.case("TC-PKG-002")
def test_dependency_manifests():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for name in ("PySide6", "pymupdf", "python-docx", "pyinstaller"):
        assert name.lower() in req.lower()
    for name in ("pytest", "pytest-cov", "pyyaml"):
        assert name.lower() in dev.lower()
    import importlib.util
    for module in ("PySide6", "pymupdf", "docx", "PyInstaller", "pytest", "yaml"):
        assert importlib.util.find_spec(module) is not None, module


@pytest.mark.case("TC-PKG-003")
def test_frozen_app_selftest_or_ci_equivalent():
    app = ROOT / "dist/文档朗读器.app"
    binary = app / "Contents/MacOS/文档朗读器"
    if not binary.exists():
        # On CI the QA gate runs before packaging; verify the workflow carries the check.
        wf = WORKFLOW.read_text(encoding="utf-8")
        assert "DOCREADER_SELFTEST" in wf and "docreader_selftest.json" in wf
        return
    assert os.access(binary, os.X_OK)
    sign = subprocess.run(["/usr/bin/codesign", "-dv", str(app)],
                          capture_output=True, text=True, timeout=30)
    assert "Signature=adhoc" in sign.stderr or sign.returncode == 0
    result_file = Path("/tmp/docreader_selftest.json")
    if result_file.exists():
        os.remove(result_file)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["DOCREADER_SELFTEST"] = "1"
    run = subprocess.run([str(binary)], env=env, capture_output=True,
                         text=True, timeout=90)
    assert run.returncode == 0, run.stdout[-500:] + run.stderr[-500:]
    assert result_file.exists(), "自检未写出结果文件"
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert data["ok"] is True and data["duration"] > 0 and data["voices"] > 0


@pytest.mark.case("TC-PKG-004")
def test_selftest_falls_back_without_chinese_voice(monkeypatch):
    import src.core.speech as sp
    import src.main as main_mod
    from src.core.speech import Voice
    monkeypatch.setattr(sp, "list_voices", lambda: [Voice("Alex", "en_US")])
    monkeypatch.setattr(sp, "choose_voice", lambda voices, preferred="": None)
    monkeypatch.setattr(
        sp.SpeechEngine, "synthesize",
        lambda self, text: (QA_CACHE / "fallback.aiff", 1.2, ""),
    )
    result_file = Path("/tmp/docreader_selftest.json")
    if result_file.exists():
        os.remove(result_file)
    code = main_mod.self_test()
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert code == 0
    assert data["ok"] is True, data
    assert data.get("fallback") is True
    assert data["voice"] == "Alex"


@pytest.mark.case("TC-PKG-005")
def test_github_actions_workflow_contract():
    assert WORKFLOW.exists()
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data.get("on") or data.get(True)
    assert triggers is not None
    assert "v*" in triggers["push"]["tags"]
    assert "workflow_dispatch" in triggers
    assert data["permissions"]["contents"] == "write"
    job = data["jobs"]["build"]
    assert job["runs-on"] == "macos-latest"
    steps = job["steps"]
    rendered = [
        str(s.get("run", "")) + str(s.get("uses", ""))
        + str(s.get("with", "")) + str(s.get("env", ""))
        for s in steps
    ]
    qa_idx = next(i for i, s in enumerate(rendered) if "run_qa.py" in s)
    build_idx = next(i for i, s in enumerate(rendered) if "build.sh" in s)
    assert qa_idx < build_idx, "质量门禁必须排在打包之前"
    assert any("DOCREADER_SELFTEST" in s for s in rendered)
    assert any("upload-artifact" in s for s in rendered)
    assert any("release" in s.lower() for s in rendered)
    assert any("actions/checkout@v4" in s or "checkout" in s for s in rendered)
    assert any("setup-python" in s for s in rendered)


@pytest.mark.case("TC-PKG-006")
def test_gitignore_protects_repo():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".venv/", "dist/", "build/", "__pycache__/", "*.pyc",
                    ".pytest_cache/", ".coverage", ".qa-workspace/",
                    ".build.log", ".pyinstaller-config/"):
        assert pattern in ignore, f"缺少忽略规则: {pattern}"
    for kept in ("src/", ".github/", "samples/", "tests/docs/"):
        assert not re.search(rf"^\s*{re.escape(kept)}\s*$", ignore, re.M)
