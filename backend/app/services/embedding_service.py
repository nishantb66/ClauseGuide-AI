from __future__ import annotations

import hashlib
import logging
import re
from functools import cached_property
from typing import Any

import numpy as np

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embeddings with optional sentence-transformers and deterministic fallback."""

    token_re = re.compile(r"\w+")

    def __init__(self) -> None:
        self.settings = get_settings()

    @cached_property
    def sentence_model(self) -> Any | None:
        if not self.settings.use_sentence_transformers:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer(self.settings.embedding_model)
        except Exception as exc:  # pragma: no cover - optional dependency path
            logger.warning("Falling back to deterministic embeddings: %s", exc)
            return None

    def embed_text(self, text: str) -> list[float]:
        content = text.strip()
        if not content:
            return [0.0] * self.settings.embedding_dim

        model = self.sentence_model
        if model is not None:
            vector = model.encode(content, normalize_embeddings=True)
            return [float(value) for value in vector.tolist()]

        return self._deterministic_hash_embedding(content)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self.sentence_model
        if model is not None:
            vectors = model.encode(texts, normalize_embeddings=True)
            return [[float(value) for value in row.tolist()] for row in vectors]
        return [self._deterministic_hash_embedding(text) for text in texts]

    def _deterministic_hash_embedding(self, text: str) -> list[float]:
        dim = self.settings.embedding_dim
        vector = np.zeros(dim, dtype=np.float32)

        tokens = self.token_re.findall(text.lower())
        if not tokens:
            return vector.tolist()

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % dim
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector.tolist()
