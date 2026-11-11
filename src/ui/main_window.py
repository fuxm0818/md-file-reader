from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..controller import ReaderController
from ..core.parsers import SUPPORTED_EXTS
from ..core.speech import cleaned_env
from ..core.store import Store
from ..core.voices import describe
from ..version import __version__
from . import theme
from .controls import ControlBar
from .playlist_view import PlaylistView, collect_paths
from .reader_view import ReaderView
from .settings_dialog import SettingsDialog

FILE_FILTER = (
    "文档 (*.txt *.text *.md *.markdown *.pdf *.docx *.log *.csv *.json *.rst);;"
    "所有文件 (*)"
)

SIDEBAR_WIDTH = 296
SIDEBAR_MIN = 200
SIDEBAR_MAX = 620


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.p = theme.palette()
        self.store = Store()
        self.controller = ReaderController(self.store)
        c = self.controller

        self.setWindowTitle("文档朗读器")
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)
        self.setStyleSheet(theme.stylesheet(self.p))

        self.reader = ReaderView()
        self.playlist = PlaylistView()
        self.controls = ControlBar()
        self.settings_dialog = SettingsDialog(c, self)

        # ------------------------------------------------------- right column
        self.doc_title = QLabel("未选择文档")
        self.doc_title.setObjectName("Title")
        self.doc_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.doc_meta = QLabel("把文档拖到左边，或点“添加文档”")
        self.doc_meta.setObjectName("Hint")

        title_text = QVBoxLayout()
        title_text.setSpacing(1)
        title_text.addWidget(self.doc_title)
        title_text.addWidget(self.doc_meta)

        self.add_button = QPushButton("打开文档")
        theme.set_icon(self.add_button, "folder", self.p.secondary, 16)
        self.add_button.clicked.connect(lambda _=False: self.add_files())

        self.settings_button = QPushButton()
        self.settings_button.setObjectName("IconButton")
        theme.set_icon(self.settings_button, "settings", self.p.secondary, 18)
        self.settings_button.setToolTip("偏好设置")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(lambda _=False: self.open_settings())

        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(20, 14, 16, 12)
        bar.setSpacing(10)
        bar.addLayout(title_text, 1)
        bar.addWidget(self.add_button)
        bar.addWidget(self.settings_button)

        card = QFrame()
        card.setObjectName("ReaderCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.addWidget(self.reader)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(toolbar)
        inner = QVBoxLayout()
        inner.setContentsMargins(16, 0, 16, 12)
        inner.addWidget(card)
        right_layout.addLayout(inner, 1)
        right_layout.addWidget(self.controls)

        self.playlist.setMinimumWidth(SIDEBAR_MIN)
        self.playlist.setMaximumWidth(SIDEBAR_MAX)

        # 左右两栏用 splitter 而不是固定 296px：目录名长的时候有人想把左边
        # 拉宽看全，读正文的时候又想把它收窄。handle 只做拖拽热区，视觉上
        # 的线由 #Sidebar 自带的右边框提供，所以这里让 handle 与窗口同色。
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        self.splitter.addWidget(self.playlist)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        width = int(c.settings.get("sidebar_width", SIDEBAR_WIDTH) or SIDEBAR_WIDTH)
        width = max(SIDEBAR_MIN, min(SIDEBAR_MAX, width))
        self.splitter.setSizes([width, max(1, self.width() - width)])
        self.setCentralWidget(self.splitter)

        # 拖动过程中每移动一像素都会发信号，攒到停手再写盘一次。
        self._split_timer = QTimer(self)
        self._split_timer.setSingleShot(True)
        self._split_timer.setInterval(400)
        self._split_timer.timeout.connect(self._save_sidebar_width)
        self.splitter.splitterMoved.connect(lambda *_: self._split_timer.start())

        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)
        self.voice_tag = QLabel()
        self.voice_tag.setObjectName("Faint")
        self.status_bar.addPermanentWidget(self.voice_tag)
        offline = QLabel("本地合成 · 不联网 · 不上传文档")
        offline.setObjectName("Faint")
        self.status_bar.addPermanentWidget(offline)

        self._build_menu()
        self._connect()
        self.controls.sync_settings(c.settings)
        self.reader.set_auto_scroll(bool(c.settings.get("auto_scroll", True)))
        self._refresh_list()
        self._refresh_voice_tag()

        if not c.has_chinese_voice():
            QMessageBox.warning(
                self,
                "未检测到中文语音",
                "本机没有可用的中文语音，朗读功能不可用。\n\n"
                "请到「系统设置 → 辅助功能 → 朗读内容 → 管理声音」下载任一中文音色后重启本程序。",
            )
        elif c.startup_message:
            self._message(c.startup_message)
        QTimer.singleShot(0, c.restore_session)

    # ------------------------------------------------------------------ ui
    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")
        action = file_menu.addAction("添加文件…")
        action.setShortcut(QKeySequence("Ctrl+O"))
        action.triggered.connect(lambda _=False: self.add_files())
        file_menu.addAction("添加文件夹…").triggered.connect(
            lambda _=False: self.add_folder()
        )
        file_menu.addSeparator()
        file_menu.addAction("退出").triggered.connect(lambda _=False: self.close())

        play = menu.addMenu("播放")
        play.addAction("播放 / 暂停").triggered.connect(
            lambda _=False: self.controller.toggle_play()
        )
        play.addAction("停止").triggered.connect(lambda _=False: self.controller.stop())
        play.addSeparator()
        play.addAction("上一句").triggered.connect(
            lambda _=False: self.controller.prev_sentence()
        )
        play.addAction("下一句").triggered.connect(
            lambda _=False: self.controller.next_sentence()
        )
        play.addAction("后退 15 秒").triggered.connect(
            lambda _=False: self.controller.skip_seconds(-15)
        )
        play.addAction("前进 15 秒").triggered.connect(
            lambda _=False: self.controller.skip_seconds(15)
        )
        play.addSeparator()
        play.addAction("上一项").triggered.connect(
            lambda _=False: self.controller.prev_item()
        )
        play.addAction("下一项").triggered.connect(
            lambda _=False: self.controller.next_item()
        )

        tools = menu.addMenu("工具")
        tools.addAction("偏好设置…").triggered.connect(
            lambda _=False: self.open_settings()
        )
        tools.addAction("清理音频缓存").triggered.connect(
            lambda _=False: self._clear_cache()
        )

        menu.addAction("关于").triggered.connect(lambda _=False: self._about())

    def _connect(self) -> None:
        c = self.controller
        c.documentLoaded.connect(self.reader.set_document)
        c.sentenceChanged.connect(self.reader.highlight)
        c.positionChanged.connect(self._on_position)
        c.stateChanged.connect(self.controls.set_playing)
        c.itemChanged.connect(self._on_item_changed)
        c.listChanged.connect(self._refresh_list)
        c.message.connect(self._message)
        c.settingsChanged.connect(self._on_settings_changed)

        self.reader.readFromHere.connect(c.seek_sentence)

        self.controls.playToggled.connect(c.toggle_play)
        self.controls.stopClicked.connect(c.stop)
        self.controls.prevItemClicked.connect(c.prev_item)
        self.controls.nextItemClicked.connect(c.next_item)
        self.controls.prevSentenceClicked.connect(c.prev_sentence)
        self.controls.nextSentenceClicked.connect(c.next_sentence)
        self.controls.skipRequested.connect(c.skip_seconds)
        self.controls.seekRequested.connect(c.seek_fraction)
        self.controls.rateChanged.connect(c.set_rate)
        self.controls.volumeChanged.connect(c.set_volume)
        self.controls.modeChanged.connect(c.set_mode)

        p = self.playlist
        p.filesDropped.connect(self._on_files_dropped)
        p.itemActivated.connect(lambda row: c.select_item(row, True))
        p.playHere.connect(lambda row: c.select_item(row, True))
        p.playNext.connect(self._play_next)
        p.removePaths.connect(self._remove_paths)
        p.orderChanged.connect(self._on_order_changed)
        p.clearRequested.connect(self._clear_list)
        p.addFilesRequested.connect(self.add_files)
        p.addFolderRequested.connect(self.add_folder)
        p.playlistSwitched.connect(self._switch_playlist)
        p.playlistCreated.connect(self._create_playlist)
        p.playlistRenamed.connect(self._rename_playlist)
        p.playlistDeleted.connect(self._delete_playlist)
        p.revealRequested.connect(self._reveal)

        d = self.settings_dialog
        d.voiceChanged.connect(c.set_voice)
        d.rateChanged.connect(c.set_rate)
        d.volumeChanged.connect(c.set_volume)
        d.autoScrollChanged.connect(self._set_auto_scroll)
        d.skipCodeChanged.connect(c.set_skip_code)
        d.autoResumeChanged.connect(c.set_auto_resume)
        d.clearCacheRequested.connect(self._clear_cache)
        d.previewRequested.connect(c.preview_voice)
        d.oralizeChanged.connect(c.set_oralize)
        d.symbolChanged.connect(c.set_symbol_cleaning)
        d.prosodyChanged.connect(c.set_prosody_level)

        QShortcut(QKeySequence("Space"), self, c.toggle_play)
        QShortcut(QKeySequence("Ctrl+Left"), self, lambda: c.skip_seconds(-15))
        QShortcut(QKeySequence("Ctrl+Right"), self, lambda: c.skip_seconds(15))
        QShortcut(QKeySequence("Ctrl+Up"), self, c.prev_item)
        QShortcut(QKeySequence("Ctrl+Down"), self, c.next_item)

    # ------------------------------------------------------------- dialogs
    def open_settings(self) -> None:
        self.settings_dialog.refresh_from_settings()
        self.settings_dialog.exec()

    def _refresh_voice_tag(self) -> None:
        voice = self.controller.voice
        self.voice_tag.setText(
            f"音色：{describe(voice)}" if voice else "没有可用的中文音色"
        )
        if voice:
            self.voice_tag.setToolTip(f"当前音色：{voice.identifier}")

    def _on_settings_changed(self) -> None:
        c = self.controller
        self.controls.sync_settings(c.settings)
        self.settings_dialog.refresh_from_settings()
        self._refresh_voice_tag()

    def _on_position(self, current, total, fraction, index, count) -> None:
        self.controls.update_position(current, total, fraction, index, count)
        if count:
            from .controls import fmt_time

            self.doc_meta.setText(f"共 {count} 句 · 约 {fmt_time(total)}")

    def _message(self, text: str) -> None:
        self.status_bar.showMessage(text, 8000)

    def _on_item_changed(self, index: int) -> None:
        items = self.store.items
        if 0 <= index < len(items):
            name = Path(items[index]["path"]).name
            self.setWindowTitle(f"{name} — 文档朗读器")
            self.doc_title.setText(name)
        elif not items:
            self.doc_title.setText("未选择文档")
            self.doc_meta.setText("把文档拖到左边，或点“添加文档”")

    def _refresh_list(self) -> None:
        self.playlist.refresh(
            self.store.items,
            self.controller.current_item,
            self.store.playlists,
            self.store.data["active_playlist_id"],
        )

    def _resync_current(self) -> None:
        c = self.controller
        if c.doc:
            for i, item in enumerate(self.store.items):
                if item["path"] == c.doc.path:
                    c.current_item = i
                    break
        else:
            c.current_item = -1
        self._refresh_list()

    def _save_sidebar_width(self) -> None:
        sizes = self.splitter.sizes()
        if not sizes:
            return
        width = max(SIDEBAR_MIN, min(SIDEBAR_MAX, sizes[0]))
        if self.store.settings.get("sidebar_width") == width:
            return
        self.store.settings["sidebar_width"] = width
        self.store.save()

    # ------------------------------------------------------------ add files
    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择文档", str(Path.home()), FILE_FILTER
        )
        if files:
            paths = [
                str(Path(f).resolve())
                for f in files
                if Path(f).suffix.lower() in SUPPORTED_EXTS and Path(f).is_file()
            ]
            self._add_paths(paths, None)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", str(Path.home()))
        if folder:
            self._add_paths(collect_paths([folder]), None)

    def _on_files_dropped(self, paths: list[str], at: int) -> None:
        self._add_paths(paths, at if at >= 0 else None)

    def _add_paths(self, paths: list[str], at: int | None) -> None:
        if not paths:
            self._message("没有找到可支持的文档")
            return
        added = self.store.add_items(paths, at)
        self._refresh_list()
        self.controller.estimate_durations()
        self._message(f"已加入 {added} 个文档（重复项已忽略）")

    # -------------------------------------------------------- playlist ops
    def _play_next(self, row: int) -> None:
        items = self.store.items
        c = self.controller
        if row < 0 or row >= len(items):
            return
        if row == c.current_item:
            self._message("这一项正在播放")
            return
        current_path = c.doc.path if c.doc else ""
        item = items.pop(row)
        target = (c.current_item + 1) if c.current_item >= 0 else 0
        if row < target:
            target -= 1
        items.insert(max(0, min(target, len(items))), item)
        self.store.save()
        for i, entry in enumerate(items):
            if entry["path"] == current_path:
                c.current_item = i
                break
        self._refresh_list()
        self._message(f"「{Path(item['path']).name}」已排到下一项播放")

    def _remove_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        c = self.controller
        current_path = c.doc.path if c.doc else ""
        if current_path in paths:
            c.reset()
            self.reader.setPlainText("")
        self.store.remove_paths(set(paths))
        self._refresh_list()
        self._message(f"已移除 {len(paths)} 项")

    def _on_order_changed(self, paths: list[str]) -> None:
        self.store.sync_order(paths)
        self._resync_current()

    def _clear_list(self) -> None:
        answer = QMessageBox.question(
            self, "清空播放列表", "确定清空当前列表吗？文档文件本身不会被删除。"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset()
        self.reader.setPlainText("")
        self.store.clear()
        self._refresh_list()
        self._message("列表已清空")

    def _switch_playlist(self, playlist_id: str) -> None:
        self.controller.reset()
        self.reader.setPlainText("")
        self.store.set_active(playlist_id)
        self.controller.restore_session()

    def _create_playlist(self, name: str) -> None:
        self.controller.reset()
        self.reader.setPlainText("")
        self.store.create_playlist(name)
        self._refresh_list()
        self.controller.restore_session()

    def _rename_playlist(self, name: str) -> None:
        self.store.rename_playlist(name)
        self._refresh_list()

    def _delete_playlist(self) -> None:
        self.controller.reset()
        self.reader.setPlainText("")
        self.store.delete_active_playlist()
        self._refresh_list()
        self.controller.restore_session()

    def _reveal(self, path: str) -> None:
        try:
            subprocess.run(
                ["/usr/bin/open", "-R", path], env=cleaned_env(), timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            self._message("无法在 Finder 中定位该文件")

    # ------------------------------------------------------------- settings
    def _set_auto_scroll(self, enabled: bool) -> None:
        self.reader.set_auto_scroll(enabled)
        self.controller.set_auto_scroll(enabled)

    def _clear_cache(self) -> None:
        engine = self.controller.engine
        count = engine.clear_cache() if engine else 0
        self.settings_dialog.refresh_cache_label()
        self._message(f"已清理 {count} 个缓存音频")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "关于文档朗读器",
            f"文档朗读器 {__version__}\n\n"
            "本地离线文档朗读器\n\n"
            "支持 txt / Markdown / PDF / Word，逐句合成、句级高亮、"
            "双坐标进度条、播放列表与断点续读。\n"
            "语音由 macOS 系统合成，不联网、不上传文档内容。",
        )

    # --------------------------------------------------------------- theme
    def apply_palette(self, p) -> None:
        """系统切换深浅色时由 ``theme.refresh`` 回调。

        主窗口自己带着一份样式表（比应用级更具体，会覆盖它），所以这里要
        重设一次；子部件由 theme 逐个遍历处理，不在这里重复下发。
        """
        self.p = p
        self.setStyleSheet(theme.stylesheet(p))
        theme.set_icon(self.add_button, "folder", p.secondary, 16)
        theme.set_icon(self.settings_button, "settings", p.secondary, 18)
        self.update()

    # --------------------------------------------------------------- events
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = collect_paths([u.toLocalFile() for u in event.mimeData().urls()])
            self._add_paths(paths, None)
            event.acceptProposedAction()

    def closeEvent(self, event):
        # 拖动后立刻关窗口时，防抖定时器还没触发，这里补一次。
        if self._split_timer.isActive():
            self._split_timer.stop()
            self._save_sidebar_width()
        self.controller.shutdown()
        super().closeEvent(event)
