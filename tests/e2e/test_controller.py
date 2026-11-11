"""TC-GUI-* — 播放控制 / 播放列表 / 断点。规格见 tests/docs/02-GUI-TEST-CASES.md。"""
from __future__ import annotations

import os

import pytest
from PySide6.QtMultimedia import QMediaPlayer

from conftest import QA_STATE, SAMPLE_PATHS, wait_ms, wait_until


@pytest.mark.case("TC-GUI-001")
def test_open_document_and_play(controller):
    c = controller
    loaded, states = [], []
    c.documentLoaded.connect(lambda doc: loaded.append(doc))
    c.stateChanged.connect(lambda on: states.append(on))
    c.select_item(0, auto_play=True)
    wait_ms(250)  # QMediaPlayer loads asynchronously, even offscreen
    assert c.doc is not None and c.doc.ok and len(c.doc.sentences) > 0
    assert c.timeline.total() > 0
    assert c.player.source().isLocalFile()
    assert c.playing is True and c.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert loaded and states and states[-1] is True


@pytest.mark.case("TC-GUI-002")
def test_pause_resume_keeps_sentence(controller):
    c = controller
    c.select_item(0, auto_play=True)
    wait_ms(250)
    index = c.sentence_index
    c.play_pause()
    assert c.playing is False
    wait_ms(150)
    assert c.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    wait_ms(300)
    c.play_pause()
    wait_ms(150)
    assert c.playing is True
    assert c.sentence_index == index
    assert c.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState


@pytest.mark.case("TC-GUI-003")
def test_seek_snaps_to_sentence(controller):
    c = controller
    c.select_item(0, auto_play=True)
    messages = []
    c.message.connect(messages.append)
    # Resolve the expected sentence BEFORE seeking: loading a sentence replaces
    # its estimate with the real audio duration and mutates the timeline.
    expected = c.timeline.sentence_at(c.timeline.time_at_fraction(0.55))
    c.seek_fraction(0.55)
    assert c.sentence_index == expected
    assert any("跳到第" in m for m in messages)
    c.seek_fraction(0.0)
    assert c.sentence_index == 0
    c.seek_fraction(1.0)
    assert c.sentence_index == len(c.doc.sentences) - 1


@pytest.mark.case("TC-GUI-004")
def test_read_from_any_sentence(controller):
    c = controller
    c.select_item(0, auto_play=True)
    messages = []
    c.message.connect(messages.append)
    target = min(5, len(c.doc.sentences) - 1)
    c.seek_sentence(target)
    assert c.sentence_index == target and c.playing is True
    assert any(f"从第 {target + 1} 句" in m for m in messages)


@pytest.mark.case("TC-GUI-005")
def test_skip_plus_minus_15_seconds(controller):
    c = controller
    c.select_item(0, auto_play=True)
    start = c.sentence_index
    c.skip_seconds(15)
    assert c.sentence_index >= start
    c.skip_seconds(-15)
    assert 0 <= c.sentence_index < len(c.doc.sentences)


@pytest.mark.case("TC-GUI-006")
def test_prev_next_sentence_navigation(controller):
    c = controller
    c.select_item(0, auto_play=True)
    c.seek_sentence(3)
    assert c.sentence_index == 3
    c.next_sentence()
    assert c.sentence_index == 4
    c.prev_sentence()
    assert c.sentence_index == 3
    c.seek_sentence(0)
    c.prev_sentence()
    assert c.sentence_index == 0
    c.seek_sentence(len(c.doc.sentences) - 1)
    c.next_sentence()
    assert c.sentence_index == len(c.doc.sentences) - 1


@pytest.mark.case("TC-GUI-007")
def test_auto_advance_and_sequence_finish(controller):
    c = controller
    c.set_mode("sequence")
    c.select_item(0, auto_play=True)
    c.sentence_index = len(c.doc.sentences) - 1
    c._advance()
    assert c.current_item == 1
    assert c.store.items[0]["status"] == "done"
    messages = []
    c.message.connect(messages.append)
    c.select_item(len(c.store.items) - 1, auto_play=True)
    c.sentence_index = len(c.doc.sentences) - 1
    c._advance()
    assert c.playing is False
    assert any("列表播放完毕" in m for m in messages)
    c.next_item()
    assert 0 <= c.current_item < len(c.store.items)


