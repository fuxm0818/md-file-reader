from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .models import Document, Heading, Sentence

SUPPORTED_EXTS = {
    ".txt", ".text", ".md", ".markdown", ".log", ".csv", ".json",
    ".py", ".js", ".ts", ".java", ".go", ".c", ".h", ".cpp", ".sh",
    ".yaml", ".yml", ".xml", ".ini", ".rst", ".pdf", ".docx",
}

END_PUNCT = set("。！？!?；;…")
SOFT_PUNCT = set("，,、：:")
CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")

RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
RE_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
RE_BARE_URL = re.compile(r"https?://\S+")
RE_INLINE_CODE = re.compile(r"`([^`]*)`")
RE_HTML_TAG = re.compile(r"<[^>]+>")
RE_EMPHASIS = re.compile(r"(\*\*|__|~~|\*|_)")
RE_TABLE_PIPE = re.compile(r"^\s*\|?[-:| ]+\|?\s*$")
RE_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff\u2190-\u21ff\u2b00-\u2bff]"
)


@dataclass
class Block:
    kind: str  # heading | para | code | table
    text: str
    level: int = 0


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def clean_inline(text: str) -> str:
    """Strip markup that would otherwise be read aloud. Order matters."""
    text = RE_HTML_COMMENT.sub(" ", text)
    text = RE_IMAGE.sub(" ", text)
    text = RE_LINK.sub(r"\1", text)
    text = RE_BARE_URL.sub(" ", text)
    text = RE_INLINE_CODE.sub(r"\1", text)
    text = RE_HTML_TAG.sub(" ", text)
    text = RE_EMPHASIS.sub("", text)
    text = RE_EMOJI.sub("", text)
    text = text.replace("|", " ").replace("#", " ").replace(">", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _friendly(text: str) -> str:
    """Text shown in the reader: cleaned, but keeps readable spacing."""
    text = RE_HTML_COMMENT.sub("", text)
    text = RE_IMAGE.sub("", text)
    text = RE_LINK.sub(r"\1", text)
    text = RE_INLINE_CODE.sub(r"\1", text)
    text = RE_HTML_TAG.sub("", text)
    text = RE_EMPHASIS.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif CJK.search(out[-1:]) and CJK.search(line[:1]):
            out += line
        else:
            out += " " + line
    return out


def parse_markdown(raw: str) -> list[Block]:
    blocks: list[Block] = []
    buf: list[str] = []
    in_code = False
    code_buf: list[str] = []

    def flush() -> None:
        if buf:
            joined = _join_lines(buf)
            if joined:
                blocks.append(Block("para", joined))
            buf.clear()

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                blocks.append(Block("code", "\n".join(code_buf)))
                code_buf = []
                in_code = False
            else:
                flush()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if not stripped:
            flush()
            continue
        if RE_TABLE_PIPE.match(stripped):
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            blocks.append(Block("heading", m.group(2).strip(), len(m.group(1))))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            buf.append("  ".join(cells))
            continue
        stripped = re.sub(r"^>\s*", "", stripped)
        stripped = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", stripped)
        buf.append(stripped)
    if in_code and code_buf:
        blocks.append(Block("code", "\n".join(code_buf)))
    flush()
    return blocks


def parse_plain(raw: str) -> list[Block]:
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", raw):
        joined = _join_lines(para.splitlines())
        if joined:
            blocks.append(Block("para", joined))
    return blocks


def parse_pdf(path: str) -> list[Block]:
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError as exc:
            raise RuntimeError("缺少 PDF 解析库 PyMuPDF") from exc

    blocks: list[Block] = []
    total_chars = 0
    with pymupdf.open(path) as pdf:
        for page in pdf:
            height = page.rect.height
            raw_blocks = page.get_text("blocks", sort=True)
            for item in raw_blocks:
                if len(item) < 5:
                    continue
                x0, y0, x1, y1, text = item[:5]
                # Some PDF producers emit CJK compatibility ideographs
                # (e.g. U+2F48 ⽂). NFKC restores standard characters for
                # both display and speech synthesis.
                text = unicodedata.normalize("NFKC", text.strip())
                if not text:
                    continue
                # Header / footer noise: short lines near page edges.
                edge = y0 < 42 or y1 > height - 42
                if edge and len(text) < 30:
                    if re.fullmatch(r"[\d\s\-—第页码/]+", text):
                        continue
                total_chars += len(re.sub(r"\s+", "", text))
                lines = [l for l in text.splitlines() if l.strip()]
                joined = _join_lines(lines)
                if joined:
                    blocks.append(Block("para", joined))
    if total_chars < 20:
        raise ValueError("无文字层（扫描版 PDF），已跳过")
    return blocks


def parse_docx(path: str) -> list[Block]:
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = DocxDocument(path)
    blocks: list[Block] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower()
            m = re.search(r"heading\s*(\d)|标题\s*(\d)", style)
            level = int(m.group(1) or m.group(2)) if m else 0
            blocks.append(Block("heading" if level else "para", text, level))
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                line = "  ".join(c for c in cells if c)
                if line:
                    blocks.append(Block("table", line))
    return blocks


def _split_with_spans(text: str, max_len: int = 90) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in END_PUNCT or ch == "\n":
            end = i + 1
            while end < len(text) and text[end] in END_PUNCT:
                end += 1
            if end > start:
                spans.append((start, end))
            start = end
    if start < len(text):
        spans.append((start, len(text)))

    result: list[tuple[int, int]] = []
    for a, b in spans:
        while text[a:a + 1].isspace() and a < b:
            a += 1
        if a >= b:
            continue
        if b - a <= max_len:
            result.append((a, b))
            continue
        # Long sentence: split at soft punctuation.
        cuts = [i + 1 for i, ch in enumerate(text[a:b], start=a) if ch in SOFT_PUNCT]
        seg_start = a
        for cut in cuts:
            if cut - seg_start >= max_len * 0.6:
                result.append((seg_start, cut))
                seg_start = cut
        if seg_start < b:
            result.append((seg_start, b))
    return result


def _build(blocks: list[Block], path: str, doc_hash: str, skip_code: bool) -> Document:
    doc = Document(path=path, title=Path(path).name, doc_hash=doc_hash)
    parts: list[str] = []
    pos = 0
    sentence_index = 0
    for para_index, block in enumerate(blocks):
        shown = _friendly(block.text)
        if not shown.strip():
            continue
        if block.kind == "code" and not skip_code:
            shown = block.text
        seg_start = pos
        parts.append(shown)
        pos += len(shown)
        if block.kind == "heading":
            doc.headings.append(Heading(seg_start, pos, block.level, shown))
        parts.append("\n\n")
        pos += 2
        if block.kind == "code" and skip_code:
            continue
        for a, b in _split_with_spans(shown):
            spoken = clean_inline(shown[a:b])
            if not spoken or not re.search(r"[\w\u3400-\u9fff]", spoken):
                continue
            doc.sentences.append(
                Sentence(sentence_index, spoken, seg_start + a, seg_start + b, para_index)
            )
            sentence_index += 1
    doc.display_text = "".join(parts).rstrip()
    if not doc.sentences:
        raise ValueError("未提取到可朗读的文字")
    return doc


def parse(path: str, skip_code: bool = True) -> Document:
    p = Path(path)
    try:
        raw_bytes = p.read_bytes()
        doc_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
        ext = p.suffix.lower()
        if ext == ".pdf":
            blocks = parse_pdf(path)
        elif ext == ".docx":
            blocks = parse_docx(path)
        elif ext in (".md", ".markdown"):
            blocks = parse_markdown(_decode(raw_bytes))
        else:
            blocks = parse_plain(_decode(raw_bytes))
        return _build(blocks, path, doc_hash, skip_code)
    except Exception as exc:
        return Document.failed(path, str(exc) or exc.__class__.__name__)
