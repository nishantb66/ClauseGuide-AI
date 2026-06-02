from __future__ import annotations

import re


class CitationVerifier:
    """Verifies that evidence snippets exist in retrieved context."""

    def verify(self, sources: list[dict], retrieved_context: list[str]) -> bool:
        return self.score(sources=sources, retrieved_context=retrieved_context) >= 0.72

    def score(self, sources: list[dict], retrieved_context: list[str]) -> float:
        context_blob = self._normalize("\n".join(retrieved_context))
        if not sources or not context_blob:
            return 0.0

        scores: list[float] = []
        for source in sources:
            evidence = self._normalize((source.get("evidence") or "").strip())
            if not evidence:
                scores.append(0.0)
                continue

            if evidence in context_blob:
                scores.append(1.0)
                continue

            evidence_tokens = set(self._tokens(evidence))
            context_tokens = set(self._tokens(context_blob))
            if len(evidence_tokens) < 4:
                scores.append(0.0)
                continue

            overlap = len(evidence_tokens & context_tokens) / max(1, len(evidence_tokens))
            if overlap >= 0.85:
                scores.append(0.88)
            elif overlap >= 0.7:
                scores.append(0.74)
            else:
                scores.append(0.0)

        return sum(scores) / max(1, len(scores))

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split()).strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token for token in re.findall(r"\w+", text.lower()) if len(token) > 2]
