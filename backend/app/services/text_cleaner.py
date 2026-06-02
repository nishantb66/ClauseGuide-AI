from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.services.document_parser import ExtractedPage


@dataclass(slots=True)
class CleanedPage:
    page_number: int
    raw_text: str
    cleaned_text: str


class TextCleaner:
    """Normalizes extracted contract text while preserving useful structure."""

    _whitespace_re = re.compile(r"[ \t]+")
    _blank_lines_re = re.compile(r"\n{3,}")

    def clean_pages(self, pages: list[ExtractedPage]) -> list[CleanedPage]:
        pre_cleaned = [
            CleanedPage(page_number=page.page_number, raw_text=page.text, cleaned_text=self.clean_text(page.text))
            for page in pages
        ]
        return self._remove_repeated_headers_footers(pre_cleaned)

    def clean_text(self, text: str) -> str:
        normalized = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
        lines = []
        for line in normalized.split("\n"):
            line = self._whitespace_re.sub(" ", line).strip()
            if line:
                lines.append(line)
            else:
                lines.append("")

        cleaned = "\n".join(lines)
        cleaned = self._blank_lines_re.sub("\n\n", cleaned)
        return cleaned.strip()

    def _remove_repeated_headers_footers(self, pages: list[CleanedPage]) -> list[CleanedPage]:
        if len(pages) < 3:
            return pages

        top_line_counter: Counter[str] = Counter()
        bottom_line_counter: Counter[str] = Counter()

        page_lines: dict[int, list[str]] = {}
        for page in pages:
            lines = [line for line in page.cleaned_text.split("\n") if line.strip()]
            page_lines[page.page_number] = lines
            if lines:
                top_line_counter[lines[0]] += 1
                bottom_line_counter[lines[-1]] += 1

        repeated_headers = {
            line for line, count in top_line_counter.items() if count >= max(2, int(len(pages) * 0.6))
        }
        repeated_footers = {
            line for line, count in bottom_line_counter.items() if count >= max(2, int(len(pages) * 0.6))
        }

        result: list[CleanedPage] = []
        for page in pages:
            lines = page_lines[page.page_number]
            if lines and lines[0] in repeated_headers:
                lines = lines[1:]
            if lines and lines[-1] in repeated_footers:
                lines = lines[:-1]
            cleaned_text = "\n".join(lines).strip()
            result.append(
                CleanedPage(
                    page_number=page.page_number,
                    raw_text=page.raw_text,
                    cleaned_text=cleaned_text,
                )
            )

        return result
