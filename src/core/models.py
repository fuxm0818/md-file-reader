from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Sentence:
    """A speakable unit. start/end are offsets into Document.display_text."""

    index: int
    text: str
    start: int
    end: int
    para: int

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


@dataclass(frozen=True)
class Heading:
    start: int
    end: int
    level: int
    text: str


@dataclass
class Document:
    path: str
    title: str = ""
    display_text: str = ""
    sentences: list[Sentence] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    doc_hash: str = ""

    @classmethod
    def failed(cls, path: str, error: str) -> "Document":
        return cls(path=path, title=Path(path).name, ok=False, error=error)

    @property
    def total_chars(self) -> int:
        return sum(s.char_count for s in self.sentences)
