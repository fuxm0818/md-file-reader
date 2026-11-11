"""AAA tests for the voice library and the symbol-cleaning layer.

Ground truth: tests/docs/06-VOICE-TEST-CASES.md
"""
from __future__ import annotations

import json

import pytest

from conftest import QA_DIR, QA_STATE, SAMPLE_PATHS


# --------------------------------------------------------------- voice data
@pytest.mark.case("TC-VOI-001")
def test_voice_profiles_are_readable():
    from src.core.speech import Voice, list_voices
    from src.core.voices import base_name, describe, profile_of

    voices = [v for v in list_voices() if v.is_chinese]
    assert voices, "本机没有中文音色，无法验证档案翻译"
    voice = voices[0]

    profile = profile_of(voice)
    assert profile.name and profile.gender in ("男声", "女声", "未知")
    assert profile.tone in ("低沉", "中性", "清亮", "未测")
    label = describe(voice)
    assert " · " in label and "zh_" not in label and "(" not in label

    # 已知音色：标识里的地区后缀被剥掉
    sandy = next((v for v in voices if v.identifier.startswith("Sandy")), None)
    if sandy is not None:
        assert base_name(sandy.identifier) == "Sandy"
        assert profile_of(sandy).pitch_hz > 200

    # 未知音色退化为原名，不抛异常
    mystery = Voice("Nobody (某语)", "zh_CN")
    assert profile_of(mystery).name == "Nobody"
    assert profile_of(mystery).tone == "未测"


@pytest.mark.case("TC-VOI-002")
def test_voice_ordering_prefers_modern_mainland():
    from src.core.speech import list_voices
    from src.core.voices import is_modern, ordered, profile_of

    voices = list_voices()
    ranking = ordered(voices)
    assert ranking, "音色列表为空"

    positions = {v.identifier: i for i, v in enumerate(ranking)}
    modern = [v for v in ranking if is_modern(v)]
    legacy = [v for v in ranking if v.identifier.split(" (")[0] == "Tingting"]
    if modern and legacy:
        assert positions[modern[0].identifier] < positions[legacy[0].identifier]

    mainland = ordered(voices, mainland_only=True)
    assert mainland and all(v.locale == "zh_CN" for v in mainland)
    assert not {v.locale for v in mainland} & {"zh_TW", "zh_HK"}

    # 同名音色的台湾版排在后面（rank +4）
    from src.core.voices import base_name

    for voice in mainland:
        twin = next(
            (
                v
                for v in voices
                if v.locale == "zh_TW" and base_name(v.identifier) == base_name(voice.identifier)
            ),
            None,
        )
        if twin is not None:
            assert profile_of(twin).rank > profile_of(voice).rank


