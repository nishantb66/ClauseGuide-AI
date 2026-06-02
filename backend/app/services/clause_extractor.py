from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

from app.services.chunker import ChunkRecord
from app.services.embedding_service import EmbeddingService
from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.legal_taxonomy import CLAUSE_DEFINITIONS
from app.services.retriever import cosine_similarity


@dataclass(slots=True)
class ExtractedClauseDraft:
    clause_type: str
    clause_title: str
    clause_text: str
    page_start: int
    page_end: int
    confidence_score: float


class ClauseExtractor:
    """Extracts clause-level entities from legal chunks."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        kb: LegalKnowledgeBase | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.kb = kb or get_legal_kb()

    @cached_property
    def clause_reference_embeddings(self) -> dict[str, list[float]]:
        descriptions = {
            clause_type: " ".join(
                part
                for part in (
                    str(details["description"]),
                    self.kb.cuad_reference_text_for(clause_type),
                )
                if part
            )
            for clause_type, details in CLAUSE_DEFINITIONS.items()
        }
        embeddings = self.embedding_service.embed_texts(list(descriptions.values()))
        return {clause_type: embedding for clause_type, embedding in zip(descriptions, embeddings, strict=False)}

    def extract(self, chunks: list[ChunkRecord]) -> list[ExtractedClauseDraft]:
        if not chunks:
            return []

        extracted: list[ExtractedClauseDraft] = []
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            clause_type, confidence = self._classify_chunk(chunk)
            if clause_type == "other":
                continue

            title = self._resolve_title(clause_type=clause_type, section_title=chunk.section_title)
            extracted.append(
                ExtractedClauseDraft(
                    clause_type=clause_type,
                    clause_title=title,
                    clause_text=chunk.chunk_text,
                    page_start=chunk.page_number,
                    page_end=chunk.page_number,
                    confidence_score=confidence,
                )
            )

        return self._merge_adjacent(extracted)

    def _classify_chunk(self, chunk: ChunkRecord) -> tuple[str, float]:
        text = chunk.chunk_text
        if not text.strip():
            return "other", 0.0

        title = chunk.section_title or ""
        search_text = f"{title}\n{text}" if title else text
        embedding = self.embedding_service.embed_text(search_text)

        best_type = "other"
        best_score = 0.0
        best_keyword_score = 0.0

        for clause_type, definition in CLAUSE_DEFINITIONS.items():
            keywords = self._keywords_for(clause_type, definition["keywords"])
            keyword_score = self._keyword_score(search_text, keywords)
            similarity = cosine_similarity(embedding, self.clause_reference_embeddings[clause_type])
            combined_score = 0.65 * keyword_score + 0.35 * max(0.0, similarity)
            combined_score += self._disambiguation_adjustment(
                clause_type=clause_type,
                text=search_text,
                section_title=title,
            )

            if chunk.clause_type == clause_type:
                combined_score += 0.22

            if title and self._title_matches_keywords(title, keywords):
                combined_score += 0.22

            if combined_score > best_score:
                best_score = combined_score
                best_type = clause_type
                best_keyword_score = keyword_score

        if best_score < 0.26:
            return "other", min(0.4, best_score)

        if best_type in {"penalty", "bond"} and best_keyword_score < 0.3:
            return "other", min(0.42, best_score)

        # Confidence is intentionally conservative for legal text.
        confidence = min(0.98, max(0.35, (best_score * 0.85) + (best_keyword_score * 0.15)))
        return best_type, confidence

    @staticmethod
    def _title_matches_keywords(title: str, keywords: tuple[str, ...] | str) -> bool:
        lowered_title = title.lower()
        if isinstance(keywords, str):
            return keywords.lower() in lowered_title
        return any(keyword.lower() in lowered_title for keyword in keywords)

    def _keywords_for(self, clause_type: str, keywords: tuple[str, ...] | str) -> tuple[str, ...]:
        if isinstance(keywords, str):
            base = [keywords]
        else:
            base = list(keywords)
        for alias in self.kb.aliases_for(clause_type):
            if alias not in base:
                base.append(alias)
        return tuple(base)

    def _keyword_score(self, text: str, keywords: tuple[str, ...] | str) -> float:
        if isinstance(keywords, str):
            keyword_list = (keywords,)
        else:
            keyword_list = keywords

        normalized = text.lower()
        matched_weight = 0.0
        max_weight = 0.0
        for keyword in keyword_list:
            lowered = keyword.lower()
            weight = 1.35 if " " in lowered else 1.0
            max_weight += weight
            if self._contains_phrase(normalized, lowered):
                matched_weight += weight

        if not keyword_list:
            return 0.0

        density = matched_weight / max(1e-9, max_weight)
        return min(1.0, density * 1.8)

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
        return bool(re.search(pattern, text))

    def _disambiguation_adjustment(self, *, clause_type: str, text: str, section_title: str | None) -> float:
        lowered = text.lower()
        lowered_title = (section_title or "").lower()

        if clause_type == "penalty":
            if any(
                marker in lowered
                for marker in (
                    "liquidated damages",
                    "penalty",
                    "forfeit",
                    "forfeiture",
                    "early exit charge",
                )
            ):
                return 0.1
            if any(
                marker in lowered
                for marker in (
                    "compensation committee",
                    "incentive plan",
                    "retirement plan",
                    "salary review",
                )
            ):
                return -0.28

        if clause_type == "bond":
            if "service bond" in lowered or "bond period" in lowered or "minimum service" in lowered:
                return 0.14
            if "posting any bond" in lowered or "surety bond" in lowered or "bonded" in lowered:
                return -0.34
            if "bond" in lowered and "service" not in lowered and "training" not in lowered:
                return -0.2

        if clause_type == "termination":
            if (
                "termination" in lowered_title
                or "discharge of law firm" in lowered
                or "withdrawal of law firm" in lowered
            ):
                return 0.18

        if clause_type == "liability":
            if any(marker in lowered for marker in ("errors and omissions", "errors & omissions", "insurance")):
                return 0.14

        if clause_type == "notice_period" and "notice" not in lowered:
            return -0.3

        if clause_type == "payment":
            if any(
                marker in lowered
                for marker in (
                    "monthly rent",
                    "security deposit",
                    "billing",
                    "hourly rate",
                    "rate schedule",
                    "fee schedule",
                    "schedule of fees",
                    "retainer",
                )
            ):
                return 0.12

        if clause_type == "scope_of_services":
            if "legal services" in lowered_title or "services covered" in lowered:
                return 0.14

        return 0.0

    def _merge_adjacent(self, clauses: list[ExtractedClauseDraft]) -> list[ExtractedClauseDraft]:
        if not clauses:
            return []

        merged: list[ExtractedClauseDraft] = [clauses[0]]

        for clause in clauses[1:]:
            previous = merged[-1]
            should_merge = (
                clause.clause_type == previous.clause_type
                and clause.page_start <= previous.page_end + 1
                and (
                    clause.clause_title == previous.clause_title
                    or clause.clause_title.lower().startswith(clause.clause_type.replace("_", " "))
                )
            )

            if should_merge:
                combined_text = f"{previous.clause_text}\n\n{clause.clause_text}".strip()
                avg_confidence = (previous.confidence_score + clause.confidence_score) / 2.0
                merged[-1] = ExtractedClauseDraft(
                    clause_type=previous.clause_type,
                    clause_title=previous.clause_title,
                    clause_text=combined_text,
                    page_start=previous.page_start,
                    page_end=max(previous.page_end, clause.page_end),
                    confidence_score=avg_confidence,
                )
            else:
                merged.append(clause)

        return merged

    @staticmethod
    def _resolve_title(clause_type: str, section_title: str | None) -> str:
        if section_title and section_title.strip():
            title = section_title.strip()
            # Drop extra numbering noise while preserving semantic heading text.
            title = re.sub(r"^\s*(clause|section|article)\s*\d+(?:\.\d+)*[:.)-]?\s*", "", title, flags=re.I)
            if title:
                return title[:255]

        return f"{clause_type.replace('_', ' ').title()} Clause"
