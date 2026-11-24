"""Knowledge-base ingestion: turn an approved text document into retrievable chunks, safely and repeatably.

Pure Python (no database, no web framework), so every rule is unit-tested in tests/test_kb_ingest.py.

* Idempotent: a chunk's identity is its content hash, stored in `source` as "upload:<file>#<hash>". Uploading the same
  document again adds nothing; editing one paragraph adds only the changed chunk and removes only the stale one.
* Scoped: stale-chunk removal only ever looks at chunks from the SAME file name inside the SAME permission scope.
* Screened: chunks that look like instructions aimed at the model ("ignore previous instructions") are NOT stored; the
  uploader is told which ones. This is a heuristic first line of defence. Retrieved text must still be treated as data.
* Supported: plain text, Markdown, Word (.docx) and PDF. DOCX is read with the standard library only (a .docx is a zip of XML,
  read with size limits and no external entities). PDF needs the maintained `pypdf` package (in requirements.txt); if it is not
  installed the upload fails with a clear message instead of crashing. Scanned PDFs without selectable text are refused (no OCR).
* File type is decided by the file's CONTENT (magic bytes), not by the name or the browser's MIME type, both of which can lie.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown", ".docx", ".pdf")
TEXT_EXTENSIONS = (".txt", ".md", ".markdown")
MAX_BYTES = 10_000_000          # binary files (PDF/DOCX)
MAX_UNZIPPED = 30_000_000       # a .docx may not expand beyond this (zip-bomb guard)
MAX_PDF_PAGES = 300
MAX_CHARS = 1_000_000
CHUNK_CHARS = 1200
OVERLAP_CHARS = 150
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ \-]")


@dataclass(frozen=True)
class Chunk:
    index: int
    heading: str
    text: str
    digest: str


@dataclass
class Plan:
    add: list
    keep: list
    remove: list      # `source` values of stale chunks to delete


def validate_upload(filename: object, text: object) -> tuple[Optional[str], Optional[str]]:
    """(clean_filename, error). The clean name contains only letters, digits, dot, space, dash and underscore."""
    raw = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_NAME.sub("", raw)[:120].strip(" .")
    if not name or not name.lower().endswith(ALLOWED_EXTENSIONS):
        return None, "Only plain text (.txt), Markdown (.md), Word (.docx) and PDF files are supported."
    if not isinstance(text, str) or not text.strip():
        return None, "The file is empty."
    if len(text) > MAX_CHARS:
        return None, f"The file is too large (limit {MAX_CHARS:,} characters)."
    if "\x00" in text:
        return None, "This does not look like a text file."
    return name, None


class ExtractError(Exception):
    """A file that cannot be turned into text; the message is safe to show to the uploader."""


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ExtractError("This text file is not UTF-8. Save it as UTF-8 and upload it again.")


def _heading_level(style: str) -> int:
    """Word paragraph style -> Markdown heading level (0 = ordinary text). "Heading 2" or "Heading2" -> 2, "Title" -> 1."""
    import re as _re
    m = _re.fullmatch(r"(?i)heading\s*([1-6])", style or "")
    if m:
        return int(m.group(1))
    return 1 if (style or "").lower() == "title" else 0


def _docx_text(data: bytes) -> str:
    import io
    import re as _re
    import zipfile
    from xml.etree import ElementTree as ET
    if not data.startswith(b"PK\x03\x04"):
        raise ExtractError("This is not a valid Word (.docx) file.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtractError("This is not a valid Word (.docx) file.") from None
    infos = zf.infolist()
    if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise ExtractError("This Word file expands to an unreasonable size and was refused.")
    try:
        info = zf.getinfo("word/document.xml")
    except KeyError:
        raise ExtractError("This is not a Word document (word/document.xml is missing).") from None
    if info.file_size > 20_000_000:
        raise ExtractError("This Word document is too large.")
    xml = zf.read(info)
    if b"<!DOCTYPE" in xml[:2000] or b"<!ENTITY" in xml:             # no entity tricks (billion laughs, external files)
        raise ExtractError("This Word document contains unsupported XML and was refused.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise ExtractError("This Word document is damaged and could not be read.") from None
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: list[str] = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == W + "t" and el.text:
                parts.append(el.text)
            elif el.tag == W + "tab":
                parts.append("\t")
            elif el.tag == W + "br":
                parts.append("\n")
        text = "".join(parts).strip()
        if not text:
            lines.append("")
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        val = (style.get(W + "val") if style is not None else "") or ""
        level = _heading_level(val)
        lines.append(("#" * level + " " + text) if level else text)
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise ExtractError("This is not a valid PDF file.")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractError("PDF support is not installed on this server. Ask the administrator to run: pip install pypdf") from None
    import io
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractError("This PDF is password-protected. Remove the password and upload it again.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ExtractError(f"This PDF has too many pages (limit {MAX_PDF_PAGES}).")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ExtractError:
        raise
    except Exception:
        raise ExtractError("This PDF is damaged or unreadable.") from None
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise ExtractError("This PDF has no selectable text (it may be a scan). Scanned documents are not supported.")
    return text


def extract_text(filename: str, data: bytes) -> str:
    """Bytes -> text for any supported file. The extension picks the parser; the CONTENT is verified by that parser."""
    if len(data) > MAX_BYTES and not filename.lower().endswith(TEXT_EXTENSIONS):
        raise ExtractError("This file is too large (limit 10 MB).")
    name = filename.lower()
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if data.startswith((b"%PDF-", b"PK\x03\x04")):
        raise ExtractError("This file is not plain text. Rename it with its real extension (.pdf or .docx).")
    return _decode_text(data)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _sections(text: str) -> list[tuple[str, str]]:
    """Split on Markdown headings, keeping the heading as context for every chunk beneath it."""
    sections, heading, buf = [], "", []
    for line in text.split("\n"):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$", line)
        if m:
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1)[:120], []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))
    return sections


def _pieces(paragraph: str, limit: int, overlap: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    out, start = [], 0
    while start < len(paragraph):
        end = min(len(paragraph), start + limit)
        if end < len(paragraph):                       # prefer to cut at a sentence end, then at a space
            cut = max(paragraph.rfind(". ", start, end), paragraph.rfind(" ", start + limit // 2, end))
            end = cut + 1 if cut > start else end
        out.append(paragraph[start:end].strip())
        if end >= len(paragraph):
            break
        start = max(end - overlap, start + 1)
    return [p for p in out if p]


def chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def chunk_document(text: str, limit: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in _sections(normalize(text)):
        group = ""
        pieces = [p for para in re.split(r"\n\s*\n", body) for p in _pieces(para.strip(), limit, overlap) if p]
        for piece in pieces + [None]:
            if piece is not None and (not group or len(group) + 2 + len(piece) <= limit):
                group = f"{group}\n\n{piece}" if group else piece
                continue
            if group:
                chunks.append(Chunk(len(chunks), heading, group, chunk_hash(f"{heading}\n{group}")))
            group = piece or ""
    return chunks


def source_prefix(filename: str) -> str:
    return f"upload:{filename}#"


def source_for(filename: str, chunk: Chunk) -> str:
    return f"{source_prefix(filename)}{chunk.digest}"


def plan(existing_sources: Iterable[str], chunks: list[Chunk], filename: str) -> Plan:
    """What to do given the chunks already stored for THIS file in THIS scope (callers pass only those)."""
    have = {s for s in existing_sources if s.startswith(source_prefix(filename))}
    wanted = {source_for(filename, c): c for c in chunks}
    return Plan(add=[c for s, c in wanted.items() if s not in have], keep=[s for s in wanted if s in have], remove=sorted(have - set(wanted)))


# --------------------------------------------------------------------------- prompt-injection screen
_INJECTION = {
    "override instructions": re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b[^.\n]{0,30}\b(instructions?|rules?|prompts?|guidelines?)\b", re.I),
    "role reassignment": re.compile(r"\byou\s+are\s+now\s+(a|an|the|no longer)\b", re.I),
    "prompt disclosure": re.compile(r"\b(reveal|show|print|repeat|output|leak)\b[^.\n]{0,40}\b(system\s+prompt|your\s+(prompt|instructions)|api[\s_-]?keys?|passwords?|secrets?)\b", re.I),
    "fake system message": re.compile(r"(^|\n)\s*(system|assistant)\s*:\s*\S|<\|\s*(im_start|im_end|system)\s*\|>|\[/?INST\]", re.I),
    "new instructions": re.compile(r"\b(new|updated)\s+instructions?\s*:", re.I),
}


def screen_chunk(text: str) -> list[str]:
    """Names of the injection patterns this chunk matches (empty = nothing suspicious found)."""
    return [name for name, rx in _INJECTION.items() if rx.search(text)]
