from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.store import MODES
from . import theme

# 低于这个宽度就把语速和音量收起来。它们是「偶尔调一次」的参数，
# 设置对话框里都有；留在窄窗口里只会把右侧顶住，让左栏拉不宽。
#
# 阈值必须大于「完整布局的最小宽度」(约 790)，否则会出现死锁：宽度要
# 先掉到阈值以下才会收起控件，可是不收控件就永远掉不下去。上限则要留
# 在默认窗口的控制栏宽度（1180 窗口、296 侧栏时约 877）以下，否则一进
# 紧凑模式就再也回不来。进入与退出用两个值（迟滞），防止拖动时闪烁。
COMPACT_ENTER = 810
COMPACT_LEAVE = 858


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ControlBar(QWidget):
    """Transport at the bottom of the window.

    One primary action (play) at 44 px, the sentence steps beside it, and the
    secondary settings pushed to the right of the seek row so the eye lands on
    the time and the play button first.
    """

    playToggled = Signal()
    stopClicked = Signal()
    prevItemClicked = Signal()
    nextItemClicked = Signal()
    prevSentenceClicked = Signal()
    nextSentenceClicked = Signal()
    skipRequested = Signal(float)
    seekRequested = Signal(float)
    rateChanged = Signal(int)
    volumeChanged = Signal(int)
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.p = theme.palette()
        self.setObjectName("Transport")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dragging = False
        self._compact = False
        self._playing = False
        # 主题切换时要按新配色重画所有图标，所以把 (按钮, 图标名, 尺寸) 记下来。
        self._icon_buttons: list[tuple[QPushButton, str, int]] = []

        def icon_button(name, tip, slot, object_name="TransportButton", size=18):
            button = QPushButton()
            button.setObjectName(object_name)
            theme.set_icon(button, name, self.p.text, size)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False: slot())
            self._icon_buttons.append((button, name, size))
            return button

        self.play_button = QPushButton()
        self.play_button.setObjectName("PlayButton")
        theme.set_icon(self.play_button, "play", self.p.accent_text, 20)
        self.play_button.setToolTip("播放 / 暂停（空格）")
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(lambda _=False: self.playToggled.emit())

        prev_item = icon_button("prev-item", "上一项（⌃↑）", self.prevItemClicked.emit)
        next_item = icon_button("next-item", "下一项（⌃↓）", self.nextItemClicked.emit)
        prev_sentence = icon_button(
            "prev-sentence", "上一句", self.prevSentenceClicked.emit, size=20
        )
        next_sentence = icon_button(
            "next-sentence", "下一句", self.nextSentenceClicked.emit, size=20
        )
        stop = icon_button("stop", "停止", self.stopClicked.emit, size=15)

        self.mode_combo = QComboBox()
        for key, label in MODES.items():
            self.mode_combo.addItem(label, key)
        self.mode_combo.setToolTip("播放模式")
        self.mode_combo.currentIndexChanged.connect(
            lambda i: self.modeChanged.emit(self.mode_combo.itemData(i))
        )

        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(6)
        transport.addStretch(1)
        transport.addWidget(prev_item)
        transport.addWidget(prev_sentence)
        transport.addWidget(self.play_button)
        transport.addWidget(next_sentence)
        transport.addWidget(next_item)
        transport.addSpacing(10)
        transport.addWidget(stop)
        transport.addStretch(1)
        # 播放模式原本和进度条挤在一行，把那一行的最小宽度顶到 920 px，
        # 左栏就再也拉不宽了。模式属于「怎么播」，跟播放键放一起更贴切。
        transport.addWidget(self.mode_combo)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setMinimumWidth(130)
        self.slider.sliderPressed.connect(self._on_press)
        self.slider.sliderReleased.connect(self._on_release)

        self.time_label = QLabel("00:00")
        self.time_label.setObjectName("TimeStrong")
        self.total_label = QLabel("/ 00:00")
        self.total_label.setObjectName("Time")
        self.sentence_label = QLabel("第 0 / 0 句")
        self.sentence_label.setObjectName("Hint")

        back = QPushButton("−15s")
        back.setToolTip("后退 15 秒")
        back.setFlat(True)
        back.clicked.connect(lambda _=False: self.skipRequested.emit(-15.0))
        forward = QPushButton("+15s")
        forward.setToolTip("前进 15 秒")
        forward.setFlat(True)
        forward.clicked.connect(lambda _=False: self.skipRequested.emit(15.0))

        self.rate_combo = QComboBox()
        for rate in range(80, 351, 20):
            self.rate_combo.addItem(f"{rate}", rate)
        self.rate_combo.setToolTip("语速，单位：字/分钟")
        self.rate_combo.currentIndexChanged.connect(
            lambda i: self.rateChanged.emit(self.rate_combo.itemData(i))
        )

        self.speaker = QLabel()
        self.speaker.setPixmap(
            theme.icon("speaker", self.p.secondary, 16).pixmap(16, 16)
        )
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(84)
        self.volume.valueChanged.connect(self.volumeChanged.emit)

        self.rate_label = QLabel("语速")

        seek = QHBoxLayout()
        seek.setContentsMargins(0, 0, 0, 0)
        seek.setSpacing(8)
        seek.addWidget(self.time_label)
        seek.addWidget(self.total_label)
        seek.addWidget(self.slider, 1)
        seek.addWidget(self.sentence_label)
        seek.addSpacing(6)
        seek.addWidget(back)
        seek.addWidget(forward)
        seek.addSpacing(10)
        seek.addWidget(self.rate_label)
        seek.addWidget(self.rate_combo)
        seek.addSpacing(8)
        seek.addWidget(self.speaker)
        seek.addWidget(self.volume)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)
        layout.addLayout(transport)
        layout.addLayout(seek)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        if self._compact and width >= COMPACT_LEAVE:
            self._compact = False
        elif not self._compact and width < COMPACT_ENTER:
            self._compact = True
        # 用 isHidden 而不是 isVisible：窗口还没显示时 isVisible 恒为 False，
        # 会误判成「应该隐藏」。isHidden 只看控件自己有没有被显式藏起来。
        for widget in (self.rate_label, self.rate_combo, self.speaker, self.volume):
            if widget.isHidden() != self._compact:
                widget.setVisible(not self._compact)

    def _on_press(self) -> None:
        self._dragging = True

    def _on_release(self) -> None:
        self._dragging = False
        self.seekRequested.emit(self.slider.value() / 1000.0)

    def update_position(self, current, total, fraction, index, count) -> None:
        if not self._dragging:
            self.slider.setValue(int(fraction * 1000))
            shown = current
        else:
            shown = self.slider.value() / 1000.0 * total
        self.time_label.setText(fmt_time(shown))
        self.total_label.setText(f"/ 约 {fmt_time(total)}")
        percent = int(fraction * 100)
        self.sentence_label.setText(
            f"第 {index + 1 if count else 0} / {count} 句 · {percent}%"
        )

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        name = "pause" if playing else "play"
        theme.set_icon(self.play_button, name, self.p.accent_text, 20)
        self.play_button.setToolTip("暂停（空格）" if playing else "播放（空格）")

    def apply_palette(self, p) -> None:
        """换主题时按新配色重画图标（图标是矢量绘制的，颜色烘在 pixmap 里）。"""
        self.p = p
        for button, name, size in self._icon_buttons:
            theme.set_icon(button, name, p.text, size)
        theme.set_icon(
            self.play_button,
            "pause" if self._playing else "play",
            p.accent_text,
            20,
        )
        self.speaker.setPixmap(theme.icon("speaker", p.secondary, 16).pixmap(16, 16))
        self.update()

    def sync_settings(self, settings: dict) -> None:
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData(settings.get("mode", "sequence"))
        self.mode_combo.setCurrentIndex(max(0, index))
        self.mode_combo.blockSignals(False)

        self.rate_combo.blockSignals(True)
        rate = int(settings.get("rate", 200))
        index = self.rate_combo.findData(rate)
        if index < 0:
            self.rate_combo.addItem(f"{rate}", rate)
            index = self.rate_combo.count() - 1
        self.rate_combo.setCurrentIndex(index)
        self.rate_combo.blockSignals(False)

        self.volume.blockSignals(True)
        self.volume.setValue(int(settings.get("volume", 80)))
        self.volume.blockSignals(False)
