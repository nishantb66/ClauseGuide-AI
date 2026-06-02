from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import OpenAI

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class LLMService:
    """Wrapper over Groq's OpenAI-compatible chat completion API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI | None:
        if not self.settings.groq_api_key:
            return None
        if self._client is None:
            self._client = OpenAI(base_url=self.settings.groq_base_url, api_key=self.settings.groq_api_key)
        return self._client

    def answer_contract_question(self, *, question: str, context_items: list[dict[str, Any]]) -> dict[str, Any]:
        if not context_items:
            return {
                "answer": "I could not find this information in the contract.",
                "confidence_score": 0.25,
                "sources": [],
                "disclaimer": "This is not legal advice.",
            }

        if not self.settings.groq_api_key:
            return self._heuristic_answer(question=question, context_items=context_items)

        prompt = self._build_prompt(question=question, context_items=context_items)

        max_attempts = max(1, self.settings.llm_max_retries + 1)
        for attempt in range(max_attempts):
            try:
                completion = self.client.chat.completions.create(
                    model=self.settings.groq_model,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=self.settings.request_timeout_seconds,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are ClauseGuide AI, a contract analysis assistant. "
                                "Answer ONLY from provided context. Never provide legal advice. "
                                "If evidence is weak or missing, answer exactly: "
                                "'I could not find this information in the contract.' "
                                "Every source evidence snippet must be verbatim from the context."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
                raw = completion.choices[0].message.content or "{}"
                parsed = json.loads(raw)
                return self._normalize_response(parsed)
            except Exception as exc:  # pragma: no cover - networked fallback path
                last_attempt = attempt == max_attempts - 1
                if last_attempt:
                    logger.warning("Groq request failed, using heuristic fallback: %s", exc)
                    return self._heuristic_answer(question=question, context_items=context_items)

                wait_seconds = self.settings.llm_retry_backoff_seconds * (2**attempt)
                logger.warning("Groq request failed (attempt %s/%s), retrying in %.2fs: %s", attempt + 1, max_attempts, wait_seconds, exc)
                time.sleep(wait_seconds)

        return self._heuristic_answer(question=question, context_items=context_items)

    def _build_prompt(self, *, question: str, context_items: list[dict[str, Any]]) -> str:
        context_lines: list[str] = []
        max_chunks = max(1, self.settings.llm_max_context_chunks)
        max_chars = max(400, self.settings.llm_context_chunk_chars)
        for item in context_items[:max_chunks]:
            chunk_text = self._compact_context(item["chunk_text"], max_chars=max_chars)
            context_lines.append(
                f"Page {item['page_number']} | clause_type={item.get('clause_type') or 'unknown'}\n"
                f"{chunk_text}"
            )

        return (
            "Return strict JSON:\n"
            "{\n"
            '  "answer": "...",\n'
            '  "confidence_score": 0.0,\n'
            '  "sources": [\n'
            "    {\"page\": 1, \"clause_type\": \"...\", \"evidence\": \"exact quote from context\"}\n"
            "  ],\n"
            '  "disclaimer": "This is not legal advice."\n'
            "}\n\n"
            "Rules:\n"
            "- Use only the context.\n"
            "- If answer is missing in context, return unsupported response with empty sources.\n"
            "- Keep answer concise and factual.\n"
            "- For each source, evidence must be a short exact quote from context.\n\n"
            f"Question:\n{question}\n\n"
            "Context:\n"
            + "\n\n---\n\n".join(context_lines)
        )

    @staticmethod
    def _compact_context(text: str, *, max_chars: int) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip() + "..."

    def _normalize_response(self, parsed: dict[str, Any]) -> dict[str, Any]:
        answer = str(parsed.get("answer") or "").strip() or "I could not find this information in the contract."
        sources = parsed.get("sources")
        if not isinstance(sources, list):
            sources = []

        normalized_sources: list[dict[str, Any]] = []
        for source in sources[:4]:
            if not isinstance(source, dict):
                continue
            evidence = str(source.get("evidence") or "").strip()
            if not evidence:
                continue
            normalized_sources.append(
                {
                    "page": source.get("page"),
                    "clause_type": source.get("clause_type") or "other",
                    "evidence": evidence,
                }
            )

        confidence = parsed.get("confidence_score", 0.5)
        try:
            confidence_score = float(confidence)
        except (TypeError, ValueError):
            confidence_score = 0.5

        return {
            "answer": answer,
            "confidence_score": max(0.0, min(1.0, confidence_score)),
            "sources": normalized_sources,
            "disclaimer": "This is not legal advice.",
        }

    def _heuristic_answer(self, *, question: str, context_items: list[dict[str, Any]]) -> dict[str, Any]:
        question_lower = question.lower()
        selected = context_items[:3]
        best = selected[0]

        if any(keyword in question_lower for keyword in ("notice", "period", "days", "months")):
            best = next((item for item in context_items if "notice" in item["chunk_text"].lower()), selected[0])
            answer = self._extract_notice_answer(best["chunk_text"])
        elif any(keyword in question_lower for keyword in ("penalty", "bond", "damages", "amount", "fee")):
            best = next(
                (
                    item
                    for item in context_items
                    if any(term in item["chunk_text"].lower() for term in ("penalty", "bond", "damages", "liquidated"))
                ),
                selected[0],
            )
            answer = self._extract_amount_answer(best["chunk_text"])
        elif any(keyword in question_lower for keyword in ("terminate", "termination", "resign", "exit")):
            best = next((item for item in context_items if "terminat" in item["chunk_text"].lower()), selected[0])
            answer = self._extract_termination_answer(best["chunk_text"])
        else:
            answer = self._extract_general_answer(best["chunk_text"])

        if not answer or answer.lower().startswith("i could not find"):
            return {
                "answer": "I could not find this information in the contract.",
                "confidence_score": 0.32,
                "sources": [],
                "disclaimer": "This is not legal advice.",
            }

        evidence = self._best_evidence_snippet(best["chunk_text"], question_lower)
        return {
            "answer": answer,
            "confidence_score": 0.54,
            "sources": [
                {
                    "page": best["page_number"],
                    "clause_type": best.get("clause_type") or "other",
                    "evidence": evidence,
                }
            ],
            "disclaimer": "This is not legal advice.",
        }

    @staticmethod
    def _best_evidence_snippet(text: str, question_lower: str) -> str:
        cleaned = " ".join(text.split())
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        if not sentences:
            return cleaned[:240]

        query_terms = {token for token in re.findall(r"\w+", question_lower) if len(token) > 3}
        best_sentence = max(
            sentences,
            key=lambda sentence: len(query_terms & {token for token in re.findall(r"\w+", sentence.lower()) if len(token) > 3}),
        )
        return best_sentence[:240].strip()

    @staticmethod
    def _extract_notice_answer(text: str) -> str:
        match = re.search(r"\b(\d{1,3})\s*(day|days|month|months)\b", text, flags=re.IGNORECASE)
        if not match:
            return "I could not find this information in the contract."
        return f"The notice period is {match.group(1)} {match.group(2).lower()}."

    @staticmethod
    def _extract_amount_answer(text: str) -> str:
        amount = re.search(r"(?:₹|inr|rs\.?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
        if amount:
            return f"The contract mentions an amount of INR {amount.group(1)}."
        numeric = re.search(r"\b([0-9][0-9,]{4,})\b", text)
        if numeric:
            return f"The contract mentions an amount of {numeric.group(1)}."
        return "I could not find this information in the contract."

    @staticmethod
    def _extract_termination_answer(text: str) -> str:
        cleaned = " ".join(text.split())
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        for sentence in sentences:
            lowered = sentence.lower()
            if "terminat" in lowered or "resign" in lowered or "notice" in lowered:
                return sentence[:260]
        return "I could not find this information in the contract."

    @staticmethod
    def _extract_general_answer(text: str) -> str:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return "I could not find this information in the contract."
        return f"Based on the contract, {cleaned[:220]}"
