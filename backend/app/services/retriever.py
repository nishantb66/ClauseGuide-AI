from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.document import DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.reranker import ChunkReranker


@dataclass(slots=True)
class RetrievalItem:
    chunk_id: int
    page_number: int
    chunk_text: str
    clause_type: str | None
    section_title: str | None
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    merged_score: float = 0.0
    rerank_score: float = 0.0
    score: float = 0.0

    def copy_with(
        self,
        *,
        semantic_score: float | None = None,
        keyword_score: float | None = None,
        merged_score: float | None = None,
        rerank_score: float | None = None,
        score: float | None = None,
    ) -> "RetrievalItem":
        return RetrievalItem(
            chunk_id=self.chunk_id,
            page_number=self.page_number,
            chunk_text=self.chunk_text,
            clause_type=self.clause_type,
            section_title=self.section_title,
            semantic_score=self.semantic_score if semantic_score is None else semantic_score,
            keyword_score=self.keyword_score if keyword_score is None else keyword_score,
            merged_score=self.merged_score if merged_score is None else merged_score,
            rerank_score=self.rerank_score if rerank_score is None else rerank_score,
            score=self.score if score is None else score,
        )


@dataclass(slots=True)
class RetrievalResult:
    items: list[RetrievalItem]
    retrieval_score: float
    reranker_score: float
    intent_coverage_score: float
    required_clause_types: list[str]
    reranker_model_used: str


