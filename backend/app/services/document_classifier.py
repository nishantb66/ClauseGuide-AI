from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.contract_type_detector import ContractTypeDetector
from app.services.text_cleaner import CleanedPage


@dataclass(slots=True)
class DocumentSectionClassification:
    document_type: str
    title: str
    page_start: int
    page_end: int
    confidence_score: float


@dataclass(slots=True)
class DocumentClassification:
    primary_document_type: str
    secondary_document_types: list[str]
    is_template: bool
    is_executed_agreement: bool
    is_collection_or_handbook: bool
    contains_multiple_document_types: bool
    confidence_score: float
    sections: list[DocumentSectionClassification] = field(default_factory=list)


class DocumentClassifier:
    """Document-level classifier with template and collection awareness."""

    template_patterns = (
        "sample",
        "template",
        "format of",
        "specimen",
        "draft",
        "form of",
        "_____",
        "________",
        "[●]",
    )
    executed_patterns = (
        "signed by",
        "signature",
        "executed on",
        "in witness whereof",
        "authorized signatory",
    )
    collection_patterns = (
        "table of contents",
        "index",
        "collection",
        "handbook",
        "compendium",
        "formats",
        "templates",
    )
    section_heading_re = re.compile(
        r"^\s*(?:\d{1,3}[.)]\s*)?(agreement|deed|lease|license|loan|nda|memorandum|format|template|form)[A-Z0-9 ,/&()\\-]{4,}$",
        re.IGNORECASE,
    )

    def __init__(self, detector: ContractTypeDetector | None = None) -> None:
        self.detector = detector or ContractTypeDetector()

    def classify(self, pages: list[CleanedPage]) -> DocumentClassification:
        full_text = "\n\n".join(page.cleaned_text for page in pages if page.cleaned_text)
        primary = self.detector.detect(full_text)
        page_results = [
            (page.page_number, self.detector.detect(page.cleaned_text))
            for page in pages
            if page.cleaned_text.strip()
        ]

        type_scores: dict[str, float] = {}
        for _, result in page_results:
            if result.contract_type == "unknown":
                continue
            type_scores[result.contract_type] = (
                type_scores.get(result.contract_type, 0.0) + result.confidence_score
            )

        secondary = [
            doc_type
            for doc_type, _ in sorted(type_scores.items(), key=lambda item: item[1], reverse=True)
            if doc_type != primary.contract_type
        ][:4]
        sections = self._classify_sections(pages)
        heading_types = {
            section.document_type for section in sections if section.confidence_score >= 0.35
        }
        contains_multiple = len(
            set(secondary[:2]) | heading_types | {primary.contract_type}
        ) > 1 and (len(sections) >= 2 or len(secondary) >= 2)

        lowered = full_text.lower()
        is_template = any(pattern in lowered for pattern in self.template_patterns)
        is_executed = (
            any(pattern in lowered for pattern in self.executed_patterns) and not is_template
        )
        is_collection = (
            contains_multiple
            or any(pattern in lowered[:5000] for pattern in self.collection_patterns)
            or len(sections) >= 4
        )

        primary_type = (
            "legal_template_collection" if is_collection and is_template else primary.contract_type
        )
        confidence = primary.confidence_score
        if primary_type == "legal_template_collection":
            confidence = max(0.72, min(0.94, confidence + 0.12))
        elif contains_multiple:
            confidence = max(0.45, confidence - 0.12)

        return DocumentClassification(
            primary_document_type=primary_type,
            secondary_document_types=secondary,
            is_template=is_template,
            is_executed_agreement=is_executed,
            is_collection_or_handbook=is_collection,
            contains_multiple_document_types=contains_multiple,
            confidence_score=round(confidence, 3),
            sections=sections[:20],
        )

    def _classify_sections(self, pages: list[CleanedPage]) -> list[DocumentSectionClassification]:
        sections: list[DocumentSectionClassification] = []
        current_title: str | None = None
        current_start: int | None = None
        current_text: list[str] = []

        def flush(end_page: int) -> None:
            nonlocal current_title, current_start, current_text
            if current_title and current_start is not None and current_text:
                result = self.detector.detect("\n".join(current_text))
                if result.contract_type != "unknown" and result.confidence_score >= 0.22:
                    sections.append(
                        DocumentSectionClassification(
                            document_type=result.contract_type,
                            title=current_title[:160],
                            page_start=current_start,
                            page_end=end_page,
                            confidence_score=result.confidence_score,
                        )
                    )
            current_title = None
            current_start = None
            current_text = []

        for page in pages:
            lines = page.cleaned_text.splitlines()
            for line in lines:
                stripped = line.strip()
                if self._looks_like_document_heading(stripped):
                    flush(page.page_number)
                    current_title = stripped
                    current_start = page.page_number
                if current_title:
                    current_text.append(stripped)
            if current_title and len(" ".join(current_text)) > 5000:
                flush(page.page_number)

        if pages:
            flush(pages[-1].page_number)
        return self._merge_adjacent_sections(sections)

    def _looks_like_document_heading(self, text: str) -> bool:
        if len(text) < 8 or len(text) > 140:
            return False
        if self.section_heading_re.match(text):
            return True
        upper_ratio = sum(1 for char in text if char.isupper()) / max(
            1, sum(1 for char in text if char.isalpha())
        )
        return upper_ratio > 0.75 and any(
            word in text.lower() for word in ("agreement", "deed", "lease", "loan", "nda")
        )

    @staticmethod
    def _merge_adjacent_sections(
        sections: list[DocumentSectionClassification],
    ) -> list[DocumentSectionClassification]:
        if not sections:
            return []
        merged = [sections[0]]
        for section in sections[1:]:
            previous = merged[-1]
            if (
                section.document_type == previous.document_type
                and section.page_start <= previous.page_end + 1
            ):
                merged[-1] = DocumentSectionClassification(
                    document_type=previous.document_type,
                    title=previous.title,
                    page_start=previous.page_start,
                    page_end=max(previous.page_end, section.page_end),
                    confidence_score=max(previous.confidence_score, section.confidence_score),
                )
            else:
                merged.append(section)
        return merged
