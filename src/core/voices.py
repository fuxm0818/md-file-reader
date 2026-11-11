"""Human-readable profiles for every voice the app can read with.

macOS system voices are identified by strings such as
``Sandy (中文（中国大陆）)``; ``say -v '?'`` is the source of truth. v1.4 起
应用固定用 ``Tingting`` 朗读，这张表仍用于把当前音色显示成人能读的名字。

The ``pitch_hz`` values are **measured**, not guessed. Every voice synthesised
the same sentence, the waveform was converted to raw mono PCM and the median
fundamental frequency was taken over voiced frames (autocorrelation, 60–400 Hz
search range). Re-run the measurement script if a system update changes a voice.

The Chinese names (桑迪, 婷婷 …) mirror Apple's own naming, with a few
transliterations of our own; they are labels, not official speaker names.
"""
from __future__ import annotations

from dataclasses import dataclass

from .speech import Voice

# name -> (中文名, 性别, 实测基频 Hz, 一句话风格, 推荐权重 越小越靠前)
_PROFILES: dict[str, tuple[str, str, int, str, int]] = {
    "Sandy": ("桑迪", "女声", 249, "播客式播报，字尾收得干净", 10),
    "Shelley": ("雪莉", "女声", 167, "偏暖，句子之间有呼吸", 20),
    "Flo": ("芙洛", "女声", 218, "轻快，适合散文和长文", 30),
    "Eddy": ("艾迪", "男声", 116, "温和克制，男声默认推荐", 15),
    "Reed": ("里德", "男声", 102, "平稳，适合说明书和技术文档", 25),
    "Rocko": ("洛可", "男声", 89, "厚重，语速听着偏慢", 40),
    "Grandma": ("奶奶", "女声", 116, "长辈口吻，慢而亲切", 50),
    "Grandpa": ("爷爷", "男声", 95, "长辈口吻，慢而沉稳", 55),
    "Tingting": ("婷婷", "女声", 245, "经典老音色，机械感最明显", 90),
    "Meijia": ("美佳", "女声", 233, "台湾腔，老音色", 80),
    "Sinji": ("善怡", "女声", 204, "粤语腔，老音色", 85),
}

# Locales we describe. Everything else gets the raw identifier plus locale.
_MAINLAND = ("zh_CN", "zh-Hans", "zh_SG")
_LOCALE_NOTE = {
    "zh_TW": "台湾腔",
    "zh_HK": "香港腔",
}

MODERN = (
    "Sandy", "Eddy", "Shelley", "Reed", "Rocko", "Flo", "Grandma", "Grandpa",
)


def base_name(identifier: str) -> str:
    """``Sandy (中文（中国大陆）)`` -> ``Sandy``."""
    return identifier.split(" (")[0].strip()


def is_modern(voice: Voice) -> bool:
    return base_name(voice.identifier) in MODERN


def tone_bucket(pitch_hz: int) -> str:
    if pitch_hz <= 0:
        return "未测"
    if pitch_hz < 130:
        return "低沉"
    if pitch_hz <= 200:
        return "中性"
    return "清亮"


@dataclass(frozen=True)
class VoiceProfile:
    key: str
    name: str
    gender: str
    pitch_hz: int
    tone: str
    note: str
    modern: bool
    rank: int
    locale_note: str

    @property
    def title(self) -> str:
        return f"{self.name} · {self.gender} · {self.tone}"

    @property
    def subtitle(self) -> str:
        parts = [self.note]
        if self.locale_note:
            parts.append(self.locale_note)
        if not self.modern:
            parts.append("经典音色")
        return "　·　".join(parts)

def profile_of(voice: Voice) -> VoiceProfile:
    key = base_name(voice.identifier)
    name, gender, pitch, note, rank = _PROFILES.get(
        key, (key, "未知", 0, "系统音色", 60)
    )
    locale_note = ""
    if voice.locale not in _MAINLAND and voice.locale in _LOCALE_NOTE:
        locale_note = _LOCALE_NOTE[voice.locale]
    elif voice.locale not in _MAINLAND and voice.is_chinese:
        locale_note = voice.locale
    return VoiceProfile(
        key=key,
        name=name,
        gender=gender,
        pitch_hz=pitch,
        tone=tone_bucket(pitch),
        note=note,
        modern=voice.is_modern,
        rank=rank + (0 if voice.locale in _MAINLAND else 4),
        locale_note=locale_note,
    )


def describe(voice: Voice) -> str:
    """One-line label for tight spaces, e.g. ``晴岚 · 女声 · 清亮``."""
    return profile_of(voice).title


def ordered(
    voices: list[Voice], chinese_only: bool = True, mainland_only: bool = False
) -> list[Voice]:
    """Modern mainland voices first, then the legacy ones."""
    pool = [v for v in voices if v.is_chinese] if chinese_only else list(voices)
    if mainland_only:
        pool = [v for v in pool if v.locale in _MAINLAND]
    return sorted(pool, key=lambda v: (profile_of(v).rank, v.identifier))


def recommended(voices: list[Voice]) -> Voice | None:
    ordered_voices = ordered(voices)
    return ordered_voices[0] if ordered_voices else None