@pytest.mark.case("TC-GUI-008")
def test_all_playback_modes(controller, fresh_store):
    c = controller
    c.set_mode("loop_all")
    c.select_item(len(c.store.items) - 1, auto_play=False)
    c._next_item(auto=True)
    assert c.current_item == 0

    c.set_mode("loop_one")
    c.select_item(0, auto_play=True)
    c.sentence_index = len(c.doc.sentences) - 1
    c._advance()
    assert c.current_item == 0 and c.sentence_index == 0

    c.set_mode("shuffle")
    c.select_item(0, auto_play=False)
    first = c.current_item
    c._next_item(auto=False)
    assert c.current_item != first
    second = c.current_item
    c._next_item(auto=False)
    assert c.current_item != second

    c.set_mode("sequence")
    from src.core.store import Store
    assert Store().settings["mode"] == "sequence"


@pytest.mark.case("TC-GUI-009")
def test_resume_bookmark_rewinds_one_sentence(fresh_store, make_controller):
    c1 = make_controller(fresh_store, SAMPLE_PATHS[:1])
    c1.select_item(0, auto_play=False)
    c1.seek_sentence(6)
    assert c1.store.get_bookmark(c1.doc.doc_hash)["sentence"] == 6
    c1.shutdown()

    store2 = type(fresh_store)()
    c2 = make_controller(store2)
    c2.restore_session()
    assert c2.doc is not None and c2.doc.path == SAMPLE_PATHS[0]
    assert c2.sentence_index == 5
    assert c2.playing is False


@pytest.mark.case("TC-GUI-010")
def test_scanned_item_skipped_without_breaking(fresh_store, make_controller, scan_pdf):
    c = make_controller(fresh_store, [SAMPLE_PATHS[0], scan_pdf, SAMPLE_PATHS[1]])
    messages = []
    c.message.connect(messages.append)
    c.select_item(1, auto_play=False)
    wait_ms(250)
    item = c.store.items[1]
    assert item["status"] == "error" and "无文字层" in item["error"]
    assert any("跳过" in m for m in messages)
    assert c.current_item == 2


@pytest.mark.case("TC-GUI-011")
def test_settings_persist_and_clamp(controller):
    c = controller
    c.select_item(0, auto_play=True)
    c.set_rate(220)
    c.set_volume(35)
    c.set_mode("loop_all")
    c.set_auto_scroll(False)
    c.set_skip_code(False)
    c.set_rate(9999)
    c.set_volume(-100)
    assert c.rate == 350 and c.engine.rate == 350
    assert c.audio.volume() == 0.0
    from src.core.store import Store
    settings = Store().settings
    assert settings["mode"] == "loop_all" and settings["auto_scroll"] is False
    assert settings["skip_code"] is False and settings["rate"] == 350
    assert c._fmt(125) == "02:05"


@pytest.mark.case("TC-GUI-012")
def test_background_duration_estimation(controller, scan_pdf):
    c = controller
    c.store.add_items([scan_pdf], None)
    c.estimate_durations()
    ready = wait_until(lambda: all(i.get("est_hash") for i in c.store.items), 10)
    assert ready, "后台估算线程未在 10 秒内完成"
    normal = next(i for i in c.store.items if i["path"] == SAMPLE_PATHS[0])
    scanned = next(i for i in c.store.items if i["path"] == scan_pdf)
    assert normal.get("est_seconds", 0) > 0
    assert scanned["status"] == "error" and "无文字层" in scanned["error"]
    assert scanned.get("est_seconds") == 0
    signature = normal["est_hash"]
    c.estimate_durations()
    wait_ms(300)
    assert c.store.items[0]["est_hash"] == signature


