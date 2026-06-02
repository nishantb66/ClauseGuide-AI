from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
from docx import Document as DocxDocument


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str


class DocumentParser:
    """Parses supported contract files into page-wise text."""

    def parse(self, file_path: Path) -> list[ExtractedPage]:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(file_path)
        if suffix == ".docx":
            return self._parse_docx(file_path)
        if suffix == ".txt":
            return self._parse_txt(file_path)
        raise ValueError(f"Unsupported file type: {suffix}")

    def _parse_pdf(self, file_path: Path) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        with fitz.open(file_path) as document:
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text", sort=True)
                pages.append(ExtractedPage(page_number=page_index, text=text or ""))

        non_empty_pages = [p for p in pages if p.text.strip()]
        if not non_empty_pages:
            raise ValueError(
                "No text found in PDF. The document may be scanned; OCR support is planned in Phase 2."
            )
        return pages

    def _parse_docx(self, file_path: Path) -> list[ExtractedPage]:
        doc = DocxDocument(str(file_path))
        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        combined = "\n\n".join(paragraphs)
        return self._split_long_text_into_pages(combined)

    def _parse_txt(self, file_path: Path) -> list[ExtractedPage]:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="latin-1")
        return self._split_long_text_into_pages(text)

    @staticmethod
    def _split_long_text_into_pages(text: str, page_size_chars: int = 3200) -> list[ExtractedPage]:
        if not text.strip():
            return [ExtractedPage(page_number=1, text="")]

        parts: list[ExtractedPage] = []
        start = 0
        page_number = 1
        while start < len(text):
            end = min(start + page_size_chars, len(text))
            chunk = text[start:end]
            parts.append(ExtractedPage(page_number=page_number, text=chunk))
            start = end
            page_number += 1
        return parts
