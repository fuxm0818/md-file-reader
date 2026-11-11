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
    # 自检会打开这个文件验证打磨后级，所以桩必须写出真实波形，
    # 不能只返回一个不存在的路径。
    import wave

    import numpy as np

    QA_CACHE.mkdir(parents=True, exist_ok=True)
    fallback_wav = QA_CACHE / "fallback.wav"
    tone = (0.85 * np.sin(2 * np.pi * 220 * np.arange(24000) / 24000)).astype(np.float32)
    with wave.open(str(fallback_wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes((tone * 32767).astype(np.int16).tobytes())
    monkeypatch.setattr(
        sp.SpeechEngine, "synthesize",
        lambda self, text, tail_pause=0.0: (fallback_wav, 1.2, ""),
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


@pytest.mark.case("TC-PKG-007")
def test_app_icon_is_shipped():
    """没有图标的 .app 在 Dock 里是一个空白文档，用户认不出来。"""
    from src.main import app_icon_path

    icns = ROOT / "assets" / "AppIcon.icns"
    png = ROOT / "assets" / "AppIcon.png"
    assert icns.exists(), "缺少 assets/AppIcon.icns"
    assert png.exists(), "缺少 assets/AppIcon.png"
    assert icns.stat().st_size > 20_000, "icns 太小，多半没有写入各尺寸"
    assert png.stat().st_size > 5_000

    script = (ROOT / "build.sh").read_text(encoding="utf-8")
    assert "--icon" in script and "AppIcon.icns" in script, "打包脚本没有指定图标"

    # 运行时窗口图标走 app_icon_path()，源码模式下应指向仓库里的 png
    path = app_icon_path()
    assert path is not None and path.suffix == ".png"


@pytest.mark.case("TC-PKG-008")
def test_version_is_single_source_and_shipped():
    """版本号只维护一份，并真的写进 .app —— 否则用户查不到自己装的是哪一版。"""
    from src.version import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__

    script = (ROOT / "build.sh").read_text(encoding="utf-8")
    assert "CFBundleShortVersionString" in script, "打包脚本没有写入版本号"
    assert "CFBundleVersion" in script
    # 改 Info.plist 会让临时签名失效，写入必须排在签名之前
    assert script.index("CFBundleShortVersionString") < script.index("codesign")

    main_src = (ROOT / "src/main.py").read_text(encoding="utf-8")
    assert "setApplicationVersion" in main_src, "Qt 应用没设置版本号"

    window_src = (ROOT / "src/ui/main_window.py").read_text(encoding="utf-8")
    assert "__version__" in window_src, "「关于」面板没有显示版本"

    plist = ROOT / "dist/文档朗读器.app/Contents/Info.plist"
    if plist.exists():
        raw = plist.read_text(encoding="utf-8")
        m = re.search(
            r"<key>CFBundleShortVersionString</key>\s*<string>([^<]*)</string>", raw
        )
        assert m, "产物缺少 CFBundleShortVersionString"
        assert m.group(1) == __version__, (
            f"产物版本 {m.group(1)} 与源码 {__version__} 不一致"
        )
        assert "<key>CFBundleVersion</key>" in raw, "产物缺少 CFBundleVersion"
