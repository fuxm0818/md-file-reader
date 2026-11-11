from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.speech import SpeechEngine


class SettingsDialog(QDialog):
    voiceChanged = Signal(str)
    rateChanged = Signal(int)
    volumeChanged = Signal(int)
    autoScrollChanged = Signal(bool)
    skipCodeChanged = Signal(bool)
    autoResumeChanged = Signal(bool)
    clearCacheRequested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(430)
        settings = controller.settings

        self.voice_combo = QComboBox()
        chinese = [v for v in controller.voices if v.is_chinese]
        others = [v for v in controller.voices if not v.is_chinese]
        for voice in chinese:
            self.voice_combo.addItem(voice.label, voice.identifier)
        if chinese and others:
            self.voice_combo.insertSeparator(len(chinese))
        for voice in others:
            self.voice_combo.addItem(voice.label, voice.identifier)
        current = self.voice_combo.findData(settings.get("voice", ""))
        if current >= 0:
            self.voice_combo.setCurrentIndex(current)
        self.voice_combo.currentIndexChanged.connect(self._on_voice)

        self.rate_combo = QComboBox()
        for rate in range(80, 351, 20):
            self.rate_combo.addItem(f"{rate} 字/分", rate)
        index = self.rate_combo.findData(int(settings.get("rate", 200)))
        self.rate_combo.setCurrentIndex(max(0, index))
        self.rate_combo.currentIndexChanged.connect(
            lambda i: self.rateChanged.emit(self.rate_combo.itemData(i))
        )

        self.volume_combo = QComboBox()
        for value in range(0, 101, 10):
            self.volume_combo.addItem(f"{value}%", value)
        index = self.volume_combo.findData(int(settings.get("volume", 80)))
        self.volume_combo.setCurrentIndex(max(0, index))
        self.volume_combo.currentIndexChanged.connect(
            lambda i: self.volumeChanged.emit(self.volume_combo.itemData(i))
        )

        self.auto_scroll = QCheckBox("朗读时自动滚动到当前句")
        self.auto_scroll.setChecked(bool(settings.get("auto_scroll", True)))
        self.auto_scroll.toggled.connect(self.autoScrollChanged.emit)

        self.skip_code = QCheckBox("跳过代码块与图片，不朗读")
        self.skip_code.setChecked(bool(settings.get("skip_code", True)))
        self.skip_code.toggled.connect(self.skipCodeChanged.emit)

        self.auto_resume = QCheckBox("打开时从上次位置继续（回退一句）")
        self.auto_resume.setChecked(bool(settings.get("auto_resume", True)))
        self.auto_resume.toggled.connect(self.autoResumeChanged.emit)

        self.cache_label = QLabel()
        self._update_cache_label()
        clear_button = QPushButton("清理缓存音频")
        clear_button.clicked.connect(lambda _=False: self.clearCacheRequested.emit())
        cache_row = QHBoxLayout()
        cache_row.addWidget(self.cache_label, 1)
        cache_row.addWidget(clear_button)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("朗读音色", self.voice_combo)
        form.addRow("语速", self.rate_combo)
        form.addRow("音量", self.volume_combo)
        form.addRow("阅读", self.auto_scroll)
        form.addRow("内容", self.skip_code)
        form.addRow("断点", self.auto_resume)
        form.addRow("缓存", cache_row)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #d98080; font-size: 12px;")
        if not chinese:
            self.warning.setText(
                "本机没有检测到中文语音。请打开「系统设置 → 辅助功能 → 朗读内容 → 系统声音 → 管理声音」，"
                "下载任一中文（中国大陆）音色后重启本程序。"
            )
        else:
            self.warning.setText(
                f"检测到 {len(chinese)} 个中文音色。切换音色或语速时会自动重新标定语速，"
                "进度条时长随之校准。"
            )

        close_button = QPushButton("关闭")
        close_button.clicked.connect(lambda _=False: self.accept())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.warning)
        layout.addStretch(1)
        layout.addWidget(close_button)

    def _on_voice(self, index: int) -> None:
        identifier = self.voice_combo.itemData(index)
        if identifier:
            self.voiceChanged.emit(identifier)

    def _update_cache_label(self) -> None:
        self.cache_label.setText(f"约 {SpeechEngine.cache_size_mb()} MB / 上限 500 MB")

    def refresh_cache_label(self) -> None:
        self._update_cache_label()

    def refresh_from_settings(self) -> None:
        settings = self.controller.settings
        for combo, key in (
            (self.rate_combo, "rate"),
            (self.volume_combo, "volume"),
        ):
            combo.blockSignals(True)
            index = combo.findData(int(settings.get(key, 200)))
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._update_cache_label()
