from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.prosody import LEVEL_LABELS
from ..core.speech import CACHE_LIMIT_MB, SpeechEngine
from ..core.voices import describe, profile_of
from . import theme
from .widgets import CheckBox


def _section(title: str, rows: list[QWidget | QHBoxLayout]) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Section")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("Caption")  # 颜色与字重交给 QSS，跟主题一起变
    layout.addWidget(label)
    for row in rows:
        if isinstance(row, QHBoxLayout):
            layout.addLayout(row)
        else:
            layout.addWidget(row)
    return frame


class SettingsDialog(QDialog):
    voiceChanged = Signal(str)
    rateChanged = Signal(int)
    volumeChanged = Signal(int)
    autoScrollChanged = Signal(bool)
    skipCodeChanged = Signal(bool)
    autoResumeChanged = Signal(bool)
    clearCacheRequested = Signal()
    previewRequested = Signal()
    oralizeChanged = Signal(bool)
    symbolChanged = Signal(bool)
    prosodyChanged = Signal(int)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.p = theme.palette()
        settings = controller.settings
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.stylesheet(self.p))

        title = QLabel("偏好设置")
        title.setObjectName("Title")

        # ---------------------------------------------------------- 音色
        self.voice_name = QLabel()
        self.voice_name.setStyleSheet(
            f"font-size: {theme.SECTION_SIZE}px; font-weight: 600;"
        )
        self.voice_detail = QLabel()
        self.voice_detail.setObjectName("Hint")
        self.voice_detail.setWordWrap(True)
        self._refresh_voice_text()

        preview = QPushButton("试听")
        preview.setToolTip("用当前音色与节奏读一小段，不打断正在播放的文档")
        preview.clicked.connect(lambda _=False: self.previewRequested.emit())

        voice_text = QVBoxLayout()
        voice_text.setSpacing(2)
        voice_text.addWidget(self.voice_name)
        voice_text.addWidget(self.voice_detail)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(8)
        voice_row.addLayout(voice_text, 1)
        voice_row.addWidget(preview)

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

        self.prosody_combo = QComboBox()
        self.prosody_combo.setToolTip(
            "停顿与语调强度。神经网络语音自带韵律，这一项只对系统语音生效。"
        )
        for level in (0, 1, 2, 3):
            self.prosody_combo.addItem(LEVEL_LABELS[level], level)
        prosody_index = self.prosody_combo.findData(
            max(0, min(3, int(settings.get("prosody_level", 2))))
        )
        self.prosody_combo.setCurrentIndex(max(0, prosody_index))
        self.prosody_combo.currentIndexChanged.connect(
            lambda i: self.prosodyChanged.emit(self.prosody_combo.itemData(i))
        )

        rate_row = QHBoxLayout()
        rate_row.setSpacing(8)
        rate_row.addWidget(QLabel("语速"))
        rate_row.addWidget(self.rate_combo)
        rate_row.addSpacing(12)
        rate_row.addWidget(QLabel("音量"))
        rate_row.addWidget(self.volume_combo)
        rate_row.addSpacing(12)
        rate_row.addWidget(QLabel("节奏"))
        rate_row.addWidget(self.prosody_combo)
        rate_row.addStretch(1)

        # ---------------------------------------------------------- 文本
        self.oralize = CheckBox("把书面长句改写成口语短句")
        self.oralize.setToolTip("只改写送去合成的文本，正文显示与句子高亮不受影响")
        self.oralize.setChecked(bool(settings.get("oralize", True)))
        self.oralize.toggled.connect(self.oralizeChanged.emit)

        self.symbols = CheckBox("跳过斜杠、破折号、星号这类符号，不读出来")
        self.symbols.setToolTip(
            "实测：/ \\ | _ > ^ ~ - — % @ . * # $ = … + & 会被念成“斜杠”“破折号”等"
        )
        self.symbols.setChecked(bool(settings.get("clean_symbols", True)))
        self.symbols.toggled.connect(self.symbolChanged.emit)

        # ---------------------------------------------------------- 阅读
        self.auto_scroll = CheckBox("朗读时自动滚动到当前句")
        self.auto_scroll.setChecked(bool(settings.get("auto_scroll", True)))
        self.auto_scroll.toggled.connect(self.autoScrollChanged.emit)

        self.auto_resume = CheckBox("打开时从上次位置继续（回退一句）")
        self.auto_resume.setChecked(bool(settings.get("auto_resume", True)))
        self.auto_resume.toggled.connect(self.autoResumeChanged.emit)

        self.skip_code = CheckBox("跳过代码块与图片，不朗读")
        self.skip_code.setChecked(bool(settings.get("skip_code", True)))
        self.skip_code.toggled.connect(self.skipCodeChanged.emit)

        # ---------------------------------------------------------- 缓存
        self.cache_label = QLabel()
        self.cache_label.setObjectName("Hint")
        self._update_cache_label()
        clear_button = QPushButton("清理缓存音频")
        clear_button.clicked.connect(lambda _=False: self.clearCacheRequested.emit())
        cache_row = QHBoxLayout()
        cache_row.setSpacing(8)
        cache_row.addWidget(self.cache_label, 1)
        cache_row.addWidget(clear_button)

        self.warning = QLabel()
        self.warning.setObjectName("Hint")
        self.warning.setWordWrap(True)
        chinese = [v for v in controller.voices if v.is_chinese]
        if not chinese:
            self.warning.setObjectName("Warning")
            self.warning.setText(
                "本机没有检测到中文语音。请打开「系统设置 → 辅助功能 → 朗读内容 → "
                "系统声音 → 管理声音」，下载任一中文（中国大陆）音色后重启本程序。"
            )
        else:
            self.warning.setText(
                f"检测到 {len(chinese)} 个中文音色。切换音色或语速后会重新标定语速，"
                "进度条和剩余时间随之更新。"
            )

        close_button = QPushButton("关闭")
        close_button.clicked.connect(lambda _=False: self.accept())
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(_section("朗读", [voice_row, rate_row]))
        layout.addWidget(_section("文本处理", [self.oralize, self.symbols]))
        layout.addWidget(
            _section("阅读行为", [self.auto_scroll, self.auto_resume, self.skip_code])
        )
        layout.addWidget(_section("存储", [cache_row]))
        layout.addWidget(self.warning)
        layout.addStretch(1)
        layout.addLayout(footer)

    def _refresh_voice_text(self) -> None:
        voice = self.controller.voice
        if not voice:
            self.voice_name.setText("没有可用音色")
            self.voice_detail.setText("请在系统设置中下载中文音色")
            return
        profile = profile_of(voice)
        self.voice_name.setText(describe(voice))
        self.voice_detail.setText(profile.subtitle)

    def refresh_voice(self) -> None:
        self._refresh_voice_text()

    def _update_cache_label(self) -> None:
        limit = int(
            self.controller.settings.get("cache_limit_mb", CACHE_LIMIT_MB)
        )
        self.cache_label.setText(
            f"缓存音频约 {SpeechEngine.cache_size_mb()} MB，超过 {limit} MB 会自动清理最旧的"
        )

    def refresh_cache_label(self) -> None:
        self._update_cache_label()

    def apply_palette(self, p) -> None:
        """对话框自己带着一份样式表，主题切换时要重新下发。"""
        self.p = p
        self.setStyleSheet(theme.stylesheet(p))
        self.update()

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
        for box, key in (
            (self.oralize, "oralize"),
            (self.symbols, "clean_symbols"),
            (self.auto_scroll, "auto_scroll"),
            (self.auto_resume, "auto_resume"),
            (self.skip_code, "skip_code"),
        ):
            box.blockSignals(True)
            box.setChecked(bool(settings.get(key, True)))
            box.blockSignals(False)
        self.prosody_combo.blockSignals(True)
        level = max(0, min(3, int(settings.get("prosody_level", 2))))
        index = self.prosody_combo.findData(level)
        if index >= 0:
            self.prosody_combo.setCurrentIndex(index)
        self.prosody_combo.blockSignals(False)
        self._refresh_voice_text()
        self._update_cache_label()
