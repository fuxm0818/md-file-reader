from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.parsers import SUPPORTED_EXTS
from . import theme


_NUMBER = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple:
    """让 ``11.md`` 排在 ``2.md`` 后面，而不是前面。

    ``sorted()`` 比的是字符串，所以文件夹里出现 ``1、11、2、21、3`` 这种
    顺序。做法是把路径按连续数字切成若干段，数字段转成 int 再逐段比较。
    每段带一个类型标记：数字段记 0、文本段记 1，这样数字整体排在文字前
    （与 Finder 一致），也避免 ``int`` 和 ``str`` 相比时抛 TypeError。

    比较的粒度是整个路径，但由于同一批文件的前缀相同，实际效果等价于
    逐级目录、再逐级文件名地自然排序。
    """
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in _NUMBER.split(value)
        if part
    )


def collect_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            try:
                for child in path.rglob("*"):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTS:
                        result.append(str(child.resolve()))
            except OSError:
                continue
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            result.append(str(path.resolve()))
    # 统一在收齐之后再排：多选十几个文件时，对话框给的顺序是点击顺序，
    # 用户看到列表里却是乱的。按自然序排一次，目录扫描和批量拖入都受益。
    result.sort(key=natural_key)
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
        self.setObjectName("PlaylistList")
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(False)
        self.setUniformItemSizes(True)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The viewport paints QPalette.Base over the stylesheet background; pick
        # the sidebar colour as the base so the column reads as one surface.
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, theme.qcolor(self.owner.p.sidebar))
        self.setPalette(palette)

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
    """Left column: playlist switcher, the document list, and add actions."""

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
        self.p = theme.palette()
        self.setObjectName("Sidebar")
        # A plain QWidget ignores a stylesheet background unless it is told to
        # paint it, which is why the sidebar first rendered in the window colour.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._current_index = -1
        self._items: list[dict] = []
        self._updating = False

        title = QLabel("播放列表")
        title.setObjectName("SectionTitle")
        self.count_label = QLabel("0 个文档")
        self.count_label.setObjectName("Faint")

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.count_label)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(120)
        self.combo.currentIndexChanged.connect(self._on_combo)

        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("新建 / 重命名 / 删除列表")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("新建列表…", self._new_playlist)
        menu.addAction("重命名列表…", self._rename_playlist)
        menu.addAction("删除当前列表", self._delete_playlist)
        more.setMenu(menu)

        bar = QHBoxLayout()
        bar.setContentsMargins(2, 0, 2, 0)
        bar.setSpacing(6)
        bar.addWidget(self.combo, 1)
        bar.addWidget(more)

        self.list = _DropList(self)
        self.list.itemDoubleClicked.connect(
            lambda item: self.itemActivated.emit(self.list.row(item))
        )
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_menu)

        add = QPushButton("添加文档")
        add.setObjectName("Primary")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.clicked.connect(lambda _=False: self.addFilesRequested.emit())

        folder = QPushButton()
        folder.setObjectName("IconButton")
        theme.set_icon(folder, "folder", self.p.secondary, 17)
        folder.setToolTip("添加整个文件夹")
        folder.setCursor(Qt.CursorShape.PointingHandCursor)
        folder.clicked.connect(lambda _=False: self.addFolderRequested.emit())
        self.folder_button = folder

        clear = QPushButton()
        clear.setObjectName("IconButton")
        theme.set_icon(clear, "document", self.p.tertiary, 17)
        clear.setToolTip("清空当前列表（不删除文件）")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(lambda _=False: self.clearRequested.emit())
        self.clear_button = clear

        actions = QHBoxLayout()
        actions.setContentsMargins(2, 0, 2, 0)
        actions.setSpacing(6)
        actions.addWidget(add, 1)
        actions.addWidget(folder)
        actions.addWidget(clear)

        hint = QLabel("拖入文件 · 拖动条目调整顺序")
        hint.setObjectName("Faint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(9)
        layout.addLayout(header)
        layout.addLayout(bar)
        layout.addWidget(self.list, 1)
        layout.addLayout(actions)
        layout.addWidget(hint)

    # ------------------------------------------------------------- playlist
    def apply_palette(self, p) -> None:
        """主题切换时重设图标与条目前景色。

        条目前景色是逐个写进 ``QListWidgetItem`` 的（不能靠样式表级联），
        换主题只能按当前数据重建一遍。
        """
        self.p = p
        theme.set_icon(self.folder_button, "folder", p.secondary, 17)
        theme.set_icon(self.clear_button, "document", p.tertiary, 17)
        self._rebuild()
        self.update()

    def refresh(self, items: list[dict], current_index: int, playlists: list[dict], active_id: str) -> None:
        self._items = items
        self._current_index = current_index
        self.count_label.setText(f"{len(items)} 个文档")
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
            suffix = f" · {fmt_duration(seconds)}" if seconds else ""
            if status == "error":
                suffix += " · 不可读"
            current = index == self._current_index
            entry = QListWidgetItem(f"{index + 1:02d}   {name}{suffix}")
            entry.setData(Qt.ItemDataRole.UserRole, item["path"])
            entry.setToolTip(
                item["path"] + (("\n" + item["error"]) if item.get("error") else "")
            )
            entry.setSizeHint(QSize(0, 38))
            if current:
                entry.setForeground(QColor(self.p.text))
                font = entry.font()
                font.setBold(True)
                entry.setFont(font)
            elif status == "done":
                entry.setForeground(QColor(self.p.tertiary))
            elif status == "error":
                entry.setForeground(QColor(self.p.danger))
            else:
                entry.setForeground(QColor(self.p.secondary))
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
