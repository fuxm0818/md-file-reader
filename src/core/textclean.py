"""Strip symbols that macOS speech reads out loud but a listener does not want.

Measured, not assumed. Each symbol was inserted into the same sentence
(``这一段{sym}前后相连``), synthesised with the same voice at rate 200, and the
duration delta against the symbol-free baseline was recorded. Symbols with
Δ > 0.06 s are spoken by the synthesiser; everything else is silent.

    spoken   /  \\  |  _  >  ^  ~  -  —  %  @  .  *  #  $  =  …  –  +  &  ①
    silent   <  [  ]  {  }  (  )  【 】 《 》 ·  •

So a path like ``/usr/local/bin`` is read as "斜杠 u s r 斜杠 local ..." and a
markdown bullet ``-`` becomes "破折号". This module removes the decorative
layer while keeping semantics: ranges become "到", a lone dash or ellipsis
becomes a comma pause, and a comparison ``>`` becomes "大于".

Only a *copy* of the sentence is cleaned. Display text and sentence spans are
never touched, so highlighting and seek stay aligned.
"""
from __future__ import annotations

import re

# Characters the synthesiser pronounces as words but that carry no meaning in
# running prose. Order matters: structural rules run before this sweep.
_NOISE = "\\|_^*#$@`~"

_LEADING_MARK = re.compile(
    # A list marker needs a following space, otherwise "1." in "1.5 秒" is eaten.
    r"^\s*(?:[-*+•·▪◦‣]+|#{1,6}|[>»]+|={2,}|\[[ xX]?\]|\d+[.)、](?=\s))\s*"
)
_RULE_LINE = re.compile(r"^\s*[-=_*~—－]{3,}\s*$")
_CIRCLED = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
# 3-5 / 3–5 / 3~5 between numbers means "到".
_RANGE = re.compile(r"(?<=\d)\s*(?:-|–|—|~|～|\+)\s*(?=\d)")
# Clause-level dash and ellipsis are pauses, not words.
_PAUSE = re.compile(r"\s*(?:—{1,}|–{1,}|\.{3,}|…+)\s*")
_COMPARE = re.compile(r"(?<=[\d\s])>(?=[\d\s])")
_RATIO = re.compile(r"(?<=\d)\s*/\s*(?=\d)")
# A hyphen inside a compound ("GPT-4", "报告-v2") is read as 破折号: make it a gap.
_HYPHEN = re.compile(r"(?<=[0-9A-Za-z\u4e00-\u9fff])-(?=[0-9A-Za-z\u4e00-\u9fff])")
# Separators become a word gap, not nothing: "txt / Markdown" must stay two words.
_SLASH = re.compile(r"\s*[\\/|]+\s*|\s*-{2,}\s*")
_LONE_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_TIDY = (
    (re.compile(r"[，,]{2,}"), "，"),
    (re.compile(r"[。．]{2,}"), "。"),
    (re.compile(r"、{2,}"), "、"),
    (re.compile(r"[：:]{2,}"), "："),
    (re.compile(r"，\s*(?=[。！？；])"), ""),
    (re.compile(r"^[\s，、。；：!?！？]+"), ""),
    (re.compile(r"[\s，、]+$"), ""),
    (re.compile(r"[ \t]{2,}"), " "),
)


def clean_symbols(text: str) -> str:
    """Return an ear-safe copy of one sentence. Never returns empty text."""
    if not text or not text.strip():
        return text
    value = text
    if _RULE_LINE.match(value):
        return ""
    value = _LEADING_MARK.sub("", value)
    value = _CIRCLED.sub("", value)
    value = _PERCENT.sub(r"\1%", value)  # normalise before the sweep
    value = _RANGE.sub("到", value)
    value = _RATIO.sub("比", value)
    value = _HYPHEN.sub(" ", value)
    value = _PAUSE.sub("，", value)
    value = _COMPARE.sub("大于", value)
    value = _SLASH.sub(" ", value)
    value = _LONE_DOT.sub("", value)
    value = re.sub(rf"[{re.escape(_NOISE)}]", "", value)
    for pattern, replacement in _TIDY:
        value = pattern.sub(replacement, value)
    return value.strip()


def symbol_report(text: str) -> list[str]:
    """Symbols that :func:`clean_symbols` would remove. Used by the UI preview."""
    return sorted({ch for ch in text if ch in _NOISE + "/\\>—–…"})
