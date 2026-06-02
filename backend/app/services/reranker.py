from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cached_property
from math import exp
from typing import TYPE_CHECKING

from app.core.settings import get_settings

if TYPE_CHECKING:
    from app.services.retriever import RetrievalItem

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RerankDiagnostics:
    avg_rerank_score: float
    model_used: str


class ChunkReranker:
    """Reranks retrieved chunks using optional cross-encoder or lexical-semantic blend."""

    token_re = re.compile(r"\w+")

    def __init__(self) -> None:
        self.settings = get_settings()

    @cached_property
    def cross_encoder(self):
        if not self.settings.use_cross_encoder_reranker:
            return None
        try:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(self.settings.reranker_model)
        except Exception as exc:  # pragma: no cover - optional path
            logger.warning("Cross-encoder reranker unavailable, fallback enabled: %s", exc)
            return None

    def rerank(
        self,
        *,
        query: str,
        items: list["RetrievalItem"],
        required_clause_types: list[str],
        top_k: int,
    ) -> tuple[list["RetrievalItem"], RerankDiagnostics]:
        if not items:
            return [], RerankDiagnostics(avg_rerank_score=0.0, model_used="none")

        encoder = self.cross_encoder
        if encoder is not None:
            scores = encoder.predict([(query, item.chunk_text) for item in items])
            ranked_items: list[RetrievalItem] = []
            for item, raw_score in zip(items, scores, strict=False):
                score = self._sigmoid(float(raw_score))
                if required_clause_types and item.clause_type in required_clause_types:
                    score = min(1.0, score + 0.06)

                enriched = item.copy_with(
                    rerank_score=score,
                    score=(0.45 * item.score) + (0.55 * score),
                )
                ranked_items.append(enriched)

            ranked_items.sort(key=lambda item: item.score, reverse=True)
            selected = ranked_items[:top_k]
            avg_score = sum(item.rerank_score for item in selected) / max(1, len(selected))
            return selected, RerankDiagnostics(avg_rerank_score=avg_score, model_used="cross_encoder")

        ranked_items = [self._lexical_semantic_score(query, item, required_clause_types) for item in items]
        ranked_items.sort(key=lambda item: item.score, reverse=True)
        selected = ranked_items[:top_k]
        avg_score = sum(item.rerank_score for item in selected) / max(1, len(selected))
        return selected, RerankDiagnostics(avg_rerank_score=avg_score, model_used="heuristic")

    def _lexical_semantic_score(
        self,
        query: str,
        item: "RetrievalItem",
        required_clause_types: list[str],
    ) -> "RetrievalItem":
        query_token_list = self._token_list(query)
        text_token_list = self._token_list(item.chunk_text)
        query_tokens = set(query_token_list)
        text_tokens = set(text_token_list)
        title_tokens = self._token_set(item.section_title or "")
        query_bigrams = self._bigram_set(query_token_list)
        text_bigrams = self._bigram_set(text_token_list)

        token_overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
        title_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens)) if title_tokens else 0.0
        bigram_overlap = len(query_bigrams & text_bigrams) / max(1, len(query_bigrams)) if query_bigrams else 0.0
        clause_boost = 0.12 if required_clause_types and item.clause_type in required_clause_types else 0.0

        rerank_score = min(
            1.0,
            (0.5 * token_overlap) + (0.2 * title_overlap) + (0.2 * bigram_overlap) + clause_boost,
        )
        final_score = (0.5 * item.score) + (0.5 * rerank_score)

        return item.copy_with(rerank_score=rerank_score, score=final_score)

    def _token_set(self, text: str) -> set[str]:
        return {token.lower() for token in self.token_re.findall(text) if len(token) > 2}

    def _token_list(self, text: str) -> list[str]:
        return [token.lower() for token in self.token_re.findall(text) if len(token) > 2]

    @staticmethod
    def _bigram_set(tokens: list[str]) -> set[str]:
        if len(tokens) < 2:
            return set()
        return {f"{tokens[index]} {tokens[index + 1]}" for index in range(len(tokens) - 1)}

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            z = exp(-value)
            return 1 / (1 + z)
        z = exp(value)
        return z / (1 + z)
