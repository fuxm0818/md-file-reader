"""Turn written document prose into copy that is comfortable to hear.

Only a *copy* of each sentence is rewritten before synthesis.
``Document.display_text`` and every ``Sentence`` span stay untouched, so
highlighting, auto-scroll and seek-to-sentence still line up with the text
the user sees. The rules are deliberately conservative: they never invent
content, never reorder clauses except for one provably reversible pattern,
and never alter numbers (saying "15" is already fine for macOS speech).
"""
from __future__ import annotations

import re
from pathlib import Path

# Documents where a light rewrite is safe. Source code, logs, CSV and JSON
# are excluded because changing a token or a unit there changes the meaning.
ORALIZABLE_EXTS = {
    "",
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".pdf",
    ".doc",
    ".docx",
}

MAX_UNIT = 22  # characters per breathing unit

_MARKUP_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"\*\*|__|~~|`"), ""),
]

_SYMBOL_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d+)\s*ms\b"), r"\1毫秒"),
    (re.compile(r"(\d+)\s*s\b"), r"\1秒"),
    (re.compile(r"(\d+)\s*%"), r"百分之\1"),
    (re.compile(r"±"), "正负"),
    (re.compile(r"→|=>"), "，接着"),
    (re.compile(r"&"), "和"),
    (re.compile(r"(?<=\d)\s*~\s*(?=\d)"), "到"),
]

# Ordered, low-ambiguity written -> spoken substitutions.
_WORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"进行(?=[验证读写替处计检合配切转])"), ""),
    (re.compile(r"予以(?=[考虑说明处理])"), ""),
    (re.compile(r"加以(?=[说明区分])"), ""),
    (re.compile(r"此外"), "另外"),
    (re.compile(r"以及"), "还有"),
    (re.compile(r"因此"), "所以"),
    (re.compile(r"然而"), "不过"),
    (re.compile(r"例如"), "比如"),
    (re.compile(r"即可"), "就行"),
    (re.compile(r"并且"), "而且"),
    (re.compile(r"上述"), "上面说的"),
    (re.compile(r"换言之"), "也就是说"),
    (re.compile(r"换算成"), "换成"),
]

# "因为 A，所以 B。" -> "B，这是因为 A。": same facts, conclusion first.
_CAUSE = re.compile(r"因为([^，,。；;？?！!]{2,60})[，,]\s*所以([^。！？?]{2,80})([。！？?])")

_SOFT_SPLIT = re.compile(r"([，,、；;])")


def oralize_enabled(path: str, master_switch: bool) -> bool:
    """Whether the口语优化 rewrite applies to this document."""
    if not master_switch:
        return False
    return Path(path).suffix.lower() in ORALIZABLE_EXTS


def _flip_cause(match: re.Match) -> str:
    return f"{match.group(2)}，这是因为{match.group(1)}{match.group(3)}"


def _shorten(text: str) -> str:
    """Upgrade at most two commas in an over-long sentence to full stops."""
    parts = _SOFT_SPLIT.split(text)
    out: list[str] = []
    carried = 0
    upgrades = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)
            carried += len(part)
            continue
        can_upgrade = (
            part in ("，", ",", "；", ";")
            and carried >= MAX_UNIT
            and upgrades < 2
            and i + 1 < len(parts)
            and bool(parts[i + 1].strip())
        )
        if can_upgrade:
            out.append("。")
            carried = 0
            upgrades += 1
        else:
            out.append(part)
            carried = 0
    return "".join(out)


def oralize(text: str) -> str:
    """Rewrite one sentence into ear-friendly copy. Never returns empty text."""
    if not text or not text.strip():
        return text
    value = text
    for pattern, replacement in _MARKUP_RULES:
        value = pattern.sub(replacement, value)
    for pattern, replacement in _SYMBOL_RULES:
        value = pattern.sub(replacement, value)
    for pattern, replacement in _WORD_RULES:
        value = pattern.sub(replacement, value)
    value = _CAUSE.sub(_flip_cause, value)
    value = _shorten(value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value or text
