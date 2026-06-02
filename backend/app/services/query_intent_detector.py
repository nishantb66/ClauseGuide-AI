from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from app.services.legal_taxonomy import CLAUSE_DEFINITIONS


@dataclass(slots=True)
class QueryIntentResult:
    intent: str
    confidence_score: float
    required_clause_types: list[str]
    rewritten_query: str


class QueryIntentDetector:
    """Rule-based query intent detector for contract QA routing."""

    intent_keywords: ClassVar[dict[str, tuple[str, ...]]] = {
        "document_overview": (
            "tell me about",
            "summarize",
            "summary of document",
            "document summary",
            "what is this document",
            "what is this contract",
            "overview",
            "brief me",
        ),
        "risk_summary": (
            "risk",
            "risky",
            "dangerous",
            "red flag",
            "overall risk",
            "top risk",
        ),
        "specific_clause_question": ("clause", "section", "article", "term"),
        "obligation_question": (
            "must",
            "required",
            "obligation",
            "am i allowed",
            "can i",
            "shall",
        ),
        "amount_question": (
            "amount",
            "pay",
            "penalty",
            "charges",
            "fee",
            "cost",
            "₹",
            "inr",
            "rs",
            "refund",
            "deposit",
        ),
        "date_question": (
            "date",
            "timeline",
            "when",
            "days",
            "months",
            "notice period",
            "duration",
        ),
        "termination_question": (
            "terminate",
            "termination",
            "leave",
            "exit",
            "resign",
            "end the agreement",
        ),
        "comparison_question": ("compare", "difference", "versus", " vs ", "better"),
        "missing_clause_question": (
            "missing",
            "not mentioned",
            "absent",
            "not included",
            "what is missing",
        ),
    }

    intent_clause_defaults: ClassVar[dict[str, tuple[str, ...]]] = {
        "termination_question": ("termination", "notice_period"),
        "amount_question": ("payment", "security_deposit", "refund"),
        "date_question": ("notice_period", "termination", "lock_in", "auto_renewal"),
        "risk_summary": (
            "termination",
            "liability",
            "auto_renewal",
            "non_compete",
        ),
        "missing_clause_question": (
            "termination",
            "payment",
            "liability",
            "jurisdiction",
        ),
    }

    intent_query_expansion: ClassVar[dict[str, tuple[str, ...]]] = {
        "document_overview": ("summary", "purpose", "parties", "main terms", "important clauses"),
        "termination_question": ("termination", "notice period", "resignation", "without cause"),
        "amount_question": ("amount", "payment", "charges", "compensation", "fees"),
        "date_question": ("days", "months", "timeline", "notice period"),
        "risk_summary": ("risk", "liability", "termination", "obligations", "restriction"),
        "missing_clause_question": ("missing clause", "protection", "not mentioned"),
    }

    clause_focus_by_trigger: ClassVar[dict[str, tuple[str, ...]]] = {
        "bond": ("bond",),
        "penalty": ("penalty",),
        "liquidated damages": ("penalty",),
        "non-compete": ("non_compete",),
        "non compete": ("non_compete",),
        "notice period": ("notice_period",),
        "termination": ("termination",),
        "resign": ("termination",),
        "refund": ("refund",),
        "security deposit": ("security_deposit",),
        "arbitration": ("arbitration",),
        "jurisdiction": ("jurisdiction",),
    }

    def detect(self, question: str) -> QueryIntentResult:
        lowered = f" {question.lower().strip()} "

        clause_type_matches = self._detect_clause_type_mentions(lowered)
        intent_scores = self._intent_scores(lowered)

        best_intent = max(intent_scores, key=intent_scores.get)
        best_score = intent_scores[best_intent]

        forced_intent = self._priority_override(lowered)
        if forced_intent is not None:
            best_intent = forced_intent
            best_score = max(best_score, 1.25)

        # If an explicit clause mention dominates, prioritize specific-clause intent.
        if clause_type_matches and best_score <= 1.0:
            best_intent = "specific_clause_question"
            best_score = 1.0

        total_score = sum(intent_scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.0
        confidence = max(0.25, min(0.98, confidence + (0.08 if clause_type_matches else 0.0)))

        required_clause_types = list(dict.fromkeys(clause_type_matches))
        for clause_type in self._explicit_focus_clauses(lowered):
            if clause_type not in required_clause_types:
                required_clause_types.append(clause_type)

        for clause_type in self.intent_clause_defaults.get(best_intent, ()):
            if clause_type not in required_clause_types:
                required_clause_types.append(clause_type)

        rewritten_query = self._rewrite_query(question=question, intent=best_intent, required_clause_types=required_clause_types)

        return QueryIntentResult(
            intent=best_intent,
            confidence_score=confidence,
            required_clause_types=required_clause_types,
            rewritten_query=rewritten_query,
        )

    def _priority_override(self, lowered_question: str) -> str | None:
        if any(keyword in lowered_question for keyword in self.intent_keywords["document_overview"]):
            return "document_overview"

        if any(keyword in lowered_question for keyword in self.intent_keywords["missing_clause_question"]):
            return "missing_clause_question"

        if any(keyword in lowered_question for keyword in self.intent_keywords["termination_question"]):
            return "termination_question"

        if any(keyword in lowered_question for keyword in self.intent_keywords["amount_question"]):
            return "amount_question"

        return None

    def _intent_scores(self, lowered_question: str) -> dict[str, float]:
        scores: dict[str, float] = {intent: 0.1 for intent in self.intent_keywords}
        for intent, keywords in self.intent_keywords.items():
            for keyword in keywords:
                if keyword in lowered_question:
                    # Slightly reward longer n-grams as stronger intent indicators.
                    scores[intent] += 1.0 + (len(keyword.split()) - 1) * 0.2
        return scores

    def _detect_clause_type_mentions(self, lowered_question: str) -> list[str]:
        matches: list[str] = []
        for clause_type, details in CLAUSE_DEFINITIONS.items():
            keywords = details["keywords"]
            for keyword in keywords:
                if keyword.lower() in lowered_question:
                    matches.append(clause_type)
                    break
        return matches

    def _explicit_focus_clauses(self, lowered_question: str) -> list[str]:
        matches: list[str] = []
        for trigger, clause_types in self.clause_focus_by_trigger.items():
            if trigger in lowered_question:
                for clause_type in clause_types:
                    if clause_type not in matches:
                        matches.append(clause_type)
        return matches

    def _rewrite_query(self, *, question: str, intent: str, required_clause_types: list[str]) -> str:
        expansions: list[str] = list(self.intent_query_expansion.get(intent, ()))

        for clause_type in required_clause_types[:4]:
            clause_terms = CLAUSE_DEFINITIONS.get(clause_type, {}).get("keywords", ())
            if isinstance(clause_terms, tuple):
                expansions.extend(list(clause_terms[:2]))

        expansion_text = " ".join(dict.fromkeys(expansions))
        if not expansion_text:
            return question.strip()

        return f"{question.strip()} {expansion_text}".strip()
