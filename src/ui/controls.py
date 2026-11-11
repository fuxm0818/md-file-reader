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


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class ControlBar(QWidget):
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
        self._dragging = False

        self.play_button = QPushButton("播放")
        self.play_button.setMinimumWidth(76)
        self.play_button.clicked.connect(lambda _=False: self.playToggled.emit())

        buttons = [
            ("上一项", lambda _=False: self.prevItemClicked.emit()),
            ("-15s", lambda _=False: self.skipRequested.emit(-15.0)),
            ("上一句", lambda _=False: self.prevSentenceClicked.emit()),
            ("下一句", lambda _=False: self.nextSentenceClicked.emit()),
            ("+15s", lambda _=False: self.skipRequested.emit(15.0)),
            ("下一项", lambda _=False: self.nextItemClicked.emit()),
        ]
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(5)
        for text, action in buttons[:3]:
            button = QPushButton(text)
            button.clicked.connect(action)
            row1.addWidget(button)
        row1.addWidget(self.play_button)
        for text, action in buttons[3:]:
            button = QPushButton(text)
            button.clicked.connect(action)
            row1.addWidget(button)
        stop = QPushButton("停止")
        stop.clicked.connect(lambda _=False: self.stopClicked.emit())
        row1.addWidget(stop)
        row1.addStretch(1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setMinimumWidth(220)
        self.slider.sliderPressed.connect(self._on_press)
        self.slider.sliderReleased.connect(self._on_release)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(110)
        self.sentence_label = QLabel("第 0 / 0 句")
        self.sentence_label.setMinimumWidth(120)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(9)
        seek_row.addWidget(self.slider, 1)
        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.sentence_label)

        self.mode_combo = QComboBox()
        for key, label in MODES.items():
            self.mode_combo.addItem(label, key)
        self.mode_combo.currentIndexChanged.connect(
            lambda i: self.modeChanged.emit(self.mode_combo.itemData(i))
        )

        self.rate_combo = QComboBox()
        for rate in range(80, 351, 20):
            self.rate_combo.addItem(f"{rate} 字/分", rate)
        self.rate_combo.currentIndexChanged.connect(
            lambda i: self.rateChanged.emit(self.rate_combo.itemData(i))
        )

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(self.volumeChanged.emit)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        row2.addWidget(QLabel("模式"))
        row2.addWidget(self.mode_combo)
        row2.addWidget(QLabel("语速"))
        row2.addWidget(self.rate_combo)
        row2.addWidget(QLabel("音量"))
        row2.addWidget(self.volume)
        row2.addStretch(1)
        tip = QLabel("进度条刻度和拖动会吸附到句子边界")
        tip.setStyleSheet("color: gray; font-size: 11px;")
        row2.addWidget(tip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(row1)
        layout.addLayout(seek_row)
        layout.addLayout(row2)

    def _on_press(self) -> None:
        self._dragging = True

    def _on_release(self) -> None:
        self._dragging = False
        self.seekRequested.emit(self.slider.value() / 1000.0)

    def update_position(self, current, total, fraction, index, count) -> None:
        if not self._dragging:
            self.slider.setValue(int(fraction * 1000))
            self.time_label.setText(f"{fmt_time(current)} / 约 {fmt_time(total)}")
        else:
            preview = self.slider.value() / 1000.0 * total
            self.time_label.setText(f"{fmt_time(preview)} / 约 {fmt_time(total)}")
        percent = int(fraction * 100)
        self.sentence_label.setText(f"第 {index + 1 if count else 0} / {count} 句 · {percent}%")

    def set_playing(self, playing: bool) -> None:
        self.play_button.setText("暂停" if playing else "播放")

    def sync_settings(self, settings: dict) -> None:
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData(settings.get("mode", "sequence"))
        self.mode_combo.setCurrentIndex(max(0, index))
        self.mode_combo.blockSignals(False)

        self.rate_combo.blockSignals(True)
        rate = int(settings.get("rate", 200))
        index = self.rate_combo.findData(rate)
        if index < 0:
            self.rate_combo.addItem(f"{rate} 字/分", rate)
            index = self.rate_combo.count() - 1
        self.rate_combo.setCurrentIndex(index)
        self.rate_combo.blockSignals(False)

        self.volume.blockSignals(True)
        self.volume.setValue(int(settings.get("volume", 80)))
        self.volume.blockSignals(False)