@pytest.mark.case("TC-GUI-013")
def test_main_window_components(fresh_store, make_controller, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox
    from src.controller import ReaderController
    from src.ui.main_window import MainWindow
    # No Chinese voice on CI runners must not open a modal warning dialog.
    monkeypatch.setattr(ReaderController, "has_chinese_voice", lambda self: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    win = MainWindow()
    assert win.reader is not None and win.playlist is not None and win.controls is not None
    assert "文档朗读器" in win.windowTitle()
    assert win.playlist.list.count() == len(win.store.items)
    win.store.add_items(SAMPLE_PATHS[:2], None)
    win._refresh_list()
    assert win.playlist.list.count() == 2
    wait_ms(30)
    win.controller.shutdown()
    win.close()


@pytest.mark.case("TC-GUI-014")
def test_stop_and_shutdown_leave_no_threads(controller):
    c = controller
    c.select_item(0, auto_play=True)
    c.stop()
    assert c.playing is False
    c.reset()
    assert c.doc is None and c.timeline is None and c.current_item == -1
    c.shutdown()
    assert not c.timer.isActive()
    assert c.pool.activeThreadCount() == 0


@pytest.mark.case("TC-GUI-015")
def test_folder_scan_uses_natural_sort(tmp_path):
    """文件夹里 1、11、2、21 的顺序是字符串比较的产物，不是用户想要的顺序。"""
    from pathlib import Path

    from src.ui.playlist_view import collect_paths

    names = ["1.md", "11.md", "2.md", "21.md", "3.md", "第1章.md", "第10章.md", "第2章.md"]
    for name in names:
        (tmp_path / name).write_text("正文", encoding="utf-8")

    got = [Path(p).name for p in collect_paths([str(tmp_path)])]
    assert got == [
        "1.md",
        "2.md",
        "3.md",
        "11.md",
        "21.md",
        "第1章.md",
        "第2章.md",
        "第10章.md",
    ], f"自然排序结果不符：{got}"


@pytest.mark.case("TC-GUI-016")
def test_sidebar_width_is_remembered(fresh_store, make_controller, monkeypatch, qapp):
    """分栏宽度要能拖、能存、重开还在，否则拖完下次又回到 296。"""
    from PySide6.QtWidgets import QMessageBox, QSplitter
    from src.controller import ReaderController
    from src.ui.main_window import SIDEBAR_MAX, SIDEBAR_MIN, MainWindow

    monkeypatch.setattr(ReaderController, "has_chinese_voice", lambda self: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    first = MainWindow()
    try:
        assert isinstance(first.splitter, QSplitter)
        assert first.splitter.count() == 2
        assert first.splitter.widget(0) is first.playlist
        assert first.splitter.handleWidth() >= 4, "拖拽热区太窄，鼠标抓不住"
        assert first.playlist.minimumWidth() == SIDEBAR_MIN
        assert first.playlist.maximumWidth() == SIDEBAR_MAX
    finally:
        first.controller.shutdown()
        first.close()

    # 记一个宽度，重开应该原样恢复。
    fresh_store.settings["sidebar_width"] = 430
    fresh_store.save()
    second = MainWindow()
    try:
        # 未 show 的窗口不会真正布局，splitter 会停在最小宽度上，
        # 这时读 sizes() 得到的是 200 而不是要验证的恢复值。
        second.resize(1180, 780)
        second.show()
        wait_ms(120)
        assert second.splitter.sizes()[0] == 430, (
            f"宽度未恢复：{second.splitter.sizes()}"
        )
    finally:
        second.controller.shutdown()
        second.close()


@pytest.mark.case("TC-GUI-017")
def test_controls_fold_on_narrow_width(monkeypatch, qapp):
    """窄窗口下语速和音量要收起，否则它们撑住右栏最小宽度，左栏拉不宽。"""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    from src.ui.controls import COMPACT_ENTER, COMPACT_LEAVE, ControlBar

    def resize(bar, width):
        """不 show 也要走一遍 resizeEvent，才能验证折叠判定。"""
        old = QSize(bar.width(), bar.height())
        bar.resize(width, 110)
        bar.resizeEvent(QResizeEvent(QSize(width, 110), old))

    bar = ControlBar()
    resize(bar, COMPACT_LEAVE + 100)
    assert not bar.rate_combo.isHidden(), "宽窗口应显示语速"

    resize(bar, COMPACT_ENTER - 40)
    assert bar.rate_combo.isHidden() and bar.volume.isHidden(), "窄窗口应收起语速与音量"
    assert not bar.slider.isHidden(), "进度条不能收起"


@pytest.mark.case("TC-GUI-018")
def test_theme_follows_system(fresh_store, make_controller, monkeypatch, qapp):
    """README 承诺「深浅色跟随系统」，就不能只是启动时算一次。"""
    from PySide6.QtWidgets import QMessageBox
    from src.controller import ReaderController
    from src.ui import theme
    from src.ui.main_window import MainWindow
    from src.ui.widgets import CheckBox

    monkeypatch.setattr(ReaderController, "has_chinese_voice", lambda self: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    window = MainWindow()
    try:
        theme.apply(qapp)
        assert window.p.dark is theme.is_dark()

        # 模拟系统切到深色。offscreen 平台不会自己发 colorSchemeChanged，
        # 所以直接换掉判定函数再走一次统一刷新入口。
        monkeypatch.setattr(theme, "is_dark", lambda *a, **k: True)
        theme.refresh(qapp)
        assert window.p.dark is True
        assert theme.DARK.window in window.styleSheet()
        assert window.playlist.p.dark is True, "左栏没有跟着换色"
        assert window.controls.p.dark is True, "控制栏没有跟着换色"
        assert window.settings_dialog.p.dark is True, "设置面板没有跟着换色"
        boxes = window.findChildren(CheckBox)
        assert boxes and all(box.p.dark for box in boxes), "自绘复选框仍是旧配色"

        monkeypatch.setattr(theme, "is_dark", lambda *a, **k: False)
        theme.refresh(qapp)
        assert window.p.dark is False
        assert theme.LIGHT.window in window.styleSheet()
        assert window.playlist.p.dark is False
    finally:
        window.controller.shutdown()
        window.close()
