from __future__ import annotations

import bisect

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit


class ReaderView(QTextEdit):
    """Reflowed text display with sentence-level highlighting and auto scroll."""

    readFromHere = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setPlaceholderText(
            "这里显示文档正文。\n\n双击任意一句，或右键选择「从这里开始朗读」即可跳转。"
        )
        font = QFont("PingFang SC", 14)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self._spans: list[tuple[int, int]] = []
        self._auto_scroll = True

    def set_document(self, doc) -> None:
        self.setPlainText(doc.display_text)
        length = len(doc.display_text)
        title_fmt = QTextCharFormat()
        title_fmt.setFontWeight(QFont.Weight.Bold)
        title_fmt.setProperty(QTextCharFormat.FontSizeAdjustment, 2)
        for heading in doc.headings:
            cursor = QTextCursor(self.document())
            cursor.setPosition(min(heading.start, length))
            cursor.setPosition(
                min(heading.end, length), QTextCursor.MoveMode.KeepAnchor
            )
            cursor.mergeCharFormat(title_fmt)
        self._spans = [(s.start, s.end) for s in doc.sentences]
        self.setExtraSelections([])
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled

    def highlight(self, index: int) -> None:
        if not self._spans:
            return
        index = max(0, min(index, len(self._spans) - 1))
        start, end = self._spans[index]
        doc_length = self.document().characterCount() - 1
        start = min(start, doc_length)
        end = min(end, doc_length)

        base = self.palette().color(QPalette.ColorRole.Base)
        dark = base.lightness() < 128
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#2f5a8f") if dark else QColor("#ffe6a0"))
        fmt.setForeground(QColor("#ffffff") if dark else QColor("#202020"))

        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(max(start, end), QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        self.setExtraSelections([selection])

        if self._auto_scroll:
            view = QTextCursor(self.document())
            view.setPosition(start)
            self.setTextCursor(view)
            self.ensureCursorVisible()

    def _index_at(self, position: int) -> int:
        if not self._spans:
            return 0
        starts = [span[0] for span in self._spans]
        index = bisect.bisect_right(starts, position) - 1
        return max(0, min(index, len(self._spans) - 1))

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            position = self.cursorForPosition(event.position().toPoint()).position()
            self.readFromHere.emit(self._index_at(position))

    def _show_menu(self, point) -> None:
        position = self.cursorForPosition(point).position()
        index = self._index_at(position)
        menu = QMenu(self)
        action = menu.addAction("从这里开始朗读")
        action.triggered.connect(lambda: self.readFromHere.emit(index))
        menu.addSeparator()
        copy_action = menu.addAction("复制选中内容")
        copy_action.triggered.connect(
            lambda: QApplication.clipboard().setText(self.textCursor().selectedText())
        )
        menu.exec(self.mapToGlobal(point))
