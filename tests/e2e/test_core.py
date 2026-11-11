"""TC-CORE-* — 解析 / 语音 / 时间轴 / 持久化。规格见 tests/docs/01-CORE-TEST-CASES.md。"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import QA_CACHE, QA_STATE, ROOT, SAMPLE_PATHS, SAMPLE_DIR

SAMPLE = SAMPLE_DIR


def _doc_with(n: int, text: str = "这是一句用于验证时间轴的测试文本。"):
    from src.core.models import Document, Sentence
    sents, cursor = [], 0
    parts = []
    for i in range(n):
        s = Sentence(i, text, cursor, cursor + len(text), i)
        sents.append(s)
        parts.append(text)
        cursor += len(text)
    return Document(path="virtual.md", display_text="".join(parts), sentences=sents)


@pytest.mark.case("TC-CORE-001")
def test_markdown_parse_skips_code():
    from src.core.parsers import parse
    doc = parse(str(SAMPLE / "示例文档.md"), skip_code=True)
    assert doc.ok and len(doc.sentences) > 5
    assert doc.headings and any(h.level >= 1 for h in doc.headings)
    assert all(0 <= s.start < s.end <= len(doc.display_text) for s in doc.sentences)
    joined = " ".join(s.text for s in doc.sentences)
    assert "def estimate" not in joined and "return chars" not in joined
    assert "拖动进度条" in joined


@pytest.mark.case("TC-CORE-002")
def test_encoding_fallback(tmp_path):
    from src.core.parsers import parse
    text = "第一段：中文编码测试。第二段：继续验证解析。"
    variants = {
        "utf8.txt": text.encode("utf-8"),
        "bom.txt": b"\xef\xbb\xbf" + text.encode("utf-8"),
        "gbk.txt": text.encode("gb18030"),
    }
    results = {}
    for name, raw in variants.items():
        p = tmp_path / name
        p.write_bytes(raw)
        results[name] = parse(str(p))
    assert all(d.ok for d in results.values())
    assert all("\ufeff" not in d.display_text for d in results.values())
    assert all("中文编码测试" in d.display_text for d in results.values())
    base = [s.text for s in results["utf8.txt"].sentences]
    assert [s.text for s in results["bom.txt"].sentences] == base
    assert [s.text for s in results["gbk.txt"].sentences] == base


@pytest.mark.case("TC-CORE-003")
def test_docx_headings_and_table():
    from src.core.parsers import parse
    doc = parse(SAMPLE_PATHS[2])
    assert doc.ok and len(doc.headings) >= 2
    assert any(h.level >= 1 for h in doc.headings)
    assert "由 macOS 系统提供" in doc.display_text
    assert "音色" in doc.display_text
    assert all(0 <= s.start < s.end <= len(doc.display_text) for s in doc.sentences)


@pytest.mark.case("TC-CORE-004")
def test_pdf_text_layer():
    from src.core.parsers import parse
    doc = parse(SAMPLE_PATHS[3])
    assert doc.ok, doc.error
    assert len(doc.sentences) >= 3
    assert "PDF 文档朗读测试" in doc.display_text
    assert all(0 <= s.start < s.end <= len(doc.display_text) for s in doc.sentences)


@pytest.mark.case("TC-CORE-005")
def test_scanned_pdf_is_flagged(scan_pdf):
    from src.core.parsers import parse
    doc = parse(scan_pdf)
    assert not doc.ok
    assert "无文字层" in doc.error


@pytest.mark.case("TC-CORE-006")
def test_missing_and_empty_files(tmp_path):
    from src.core.parsers import parse
    missing = parse(str(tmp_path / "不存在的文件.md"))
    assert not missing.ok and missing.error
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    blank = parse(str(empty))
    assert not blank.ok and "未提取到可朗读的文字" in blank.error


@pytest.mark.case("TC-CORE-007")
def test_inline_markup_cleanup():
    from src.core.parsers import clean_inline
    src = (
        "见 [官方文档](https://example.com/a?x=1) 与 https://bare.url/x "
        "![图片](pic.png) <!-- 隐藏注释 --> `code` **粗体** 🚀 | 表格 > 引用"
    )
    out = clean_inline(src)
    assert "官方文档" in out and "粗体" in out and "code" in out
    for forbidden in ("http", "example.com", "隐藏注释", "图片", "🚀", "|", "#", ">"):
        assert forbidden not in out, f"残留: {forbidden}"
    assert not re.search(r"\s{2,}", out)


@pytest.mark.case("TC-CORE-008")
def test_sentence_splitting_and_long_sentence():
    from src.core.parsers import _split_with_spans
    text = "第一句。第二句！第三句？第四段；结尾"
    spans = _split_with_spans(text)
    assert len(spans) >= 4
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))
    long_text = "甲，" * 100
    cuts = _split_with_spans(long_text)
    assert len(cuts) > 1
    assert max(b - a for a, b in cuts) <= 90


@pytest.mark.case("TC-CORE-009")
def test_all_samples_have_valid_spans():
    from src.core.parsers import parse
    for path in SAMPLE_PATHS:
        doc = parse(path)
        assert doc.ok, f"{path}: {doc.error}"
        assert all(0 <= s.start < s.end <= len(doc.display_text) for s in doc.sentences)
        assert [s.index for s in doc.sentences] == list(range(len(doc.sentences)))
        assert all(doc.sentences[i].para <= doc.sentences[i + 1].para
                   for i in range(len(doc.sentences) - 1))


@pytest.mark.case("TC-CORE-010")
def test_calibration_formula(monkeypatch, voice):
    from src.core.speech import CALIBRATION_TEXT, DEFAULT_SEC_PER_CHAR, SpeechEngine
    engine = SpeechEngine(voice, 200)
    chars = len(re.sub(r"[\s，。！？、；：]", "", CALIBRATION_TEXT))
    monkeypatch.setattr(SpeechEngine, "synthesize", lambda self, text, tail_pause=0.0: (None, 20.0, ""))
    assert engine.calibrate() == round(20.0 / chars, 4)
    monkeypatch.setattr(SpeechEngine, "synthesize", lambda self, text, tail_pause=0.0: (None, 0.0, "失败"))
    assert engine.calibrate() == DEFAULT_SEC_PER_CHAR


@pytest.mark.case("TC-CORE-011")
def test_real_synthesis_and_cache_hit(voice, tts_text):
    from src.core.speech import SpeechEngine
    engine = SpeechEngine(voice, 333)
    text = tts_text + " 123"
    path, duration, error = engine.synthesize(text)
    assert path is not None and path.exists() and path.stat().st_size > 100, error
    assert duration > 0 and not error
    path2, duration2, error2 = engine.synthesize(text)
    assert path2 == path and abs(duration2 - duration) < 0.01 and not error2
    assert engine.key(text) != SpeechEngine(voice, 200).key(text)
    assert re.fullmatch(r"[0-9a-f]{24}", engine.key(text))


@pytest.mark.case("TC-CORE-012")
def test_voice_discovery_and_selection():
    from src.core.speech import Voice, choose_voice, list_voices
    real = list_voices()
    assert real and all(v.identifier and v.locale for v in real)
    fake = [
        Voice("Alex", "en_US"),
        Voice("Sinji", "zh_HK"),
        Voice("Tingting", "zh_CN"),
        Voice("Meijia", "zh_TW"),
    ]
    assert choose_voice(fake).identifier == "Tingting"
    assert choose_voice(fake, "Meijia").identifier == "Meijia"
    assert choose_voice([Voice("Alex", "en_US")]) is None
    assert choose_voice([Voice("Sinji", "zh_HK")]).identifier == "Sinji"


@pytest.mark.case("TC-CORE-013")
def test_cleaned_env_removes_injectable_vars(monkeypatch):
    from src.core.speech import cleaned_env
    dangerous = ["DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "PYTHONPATH",
                 "PYTHONHOME", "_MEIPASS2", "LD_LIBRARY_PATH", "_PYI_ARCHIVE_FILE"]
    for key in dangerous:
        monkeypatch.setenv(key, "/tmp/evil")
    env = cleaned_env()
    for key in dangerous:
        assert key not in env
    assert env["PATH"].startswith("/usr/bin:/bin:")
    assert os_env_unchanged(dangerous)


def os_env_unchanged(keys):
    import os
    return all(os.environ.get(k) == "/tmp/evil" for k in keys)


@pytest.mark.case("TC-CORE-014")
def test_probe_duration_parsing(monkeypatch):
    import src.core.speech as sp
    payload = {"stdout": ""}

    def fake(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, payload["stdout"], "")

    monkeypatch.setattr(sp, "_run", fake)
    payload["stdout"] = "File: x.aiff\nestimated duration: 7.222132 sec\n"
    assert abs(sp.probe_duration(Path("x.aiff")) - 7.222132) < 1e-6
    payload["stdout"] = "duration 3.5 sec"
    assert sp.probe_duration(Path("x.aiff")) == 3.5
    payload["stdout"] = ""
    assert sp.probe_duration(Path("x.aiff")) == 0.0

    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired("afinfo", 1)

    monkeypatch.setattr(sp, "_run", timeout)
    assert sp.probe_duration(Path("x.aiff")) == 0.0


@pytest.mark.case("TC-CORE-015")
def test_timeline_estimate_real_and_reverse_lookup():
    from src.core.timeline import Timeline
    doc = _doc_with(5)
    tl = Timeline(doc, 0.2)
    assert tl.sec_per_char == 0.2
    initial_total = tl.total()
    before = tl.start_of(3)
    tl.set_real(1, 9.0)
    assert tl.total() > initial_total and tl.start_of(3) > before
    assert tl.duration(1) == 9.0
    for i in range(5):
        assert tl.sentence_at(tl.start_of(i)) == i
    assert abs(tl.time_at_fraction(0.5) - tl.total() * 0.5) < 1e-6
    assert abs(tl.fraction_at(tl.time_at_fraction(0.5)) - 0.5) < 1e-6


@pytest.mark.case("TC-CORE-016")
def test_timeline_boundaries():
    from src.core.models import Document
    from src.core.timeline import Timeline
    empty = Timeline(Document(path="empty.md"), 0.2)
    assert empty.total() == 0 and empty.sentence_at(10) == 0 and empty.fraction_at(5) == 0
    tl = Timeline(_doc_with(3), 0)
    assert tl.sec_per_char >= 0.05
    assert tl.sentence_at(-100) == 0
    assert tl.sentence_at(tl.total() * 10) == 2
    assert tl.time_at_fraction(2.0) == tl.total()
    tl.set_real(-1, 5.0)
    tl.set_real(2, 0.0)
    assert tl.real == [None, None, None]


@pytest.mark.case("TC-CORE-017")
def test_playlist_crud(fresh_store):
    store = fresh_store
    paths = [f"/tmp/qa/doc{i}.md" for i in range(4)]
    assert store.add_items(paths[:3]) == 3
    assert store.add_items([paths[0]]) == 0
    assert store.add_items([paths[3]], at=1) == 1
    assert [i["path"] for i in store.items] == [paths[0], paths[3], paths[1], paths[2]]
    order = [paths[2], paths[3], paths[0], paths[1]]
    store.sync_order(order)
    assert [i["path"] for i in store.items] == order
    store.remove_paths({paths[3], paths[1]})
    assert len(store.items) == 2
    store.clear()
    assert store.items == []
    new = store.create_playlist("测试列表")
    assert store.active["id"] == new["id"] and store.active["name"] == "测试列表"
    store.rename_playlist("改名后")
    assert store.active["name"] == "改名后"
    store.add_items(paths[:2])
    store.set_active("default")
    assert store.active["name"] == "默认列表" and store.items == []
    store.set_active(new["id"])
    assert len(store.items) == 2
    store.delete_active_playlist()
    assert len(store.playlists) == 1 and len(store.items) == 0


@pytest.mark.case("TC-CORE-018")
def test_bookmark_persist_and_hash_change(fresh_store, tmp_path):
    from src.core.parsers import parse
    store = fresh_store
    path = SAMPLE_PATHS[0]
    store.add_items([path])
    old_hash = parse(path).doc_hash
    store.bookmark(old_hash, path, 12)
    reloaded = type(store)()
    assert reloaded.get_bookmark(old_hash) == {"path": path, "sentence": 12}
    assert reloaded.items[0]["position"] == 12
    assert reloaded.items[0]["doc_hash"] == old_hash
    changed = tmp_path / "changed.md"
    changed.write_text(Path(path).read_text(encoding="utf-8") + "\n新增一行内容。", encoding="utf-8")
    assert parse(str(changed)).doc_hash != old_hash
    before = len(reloaded.data["bookmarks"])
    reloaded.bookmark("", path, 3)
    assert len(reloaded.data["bookmarks"]) == before


@pytest.mark.case("TC-CORE-019")
def test_state_atomic_save_and_corruption_fallback(fresh_store):
    store = fresh_store
    store.settings["mode"] = "loop_all"
    store.save()
    assert QA_STATE.exists() and not QA_STATE.with_suffix(".json.tmp").exists()
    assert json.loads(QA_STATE.read_text(encoding="utf-8"))["settings"]["mode"] == "loop_all"
    assert "os.replace" in (ROOT / "src/core/store.py").read_text(encoding="utf-8")
    QA_STATE.write_text("{ this is not json", encoding="utf-8")
    recovered = type(store)()
    assert recovered.settings["rate"] == 200
    assert recovered.settings["mode"] == "sequence"
    assert recovered.playlists and recovered.active["items"] == []


@pytest.mark.case("TC-CORE-020")
def test_cache_cleanup(monkeypatch, tmp_path, voice):
    import src.core.speech as sp
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("a.aiff", "b.aiff", "c.aiff"):
        (cache / name).write_bytes(b"x" * 200_000)
    (cache / "subdir").mkdir()
    monkeypatch.setattr(sp, "CACHE_DIR", cache)
    engine = sp.SpeechEngine(voice, 200)
    assert engine.cache_size_mb() > 0
    assert engine.clear_cache() == 3
    assert (cache / "subdir").is_dir()
    assert engine.clear_cache() == 0


@pytest.mark.case("TC-CORE-021")
def test_cache_limit_evicts_oldest(monkeypatch, tmp_path, voice):
    """设置面板许诺「超过上限自动清理最旧的」，就得真的按 mtime 淘汰。"""
    import os

    import src.core.speech as sp

    cache = tmp_path / "cache"
    cache.mkdir()
    files = []
    for i in range(20):
        path = cache / f"{i:02d}.wav"
        path.write_bytes(b"x" * 120_000)
        # mtime 依次递增，00 最旧、19 最新
        stamp = 1_700_000_000 + i
        os.utime(path, (stamp, stamp))
        files.append(path)

    monkeypatch.setattr(sp, "CACHE_DIR", cache)
    limit = 1  # MB
    engine = sp.SpeechEngine(voice, 200, cache_limit_mb=limit)

    before = sum(p.stat().st_size for p in files)
    assert before > limit * 1024 * 1024

    removed = engine.enforce_cache_limit()
    assert removed > 0
    left = [p for p in cache.iterdir() if p.is_file()]
    after = sum(p.stat().st_size for p in left)
    assert after <= limit * 1024 * 1024 * 0.85 + 1, f"没删够，还剩 {after} 字节"
    assert not files[0].exists(), "最旧的文件应当先被淘汰"
    assert files[-1].exists(), "最新的文件不能被删"

    # 已经低于上限，再调一次不该继续删
    assert engine.enforce_cache_limit() == 0
    # 0 表示不限制
    unlimited = sp.SpeechEngine(voice, 200, cache_limit_mb=0)
    assert unlimited.enforce_cache_limit() == 0