@pytest.mark.case("TC-VOI-003")
def test_stale_voice_falls_back_to_default(qapp, sample_audio, monkeypatch):
    """v1.4 移除了神经引擎，老配置里的 zf_001 之类的 ID 已经不存在。

    这类悬空 ID 必须静默回落到默认音色（婷婷），而不是让应用没有声音。
    """
    from src.core.speech import DEFAULT_VOICE, SpeechEngine

    monkeypatch.setattr(SpeechEngine, "calibrate", lambda self: 0.2)
    monkeypatch.setattr(
        SpeechEngine, "cached", lambda self, text, tail_pause=0.0: sample_audio
    )

    from src.controller import ReaderController
    from src.core.store import Store

    if QA_STATE.exists():
        QA_STATE.unlink()
    QA_STATE.write_text(
        json.dumps({"settings": {"voice": "zf_001"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    store = Store()
    controller = ReaderController(store)
    try:
        assert controller.voice is not None, "悬空音色 ID 不该让应用失去声音"
        assert controller.voice.identifier.startswith(
            DEFAULT_VOICE
        ), f"应回落到 {DEFAULT_VOICE}，实际 {controller.voice.identifier}"
        assert store.settings["voice"] == controller.voice.identifier
    finally:
        controller.shutdown()


@pytest.mark.case("TC-VOI-004")
def test_voice_library_is_gone(qapp):
    """v1.4 删除了音色库：应用只用一个音色，留着一堆选项反而添乱。

    这条用例锁死删除结果，防止以后有人不小心把入口加回来却没人维护。
    """
    import importlib.util

    assert importlib.util.find_spec("src.ui.voice_dialog") is None, "音色库模块应已移除"

    from src.ui.main_window import MainWindow

    assert not hasattr(MainWindow, "open_voices"), "音色库入口应已移除"
    assert not hasattr(MainWindow, "_choose_voice"), "音色切换回调应已移除"


# ------------------------------------------------------------ voice actions
@pytest.mark.case("TC-VOI-005")
def test_preview_any_voice_keeps_setting(fresh_store, make_controller, monkeypatch):
    from src.core.speech import SpeechEngine, list_voices

    monkeypatch.setattr(SpeechEngine, "cached", lambda self, text, tail_pause=0.0: (None, 0.0))
    monkeypatch.setattr(
        SpeechEngine,
        "synthesize",
        lambda self, text, tail_pause=0.0: (__import__("pathlib").Path("/tmp/none.aiff"), 1.0, ""),
    )
    controller = make_controller(fresh_store, SAMPLE_PATHS[:1])
    original = controller.settings["voice"]
    messages: list[str] = []
    controller.message.connect(messages.append)

    others = [v for v in list_voices() if v.identifier != controller.voice.identifier]
    if others:
        controller.preview_voice(others[0].identifier)
        assert controller.settings["voice"] == original, "试听不得改动默认音色"
        assert messages and "正在试听" in messages[-1]

    controller.preview_voice("不存在的音色")
    assert messages[-1].startswith("这个音色")


@pytest.mark.case("TC-VOI-009")
def test_main_window_shows_current_voice(fresh_store, make_controller, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    from src.controller import ReaderController
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(ReaderController, "has_chinese_voice", lambda self: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    window = MainWindow()
    try:
        text = window.voice_tag.text()
        assert text.startswith("音色："), f"状态栏应显示当前音色，实际为 {text!r}"
        assert " · " in text and "zh_" not in text
        assert not hasattr(window, "voice_button"), "工具栏音色按钮应已移除"
    finally:
        window.controller.shutdown()
        window.close()


@pytest.mark.case("TC-VOI-010")
def test_system_voice_output_is_polished(qapp):
    """打磨后级是 v1.4 保留的核心改进：音量提上去，切换不爆音。"""
    import uuid
    import wave

    import numpy as np

    from src.core.speech import SpeechEngine, choose_voice, list_voices

    voice = choose_voice(list_voices())
    assert voice is not None, "本机没有可用的中文音色"
    path, duration, error = SpeechEngine(voice, 200).synthesize(
        f"打磨检查 {uuid.uuid4().hex[:6]}。"
    )
    assert path and error == "", f"合成失败：{error}"
    assert path.suffix == ".wav", "打磨后应输出 wav，而不是原始 aiff"

    with wave.open(str(path)) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    peak = 20.0 * float(np.log10(max(float(np.abs(samples).max()), 1e-9)))
    assert -3.5 <= peak <= -0.5, f"峰值 {peak:.2f} dBFS 不在交付区间"
    assert rate >= 22000, "采样率异常"
    assert abs(float(samples[0])) < 0.05 and abs(float(samples[-1])) < 0.05, "首尾应有淡入淡出"


# --------------------------------------------------------- symbol cleaning
@pytest.mark.case("TC-VOI-006")
def test_symbol_cleaning_removes_spoken_noise():
    from src.core.textclean import clean_symbols

    cases = {
        "安装到 /usr/local/bin 目录": ("usr", "local", "bin"),
        "姓名|年龄|城市": ("姓名", "年龄", "城市"),
        "第 3-5 章": ("3到5",),
        "3/4 的用户": ("3比4",),
        "他来了——然后又走了": ("他来了，然后又走了",),
        "等等……还没结束": ("等等，还没结束",),
        "## 二级标题": ("二级标题",),
        "- 第一项": ("第一项",),
        "1.5 秒之后开始": ("1.5 秒之后开始",),
        "如果 a > b 就交换": ("a 大于 b",),
    }
    for source, expected in cases.items():
        out = clean_symbols(source)
        for fragment in expected:
            assert fragment in out, f"{source!r} → {out!r} 缺少 {fragment!r}"

    assert clean_symbols("-----") == ""
    assert clean_symbols("=====") == ""
    assert clean_symbols("----- 分隔 -----") == "分隔", "两端的横线去掉，文字保留"
    assert "/" not in clean_symbols("路径 /usr/local/bin")
    assert "|" not in clean_symbols("姓名|年龄")
    assert "\\" not in clean_symbols(r"目录 C:\Users\doc")
    # 小数不能被破坏
    assert "3.5" in clean_symbols("准确率 3.5% 以上")


@pytest.mark.case("TC-VOI-007")
def test_cleaning_does_not_touch_display_or_spans(fresh_store, make_controller):
    from src.core.textclean import clean_symbols

    source = QA_DIR / "符号坐标测试.md"
    source.write_text(
        "# 标题一\n\n- 安装到 /usr/local/bin 目录\n\n姓名|年龄 与 3-5 章 —— 都在这里。\n",
        encoding="utf-8",
    )
    controller = make_controller(fresh_store, [str(source)])
    controller.select_item(0, auto_play=False)

    shown = controller.doc.display_text
    assert "/usr/local/bin" in shown, "正文显示必须保留原始符号"
    assert "3-5" in shown

    # 坐标必须仍然可用：切片长度与句子一致、区间递增、不越界。
    # 表格竖线在句子里被规范成空格（等长），因此逐字符相等不成立。
    previous_end = 0
    for sentence in controller.doc.sentences:
        assert 0 <= sentence.start < sentence.end <= len(shown)
        assert sentence.start >= previous_end, "句子区间必须单调递增"
        assert len(shown[sentence.start : sentence.end]) == len(sentence.text)
        previous_end = sentence.end

    speech = " ".join(
        controller._speech_text(i) for i in range(len(controller.doc.sentences))
    )
    assert "/" not in speech and "|" not in speech
    assert "3到5" in speech
    assert clean_symbols("- 安装到 /usr/local/bin 目录").startswith("安装到")


@pytest.mark.case("TC-VOI-008")
def test_symbol_switching_persists(fresh_store, make_controller):
    source = QA_DIR / "符号开关测试.md"
    source.write_text("安装到 /usr/local/bin 目录即可。\n", encoding="utf-8")
    controller = make_controller(fresh_store, [str(source)])
    controller.select_item(0, auto_play=False)

    assert controller.settings.get("clean_symbols", True) is True
    assert "/" not in controller._speech_text(0)

    controller.set_symbol_cleaning(False)
    assert controller._speech_text(0).count("/") >= 2, "关闭后应保留原始符号"

    saved = json.loads(QA_STATE.read_text(encoding="utf-8"))
    assert saved["settings"]["clean_symbols"] is False

    controller.set_symbol_cleaning(True)
    assert "/" not in controller._speech_text(0)


@pytest.mark.case("TC-VOI-011")
def test_old_cache_is_purged_once(fresh_store, sample_audio, monkeypatch):
    """v1.4 换了缓存键与音频容器，旧文件永远不会再命中，升级时要清一次。"""
    from src.controller import CACHE_SCHEMA, ReaderController
    from src.core.speech import SpeechEngine
    from src.core.store import Store

    # 造出「升级前」的状态：没有 cache_schema
    fresh_store.settings.pop("cache_schema", None)
    fresh_store.save()

    calls = {"n": 0}

    def counting(self):
        calls["n"] += 1
        return 7

    monkeypatch.setattr(SpeechEngine, "calibrate", lambda self: 0.2)
    monkeypatch.setattr(
        SpeechEngine, "cached", lambda self, text, tail_pause=0.0: sample_audio
    )
    monkeypatch.setattr(SpeechEngine, "clear_cache", counting)

    first = ReaderController(fresh_store)
    try:
        assert calls["n"] == 1, "首次启动应清理一次旧缓存"
        assert fresh_store.settings["cache_schema"] == CACHE_SCHEMA
        assert "旧版音频缓存" in first.startup_message
    finally:
        first.shutdown()

    second = ReaderController(Store())
    try:
        assert calls["n"] == 1, "清理只应发生一次，不能每次启动都删缓存"
    finally:
        second.shutdown()
