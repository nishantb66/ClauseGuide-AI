from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clause import Clause, RiskFinding
from app.models.document import Document


class ClauseService:
    async def list_clauses(
        self, session: AsyncSession, document_id: str, *, owner_user_id: str | None = None
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")

        clauses_query = await session.execute(
            select(Clause)
            .where(Clause.document_id == document_id)
            .order_by(Clause.page_start.asc(), Clause.id.asc())
        )
        clauses = clauses_query.scalars().all()

        findings_query = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc())
        )
        findings = findings_query.scalars().all()

        top_risk_by_clause: dict[int, RiskFinding] = {}
        for finding in findings:
            if finding.clause_id is None:
                continue
            existing = top_risk_by_clause.get(finding.clause_id)
            if existing is None or finding.risk_score > existing.risk_score:
                top_risk_by_clause[finding.clause_id] = finding

        response_items = []
        for clause in clauses:
            top_risk = top_risk_by_clause.get(clause.id)
            response_items.append(
                {
                    "id": clause.id,
                    "clause_type": clause.clause_type,
                    "clause_title": clause.clause_title,
                    "page_start": clause.page_start,
                    "page_end": clause.page_end,
                    "confidence_score": clause.confidence_score,
                    "risk_level": top_risk.risk_level if top_risk else None,
                    "risk_score": top_risk.risk_score if top_risk else None,
                    "risk_summary": top_risk.summary if top_risk else None,
                }
            )

        return {"document_id": document_id, "clauses": response_items}

    async def get_clause_detail(
        self,
        session: AsyncSession,
        document_id: str,
        clause_id: int,
        *,
        owner_user_id: str | None = None,
    ) -> dict:
        document = await session.get(Document, document_id)
        if document is None or (
            owner_user_id is not None and document.owner_user_id != owner_user_id
        ):
            raise ValueError("Document not found")

        clause = await session.get(Clause, clause_id)
        if clause is None or clause.document_id != document_id:
            raise ValueError("Clause not found")

        findings_query = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id, RiskFinding.clause_id == clause.id)
            .order_by(RiskFinding.risk_score.desc())
        )
        findings = findings_query.scalars().all()

        return {
            "id": clause.id,
            "document_id": clause.document_id,
            "clause_type": clause.clause_type,
            "clause_title": clause.clause_title,
            "clause_text": clause.clause_text,
            "normalized_text": clause.normalized_text,
            "page_start": clause.page_start,
            "page_end": clause.page_end,
            "confidence_score": clause.confidence_score,
            "risks": [
                {
                    "finding_id": finding.id,
                    "risk_category": finding.risk_category,
                    "risk_level": finding.risk_level,
                    "risk_score": finding.risk_score,
                    "summary": finding.summary,
                    "why_risky": finding.why_risky,
                    "suggested_question": finding.suggested_question,
                    "page_number": finding.page_number,
                }
                for finding in findings
            ],
        }
