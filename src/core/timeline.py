from __future__ import annotations

import bisect

from .models import Document

MIN_SENTENCE = 0.35  # seconds
PAUSE = 0.18  # seconds, punctuation breathing room


class Timeline:
    """Maps a text coordinate (sentence index) onto a virtual time axis."""

    def __init__(
        self, document: Document, sec_per_char: float, pause: float = PAUSE
    ):
        self.document = document
        self.sec_per_char = max(0.05, sec_per_char)
        # ``pause`` includes the prosody layer's breathing pauses so the
        # estimated axis stays close to the real (afinfo-calibrated) one.
        self.pause = max(0.0, float(pause))
        count = len(document.sentences)
        self.estimated = [
            max(MIN_SENTENCE, s.char_count * self.sec_per_char + self.pause)
            for s in document.sentences
        ]
        self.real: list[float | None] = [None] * count
        self._starts: list[float] | None = None
        self._total: float = 0.0

    def duration(self, index: int) -> float:
        if 0 <= index < len(self.estimated):
            value = self.real[index]
            if value and value > 0.05:
                return value
            return self.estimated[index]
        return 0.0

    def _rebuild(self) -> None:
        starts: list[float] = []
        current = 0.0
        for i in range(len(self.estimated)):
            starts.append(current)
            current += self.duration(i)
        self._starts = starts
        self._total = current

    def _ensure(self) -> None:
        if self._starts is None:
            self._rebuild()

    def start_of(self, index: int) -> float:
        self._ensure()
        assert self._starts is not None
        if not self._starts:
            return 0.0
        return self._starts[max(0, min(index, len(self._starts) - 1))]

    def total(self) -> float:
        self._ensure()
        return self._total

    def set_real(self, index: int, seconds: float) -> None:
        if 0 <= index < len(self.real) and seconds > 0.05:
            self.real[index] = round(seconds, 3)
            self._starts = None

    def sentence_at(self, seconds: float) -> int:
        self._ensure()
        assert self._starts is not None
        if not self._starts:
            return 0
        return max(0, bisect.bisect_right(self._starts, max(0.0, seconds)) - 1)

    def fraction_at(self, seconds: float) -> float:
        total = self.total()
        return min(1.0, max(0.0, seconds / total)) if total > 0 else 0.0

    def time_at_fraction(self, fraction: float) -> float:
        return max(0.0, min(1.0, fraction)) * self.total()
