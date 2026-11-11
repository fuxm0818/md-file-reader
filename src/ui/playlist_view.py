from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.parsers import SUPPORTED_EXTS


def collect_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            try:
                for child in sorted(path.rglob("*")):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTS:
                        result.append(str(child.resolve()))
            except OSError:
                continue
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            result.append(str(path.resolve()))
    seen: set[str] = set()
    unique: list[str] = []
    for path in result:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class _DropList(QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.source() is self:
            super().dropEvent(event)
            self.owner._on_internal_move()
            return
        if event.mimeData().hasUrls():
            paths = collect_paths([u.toLocalFile() for u in event.mimeData().urls()])
            row = self.row(self.itemAt(event.position().toPoint()))
            at = row if row >= 0 else None
            self.owner.filesDropped.emit(paths, -1 if at is None else at)
            event.acceptProposedAction()


class PlaylistView(QWidget):
    filesDropped = Signal(list, int)
    itemActivated = Signal(int)
    playHere = Signal(int)
    playNext = Signal(int)
    removePaths = Signal(list)
    orderChanged = Signal(list)
    clearRequested = Signal()
    addFilesRequested = Signal()
    addFolderRequested = Signal()
    playlistSwitched = Signal(str)
    playlistCreated = Signal(str)
    playlistRenamed = Signal(str)
    playlistDeleted = Signal()
    revealRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_index = -1
        self._items: list[dict] = []
        self._updating = False

        header = QLabel("播放列表")
        header.setStyleSheet("font-weight: 500; padding: 2px 0;")
        self.combo = QComboBox()
        self.combo.setMinimumWidth(120)
        self.combo.currentIndexChanged.connect(self._on_combo)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        bar.addWidget(self.combo, 1)
        for text, tip, slot in (
            ("+", "新建播放列表", self._new_playlist),
            ("✎", "重命名当前列表", self._rename_playlist),
            ("−", "删除当前列表", self._delete_playlist),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=slot: s())
            bar.addWidget(button)
        bar_widget = QWidget()
        bar_widget.setLayout(bar)

        self.list = _DropList(self)
        self.list.itemDoubleClicked.connect(
            lambda item: self.itemActivated.emit(self.list.row(item))
        )
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_menu)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        for text, tip, slot in (
            ("添加文件", "从任意目录选择文件", self.addFilesRequested),
            ("添加文件夹", "批量导入整个文件夹", self.addFolderRequested),
            ("清空", "清空当前列表", self.clearRequested),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=slot: s.emit())
            actions.addWidget(button)
        actions.addStretch(1)
        actions_widget = QWidget()
        actions_widget.setLayout(actions)

        hint = QLabel("拖入文件或文件夹 · 拖动条目调整顺序")
        hint.setStyleSheet("color: gray; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        layout.addWidget(header)
        layout.addWidget(bar_widget)
        layout.addWidget(self.list, 1)
        layout.addWidget(actions_widget)
        layout.addWidget(hint)

    # ------------------------------------------------------------- playlist
    def refresh(self, items: list[dict], current_index: int, playlists: list[dict], active_id: str) -> None:
        self._items = items
        self._current_index = current_index
        self._updating = True
        self.combo.blockSignals(True)
        self.combo.clear()
        for playlist in playlists:
            self.combo.addItem(playlist["name"], playlist["id"])
        active = self.combo.findData(active_id)
        if active >= 0:
            self.combo.setCurrentIndex(active)
        self.combo.blockSignals(False)
        self._updating = False
        self._rebuild()

    def _rebuild(self) -> None:
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for index, item in enumerate(self._items):
            name = Path(item["path"]).name
            status = item.get("status", "pending")
            seconds = item.get("est_seconds", 0)
            suffix = f"   {fmt_duration(seconds)}" if seconds else ""
            if status == "error":
                suffix += "   [不可读]"
            marker = "▶ " if index == self._current_index else "   "
            entry = QListWidgetItem(f"{marker}{index + 1:02d}  {name}{suffix}")
            entry.setData(Qt.ItemDataRole.UserRole, item["path"])
            entry.setToolTip(item["path"] + (("\n" + item["error"]) if item.get("error") else ""))
            if index == self._current_index:
                entry.setBackground(QColor(80, 120, 175, 90))
            elif status == "done":
                entry.setForeground(QColor(128, 128, 128))
            elif status == "error":
                entry.setForeground(QColor(210, 90, 90))
            self.list.addItem(entry)
        self.list.verticalScrollBar().setValue(scroll)

    def _on_internal_move(self) -> None:
        paths = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
        ]
        self.orderChanged.emit(paths)

    def _on_combo(self, index: int) -> None:
        if self._updating or index < 0:
            return
        self.playlistSwitched.emit(self.combo.itemData(index))

    def _selected_paths(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()
        ]

    # --------------------------------------------------------------- menus
    def _show_menu(self, point) -> None:
        item = self.list.itemAt(point)
        if not item:
            return
        row = self.list.row(item)
        menu = QMenu(self)
        menu.addAction("从这里开始播放", lambda: self.playHere.emit(row))
        menu.addAction("设为下一项播放", lambda: self.playNext.emit(row))
        menu.addSeparator()
        menu.addAction("上移一位", lambda: self._move(row, -1))
        menu.addAction("下移一位", lambda: self._move(row, 1))
        menu.addSeparator()
        menu.addAction(
            "在 Finder 中显示",
            lambda: self.revealRequested.emit(item.data(Qt.ItemDataRole.UserRole)),
        )
        menu.addAction("移除选中项", lambda: self.removePaths.emit(self._selected_paths()))
        menu.exec(self.list.mapToGlobal(point))

    def _move(self, row: int, delta: int) -> None:
        target = max(0, min(self.list.count() - 1, row + delta))
        if target == row:
            return
        taken = self.list.takeItem(row)
        self.list.insertItem(target, taken)
        self.list.setCurrentItem(taken)
        self._on_internal_move()

    # ---------------------------------------------------------- dialogs
    def _new_playlist(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新建播放列表", "名称：")
        if ok and name.strip():
            self.playlistCreated.emit(name.strip())

    def _rename_playlist(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "重命名播放列表", "名称：", text=self.combo.currentText()
        )
        if ok and name.strip():
            self.playlistRenamed.emit(name.strip())

    def _delete_playlist(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "删除播放列表",
            f"确定删除「{self.combo.currentText()}」吗？文件本身不会被删除。",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.playlistDeleted.emit()
