"""Design tokens, stylesheet and vector icons for the reader UI.

Values follow Apple's Human Interface Guidelines rather than taste: body text
17 px, footnote 13 px, 44 px hit targets, WCAG AA contrast, system blue
``#007AFF`` in light mode and ``#0A84FF`` in dark mode. Both palettes are
defined here so a single switch repaints the whole app.

Icons are drawn with ``QPainter`` instead of shipping image assets: it keeps
the bundle free of PNGs, stays crisp on Retina at any size, and lets every
glyph inherit the current text colour.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


@dataclass(frozen=True)
class Palette:
    dark: bool
    window: str          # window chrome behind everything
    sidebar: str         # navigation column
    content: str         # reading surface
    raised: str          # popovers, cards
    border: str          # hairline separators
    text: str            # primary text
    secondary: str       # secondary text (~60%)
    tertiary: str        # placeholders, disabled
    accent: str          # system blue
    accent_hover: str
    accent_soft: str     # tinted row / selection background
    accent_text: str     # text on accent fill
    control: str         # default control fill
    control_hover: str
    highlight: str       # current-sentence background
    danger: str


LIGHT = Palette(
    dark=False,
    window="#F5F5F7",
    sidebar="#EFEFF2",
    content="#FFFFFF",
    raised="#FFFFFF",
    border="rgba(60, 60, 67, 0.14)",
    text="#1D1D1F",
    secondary="#6E6E73",
    tertiary="#A1A1A6",
    accent="#007AFF",
    accent_hover="#0066D6",
    accent_soft="rgba(0, 122, 255, 0.12)",
    accent_text="#FFFFFF",
    control="#FFFFFF",
    control_hover="#F0F0F3",
    highlight="rgba(0, 122, 255, 0.16)",
    danger="#D70015",
)

DARK = Palette(
    dark=True,
    window="#1E1E1F",
    sidebar="#191919",
    content="#252527",
    raised="#2C2C2E",
    border="rgba(255, 255, 255, 0.10)",
    text="#F2F2F7",
    secondary="#9A9A9F",
    tertiary="#6E6E73",
    accent="#0A84FF",
    accent_hover="#3D9BFF",
    accent_soft="rgba(10, 132, 255, 0.22)",
    accent_text="#FFFFFF",
    control="#2C2C2E",
    control_hover="#3A3A3C",
    highlight="rgba(10, 132, 255, 0.30)",
    danger="#FF453A",
)

FONT_STACK = '"PingFang SC", "Helvetica Neue", "Hiragino Sans GB", sans-serif'
READER_SIZE = 17      # HIG Body
UI_SIZE = 13          # HIG Footnote
SECTION_SIZE = 15     # HIG Subhead
TITLE_SIZE = 20       # HIG Title 3
ROW_HEIGHT = 44       # HIG minimum hit target
ICON_SIZE = 18


def is_dark(app: QGuiApplication | None = None) -> bool:
    app = app or QGuiApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return app.palette().window().color().lightness() < 128


def palette(app: QGuiApplication | None = None) -> Palette:
    return DARK if is_dark(app) else LIGHT


#: 挂在 QApplication 上的标记，保证主题切换只连一次信号。
_HOOK_ATTR = "_docreader_theme_hooked"


def apply(app: QGuiApplication) -> None:
    """把当前外观刷到整个应用，并跟随系统深浅色切换。

    此前 palette 只在启动那一刻算一次：用户在「系统设置 → 外观」里切到深色，
    界面仍是浅色，正文高亮还会和背景撞色。切换时逐个部件重设，自绘部分由
    部件自己的 ``apply_palette()`` 负责（图标颜色、列表前景色、句级高亮都是
    按 palette 生成的，换样式表不会自动跟着变）。
    """
    refresh(app)
    hints = getattr(app, "styleHints", lambda: None)()
    signal = getattr(hints, "colorSchemeChanged", None)
    if signal is not None and not getattr(app, _HOOK_ATTR, False):
        signal.connect(lambda _scheme=None: refresh(app))
        setattr(app, _HOOK_ATTR, True)


def refresh(app: QGuiApplication) -> None:
    """Re-apply the palette without touching signal wiring (tests use this)."""
    p = palette(app)
    app.setStyleSheet(stylesheet(p))
    for widget in app.allWidgets():
        try:
            hook = getattr(widget, "apply_palette", None)
            if callable(hook):
                hook(p)
            else:
                if hasattr(widget, "p"):
                    widget.p = p
                widget.update()
        except RuntimeError:
            # Qt 对象已随父窗口销毁、Python 包装器还在：跳过即可。
            continue


def stylesheet(p: Palette) -> str:
    """One stylesheet for the whole app; widgets opt in via objectName."""
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: {UI_SIZE}px;
    color: {p.text};
    outline: none;
}}
QMainWindow, QDialog {{ background: {p.window}; }}
QToolTip {{
    background: {p.raised}; color: {p.text};
    border: 1px solid {p.border}; border-radius: 6px; padding: 5px 8px;
}}

/* ---------------------------------------------------------- surfaces */
#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
/* 两栏之间的拖拽热区：只有热区，没有装饰。分隔线用 #Sidebar 的右边框，
   这样拖动时线条跟着手指走，停在哪里都是 1px。 */
#MainSplitter::handle {{ background: {p.window}; }}
#Transport {{ background: {p.window}; border-top: 1px solid {p.border}; }}
#Toolbar {{ background: {p.window}; }}
#ReaderCard {{
    background: {p.content};
    border: 1px solid {p.border};
    border-radius: 12px;
}}
#Section {{ background: {p.raised}; border: 1px solid {p.border}; border-radius: 10px; }}

/* ------------------------------------------------------------- text */
#Title {{ font-size: {TITLE_SIZE}px; font-weight: 600; }}
#SectionTitle {{ font-size: {SECTION_SIZE}px; font-weight: 600; }}
#Subtitle, #Hint {{ color: {p.secondary}; font-size: {UI_SIZE - 1}px; }}
#Caption {{ color: {p.secondary}; font-size: {UI_SIZE}px; font-weight: 600; }}
#Faint {{ color: {p.tertiary}; font-size: {UI_SIZE - 1}px; }}
#Time {{
    color: {p.secondary};
    font-family: "SF Mono", "Menlo", monospace;
    font-size: {UI_SIZE}px;
}}
#TimeStrong {{
    color: {p.text};
    font-family: "SF Mono", "Menlo", monospace;
    font-size: {UI_SIZE}px;
}}
#Warning {{ color: {p.danger}; font-size: {UI_SIZE}px; }}

/* --------------------------------------------------------- buttons */
QPushButton {{
    background: {p.control};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 12px;
    min-height: 24px;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.control_hover}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.tertiary}; }}
QPushButton#Primary {{
    background: {p.accent}; color: {p.accent_text};
    border: none; font-weight: 600; padding: 6px 16px;
}}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#IconButton {{
    background: transparent; border: none; border-radius: 8px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    padding: 0;
}}
QPushButton#IconButton:hover {{ background: {p.accent_soft}; }}
QPushButton#IconButton:pressed {{ background: {p.border}; }}
QPushButton#PlayButton {{
    background: {p.accent}; border: none; border-radius: 22px;
    min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    padding: 0;
}}
QPushButton#PlayButton:hover {{ background: {p.accent_hover}; }}
QPushButton#TransportButton {{
    background: transparent; border: none; border-radius: 8px;
    min-width: 36px; max-width: 36px; min-height: 32px; max-height: 32px;
    padding: 0;
}}
QPushButton#TransportButton:hover {{ background: {p.accent_soft}; }}
QToolButton {{
    background: transparent; border: none; border-radius: 7px;
    padding: 4px 8px; color: {p.secondary};
}}
QToolButton:hover {{ background: {p.accent_soft}; color: {p.text}; }}

/* ------------------------------------------------------------ combo */
QComboBox {{
    background: {p.control};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 4px 10px;
    min-height: 24px;
}}
QComboBox:hover {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.raised};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {p.accent_soft};
    selection-color: {p.text};
    outline: none;
}}

/* ------------------------------------------------------------ list */
QListWidget#PlaylistList {{
    background: transparent; border: none; outline: none;
}}
QListWidget#PlaylistList::item {{
    border-radius: 8px;
    padding: 8px 10px;
    margin: 1px 0;
    color: {p.text};
}}
QListWidget#PlaylistList::item:hover {{ background: {p.accent_soft}; }}
QListWidget#PlaylistList::item:selected {{
    background: {p.accent_soft};
    color: {p.text};
}}
QListWidget#VoiceList {{
    background: transparent; border: none; outline: none;
}}
QListWidget#VoiceList::item {{
    border: 1px solid transparent;
    border-radius: 10px;
    margin: 2px 0;
    padding: 8px;
}}
QListWidget#VoiceList::item:hover {{ background: {p.control_hover}; }}
QListWidget#VoiceList::item:selected {{
    background: {p.accent_soft};
    border-color: {p.accent};
}}

/* ---------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: {p.border};
}}
QSlider::sub-page:horizontal {{
    height: 4px; border-radius: 2px; background: {p.accent};
}}
QSlider::handle:horizontal {{
    width: 13px; height: 13px; margin: -5px 0;
    border-radius: 6px; background: {p.content};
    border: 0.5px solid rgba(0, 0, 0, 0.25);
}}
QSlider::handle:horizontal:hover {{ border-color: {p.accent}; }}

/* -------------------------------------------------------- scrollbar */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.tertiary}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {p.border}; border-radius: 4px; min-width: 32px;
}}

/* ------------------------------------------------------- misc chrome */
QSplitter::handle {{ background: transparent; width: 1px; }}
QStatusBar {{
    background: {p.window};
    border-top: 1px solid {p.border};
    color: {p.secondary};
    font-size: {UI_SIZE - 1}px;
}}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: transparent; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {p.accent_soft}; }}
QMenu {{
    background: {p.raised}; border: 1px solid {p.border};
    border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {p.tertiary}; background: {p.control};
}}
QCheckBox::indicator:checked {{
    background: {p.accent}; border-color: {p.accent};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}

QLineEdit {{
    background: {p.control}; border: 1px solid {p.border};
    border-radius: 7px; padding: 5px 9px; min-height: 22px;
}}
QLineEdit:focus {{ border-color: {p.accent}; }}

QTextEdit#Reader {{
    background: transparent; border: none;
    font-size: {READER_SIZE}px;
    color: {p.text};
    selection-background-color: {p.accent_soft};
}}
QTextEdit#Reader[placeholder=true] {{ color: {p.tertiary}; }}
"""


