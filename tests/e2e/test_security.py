"""TC-SEC-* — OWASP Top 10 适用性裁剪验证。规格见 tests/docs/03-SEC-TEST-CASES.md。"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from conftest import QA_CACHE, QA_STATE, ROOT


def _source_text() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (ROOT / "src").rglob("*.py")
    )


@pytest.mark.case("TC-SEC-001")
def test_command_injection_is_impossible(monkeypatch, voice, tmp_path):
    import src.core.speech as sp
    # Use a fresh cache so synthesize() always takes the miss branch and
    # actually invokes /usr/bin/say (a cache hit would only call afinfo).
    cache = tmp_path / "inject_cache"
    cache.mkdir()
    monkeypatch.setattr(sp, "CACHE_DIR", cache)
    # 必须在下面对 _run 打桩之前取音色，否则 list_system_voices 拿到的是假输出。
    system_voice = next(
        (v for v in sp.list_system_voices() if v.is_chinese), None
    )
    captured = []

    def fake_run(args, input_text=None, **kwargs):
        captured.append((args, input_text, kwargs))
        if args[0] == sp.AFINFO:
            return subprocess.CompletedProcess(args, 0, "estimated duration: 1.25 sec", "")
        Path(args[-1]).write_bytes(b"AIFF" * 100)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(sp, "_run", fake_run)
    # 命令注入的风险面是「把文本拼进 argv / 走 shell」。神经语音完全在本进程
    # 内推理、不调用任何外部命令，所以这里针对 say 路径做验证。
    if system_voice is None:
        pytest.skip("本机没有中文系统音色，无法验证 argv 注入面")
    engine = sp.SpeechEngine(system_voice, 200)
    payload = '"; touch /tmp/pwned_QA; rm -rf $HOME; # `whoami` $(id)\n'
    path, duration, error = engine.synthesize(payload)
    assert path is not None and duration == 1.25 and not error
    args, stdin_text, kwargs = captured[0]
    assert isinstance(args, list) and "shell" not in kwargs
    for fragment in ("touch", "pwned_QA", "rm -rf", "whoami", "$(id)"):
        assert all(fragment not in a for a in args), f"恶意片段进入 argv: {fragment}"
    assert stdin_text == payload
    assert args[args.index("-f") + 1] == "-"
    assert not Path("/tmp/pwned_QA").exists()
    assert "shell=True" not in (ROOT / "src/core/speech.py").read_text(encoding="utf-8")


@pytest.mark.case("TC-SEC-002")
def test_cache_key_blocks_path_traversal(voice, tmp_path):
    import src.core.speech as sp
    from src.core.parsers import parse
    engine = sp.SpeechEngine(voice, 200)
    for payload in ("../../etc/passwd", "/etc/passwd\x00", "..\\..\\windows", "/" * 50):
        key = engine.key(payload)
        assert re.fullmatch(r"[0-9a-f]{24}", key)
        assert engine.audio_path(payload).parent == sp.CACHE_DIR
        assert ".." not in engine.audio_path(payload).name
    assert not parse("../../etc/passwd").ok
    assert not parse("x" * 5000 + ".md").ok


@pytest.mark.case("TC-SEC-003")
def test_subprocess_env_is_sanitized(monkeypatch):
    import src.core.speech as sp
    dangerous = ["DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_FRAMEWORK_PATH",
                 "PYTHONPATH", "PYTHONHOME", "_MEIPASS2", "LD_LIBRARY_PATH"]
    for key in dangerous:
        monkeypatch.setenv(key, "/tmp/evil")
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs.get("env", {}))
        return subprocess.CompletedProcess(args, 0, "estimated duration: 1.0 sec", "")

    monkeypatch.setattr(sp.subprocess, "run", fake_run)
    sp.probe_duration(Path("fake.aiff"))
    for key in dangerous:
        assert key not in seen
    assert seen["PATH"].startswith("/usr/bin:/bin:")
    assert all(os.environ.get(k) == "/tmp/evil" for k in dangerous)


@pytest.mark.case("TC-SEC-004")
def test_malformed_and_huge_inputs(tmp_path):
    from src.core.parsers import parse
    big = tmp_path / "big.txt"
    big.write_text("甲" * 1_000_000, encoding="utf-8")
    t0 = time.time()
    doc_big = parse(str(big))
    assert isinstance(doc_big.ok, bool) and time.time() - t0 < 10

    punct = tmp_path / "punct.txt"
    punct.write_text("啊。" * 20_000, encoding="utf-8")
    t0 = time.time()
    doc_punct = parse(str(punct))
    assert doc_punct.ok and len(doc_punct.sentences) > 1 and time.time() - t0 < 10

    for suffix in (".txt", ".pdf"):
        f = tmp_path / ("binary" + suffix)
        f.write_bytes(os.urandom(20_000))
        assert isinstance(parse(str(f)).ok, bool)


@pytest.mark.case("TC-SEC-005")
def test_error_messages_do_not_leak_stacks():
    from src.core.parsers import parse
    err = parse("/tmp/qa_no_such_dir_xyz/secret.md").error
    assert err and len(err) < 400
    assert "Traceback" not in err and 'File "' not in err
    controller_src = (ROOT / "src/controller.py").read_text(encoding="utf-8")
    assert "Path(item['path']).name" in controller_src  # user-facing hint uses file name


@pytest.mark.case("TC-SEC-006")
def test_no_secrets_on_disk_and_atomic_writes(fresh_store):
    import json
    fresh_store.settings["mode"] = "loop_one"
    fresh_store.save()
    text = QA_STATE.read_text(encoding="utf-8")
    assert not re.search(r"password|passwd|api[_-]?key|secret|bearer|token", text, re.I)
    assert not re.search(
        r"(api[_-]?key|secret|password)\s*=\s*['\"][A-Za-z0-9]{12,}", _source_text(), re.I
    )
    assert "os.replace" in (ROOT / "src/core/store.py").read_text(encoding="utf-8")
    assert isinstance(json.loads(text), dict)
    QA_STATE.write_text("not json", encoding="utf-8")
    assert type(fresh_store)().settings["mode"] == "sequence"


@pytest.mark.case("TC-SEC-007")
def test_dependency_constraints_and_no_network():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    lines = [l.strip() for l in (req + "\n" + dev).splitlines() if l.strip() and not l.startswith("#")]
    assert all(re.search(r"[<>=!~]", line) for line in lines)
    assert re.search(r"pymupdf.*<2", req)
    assert "pytest" in dev and "pytest-cov" in dev
    src = _source_text()
    forbidden = ["requests.get", "urllib.request", "socket.", "http.client",
                 "urlopen", "os.system", "shell=True", "pickle.loads", "eval("]
    for pattern in forbidden:
        assert pattern not in src, f"发现危险调用: {pattern}"
    import importlib.util
    for module in ("PySide6", "pymupdf", "docx", "pytest", "yaml"):
        assert importlib.util.find_spec(module) is not None


@pytest.mark.case("TC-SEC-008")
def test_secure_default_settings():
    from src.core.store import DEFAULT_SETTINGS, MODES
    assert DEFAULT_SETTINGS["rate"] == 200
    assert DEFAULT_SETTINGS["volume"] == 80
    assert DEFAULT_SETTINGS["mode"] == "sequence"
    assert DEFAULT_SETTINGS["auto_resume"] is True
    assert DEFAULT_SETTINGS["cache_limit_mb"] > 0
    assert set(MODES) == {"sequence", "loop_all", "loop_one", "shuffle"}
    for key in ("password", "admin", "remote_endpoint", "api_key"):
        assert key not in DEFAULT_SETTINGS


@pytest.mark.case("TC-SEC-009")
def test_numeric_clamping(voice, controller):
    from src.core.speech import SpeechEngine
    from src.core.timeline import Timeline
    assert SpeechEngine(voice, -1).rate == 60
    assert SpeechEngine(voice, 99999).rate == 400
    controller.set_rate(9999)
    assert controller.rate == 350
    controller.set_volume(-100)
    assert controller.audio.volume() == 0.0
    from src.core.models import Document
    assert Timeline(Document(path="x"), 0).sec_per_char >= 0.05


@pytest.mark.case("TC-SEC-010")
def test_na_access_control_argument():
    src = _source_text().lower()
    assert not re.search(r"\b(sudo|chmod|rls|admin_role|setuid|permission_denied)\b", src)
    assert "os.stat(" in src  # only reads metadata of user-selected files


@pytest.mark.case("TC-SEC-011")
def test_na_authentication_argument():
    src = _source_text().lower()
    assert not re.search(r"\b(login|jwt|oauth|csrf|password|set_cookie|session_token)\b", src)


@pytest.mark.case("TC-SEC-012")
def test_na_ssrf_argument():
    src = _source_text()
    for pattern in ("requests.", "urllib.request", "socket.socket", "http.client", "urlopen"):
        assert pattern not in src
    speech_src = (ROOT / "src/core/speech.py").read_text(encoding="utf-8")
    assert 'SAY = "/usr/bin/say"' in speech_src
    assert 'AFINFO = "/usr/bin/afinfo"' in speech_src
    assert "RE_BARE_URL" not in speech_src
