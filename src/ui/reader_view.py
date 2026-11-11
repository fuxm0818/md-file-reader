from __future__ import annotations

import bisect

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QMenu, QTextEdit

from . import theme


class ReaderView(QTextEdit):
    """Reflowed text display with sentence-level highlighting and auto scroll.

    Type is HIG Body (17 px) with 1.6 line height: Chinese prose at 14 px with
    single spacing is the main reason a long document feels tiring to read.
    """

    readFromHere = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Reader")
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setPlaceholderText(
            "还没有打开文档。\n把 txt、Markdown、PDF 或 Word 拖进左边的列表，"
            "双击任意一句就能从那里开始读。"
        )
        font = QFont("PingFang SC")
        font.setPixelSize(theme.READER_SIZE)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.document().setDocumentMargin(30)
        self._spans: list[tuple[int, int]] = []
        self._auto_scroll = True
        self._current_index = -1

    def set_document(self, doc) -> None:
        self.setPlainText(doc.display_text)
        self._apply_spacing()
        length = len(doc.display_text)
        # Explicit pixel size: FontSizeAdjustment is relative to the point size,
        # and the document font is defined in pixels, so it doubled 17 px to 34.
        heading_font = QFont(self.document().defaultFont())
        heading_font.setPixelSize(theme.READER_SIZE + 3)
        heading_font.setWeight(QFont.Weight.DemiBold)
        title_fmt = QTextCharFormat()
        title_fmt.setFont(heading_font)
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

    def _apply_spacing(self) -> None:
        """1.65 line height, with empty paragraphs squeezed to a gap.

        Proportional line height stacked with a per-block bottom margin turned
        the blank line between paragraphs into a ~50 px hole. Fixed heights per
        block keep the rhythm predictable: text blocks scale with their own
        font size, blank blocks collapse to a paragraph gap.
        """
        block = self.document().begin()
        while block.isValid():
            fmt = block.blockFormat()
            if not block.text().strip():
                fmt.setLineHeight(9, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
            else:
                it = block.begin()
                size = theme.READER_SIZE
                if not it.atEnd():
                    px = it.fragment().charFormat().font().pixelSize()
                    size = px if px and px > 0 else size
                fmt.setLineHeight(
                    round(size * 1.65), QTextBlockFormat.LineHeightTypes.FixedHeight.value
                )
                fmt.setTopMargin(0)
                fmt.setBottomMargin(4)
            fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
            cursor = QTextCursor(block)
            cursor.setBlockFormat(fmt)
            block = block.next()

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled

    def apply_palette(self, p) -> None:
        """换主题后重刷当前句高亮。

        高亮是写进 ``ExtraSelection`` 的字符格式，不会随样式表变色；不重设的话
        深色模式下会留下浅色高亮块。切主题时不该顺带滚动正文，所以临时关掉
        自动滚动。
        """
        if self._current_index < 0:
            self.update()
            return
        keep = self._auto_scroll
        self._auto_scroll = False
        self.highlight(self._current_index)
        self._auto_scroll = keep
        self.update()

    def highlight(self, index: int) -> None:
        if not self._spans:
            return
        p = theme.palette()
        index = max(0, min(index, len(self._spans) - 1))
        self._current_index = index
        start, end = self._spans[index]
        doc_length = self.document().characterCount() - 1
        start = min(start, doc_length)
        end = min(end, doc_length)

        fmt = QTextCharFormat()
        fmt.setBackground(theme.qcolor(p.highlight))
        fmt.setForeground(theme.qcolor(p.text))

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
