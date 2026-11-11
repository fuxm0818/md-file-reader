"""Render breathing pauses and light intonation into macOS ``say`` text.

Verified on this machine against exported AIFF audio:
  [[slnc N]]   adds N ms of silence (4.08s -> 5.14s for N=1200)
  [[rate N]]   changes local speed (4.87s -> 5.47s for N=160)
  [[pbas +N]]  shifts pitch (F0 108 -> 210 Hz for N=25)
  [[volm x]]   changes loudness (RMS 4591 -> 2004 for x=0.7)
[[pmod]] / [[emph]] are accepted but have no audible effect on Chinese
voices, so emphasis is built from pauses and speed contrast instead.
"""
from __future__ import annotations

import re

# 0 = off, 1 = light, 2 = standard, 3 = strong (adds pitch variation)
LEVELS: dict[int, dict] = {
    0: {"short": 0, "medium": 0, "long": 0, "tail": 0, "pitch": False},
    1: {"short": 120, "medium": 220, "long": 350, "tail": 220, "pitch": False},
    2: {"short": 220, "medium": 380, "long": 600, "tail": 380, "pitch": False},
    3: {"short": 320, "medium": 520, "long": 850, "tail": 520, "pitch": True},
}

LEVEL_LABELS = {
    0: "关闭（原样连读）",
    1: "轻（少量气口）",
    2: "标准（推荐）",
    3: "强（气口 + 语调起伏）",
}

SHORT_PUNCT = "，,、：:；;（）()"
MEDIUM_PUNCT = "。.！!？?"
_SILENCE = re.compile(r"\[\[slnc\s+(\d+)\]\]")
_COMMAND = re.compile(r"\[\[[^]]*\]\]")


def config(level: int) -> dict:
    return LEVELS.get(max(0, min(3, int(level))), LEVELS[2])


def sanitize(text: str) -> str:
    """Strip embedded speech commands coming from untrusted document text.

    ``say`` interprets ``[[...]]`` even when the text arrives on stdin. Without
    this, a document could inject ``[[slnc 999999]]`` or ``[[rate 400]]``.
    Only the synthesis copy is cleaned; the visible document is untouched.
    """
    return _COMMAND.sub("", text)


def pause_budget(level: int) -> float:
    """Average extra seconds per sentence, used only for the estimated axis."""
    cfg = config(level)
    # Matches a typical sentence: 2 short + 2 medium pauses plus sentence tail.
    return round(
        (2 * cfg["short"] + 2 * cfg["medium"] + cfg["tail"]) / 1000.0, 3
    )


def estimated_pause(rendered: str) -> float:
    """Exact silence inserted into one rendered sentence, in seconds."""
    return round(sum(int(v) for v in _SILENCE.findall(rendered)) / 1000.0, 3)


def _prefix(text: str, rate: int, cfg: dict, para_end: bool, para_start: bool) -> str:
    plain = _COMMAND.sub("", text)
    length = len(plain)
    factor = 1.0
    if length > 40:
        factor = 0.92  # long sentence: give the ear more time
    latin = sum(1 for c in plain if c.isascii() and (c.isalnum() or c in ".%"))
    if length and latin / length > 0.25:
        factor = min(factor, 0.90)  # dense numbers / Latin letters
    parts: list[str] = []
    if factor < 1.0:
        parts.append(f"[[rate {max(80, min(400, int(rate * factor)))}]]")
    if cfg["pitch"]:
        if "？" in plain or "?" in plain:
            parts.append("[[pbas +6]]")
        elif para_end:
            parts.append("[[pbas -4]]")
        elif para_start:
            parts.append("[[pbas +3]]")
    return "".join(parts)


def render(
    text: str,
    level: int,
    rate: int = 200,
    *,
    is_para_end: bool = False,
    is_para_start: bool = False,
) -> str:
    """Return synthesis text with embedded prosody commands."""
    if not text or not text.strip():
        return text
    # Sanitize BEFORE any early return: even with prosody disabled, document
    # text must never be allowed to inject say embedded commands.
    text = sanitize(text)
    cfg = config(level)
    if not cfg["short"] and not cfg["pitch"]:
        return text
    prefix = _prefix(text, rate, cfg, is_para_end, is_para_start)
    chars = list(text)
    out: list[str] = []
    last = len(chars) - 1
    for i, ch in enumerate(chars):
        out.append(ch)
        if i == last:
            continue
        following = chars[i + 1]
        if ch in MEDIUM_PUNCT:
            ms = cfg["medium"]
        elif ch in SHORT_PUNCT:
            ms = cfg["short"]
        else:
            continue
        if following in SHORT_PUNCT or following in MEDIUM_PUNCT:
            continue  # avoid stacking pauses on "……" or "？！"
        if ms:
            out.append(f"[[slnc {ms}]]")
    tail = cfg["long"] if is_para_end else cfg["tail"]
    if tail:
        out.append(f"[[slnc {tail}]]")
    return prefix + "".join(out)
