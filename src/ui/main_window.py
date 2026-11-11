from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..controller import ReaderController
from ..core.parsers import SUPPORTED_EXTS
from ..core.speech import cleaned_env
from ..core.store import Store
from .controls import ControlBar
from .playlist_view import PlaylistView, collect_paths
from .reader_view import ReaderView
from .settings_dialog import SettingsDialog

FILE_FILTER = (
    "文档 (*.txt *.text *.md *.markdown *.pdf *.docx *.log *.csv *.json *.rst);;"
    "所有文件 (*)"
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = Store()
        self.controller = ReaderController(self.store)
        c = self.controller

        self.setWindowTitle("文档朗读器")
        self.resize(1120, 740)
        self.setAcceptDrops(True)

        self.reader = ReaderView()
        self.playlist = PlaylistView()
        self.controls = ControlBar()
        self.settings_dialog = SettingsDialog(c, self)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.reader, 1)
        right_layout.addWidget(self.controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.playlist)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 820])
        self.setCentralWidget(splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("就绪")
        self.status_bar.addPermanentWidget(self.status_label)

        self._build_menu()
        self._connect()
        self.controls.sync_settings(c.settings)
        self.reader.set_auto_scroll(bool(c.settings.get("auto_scroll", True)))
        self._refresh_list()

        if not c.has_chinese_voice():
            QMessageBox.warning(
                self,
                "未检测到中文语音",
                "本机没有可用的中文语音，朗读功能不可用。\n\n"
                "请到「系统设置 → 辅助功能 → 朗读内容 → 管理声音」下载任一中文音色后重启本程序。",
            )
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
            lambda _=False: self.settings_dialog.exec()
        )
        tools.addAction("清理音频缓存").triggered.connect(
            lambda _=False: self._clear_cache()
        )

        menu.addAction("关于").triggered.connect(lambda _=False: self._about())

    def _connect(self) -> None:
        c = self.controller
        c.documentLoaded.connect(self.reader.set_document)
        c.sentenceChanged.connect(self.reader.highlight)
        c.positionChanged.connect(self.controls.update_position)
        c.stateChanged.connect(self.controls.set_playing)
        c.itemChanged.connect(self._on_item_changed)
        c.listChanged.connect(self._refresh_list)
        c.message.connect(self._message)
        c.settingsChanged.connect(
            lambda: (
                self.controls.sync_settings(c.settings),
                self.settings_dialog.refresh_from_settings(),
            )
        )

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

        QShortcut(QKeySequence("Space"), self, c.toggle_play)
        QShortcut(QKeySequence("Ctrl+Left"), self, lambda: c.skip_seconds(-15))
        QShortcut(QKeySequence("Ctrl+Right"), self, lambda: c.skip_seconds(15))
        QShortcut(QKeySequence("Ctrl+Up"), self, c.prev_item)
        QShortcut(QKeySequence("Ctrl+Down"), self, c.next_item)

    def _message(self, text: str) -> None:
        self.status_bar.showMessage(text, 8000)
        self.status_label.setText(text)

    def _on_item_changed(self, index: int) -> None:
        items = self.store.items
        if 0 <= index < len(items):
            self.setWindowTitle(f"{Path(items[index]['path']).name} — 文档朗读器")

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
        folder = QFileDialog.getExistingDirectory(
            self, "选择文件夹", str(Path.home())
        )
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
            "本地离线文档朗读器\n\n"
            "支持 txt / Markdown / PDF / Word，逐句合成、句级高亮、"
            "双坐标进度条、播放列表与断点续读。\n"
            "语音由 macOS 系统合成，不联网、不上传文档内容。",
        )

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
        self.controller.shutdown()
        super().closeEvent(event)
