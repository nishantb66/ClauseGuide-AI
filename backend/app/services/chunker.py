from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.clause_normalizer import ClauseNormalizer
from app.services.legal_taxonomy import CLAUSE_DEFINITIONS
from app.services.text_cleaner import CleanedPage


@dataclass(slots=True)
class ChunkRecord:
    page_number: int
    chunk_index: int
    chunk_text: str
    token_count: int
    section_title: str | None
    clause_type: str | None
    start_char: int
    end_char: int


class LegalChunker:
    """Clause-aware chunking for contract text."""

    heading_re = re.compile(
        r"^(?:\s*(?:clause|section|article|schedule|annexure|appendix)\s+\d*(?:\.\d+)*[:.)-]?\s*.*|\d{1,3}(?:\.\d+)*[.)]\s+.{4,}|[A-Z][A-Z\s&\-/()]{6,})$",
        re.IGNORECASE,
    )

    clause_patterns: dict[str, tuple[str, ...]] = {
        "scope_of_services": (
            "scope of services",
            "legal services",
            "services covered",
            "representation",
        ),
        "termination": (
            "termination",
            "terminate",
            "discharge",
            "withdraw",
            "expiry",
            "end this agreement",
        ),
        "notice_period": ("notice period", "prior notice", "days notice"),
        "penalty": (
            "penalty",
            "liquidated damages",
            "forfeit",
            "early exit charge",
            "breach cost",
        ),
        "bond": ("bond period", "service bond", "minimum service period", "training cost recovery"),
        "non_compete": ("non-compete", "competitor", "competing business"),
        "confidentiality": ("confidentiality", "confidential", "non-disclosure"),
        "jurisdiction": ("jurisdiction", "governing law", "courts of"),
        "arbitration": ("arbitration", "arbitrator", "dispute resolution"),
        "payment": ("payment", "fees", "invoice", "rent", "billing", "hourly rate", "retainer"),
        "security_deposit": ("security deposit", "deposit refund", "refundable deposit"),
        "lock_in": ("lock-in", "lock in period", "minimum tenure"),
        "rent_escalation": ("rent escalation", "rent increase", "increase in rent"),
        "maintenance": ("maintenance", "repairs", "utilities", "electricity", "water charges"),
        "use_restrictions": ("use of premises", "sublet", "assignment", "alterations"),
    }

    def __init__(self, target_tokens: int = 700, overlap_tokens: int = 120) -> None:
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.normalizer = ClauseNormalizer()

    def chunk_pages(self, pages: list[CleanedPage]) -> list[ChunkRecord]:
        output: list[ChunkRecord] = []
        chunk_counter = 0

        for page in pages:
            if not page.cleaned_text.strip():
                continue

            sections = self._split_sections(page.cleaned_text)
            for section_title, section_text, section_start in sections:
                for chunk_text, start_char, end_char in self._window_chunk(
                    section_text, section_start
                ):
                    token_count = self._token_count(chunk_text)
                    output.append(
                        ChunkRecord(
                            page_number=page.page_number,
                            chunk_index=chunk_counter,
                            chunk_text=chunk_text,
                            token_count=token_count,
                            section_title=section_title,
                            clause_type=self._infer_clause_type(chunk_text),
                            start_char=start_char,
                            end_char=end_char,
                        )
                    )
                    chunk_counter += 1

        return output

    def _split_sections(self, page_text: str) -> list[tuple[str | None, str, int]]:
        page_text = self._normalize_inline_headings(page_text)
        lines = page_text.split("\n")
        sections: list[tuple[str | None, str, int]] = []
        buffer: list[str] = []
        current_title: str | None = None
        char_cursor = 0
        section_start = 0

        for line in lines:
            stripped = line.strip()
            is_heading = bool(stripped and self.heading_re.match(stripped))
            if is_heading and buffer:
                section_text = "\n".join(buffer).strip()
                if section_text:
                    sections.append((current_title, section_text, section_start))
                buffer = [line]
                current_title = stripped
                section_start = char_cursor
            else:
                if is_heading and not buffer:
                    current_title = stripped
                    section_start = char_cursor
                buffer.append(line)
            char_cursor += len(line) + 1

        if buffer:
            section_text = "\n".join(buffer).strip()
            if section_text:
                sections.append((current_title, section_text, section_start))

        return sections

    @staticmethod
    def _normalize_inline_headings(text: str) -> str:
        # Many PDFs flatten numbered legal headings into paragraphs.
        return re.sub(
            r"\s+((?:\d{1,3}(?:\.\d+)*[.)]|(?:SCHEDULE|ANNEXURE|APPENDIX)\s+\w*)\s+[A-Z][A-Z\s&\-/()]{4,}\.?)",
            r"\n\1\n",
            text,
        )

    def _window_chunk(self, text: str, page_offset: int) -> list[tuple[str, int, int]]:
        words = text.split()
        if not words:
            return []

        if len(words) <= self.target_tokens:
            return [(text, page_offset, page_offset + len(text))]

        chunks: list[tuple[str, int, int]] = []
        start_word = 0

        while start_word < len(words):
            end_word = min(start_word + self.target_tokens, len(words))
            chunk_words = words[start_word:end_word]
            chunk_text = " ".join(chunk_words).strip()

            start_char = page_offset + self._char_offset_for_word_index(words, start_word)
            end_char = page_offset + self._char_offset_for_word_index(words, end_word)
            chunks.append((chunk_text, start_char, end_char))

            if end_word == len(words):
                break
            start_word = max(0, end_word - self.overlap_tokens)

        return chunks

    @staticmethod
    def _char_offset_for_word_index(words: list[str], word_index: int) -> int:
        if word_index <= 0:
            return 0
        return sum(len(word) + 1 for word in words[:word_index])

    @staticmethod
    def _token_count(text: str) -> int:
        return len(text.split())

    def _infer_clause_type(self, text: str) -> str | None:
        for clause_type in CLAUSE_DEFINITIONS:
            signal = self.normalizer.signal_for(clause_type, text)
            if signal.exists:
                return clause_type
        return None
