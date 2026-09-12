from dataclasses import dataclass

from app.rag.parser import ExtractedSection


@dataclass(frozen=True)
class TextChunk:
    content: str
    locator: str
    index: int


def chunk_sections(
    sections: list[ExtractedSection], *, chunk_size: int, overlap: int
) -> list[TextChunk]:
    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    chunks: list[TextChunk] = []
    for section in sections:
        text = section.text.strip()
        start = 0
        while start < len(text):
            hard_end = min(len(text), start + chunk_size)
            end = _natural_boundary(text, start, hard_end)
            content = text[start:end].strip()
            if content:
                chunks.append(
                    TextChunk(
                        content=content,
                        locator=f"{section.locator}, chars {start + 1}-{end}",
                        index=len(chunks),
                    )
                )
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks


def _natural_boundary(text: str, start: int, hard_end: int) -> int:
    if hard_end >= len(text):
        return len(text)
    minimum = start + int((hard_end - start) * 0.6)
    for marker in ("\n\n", "\n", "。", ". ", "；", "; "):
        position = text.rfind(marker, minimum, hard_end)
        if position >= minimum:
            return position + len(marker)
    return hard_end