class HybridRetriever:
    """Hybrid retrieval with lexical BM25, semantic vectors, and clause-aware reranking."""

    token_re: ClassVar[re.Pattern[str]] = re.compile(r"\w+")
    stopwords: ClassVar[set[str]] = {
        "the",
        "and",
        "for",
        "this",
        "that",
        "with",
        "from",
        "into",
        "under",
        "about",
        "there",
        "what",
        "when",
        "which",
        "your",
        "their",
        "have",
        "will",
        "would",
        "could",
        "should",
        "agreement",
        "contract",
        "clause",
    }

    def __init__(self, embedding_service: EmbeddingService, reranker: ChunkReranker | None = None) -> None:
        self.embedding_service = embedding_service
        self.reranker = reranker or ChunkReranker()
        self.settings = get_settings()

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        query: str,
        required_clause_types: list[str] | None = None,
        top_k: int = 6,
        semantic_pool: int = 20,
        keyword_pool: int = 20,
    ) -> RetrievalResult:
        del semantic_pool, keyword_pool  # candidate generation is unified now

        required_clause_types = required_clause_types or []
        rows = await session.execute(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
        all_chunks = rows.scalars().all()
        if not all_chunks:
            return RetrievalResult(
                items=[],
                retrieval_score=0.0,
                reranker_score=0.0,
                intent_coverage_score=0.0,
                required_clause_types=required_clause_types,
                reranker_model_used="none",
            )

        preferred_chunks = all_chunks
        if required_clause_types:
            filtered = [chunk for chunk in all_chunks if chunk.clause_type in required_clause_types]
            if len(filtered) >= max(4, top_k):
                preferred_chunks = filtered

        query_tokens = self._tokenize(query)
        chunk_tokens = [self._tokenize(chunk.chunk_text) for chunk in preferred_chunks]
        query_embedding = self.embedding_service.embed_text(query)

        doc_freq: Counter[str] = Counter()
        for tokens in chunk_tokens:
            doc_freq.update(set(tokens))

        avg_len = sum(len(tokens) for tokens in chunk_tokens) / max(1, len(chunk_tokens))
        bm25_raw: list[float] = []
        semantic_raw: list[float] = []
        keyword_raw: list[float] = []
        items: list[RetrievalItem] = []

        for chunk, tokens in zip(preferred_chunks, chunk_tokens, strict=False):
            semantic_score = max(0.0, cosine_similarity(query_embedding, chunk.embedding))
            keyword_score = self._keyword_overlap(query_tokens, tokens)
            keyword_score += self._phrase_alignment_score(
                query=query,
                chunk_text=chunk.chunk_text,
                section_title=chunk.section_title,
            )
            keyword_score = min(1.0, keyword_score)

            bm25 = self._bm25_score(
                query_tokens=query_tokens,
                chunk_tokens=tokens,
                doc_freq=doc_freq,
                corpus_size=len(preferred_chunks),
                avg_doc_len=avg_len,
            )

            items.append(
                RetrievalItem(
                    chunk_id=chunk.id,
                    page_number=chunk.page_number,
                    chunk_text=chunk.chunk_text,
                    clause_type=chunk.clause_type,
                    section_title=chunk.section_title,
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    score=0.0,
                )
            )
            semantic_raw.append(semantic_score)
            keyword_raw.append(keyword_score)
            bm25_raw.append(bm25)

        bm25_norm = self._normalize_scores(bm25_raw)
        semantic_norm = self._normalize_scores(semantic_raw)
        keyword_norm = self._normalize_scores(keyword_raw)

        merged_items: list[RetrievalItem] = []
        for index, item in enumerate(items):
            clause_boost = 0.12 if required_clause_types and item.clause_type in required_clause_types else 0.0
            title_boost = 0.06 if self._title_aligned(query_tokens, item.section_title) else 0.0
            merged_score = min(
                1.0,
                (0.42 * semantic_norm[index])
                + (0.36 * bm25_norm[index])
                + (0.16 * keyword_norm[index])
                + clause_boost
                + title_boost,
            )
            merged_items.append(item.copy_with(merged_score=merged_score, score=merged_score))

        merged_items.sort(key=lambda row: row.merged_score, reverse=True)
        preselected = merged_items[: max(16, top_k * 3)]

        reranked, rerank_diag = self.reranker.rerank(
            query=query,
            items=preselected,
            required_clause_types=required_clause_types,
            top_k=max(10, top_k * 2),
        )

        final_items = self._diversify(reranked, top_k=top_k)
        retrieval_score = sum(item.score for item in final_items) / max(1, len(final_items)) if final_items else 0.0

        if required_clause_types and final_items:
            hits = sum(1 for item in final_items if item.clause_type in required_clause_types)
            intent_coverage_score = hits / len(final_items)
        else:
            intent_coverage_score = 1.0 if final_items else 0.0

        return RetrievalResult(
            items=final_items,
            retrieval_score=max(0.0, min(1.0, retrieval_score)),
            reranker_score=max(0.0, min(1.0, rerank_diag.avg_rerank_score)),
            intent_coverage_score=max(0.0, min(1.0, intent_coverage_score)),
            required_clause_types=required_clause_types,
            reranker_model_used=rerank_diag.model_used,
        )

    def _tokenize(self, text: str) -> list[str]:
        return [
            token.lower()
            for token in self.token_re.findall(text)
            if len(token) > 2 and token.lower() not in self.stopwords
        ]

    @staticmethod
    def _normalize_scores(scores: list[float]) -> list[float]:
        if not scores:
            return []
        max_score = max(scores)
        min_score = min(scores)
        if max_score <= min_score:
            return [0.0 if max_score <= 0 else 1.0 for _ in scores]
        return [(score - min_score) / (max_score - min_score) for score in scores]

    @staticmethod
    def _keyword_overlap(query_tokens: list[str], chunk_tokens: list[str]) -> float:
        if not query_tokens or not chunk_tokens:
            return 0.0
        query_set = set(query_tokens)
        chunk_set = set(chunk_tokens)
        overlap = len(query_set & chunk_set)
        return overlap / max(1, len(query_set))

    def _phrase_alignment_score(self, *, query: str, chunk_text: str, section_title: str | None) -> float:
        score = 0.0
        lowered_chunk = chunk_text.lower()
        lowered_title = (section_title or "").lower()
        query_ngrams = self._query_ngrams(query)

        for ngram in query_ngrams:
            if ngram in lowered_title:
                score += 0.22
            elif ngram in lowered_chunk:
                score += 0.08

        return min(0.4, score)

    def _query_ngrams(self, query: str) -> list[str]:
        tokens = self._tokenize(query)
        if len(tokens) < 2:
            return tokens
        ngrams: list[str] = []
        for index in range(len(tokens) - 1):
            ngrams.append(f"{tokens[index]} {tokens[index + 1]}")
        return ngrams[:8]

    def _bm25_score(
        self,
        *,
        query_tokens: list[str],
        chunk_tokens: list[str],
        doc_freq: Counter[str],
        corpus_size: int,
        avg_doc_len: float,
    ) -> float:
        if not query_tokens or not chunk_tokens or corpus_size == 0:
            return 0.0

        k1 = self.settings.bm25_k1
        b = self.settings.bm25_b

        token_counts = Counter(chunk_tokens)
        doc_len = len(chunk_tokens)
        score = 0.0

        for token in query_tokens:
            df = doc_freq.get(token, 0)
            if df == 0:
                continue

            idf = math.log(1.0 + ((corpus_size - df + 0.5) / (df + 0.5)))
            tf = float(token_counts.get(token, 0))
            if tf == 0:
                continue

            denom = tf + k1 * (1.0 - b + b * (doc_len / max(1.0, avg_doc_len)))
            score += idf * ((tf * (k1 + 1.0)) / max(1e-9, denom))

        return max(0.0, score)

    @staticmethod
    def _title_aligned(query_tokens: list[str], section_title: str | None) -> bool:
        if not section_title:
            return False
        title_tokens = {token.lower() for token in re.findall(r"\w+", section_title) if len(token) > 2}
        return bool(set(query_tokens) & title_tokens)

    @staticmethod
    def _diversify(items: list[RetrievalItem], *, top_k: int) -> list[RetrievalItem]:
        if len(items) <= top_k:
            return items

        selected: list[RetrievalItem] = []
        per_page: dict[int, int] = {}

        for item in items:
            if len(selected) >= top_k:
                break
            page_hits = per_page.get(item.page_number, 0)
            if page_hits >= 2:
                continue
            selected.append(item)
            per_page[item.page_number] = page_hits + 1

        if len(selected) < top_k:
            seen_ids = {item.chunk_id for item in selected}
            for item in items:
                if len(selected) >= top_k:
                    break
                if item.chunk_id in seen_ids:
                    continue
                selected.append(item)

        return selected


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right, strict=False):
        dot += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value

    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)
