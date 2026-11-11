"""AAA tests for the voice-naturalness layers (L0 voice / L1 oralizer / L2 prosody)."""
from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from conftest import QA_STATE, SAMPLE_PATHS


@pytest.mark.case("TC-NAT-001")
def test_oralizer_splits_rewrites_and_speaks_symbols():
    from src.core.oralizer import oralize

    raw = (
        "文档本身没有时间轴，所以程序按语速把字数换算成时间。"
        "已经合成过的句子会用音频的真实时长替换估算值，剩余时间会越听越准。"
    )
    out = oralize(raw)
    assert "换成时间" in out and "换算成" not in out
    assert out.count("。") > raw.count("。"), "over-long comma clauses must be split"
    han = lambda s: len(re.findall(r"[\u4e00-\u9fff]", s))
    assert han(out) <= han(raw) and out.strip()

    symbols = oralize("支持 ±15s 与 80% 的进度，此外 A&B 以及 [链接](https://x) 也可以。")
    assert "正负15秒" in symbols
    assert "百分之80" in symbols
    assert "另外" in symbols and "此外" not in symbols
    assert "A和B" in symbols and "还有" in symbols
    assert "https://x" not in symbols and "链接" in symbols

    assert oralize("") == "" and oralize("   ") == "   "


@pytest.mark.case("TC-NAT-002")
def test_cause_clause_puts_conclusion_first():
    from src.core.oralizer import oralize

    out = oralize("因为文档没有时间轴，所以程序必须自己换算时间。")
    assert out.startswith("程序必须自己换算时间")
    assert "这是因为文档没有时间轴" in out
    assert "文档没有时间轴" in out and "程序必须自己换算时间" in out
    assert not out.startswith("因为")


@pytest.mark.case("TC-NAT-003")
def test_rewrite_never_touches_display_text_or_spans():
    from src.core.oralizer import oralize
    from src.core.parsers import parse
    from src.core.prosody import render

    doc = parse(SAMPLE_PATHS[0])
    before = doc.display_text
    spans = [(s.start, s.end, s.text) for s in doc.sentences]
    for sentence in doc.sentences:
        render(oralize(sentence.text), 2, 200)
    assert doc.display_text == before
    assert [(s.start, s.end, s.text) for s in doc.sentences] == spans
    assert all(0 <= s.start < s.end <= len(doc.display_text) for s in doc.sentences)


@pytest.mark.case("TC-NAT-004")
def test_oralizer_auto_disables_for_technical_files():
    from src.core.oralizer import oralize_enabled

    for name in ("a.md", "a.txt", "a.pdf", "a.docx", "a"):
        assert oralize_enabled(name, True), name
    for name in ("a.py", "a.json", "a.csv", "a.log", "a.js"):
        assert not oralize_enabled(name, True), name
    assert not oralize_enabled("a.md", False)


@pytest.mark.case("TC-NAT-005")
def test_prosody_levels_add_monotonic_breathing_pauses():
    from src.core.prosody import LEVEL_LABELS, config, estimated_pause, render

    text = "文档本身没有时间轴，所以按语速把字数换成时间。剩余时间会越听越准。"
    pauses = []
    for level in (0, 1, 2, 3):
        rendered = render(text, level, 200, is_para_end=True)
        pauses.append(estimated_pause(rendered))
        if level == 0:
            assert "[[" not in rendered and rendered == text
        if level == 3:
            assert "[[pbas" in rendered
    assert pauses == sorted(pauses) and pauses[0] == 0
    assert pauses[1] < pauses[2] < pauses[3]
    assert config(-1) is config(0) and config(99) is config(3)
    assert set(LEVEL_LABELS) == {0, 1, 2, 3}


@pytest.mark.case("TC-NAT-006")
def test_document_cannot_inject_say_embedded_commands(controller, monkeypatch):
    from src.core.models import Document, Sentence
    from src.core.prosody import render, sanitize
    from src.core.timeline import Timeline

    payload = "这是正文[[slnc 999999]]，还有[[rate 400]]与[[pbas +99]]。"
    for level in (0, 2):
        rendered = render(payload, level)
        assert "999999" not in rendered and "[[rate 400]]" not in rendered
        assert "+99" not in rendered
        assert all(int(v) <= 850 for v in re.findall(r"\[\[slnc\s+(\d+)\]\]", rendered))
    assert sanitize(payload) == "这是正文，还有与。"

    doc = Document(
        path="probe.md", title="probe", display_text=payload,
        sentences=[Sentence(0, payload, 0, len(payload), 0)],
        ok=True, doc_hash="probe",
    )
    controller.doc = doc
    controller.timeline = Timeline(doc, 0.2)
    speech_text = controller._speech_text(0)
    assert "999999" not in speech_text
    assert doc.display_text == payload  # visible text still intact


@pytest.mark.case("TC-NAT-007")
def test_pause_budget_matches_rendered_pauses_and_timeline():
    from src.core.models import Document, Sentence
    from src.core.prosody import estimated_pause, pause_budget, render
    from src.core.timeline import PAUSE, Timeline

    budgets = [pause_budget(i) for i in range(4)]
    assert budgets == sorted(budgets) and budgets[0] == 0
    text = "文档本身没有时间轴，所以按语速把字数换成时间。剩余时间会越听越准。"
    measured = estimated_pause(render(text, 2, 200, is_para_end=True))
    assert abs(budgets[2] - measured) <= 0.4

    sents = [Sentence(i, "这是一句用于验证时间轴的文本。", i * 12, i * 12 + 12, 0)
             for i in range(3)]
    doc = Document(path="x.md", sentences=sents, display_text="x" * 36)
    plain = Timeline(doc, 0.2)
    compensated = Timeline(doc, 0.2, PAUSE + budgets[2])
    assert compensated.total() > plain.total()
    before = compensated.total()
    compensated.set_real(0, 9.0)
    assert compensated.total() != before


