from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.legal_kb_service import LegalKnowledgeBase, get_legal_kb
from app.services.legal_taxonomy import CLAUSE_DEFINITIONS


@dataclass(slots=True)
class ClauseSignal:
    clause_type: str
    exists: bool
    positive_hits: list[str] = field(default_factory=list)
    negative_hits: list[str] = field(default_factory=list)
    confidence_score: float = 0.0


class ClauseNormalizer:
    """Normalizes legal wording into clause-existence signals.

    This layer intentionally separates "clause exists" from "clause is risky".
    Positive patterns prove existence; negative patterns prevent weak phrases from
    becoming false positives.
    """

    negative_patterns: dict[str, tuple[str, ...]] = {
        "auto_renewal": (
            "may be renewed",
            "can be renewed",
            "subject to renewal",
            "extended by mutual consent",
            "renewed by mutual agreement",
            "subject to approval",
            "at discretion",
        ),
        "assignment": (
            "successors and assigns",
            "binding upon successors",
        ),
        "penalty": (
            "salary review",
            "incentive plan",
            "retirement plan",
            "compensation committee",
        ),
        "bond": (
            "posting any bond",
            "surety bond",
            "bonded warehouse",
        ),
        "notice_period": (
            "notice address",
            "notice details",
        ),
    }

    required_positive_patterns: dict[str, tuple[str, ...]] = {
        "auto_renewal": (
            "automatically renew",
            "shall renew automatically",
            "will renew automatically",
            "successive renewal terms unless",
            "renewed automatically",
        ),
        "assignment": (
            "may assign",
            "shall not assign",
            "assignment requires",
            "prior consent to assign",
            "change of control",
        ),
    }
    weak_aliases = {
        "after",
        "before",
        "agreement",
        "party",
        "parties",
        "company",
        "services",
        "section",
        "term",
        "terms",
        "date",
        "days",
        "right",
        "rights",
        "time",
        "law",
        "provided",
        "provide",
    }

    def __init__(self, kb: LegalKnowledgeBase | None = None) -> None:
        self.kb = kb or get_legal_kb()

    def signal_for(self, clause_type: str, text: str) -> ClauseSignal:
        normalized = self._normalize(text)
        positives = self._positive_patterns(clause_type)
        negatives = self.negative_patterns.get(clause_type, ())

        positive_hits = [pattern for pattern in positives if self._contains(normalized, pattern)]
        negative_hits = [pattern for pattern in negatives if self._contains(normalized, pattern)]

        required = self.required_positive_patterns.get(clause_type)
        if required is not None:
            positive_hits = [pattern for pattern in required if self._contains(normalized, pattern)]

        exists = bool(positive_hits) and not self._negative_overrides(
            clause_type, positive_hits, negative_hits
        )
        confidence = 0.0
        if exists:
            confidence = min(0.95, 0.45 + (0.12 * len(positive_hits)))
            if negative_hits:
                confidence = max(0.35, confidence - 0.2)

        return ClauseSignal(
            clause_type=clause_type,
            exists=exists,
            positive_hits=positive_hits[:8],
            negative_hits=negative_hits[:8],
            confidence_score=confidence,
        )

    def present_clause_types(self, clause_texts: list[tuple[str, str]]) -> set[str]:
        corpus = "\n".join(f"{title}\n{text}" for title, text in clause_texts)
        present: set[str] = set()
        for clause_type in CLAUSE_DEFINITIONS:
            signal = self.signal_for(clause_type, corpus)
            if signal.exists:
                present.add(clause_type)
        return present

    def _positive_patterns(self, clause_type: str) -> tuple[str, ...]:
        definition = CLAUSE_DEFINITIONS.get(clause_type, {})
        keywords = definition.get("keywords", ())
        if isinstance(keywords, str):
            patterns = [keywords]
        else:
            patterns = [str(item) for item in keywords]
        patterns.extend(
            alias for alias in self.kb.aliases_for(clause_type) if self._is_strong_alias(alias)
        )
        return tuple(dict.fromkeys(patterns))

    def _is_strong_alias(self, alias: str) -> bool:
        normalized = alias.lower().strip()
        if not normalized or normalized in self.weak_aliases:
            return False
        if " " in normalized:
            return len(normalized) >= 8
        return len(normalized) >= 7

    @staticmethod
    def _negative_overrides(
        clause_type: str, positive_hits: list[str], negative_hits: list[str]
    ) -> bool:
        if not negative_hits:
            return False
        if clause_type in {"auto_renewal", "assignment"}:
            return True
        return bool(negative_hits and len(positive_hits) <= 1)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        phrase = phrase.lower().strip()
        if not phrase:
            return False
        if re.search(r"^[a-z0-9 ]+$", phrase):
            return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))
        return phrase in text
