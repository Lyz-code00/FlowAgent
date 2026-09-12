import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


class DocumentParseError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedSection:
    text: str
    locator: str


def parse_document(filename: str, data: bytes) -> list[ExtractedSection]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        text = _decode_text(data)
        return _markdown_sections(text)
    if suffix == ".txt":
        text = _decode_text(data)
        return [ExtractedSection(text=text, locator="text")]
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            sections = [
                ExtractedSection(text=page.extract_text() or "", locator=f"page {index}")
                for index, page in enumerate(reader.pages, 1)
            ]
        except Exception as exc:
            raise DocumentParseError("PDF could not be parsed") from exc
        sections = [section for section in sections if section.text.strip()]
        if not sections:
            raise DocumentParseError("PDF does not contain extractable text")
        return sections
    raise DocumentParseError("only Markdown, TXT and PDF files are supported")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
            if text.strip():
                return text
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("text file encoding is not supported or the file is empty")


def _markdown_sections(text: str) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    heading = "document"
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            if "\n".join(buffer).strip():
                sections.append(
                    ExtractedSection(text="\n".join(buffer), locator=heading)
                )
            heading = match.group(1).strip()
            buffer = [line]
        else:
            buffer.append(line)
    if "\n".join(buffer).strip():
        sections.append(ExtractedSection(text="\n".join(buffer), locator=heading))
    return sections
