"""Small widgets that QSS cannot express on its own.

Qt's stylesheet can colour a checkbox indicator but cannot draw a tick inside
it without an image file. A checked box that is merely a filled square is
ambiguous - it reads the same as an indeterminate one - so the tick is painted
here instead of shipping PNGs.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox

from . import theme

BOX = 16
GAP = 8


class CheckBox(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.p = theme.palette()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hide the built-in indicator; paintEvent draws box, tick and text.
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }")

    def paintEvent(self, event):
        # Drawn from scratch: leaving text to the base class keeps a stray
        # indicator dot between the box and the label.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        top = (self.height() - BOX) / 2
        box = QRectF(0, top, BOX, BOX)
        checked = self.isChecked()
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(self.p.accent))
            painter.drawRoundedRect(box, 4, 4)
            tick = QPainterPath()
            tick.moveTo(box.left() + 3.6, box.top() + 8.4)
            tick.lineTo(box.left() + 6.8, box.top() + 11.4)
            tick.lineTo(box.left() + 12.2, box.top() + 4.9)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QColor(self.p.accent_text),
                    1.8,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(tick)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.qcolor(self.p.tertiary), 1.2))
            painter.drawRoundedRect(box, 4, 4)
        painter.setFont(self.font())
        painter.setPen(
            theme.qcolor(self.p.text if self.isEnabled() else self.p.tertiary)
        )
        text_rect = self.rect().adjusted(BOX + GAP, 0, 0, 0)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )
        painter.end()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(hint.width() + BOX + GAP)
        return hint