# ------------------------------------------------------------------ icons
_SVG_CACHE: dict[tuple[str, str, int], QIcon] = {}


def qcolor(value: str) -> QColor:
    """Build a QColor from ``#RRGGBB`` or CSS ``rgba(r, g, b, a)``.

    ``QColor("rgba(...)")`` is invalid and silently becomes black, so palette
    entries written in CSS form must go through this parser.
    """
    text = value.strip()
    if text.startswith("rgba") or text.startswith("rgb"):
        inside = text[text.index("(") + 1 : text.rindex(")")]
        parts = [part.strip() for part in inside.split(",")]
        red, green, blue = (int(float(part)) for part in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return QColor(red, green, blue, int(round(alpha * 255)))
    return QColor(text)


def _path(name: str, size: float) -> QPainterPath:
    """Stroke/fill geometry in a 24x24 design box."""
    path = QPainterPath()
    s = 24.0

    def q(x: float, y: float) -> QPointF:
        return QPointF(x, y)

    if name == "play":
        path.moveTo(q(8, 5))
        path.lineTo(q(19, 12))
        path.lineTo(q(8, 19))
        path.closeSubpath()
    elif name == "pause":
        path.addRoundedRect(QRectF(7, 5, 3.6, 14), 1.2, 1.2)
        path.addRoundedRect(QRectF(13.4, 5, 3.6, 14), 1.2, 1.2)
    elif name == "stop":
        path.addRoundedRect(QRectF(7, 7, 10, 10), 2.0, 2.0)
    elif name == "prev-sentence":
        path.moveTo(q(15, 6))
        path.lineTo(q(7, 12))
        path.lineTo(q(15, 18))
        path.closeSubpath()
    elif name == "next-sentence":
        path.moveTo(q(9, 6))
        path.lineTo(q(17, 12))
        path.lineTo(q(9, 18))
        path.closeSubpath()
    elif name == "prev-item":
        path.addRoundedRect(QRectF(5.5, 6, 2.6, 12), 1.0, 1.0)
        path.moveTo(q(18, 6))
        path.lineTo(q(10, 12))
        path.lineTo(q(18, 18))
        path.closeSubpath()
    elif name == "next-item":
        path.moveTo(q(6, 6))
        path.lineTo(q(14, 12))
        path.lineTo(q(6, 18))
        path.closeSubpath()
        path.addRoundedRect(QRectF(15.9, 6, 2.6, 12), 1.0, 1.0)
    elif name == "speaker":
        path.moveTo(q(4, 10))
        path.lineTo(q(7, 10))
        path.lineTo(q(12, 6))
        path.lineTo(q(12, 18))
        path.lineTo(q(7, 14))
        path.lineTo(q(4, 14))
        path.closeSubpath()
        wave = QPainterPath()
        wave.moveTo(q(15, 9))
        wave.cubicTo(q(18, 11), q(18, 13), q(15, 15))
        path.addPath(wave)
    elif name in ("settings", "gear"):
        # Three sliders read as "settings" at 18 px far better than a gear.
        for y, x in ((7.0, 9.5), (12.0, 15.0), (17.0, 11.0)):
            path.moveTo(q(4, y))
            path.lineTo(q(x - 2.0, y))
            path.moveTo(q(x + 2.0, y))
            path.lineTo(q(20, y))
            path.addEllipse(QRectF(x - 2.0, y - 2.0, 4.0, 4.0))
    elif name == "folder":
        path.moveTo(q(3.5, 7))
        path.lineTo(q(9.5, 7))
        path.lineTo(q(11.2, 9.2))
        path.lineTo(q(20.5, 9.2))
        path.lineTo(q(20.5, 18))
        path.lineTo(q(3.5, 18))
        path.closeSubpath()
    elif name == "plus":
        path.moveTo(q(12, 6))
        path.lineTo(q(12, 18))
        path.moveTo(q(6, 12))
        path.lineTo(q(18, 12))
    elif name == "check":
        path.moveTo(q(6, 12.5))
        path.lineTo(q(10.2, 16.5))
        path.lineTo(q(18, 8))
    elif name == "search":
        path.addEllipse(QRectF(5.5, 5.5, 10, 10))
        path.moveTo(q(15.6, 15.6))
        path.lineTo(q(19, 19))
    elif name == "wave":
        for i, h in enumerate((6, 11, 16, 11, 6)):
            x = 4 + i * 4
            path.moveTo(q(x, 12 - h / 2))
            path.lineTo(q(x, 12 + h / 2))
    elif name == "document":
        path.moveTo(q(6, 3.5))
        path.lineTo(q(14, 3.5))
        path.lineTo(q(19, 8.5))
        path.lineTo(q(19, 20.5))
        path.lineTo(q(6, 20.5))
        path.closeSubpath()
        path.moveTo(q(14, 3.5))
        path.lineTo(q(14, 8.5))
        path.lineTo(q(19, 8.5))
    return path


def _render(name: str, color: str, device_size: int) -> QPixmap:
    pixmap = QPixmap(device_size, device_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(device_size / 24.0, device_size / 24.0)  # design box is 24x24
    c = QColor(color)
    filled = (
        "play", "pause", "stop", "prev-sentence", "next-sentence",
        "prev-item", "next-item", "speaker", "check",
    )
    path = _path(name, device_size)
    if name in filled:
        painter.setBrush(c)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        if name in ("speaker", "check"):
            painter.setPen(
                QPen(c, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
    else:
        painter.setPen(
            QPen(c, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                 Qt.PenJoinStyle.RoundJoin)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.end()
    return pixmap


def icon(name: str, color: str, size: int = ICON_SIZE) -> QIcon:
    """Icon supplied at both 1x and 2x.

    A single pixmap labelled with devicePixelRatio(2) is not a 2x icon: Qt
    treats its top-left quarter as the logical image, which is why the
    transport icons first rendered as corner fragments. Two plain pixmaps are
    unambiguous - Qt picks the 2x one on Retina.
    """
    key = (name, color, size)
    cached = _SVG_CACHE.get(key)
    if cached is not None:
        return cached
    result = QIcon()
    result.addPixmap(_render(name, color, size))
    result.addPixmap(_render(name, color, size * 2))
    _SVG_CACHE[key] = result
    return result


def set_icon(button, name: str, color: str, size: int = ICON_SIZE) -> None:
    """Set both the icon and its size; QPushButton otherwise defaults to 16 px."""
    from PySide6.QtCore import QSize

    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))
