from __future__ import annotations

import re
from pathlib import Path

import anyio
import fitz
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentPage, DocumentStatus
from app.services.verification_service import VerificationService


class DocumentReviewService:
    """Builds source-highlight payloads for the interactive document review UI."""

    sentence_re = re.compile(r"(?<=[.!?;:])\s+|\n+")
    token_re = re.compile(r"\w+")

    def __init__(self) -> None:
        self.verifier = VerificationService()

    async def get_review_workspace(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        owner_user_id: str,
    ) -> dict:
        document, pages, clauses, findings = await self._load_review_data(
            session, document_id=document_id, owner_user_id=owner_user_id
        )
        clause_map = {clause.id: clause for clause in clauses}
        page_map = {page.page_number: page for page in pages}

        pdf_document = self._open_pdf(document)
        try:
            risks = [
                self._build_review_risk(
                    document=document,
                    finding=finding,
                    clause=clause_map.get(finding.clause_id) if finding.clause_id else None,
                    page_map=page_map,
                    pdf_document=pdf_document,
                )
                for finding in findings
            ]
        finally:
            if pdf_document is not None:
                pdf_document.close()

        return {
            "document_id": document.id,
            "title": document.title,
            "file_name": document.file_name,
            "file_type": document.file_type,
            "total_pages": document.total_pages,
            "file_url": f"/api/documents/{document.id}/file",
            "canvas_mode": "pdf" if document.file_type == ".pdf" else "text",
            "risks": risks,
            "pages": self._page_payload(pages),
        }

    async def get_important_points(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        owner_user_id: str,
    ) -> dict:
        workspace = await self.get_review_workspace(
            session,
            document_id=document_id,
            owner_user_id=owner_user_id,
        )
        risks = workspace["risks"]
        ranked = sorted(
            risks,
            key=lambda item: (
                item["risk_score"],
                1 if item.get("verification", {}).get("status") == "verified" else 0,
            ),
            reverse=True,
        )

        points = []
        seen: set[tuple[str, int]] = set()
        for risk in ranked:
            key = (risk["clause_type"], risk["page"])
            if key in seen:
                continue
            seen.add(key)
            points.append(
                {
                    "id": f"important-{risk['finding_id']}",
                    "title": risk["title"],
                    "reason": risk["summary"],
                    "action": risk["suggested_question"],
                    "risk_level": risk["risk_level"],
                    "risk_score": risk["risk_score"],
                    "page": risk["page"],
                    "source_finding_id": risk["finding_id"],
                    "highlight": risk.get("highlight"),
                    "verification": risk.get("verification"),
                }
            )
            if len(points) >= 10:
                break

        return {
            "document_id": workspace["document_id"],
            "title": workspace["title"],
            "file_name": workspace["file_name"],
            "file_type": workspace["file_type"],
            "total_pages": workspace["total_pages"],
            "file_url": workspace["file_url"],
            "canvas_mode": workspace["canvas_mode"],
            "points": points,
            "pages": workspace["pages"],
        }

    async def get_document_file(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        owner_user_id: str,
    ) -> tuple[Document, Path]:
        document = await self._load_document(
            session, document_id=document_id, owner_user_id=owner_user_id
        )
        file_path = Path(document.file_path)
        if not await anyio.Path(file_path).exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        return document, file_path

    async def _load_review_data(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        owner_user_id: str,
    ) -> tuple[Document, list[DocumentPage], list[Clause], list[RiskFinding]]:
        document = await self._load_document(
            session, document_id=document_id, owner_user_id=owner_user_id
        )
        if document.status != DocumentStatus.analyzed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document must be analysed before opening the review workspace.",
            )

        page_rows = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
        )
        clause_rows = await session.execute(select(Clause).where(Clause.document_id == document_id))
        finding_rows = await session.execute(
            select(RiskFinding)
            .where(RiskFinding.document_id == document_id)
            .order_by(RiskFinding.risk_score.desc(), RiskFinding.id.asc())
        )
        return (
            document,
            list(page_rows.scalars().all()),
            list(clause_rows.scalars().all()),
            list(finding_rows.scalars().all()),
        )

    async def _load_document(
        self,
        session: AsyncSession,
        *,
        document_id: str,
        owner_user_id: str,
    ) -> Document:
        document = await session.get(Document, document_id)
        if document is None or document.owner_user_id != owner_user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document

    def _build_review_risk(
        self,
        *,
        document: Document,
        finding: RiskFinding,
        clause: Clause | None,
        page_map: dict[int, DocumentPage],
        pdf_document: fitz.Document | None,
    ) -> dict:
        clause_type = clause.clause_type if clause else self._clause_type_from_finding(finding)
        page_number = finding.page_number or (clause.page_start if clause else 1)
        page = page_map.get(page_number)
        statement = self._best_statement(
            finding=finding,
            clause=clause,
            page_text=page.cleaned_text if page else "",
        )
        highlight = self._build_highlight(
            pdf_document=pdf_document,
            page=page,
            statement=statement,
        )
        verification = self.verifier.verify_risk_finding(
            finding=finding,
            clause=clause,
            contract_type=document.contract_type or "unknown",
        )
        return {
            "finding_id": finding.id,
            "clause_id": finding.clause_id,
            "clause_type": clause_type,
            "risk_category": finding.risk_category,
            "risk_level": finding.risk_level,
            "risk_score": finding.risk_score,
            "title": self._pretty_label(clause_type),
            "summary": finding.summary,
            "why_risky": finding.why_risky,
            "suggested_question": finding.suggested_question,
            "page": page_number,
            "evidence": finding.evidence_text,
            "highlight": highlight,
            "verification": verification,
        }

    def _best_statement(
        self,
        *,
        finding: RiskFinding,
        clause: Clause | None,
        page_text: str,
    ) -> str:
        evidence_candidates = self._statement_candidates(finding.evidence_text)
        clause_candidates = self._statement_candidates(clause.clause_text if clause else "")
        candidates = [*evidence_candidates, *clause_candidates]
        if not candidates:
            return self._compact(finding.evidence_text, 360)

        query = " ".join(
            [
                finding.summary,
                finding.why_risky,
                finding.risk_category.replace("_", " "),
                clause.clause_type.replace("_", " ") if clause else "",
            ]
        )
        query_tokens = set(self._tokens(query))
        page_norm = self._normalize(page_text)

        def score(candidate: str) -> float:
            candidate_tokens = set(self._tokens(candidate))
            overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
            exact_bonus = 0.45 if self._normalize(candidate) in page_norm else 0.0
            length_bonus = 0.12 if 45 <= len(candidate) <= 420 else 0.0
            return overlap + exact_bonus + length_bonus

        best = max(candidates, key=score)
        return self._compact(best, 520)

    def _build_highlight(
        self,
        *,
        pdf_document: fitz.Document | None,
        page: DocumentPage | None,
        statement: str,
    ) -> dict | None:
        if page is None or not statement:
            return None

        start_char, end_char, text_confidence = self._locate_offsets(
            page.cleaned_text,
            statement,
        )
        rects = self._pdf_rects(
            pdf_document=pdf_document,
            page_number=page.page_number,
            statement=statement,
        )
        rect_confidence = 1.0 if rects else 0.0
        confidence = max(text_confidence, rect_confidence)
        return {
            "page": page.page_number,
            "statement": statement,
            "start_char": start_char,
            "end_char": end_char,
            "match_confidence": round(confidence, 3),
            "rects": rects,
        }

    def _pdf_rects(
        self,
        *,
        pdf_document: fitz.Document | None,
        page_number: int,
        statement: str,
    ) -> list[dict]:
        if pdf_document is None or page_number <= 0 or page_number > pdf_document.page_count:
            return []

        page = pdf_document.load_page(page_number - 1)
        search_terms = self._pdf_search_terms(statement)
        rects: list[dict] = []
        for term in search_terms:
            matches = page.search_for(term, quads=False)
            if not matches:
                continue
            page_rect = page.rect
            rects = [
                {
                    "page": page_number,
                    "x0": round(rect.x0, 2),
                    "y0": round(rect.y0, 2),
                    "x1": round(rect.x1, 2),
                    "y1": round(rect.y1, 2),
                    "page_width": round(page_rect.width, 2),
                    "page_height": round(page_rect.height, 2),
                }
                for rect in matches[:12]
            ]
            break
        return rects

    def _locate_offsets(self, text: str, statement: str) -> tuple[int | None, int | None, float]:
        normalized_text, index_map = self._normalized_with_index_map(text)
        normalized_statement = self._normalize(statement)
        if not normalized_text or not normalized_statement:
            return None, None, 0.0

        candidates = [normalized_statement]
        if len(normalized_statement) > 180:
            candidates.append(normalized_statement[:180].rstrip())
        if len(normalized_statement) > 90:
            candidates.append(normalized_statement[:90].rstrip())

        for candidate in candidates:
            position = normalized_text.find(candidate)
            if position < 0:
                continue
            start = index_map[position]
            end = index_map[min(position + len(candidate) - 1, len(index_map) - 1)] + 1
            confidence = min(1.0, len(candidate) / max(1, len(normalized_statement)))
            return start, end, confidence

        return None, None, 0.0

    def _statement_candidates(self, text: str) -> list[str]:
        normalized = " ".join((text or "").split())
        if not normalized or normalized.lower().startswith("not found"):
            return []

        parts = [part.strip() for part in self.sentence_re.split(normalized) if part.strip()]
        candidates = [
            part
            for part in parts
            if 28 <= len(part) <= 650 and len(self._tokens(part)) >= 5
        ]
        if candidates:
            return candidates[:24]
        return [self._compact(normalized, 520)]

    @staticmethod
    def _open_pdf(document: Document) -> fitz.Document | None:
        if document.file_type != ".pdf":
            return None
        file_path = Path(document.file_path)
        if not file_path.exists():
            return None
        return fitz.open(file_path)

    @staticmethod
    def _pdf_search_terms(statement: str) -> list[str]:
        compact = " ".join(statement.split()).strip()
        if not compact:
            return []
        terms = [compact[:240]]
        words = compact.split()
        if len(words) > 16:
            terms.append(" ".join(words[:16]))
        if len(words) > 10:
            terms.append(" ".join(words[:10]))
        return list(dict.fromkeys(term for term in terms if len(term) >= 24))

    @staticmethod
    def _normalized_with_index_map(text: str) -> tuple[str, list[int]]:
        output: list[str] = []
        index_map: list[int] = []
        previous_space = True
        for index, char in enumerate(text):
            if char.isspace():
                if not previous_space:
                    output.append(" ")
                    index_map.append(index)
                previous_space = True
                continue
            output.append(char.lower())
            index_map.append(index)
            previous_space = False
        while output and output[-1] == " ":
            output.pop()
            index_map.pop()
        return "".join(output), index_map

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [
            token.lower()
            for token in DocumentReviewService.token_re.findall(text)
            if len(token) > 2
        ]

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").lower().split()).strip()

    @staticmethod
    def _compact(text: str, max_chars: int) -> str:
        normalized = " ".join((text or "").split()).strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _pretty_label(value: str) -> str:
        return value.replace("_", " ").title()

    @staticmethod
    def _clause_type_from_finding(finding: RiskFinding) -> str:
        if finding.risk_category == "blank_placeholder_risk":
            return "other"
        if ":" in finding.summary:
            return (
                finding.summary.split(":", 1)[1]
                .strip(" .")
                .lower()
                .replace(" ", "_")
                .replace("-", "_")
            )
        return finding.risk_category.replace("_risk", "")

    @staticmethod
    def _page_payload(pages: list[DocumentPage]) -> list[dict]:
        return [{"page": page.page_number, "text": page.cleaned_text} for page in pages]
