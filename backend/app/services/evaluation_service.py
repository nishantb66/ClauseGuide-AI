from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentStatus
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.schemas.evaluation_schema import EvaluationTestCase
from app.services.chat_service import ChatService


@dataclass(slots=True)
class CaseComputation:
    question: str
    expected_answer: str | None
    actual_answer: str
    expected_source_page: int | None
    expected_clause_type: str | None
    expected_risk_level: str | None
    sources: list[dict]
    retrieved_context: list[str]

    faithfulness_score: float
    answer_relevancy_score: float
    context_precision_score: float
    context_recall_score: float

    amount_accuracy_score: float
    date_accuracy_score: float
    clause_classification_score: float
    risk_level_accuracy_score: float
    citation_exact_match_score: float
    unsupported_refusal_score: float


class EvaluationService:
    amount_re = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
    day_month_re = re.compile(r"\b\d{1,3}\s*(?:day|days|month|months)\b", re.IGNORECASE)
    date_re = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
    token_re = re.compile(r"\w+")

    unsupported_text = "i could not find this information in the contract."

    def __init__(self, chat_service: ChatService | None = None) -> None:
        self.settings = get_settings()
        self.chat_service = chat_service or ChatService()

    async def run_evaluation(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        run_label: str,
        use_ragas: bool,
        test_cases: list[EvaluationTestCase] | None,
        owner_user_id: str | None = None,
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")
        if document.status != DocumentStatus.analyzed:
            raise ValueError("Document is not processed yet. Run /process first.")

        final_cases = test_cases or await self._generate_default_test_cases(session, document_id=document_id)
        if not final_cases:
            raise ValueError("No evaluation test cases available for this document")

        risk_level_by_clause = await self._risk_level_lookup(session, document_id=document_id)

        run = EvaluationRun(document_id=document_id, run_label=run_label, ragas_enabled=use_ragas)
        session.add(run)
        await session.flush()

        computed: list[CaseComputation] = []
        for case in final_cases:
            answer = await self.chat_service.ask_ephemeral(
                session,
                document_id=document_id,
                question=case.question,
                owner_user_id=owner_user_id,
            )
            computed.append(
                self._score_case(
                    case=case,
                    answer=answer,
                    risk_level_by_clause=risk_level_by_clause,
                )
            )

        ragas_summary, ragas_applied = self._maybe_compute_ragas_aggregate(computed=computed, requested=use_ragas)

        metrics_summary = self._build_metrics_summary(
            computed=computed,
            ragas_enabled=use_ragas,
            ragas_applied=ragas_applied,
            ragas_summary=ragas_summary,
        )

        run.summary_json = metrics_summary

        for row in computed:
            session.add(
                EvaluationResult(
                    run_id=run.id,
                    document_id=document_id,
                    question=row.question,
                    expected_answer=row.expected_answer,
                    actual_answer=row.actual_answer,
                    expected_source_page=row.expected_source_page,
                    expected_clause_type=row.expected_clause_type,
                    expected_risk_level=row.expected_risk_level,
                    actual_sources_json=row.sources,
                    retrieved_context_json=row.retrieved_context,
                    faithfulness_score=row.faithfulness_score,
                    answer_relevancy_score=row.answer_relevancy_score,
                    context_precision_score=row.context_precision_score,
                    context_recall_score=row.context_recall_score,
                    amount_accuracy_score=row.amount_accuracy_score,
                    date_accuracy_score=row.date_accuracy_score,
                    clause_classification_score=row.clause_classification_score,
                    risk_level_accuracy_score=row.risk_level_accuracy_score,
                    citation_exact_match_score=row.citation_exact_match_score,
                    unsupported_refusal_score=row.unsupported_refusal_score,
                )
            )

        await session.commit()
        await session.refresh(run)

        return {
            "run_id": run.id,
            "document_id": run.document_id,
            "run_label": run.run_label,
            "created_at": run.created_at,
            "metrics": metrics_summary,
            "results": [
                {
                    "question": row.question,
                    "expected_answer": row.expected_answer,
                    "actual_answer": row.actual_answer,
                    "faithfulness_score": row.faithfulness_score,
                    "answer_relevancy_score": row.answer_relevancy_score,
                    "context_precision_score": row.context_precision_score,
                    "context_recall_score": row.context_recall_score,
                    "amount_accuracy_score": row.amount_accuracy_score,
                    "date_accuracy_score": row.date_accuracy_score,
                    "clause_classification_score": row.clause_classification_score,
                    "risk_level_accuracy_score": row.risk_level_accuracy_score,
                    "citation_exact_match_score": row.citation_exact_match_score,
                    "unsupported_refusal_score": row.unsupported_refusal_score,
                }
                for row in computed
            ],
        }

    async def list_runs(
        self, session: AsyncSession, *, document_id: str, owner_user_id: str | None = None
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")

        rows = await session.execute(
            select(EvaluationRun)
            .where(EvaluationRun.document_id == document_id)
            .order_by(EvaluationRun.created_at.desc())
        )
        runs = rows.scalars().all()

        return {
            "document_id": document_id,
            "runs": [
                {
                    "run_id": run.id,
                    "run_label": run.run_label,
                    "created_at": run.created_at,
                    "metrics": run.summary_json,
                }
                for run in runs
            ],
        }

    async def get_run(self, session: AsyncSession, *, run_id: str) -> dict:
        run = await session.get(EvaluationRun, run_id)
        if run is None:
            raise ValueError("Evaluation run not found")

        rows = await session.execute(
            select(EvaluationResult)
            .where(EvaluationResult.run_id == run_id)
            .order_by(EvaluationResult.id.asc())
        )
        results = rows.scalars().all()

        return {
            "run_id": run.id,
            "document_id": run.document_id,
            "run_label": run.run_label,
            "created_at": run.created_at,
            "metrics": run.summary_json,
            "results": [
                {
                    "question": row.question,
                    "expected_answer": row.expected_answer,
                    "actual_answer": row.actual_answer,
                    "faithfulness_score": row.faithfulness_score,
                    "answer_relevancy_score": row.answer_relevancy_score,
                    "context_precision_score": row.context_precision_score,
                    "context_recall_score": row.context_recall_score,
                    "amount_accuracy_score": row.amount_accuracy_score,
                    "date_accuracy_score": row.date_accuracy_score,
                    "clause_classification_score": row.clause_classification_score,
                    "risk_level_accuracy_score": row.risk_level_accuracy_score,
                    "citation_exact_match_score": row.citation_exact_match_score,
                    "unsupported_refusal_score": row.unsupported_refusal_score,
                }
                for row in results
            ],
        }

    async def _generate_default_test_cases(
        self,
        session: AsyncSession,
        *,
        document_id: str,
    ) -> list[EvaluationTestCase]:
        clause_rows = await session.execute(
            select(Clause)
            .where(Clause.document_id == document_id)
            .order_by(Clause.page_start.asc(), Clause.id.asc())
        )
        clauses = clause_rows.scalars().all()

        findings_rows = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc())
        )
        findings = findings_rows.scalars().all()

        cases: list[EvaluationTestCase] = []
        seen_questions: set[str] = set()

        for clause in clauses:
            if clause.clause_type == "notice_period":
                self._add_case(
                    cases,
                    seen_questions,
                    EvaluationTestCase(
                        question="What is the notice period in this contract?",
                        expected_answer=self._snippet(clause.clause_text, 180),
                        expected_source_page=clause.page_start,
                        expected_clause_type="notice_period",
                    ),
                )
            if clause.clause_type in {"bond", "penalty"}:
                if not self._clause_has_financial_exit_signal(clause.clause_text):
                    continue
                self._add_case(
                    cases,
                    seen_questions,
                    EvaluationTestCase(
                        question="What penalty or bond amount applies for early exit?",
                        expected_answer=self._snippet(clause.clause_text, 180),
                        expected_source_page=clause.page_start,
                        expected_clause_type=clause.clause_type,
                    ),
                )
            if clause.clause_type == "termination":
                self._add_case(
                    cases,
                    seen_questions,
                    EvaluationTestCase(
                        question="How can termination happen under this agreement?",
                        expected_answer=self._snippet(clause.clause_text, 180),
                        expected_source_page=clause.page_start,
                        expected_clause_type="termination",
                    ),
                )

        for finding in findings[:4]:
            clause_type = "other"
            if finding.clause_id:
                clause_match = next((clause for clause in clauses if clause.id == finding.clause_id), None)
                if clause_match:
                    clause_type = clause_match.clause_type
            self._add_case(
                cases,
                seen_questions,
                EvaluationTestCase(
                    question=f"What is the main risk around {clause_type.replace('_', ' ')}?",
                    expected_answer=finding.summary,
                    expected_source_page=finding.page_number,
                    expected_clause_type=clause_type,
                    expected_risk_level=finding.risk_level,
                ),
            )

        self._add_case(
            cases,
            seen_questions,
            EvaluationTestCase(
                question="Is there a clause about unlimited overtime compensation in this contract?",
                expected_answer=None,
                expected_source_page=None,
                expected_clause_type=None,
                expected_risk_level=None,
            ),
        )

        return cases[:12]

    @staticmethod
    def _clause_has_financial_exit_signal(text: str) -> bool:
        lowered = text.lower()
        has_exit_signal = any(
            marker in lowered
            for marker in ("early exit", "leave before", "breach", "termination", "resignation", "resign")
        )
        has_financial_signal = any(
            marker in lowered
            for marker in (
                "penalty",
                "liquidated damages",
                "forfeit",
                "inr",
                "rs",
                "₹",
                "amount",
                "charge",
                "cost",
            )
        )
        return has_exit_signal and has_financial_signal

    @staticmethod
    def _add_case(
        cases: list[EvaluationTestCase],
        seen_questions: set[str],
        case: EvaluationTestCase,
    ) -> None:
        key = case.question.strip().lower()
        if key in seen_questions:
            return
        seen_questions.add(key)
        cases.append(case)

    async def _risk_level_lookup(self, session: AsyncSession, *, document_id: str) -> dict[str, str]:
        rows = await session.execute(
            select(Clause.clause_type, RiskFinding.risk_level)
            .join(RiskFinding, RiskFinding.clause_id == Clause.id)
            .where(Clause.document_id == document_id)
        )
        mapping: dict[str, str] = {}
        for clause_type, risk_level in rows.all():
            if clause_type not in mapping:
                mapping[clause_type] = risk_level
        return mapping

    def _score_case(
        self,
        *,
        case: EvaluationTestCase,
        answer: dict,
        risk_level_by_clause: dict[str, str],
    ) -> CaseComputation:
        actual_answer = str(answer.get("answer", "")).strip()
        sources = answer.get("sources") or []
        retrieved_context = [str(text) for text in (answer.get("retrieved_context") or [])]

        faithfulness_score = self._faithfulness(actual_answer, retrieved_context)
        answer_relevancy_score = self._answer_relevancy(case.question, actual_answer)
        context_precision_score = self._context_precision(sources=sources, retrieved_context=retrieved_context)
        context_recall_score = self._context_recall(expected_answer=case.expected_answer, retrieved_context=retrieved_context)

        amount_accuracy_score = self._amount_accuracy(case.expected_answer, actual_answer)
        date_accuracy_score = self._date_accuracy(case.expected_answer, actual_answer)
        clause_classification_score = self._clause_accuracy(case.expected_clause_type, sources)
        risk_level_accuracy_score = self._risk_level_accuracy(
            expected_clause_type=case.expected_clause_type,
            expected_risk_level=case.expected_risk_level,
            risk_level_by_clause=risk_level_by_clause,
        )
        citation_exact_match_score = self._citation_exact_match(case.expected_source_page, sources)
        unsupported_refusal_score = self._unsupported_refusal(case.expected_answer, actual_answer)

        return CaseComputation(
            question=case.question,
            expected_answer=case.expected_answer,
            actual_answer=actual_answer,
            expected_source_page=case.expected_source_page,
            expected_clause_type=case.expected_clause_type,
            expected_risk_level=case.expected_risk_level,
            sources=sources,
            retrieved_context=retrieved_context,
            faithfulness_score=faithfulness_score,
            answer_relevancy_score=answer_relevancy_score,
            context_precision_score=context_precision_score,
            context_recall_score=context_recall_score,
            amount_accuracy_score=amount_accuracy_score,
            date_accuracy_score=date_accuracy_score,
            clause_classification_score=clause_classification_score,
            risk_level_accuracy_score=risk_level_accuracy_score,
            citation_exact_match_score=citation_exact_match_score,
            unsupported_refusal_score=unsupported_refusal_score,
        )

    def _build_metrics_summary(
        self,
        *,
        computed: list[CaseComputation],
        ragas_enabled: bool,
        ragas_applied: bool,
        ragas_summary: dict[str, float] | None,
    ) -> dict:
        def avg(values: list[float]) -> float:
            return round(mean(values), 4) if values else 0.0

        summary = {
            "total_cases": len(computed),
            "ragas_enabled": ragas_enabled,
            "ragas_applied": ragas_applied,
            "faithfulness_score": avg([row.faithfulness_score for row in computed]),
            "answer_relevancy_score": avg([row.answer_relevancy_score for row in computed]),
            "context_precision_score": avg([row.context_precision_score for row in computed]),
            "context_recall_score": avg([row.context_recall_score for row in computed]),
            "amount_accuracy_score": avg([row.amount_accuracy_score for row in computed]),
            "date_accuracy_score": avg([row.date_accuracy_score for row in computed]),
            "clause_classification_score": avg([row.clause_classification_score for row in computed]),
            "risk_level_accuracy_score": avg([row.risk_level_accuracy_score for row in computed]),
            "citation_exact_match_score": avg([row.citation_exact_match_score for row in computed]),
            "unsupported_refusal_score": avg([row.unsupported_refusal_score for row in computed]),
        }

        if ragas_summary:
            for key in ("faithfulness_score", "answer_relevancy_score", "context_precision_score", "context_recall_score"):
                if key in ragas_summary:
                    summary[key] = float(round(ragas_summary[key], 4))

        return summary

    def _maybe_compute_ragas_aggregate(
        self,
        *,
        computed: list[CaseComputation],
        requested: bool,
    ) -> tuple[dict[str, float] | None, bool]:
        if not requested:
            return None, False

        try:
            from datasets import Dataset
            from ragas import evaluate
            from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
        except Exception:
            return None, False

        data = {
            "question": [row.question for row in computed],
            "answer": [row.actual_answer for row in computed],
            "contexts": [row.retrieved_context or [""] for row in computed],
            "ground_truth": [row.expected_answer or "" for row in computed],
        }

        try:
            dataset = Dataset.from_dict(data)
            result = evaluate(
                dataset,
                metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            )
        except Exception:
            return None, False

        summary = self._extract_ragas_summary(result)
        if not summary:
            return None, False
        return summary, True

    @staticmethod
    def _extract_ragas_summary(result: Any) -> dict[str, float]:
        keys = {
            "faithfulness": "faithfulness_score",
            "answer_relevancy": "answer_relevancy_score",
            "context_precision": "context_precision_score",
            "context_recall": "context_recall_score",
        }

        out: dict[str, float] = {}

        if isinstance(result, dict):
            for src, dst in keys.items():
                value = result.get(src)
                if isinstance(value, (int, float)):
                    out[dst] = float(value)
            return out

        # RAGAS EvaluationResult often exposes dict-like access and to_pandas().
        for src, dst in keys.items():
            try:
                value = result[src]
            except Exception:
                value = None
            if isinstance(value, (int, float)):
                out[dst] = float(value)

        if out:
            return out

        try:
            frame = result.to_pandas()
        except Exception:
            return out

        for src, dst in keys.items():
            if src in frame.columns:
                series = frame[src].dropna()
                if len(series) > 0:
                    out[dst] = float(series.mean())

        return out

    def _faithfulness(self, actual_answer: str, retrieved_context: list[str]) -> float:
        if not actual_answer:
            return 0.0
        if not retrieved_context:
            return 0.0

        answer_tokens = self._token_set(actual_answer)
        context_tokens = self._token_set(" ".join(retrieved_context))
        if not answer_tokens:
            return 0.0

        overlap = len(answer_tokens & context_tokens) / len(answer_tokens)
        return round(self._clip(overlap), 4)

    def _answer_relevancy(self, question: str, actual_answer: str) -> float:
        question_tokens = self._token_set(question)
        answer_tokens = self._token_set(actual_answer)
        if not question_tokens:
            return 0.0

        overlap = len(question_tokens & answer_tokens) / len(question_tokens)
        fallback_penalty = 0.35 if self._normalize(actual_answer) == self.unsupported_text else 0.0
        score = max(0.0, overlap - fallback_penalty)
        return round(self._clip(score), 4)

    def _context_precision(self, *, sources: list[dict], retrieved_context: list[str]) -> float:
        if not sources:
            return 0.0
        context_blob = self._normalize(" ".join(retrieved_context))
        if not context_blob:
            return 0.0

        valid = 0
        for source in sources:
            evidence = self._normalize(str(source.get("evidence", "")))
            if evidence and evidence in context_blob:
                valid += 1

        return round(self._clip(valid / len(sources)), 4)

    def _context_recall(self, expected_answer: str | None, retrieved_context: list[str]) -> float:
        if not expected_answer:
            return 1.0
        expected_tokens = self._token_set(expected_answer)
        if not expected_tokens:
            return 1.0

        context_tokens = self._token_set(" ".join(retrieved_context))
        if not context_tokens:
            return 0.0

        coverage = len(expected_tokens & context_tokens) / len(expected_tokens)
        return round(self._clip(coverage), 4)

    def _amount_accuracy(self, expected_answer: str | None, actual_answer: str) -> float:
        expected_amounts = self._extract_amounts(expected_answer or "")
        if not expected_amounts:
            return 1.0

        actual_amounts = self._extract_amounts(actual_answer)
        if not actual_amounts:
            return 0.0

        hits = sum(1 for amount in expected_amounts if amount in actual_amounts)
        return round(self._clip(hits / len(expected_amounts)), 4)

    def _date_accuracy(self, expected_answer: str | None, actual_answer: str) -> float:
        expected = self._extract_time_tokens(expected_answer or "")
        if not expected:
            return 1.0

        actual = self._extract_time_tokens(actual_answer)
        if not actual:
            return 0.0

        hits = sum(1 for item in expected if item in actual)
        return round(self._clip(hits / len(expected)), 4)

    def _clause_accuracy(self, expected_clause_type: str | None, sources: list[dict]) -> float:
        if not expected_clause_type:
            return 1.0
        actual = {str(source.get("clause_type", "")).lower() for source in sources}
        return 1.0 if expected_clause_type.lower() in actual else 0.0

    def _risk_level_accuracy(
        self,
        *,
        expected_clause_type: str | None,
        expected_risk_level: str | None,
        risk_level_by_clause: dict[str, str],
    ) -> float:
        if not expected_risk_level:
            return 1.0
        if not expected_clause_type:
            return 0.0

        predicted = risk_level_by_clause.get(expected_clause_type)
        if not predicted:
            return 0.0
        return 1.0 if predicted.lower() == expected_risk_level.lower() else 0.0

    def _citation_exact_match(self, expected_source_page: int | None, sources: list[dict]) -> float:
        if expected_source_page is None:
            return 1.0
        pages = {source.get("page") for source in sources}
        return 1.0 if expected_source_page in pages else 0.0

    def _unsupported_refusal(self, expected_answer: str | None, actual_answer: str) -> float:
        if expected_answer:
            return 1.0
        return 1.0 if self._normalize(actual_answer) == self.unsupported_text else 0.0

    def _extract_amounts(self, text: str) -> set[str]:
        return {match.group(1).replace(",", "") for match in self.amount_re.finditer(text)}

    def _extract_time_tokens(self, text: str) -> set[str]:
        values = {self._normalize(match.group(0)).lower() for match in self.day_month_re.finditer(text)}
        values.update(self._normalize(match.group(0)).lower() for match in self.date_re.finditer(text))
        return values

    def _token_set(self, text: str) -> set[str]:
        return {token.lower() for token in self.token_re.findall(text) if len(token) > 2}

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split()).strip()

    @staticmethod
    def _snippet(text: str, max_len: int) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= max_len:
            return normalized
        return normalized[: max_len - 3].rstrip() + "..."

    @staticmethod
    def _clip(value: float) -> float:
        return max(0.0, min(1.0, value))