@pytest.mark.case("TC-NAT-008")
def test_default_voice_prefers_modern_and_keeps_legacy_compatibility(voice):
    from src.core.speech import Voice, choose_voice, list_voices

    voices = list_voices()
    modern = [v for v in voices if v.is_chinese and v.is_modern]
    chosen = choose_voice(voices)
    assert chosen is not None and chosen.is_chinese
    if modern:
        assert chosen.is_modern and chosen.locale == "zh_CN"
    fake = [
        Voice("Alex", "en_US"), Voice("Sinji", "zh_HK"),
        Voice("Tingting", "zh_CN"), Voice("Meijia", "zh_TW"),
    ]
    assert choose_voice(fake).identifier == "Tingting"
    assert choose_voice(fake, "Meijia").identifier == "Meijia"
    assert choose_voice([Voice("Alex", "en_US")]) is None
    assert choose_voice([Voice("Sinji", "zh_HK")]).identifier == "Sinji"
    assert Voice("Sandy (中文（中国大陆）)", "zh_CN").is_modern
    assert not Voice("Tingting", "zh_CN").is_modern


@pytest.mark.case("TC-NAT-009")
def test_empty_audio_is_rejected_and_voice_falls_back(voice, monkeypatch, sample_audio,
                                                      make_controller, fresh_store):
    import src.core.speech as sp
    from src.core.speech import MIN_AUDIO_DURATION, SpeechEngine, Voice

    def fake_run(args, timeout=120, input_text=None):
        target = Path(args[args.index("-o") + 1])
        target.write_bytes(b"RIFF" + b"0" * 200)
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    # Keep the probe patches local: patching module-level _run would also
    # intercept list_voices() when make_controller builds a controller.
    with monkeypatch.context() as probe:
        probe.setattr(sp, "_run", fake_run)
        probe.setattr(sp, "probe_duration", lambda path: 0.01)
        probe.setattr(SpeechEngine, "cached", lambda self, text: (None, 0.0))
        engine = SpeechEngine(voice, 200)
        path, duration, error = engine.synthesize("空音频探测文本")
        assert path is None and duration == 0.0
        assert error.startswith("EMPTY_AUDIO:")
        assert MIN_AUDIO_DURATION >= 0.016

    c = make_controller(fresh_store, SAMPLE_PATHS)
    original = c.voice.identifier
    c.voices = [Voice(original, "zh_CN"), Voice("Backup", "zh_CN")]
    calls = []

    def flaky(self, text):
        calls.append(text)
        if len(calls) == 1:
            return None, 0.0, "EMPTY_AUDIO:Bad"
        return sample_audio[0], 3.0, ""

    monkeypatch.setattr(SpeechEngine, "synthesize", flaky)
    assert c._ensure_usable_voice() is True
    assert c.voice.identifier != original
    assert c.settings["voice"] == c.voice.identifier
    assert c.startup_message


@pytest.mark.case("TC-NAT-010")
def test_cache_key_isolates_rewrite_prosody_voice_and_rate(voice):
    from src.core.oralizer import oralize
    from src.core.prosody import render
    from src.core.speech import SpeechEngine, Voice

    raw = "文档本身没有时间轴，所以程序按语速把字数换成时间。"
    variants = [
        raw,
        render(oralize(raw), 2, 200),
        render(oralize(raw), 3, 200),
    ]
    e = SpeechEngine(voice, 200)
    keys = [e.key(t) for t in variants]
    keys.append(SpeechEngine(Voice("Tingting", "zh_CN"), 200).key(variants[1]))
    keys.append(SpeechEngine(voice, 240).key(variants[1]))
    assert len(set(keys)) == len(keys)
    assert e.key(variants[1]) == keys[1]
    assert all(re.fullmatch(r"[0-9a-f]{24}", k) for k in keys)


@pytest.mark.case("TC-NAT-011")
def test_naturalness_settings_persist_and_rebuild(controller, fresh_store):
    import json
    from src.core.store import Store

    controller.select_item(0, auto_play=False)
    controller.set_oralize(False)
    controller.set_prosody_level(3)
    saved = json.loads(QA_STATE.read_text(encoding="utf-8"))
    assert saved["settings"]["oralize"] is False
    assert saved["settings"]["prosody_level"] == 3
    assert Store().settings["prosody_level"] == 3
    controller.set_prosody_level(99)
    assert controller._prosody_level() == 3
    assert controller.timeline is not None and controller.doc is not None


@pytest.mark.case("TC-NAT-012")
def test_preview_does_not_disturb_current_playback(controller):
    from PySide6.QtMultimedia import QMediaPlayer

    controller.select_item(0, auto_play=True)
    before_state = controller.player.playbackState()
    before_index = controller.sentence_index
    messages = []
    controller.message.connect(messages.append)
    controller.preview_voice()
    assert controller._preview_player is not None
    player = controller._preview_player[0]
    assert isinstance(player, QMediaPlayer)
    assert controller.player.playbackState() == before_state
    assert controller.sentence_index == before_index
    assert any("试听" in m for m in messages)
