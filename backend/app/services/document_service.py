from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.clause import Clause, RiskFinding
from app.models.document import Document, DocumentChunk, DocumentPage, DocumentStatus
from app.services.chunker import LegalChunker
from app.services.clause_extractor import ClauseExtractor
from app.services.document_classifier import DocumentClassifier
from app.services.document_parser import DocumentParser
from app.services.embedding_service import EmbeddingService
from app.services.placeholder_detector import PlaceholderDetector
from app.services.risk_engine import ClauseRiskInput, RiskEngine
from app.services.text_cleaner import TextCleaner

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.parser = DocumentParser()
        self.cleaner = TextCleaner()
        self.chunker = LegalChunker()
        self.embedding_service = EmbeddingService()
        self.document_classifier = DocumentClassifier()
        self.clause_extractor = ClauseExtractor(self.embedding_service)
        self.placeholder_detector = PlaceholderDetector()
        self.risk_engine = RiskEngine()

    async def upload_document(
        self, session: AsyncSession, upload: UploadFile, *, owner_user_id: str
    ) -> Document:
        if not upload.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name")

        extension = Path(upload.filename).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {extension}. Allowed: {sorted(self.settings.allowed_extensions)}",
            )

        storage_path = (
            self.settings.upload_path / f"{datetime.now(UTC).timestamp()}_{upload.filename}"
        )
        with storage_path.open("wb") as target:
            shutil.copyfileobj(upload.file, target)

        title = Path(upload.filename).stem
        document = Document(
            owner_user_id=owner_user_id,
            title=title,
            file_name=upload.filename,
            file_type=extension,
            file_path=str(storage_path),
            status=DocumentStatus.uploaded,
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document

    async def process_document(
        self,
        session: AsyncSession,
        document_id: str,
        *,
        owner_user_id: str,
    ) -> tuple[Document, int, int, int]:
        document = await self.get_document(session, document_id, owner_user_id=owner_user_id)

        file_path = Path(document.file_path)
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded file not found"
            )

        await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        await session.execute(delete(Clause).where(Clause.document_id == document_id))
        await session.execute(delete(RiskFinding).where(RiskFinding.document_id == document_id))

        try:
            document.status = DocumentStatus.parsing
            await session.commit()

            extracted_pages = self.parser.parse(file_path)
            cleaned_pages = self.cleaner.clean_pages(extracted_pages)

            for page in cleaned_pages:
                session.add(
                    DocumentPage(
                        document_id=document.id,
                        page_number=page.page_number,
                        raw_text=page.raw_text,
                        cleaned_text=page.cleaned_text,
                    )
                )

            full_text = "\n\n".join(
                page.cleaned_text for page in cleaned_pages if page.cleaned_text
            )
            document_classification = self.document_classifier.classify(cleaned_pages)
            document.contract_type = document_classification.primary_document_type

            document.total_pages = len(cleaned_pages)
            document.status = DocumentStatus.chunking
            await session.commit()

            chunks = self.chunker.chunk_pages(cleaned_pages)
            embeddings = self.embedding_service.embed_texts([chunk.chunk_text for chunk in chunks])

            document.status = DocumentStatus.embedding
            await session.commit()

            for chunk, embedding in zip(chunks, embeddings, strict=False):
                session.add(
                    DocumentChunk(
                        document_id=document.id,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        chunk_text=chunk.chunk_text,
                        token_count=chunk.token_count,
                        section_title=chunk.section_title,
                        clause_type=chunk.clause_type,
                        start_char=chunk.start_char,
                        end_char=chunk.end_char,
                        embedding=embedding,
                    )
                )

            clause_drafts = self.clause_extractor.extract(chunks)
            clause_rows: list[Clause] = []
            for clause_draft in clause_drafts:
                clause_row = Clause(
                    document_id=document.id,
                    clause_type=clause_draft.clause_type,
                    clause_title=clause_draft.clause_title,
                    clause_text=clause_draft.clause_text,
                    normalized_text=self._normalize_clause_text(clause_draft.clause_text),
                    page_start=clause_draft.page_start,
                    page_end=clause_draft.page_end,
                    confidence_score=clause_draft.confidence_score,
                )
                session.add(clause_row)
                clause_rows.append(clause_row)

            await session.flush()

            risk_inputs = [
                ClauseRiskInput(
                    id=clause.id,
                    clause_type=clause.clause_type,
                    clause_title=clause.clause_title,
                    clause_text=clause.clause_text,
                    normalized_text=clause.normalized_text,
                    page_start=clause.page_start,
                )
                for clause in clause_rows
            ]
            risk_analysis = self.risk_engine.analyze(
                document.contract_type or "unknown",
                risk_inputs,
                document_confidence=document_classification.confidence_score,
            )

            for finding in risk_analysis.findings:
                session.add(
                    RiskFinding(
                        document_id=document.id,
                        clause_id=finding.clause_id,
                        risk_category=finding.risk_category,
                        risk_level=finding.risk_level,
                        risk_score=finding.risk_score,
                        summary=finding.summary,
                        why_risky=finding.why_risky,
                        suggested_question=finding.suggested_question,
                        evidence_text=finding.evidence_text,
                        page_number=finding.page_number,
                        confidence_score=finding.confidence_score,
                    )
                )

            placeholder_issues = self.placeholder_detector.detect_pages(
                [(page.page_number, page.cleaned_text) for page in cleaned_pages]
            )
            for issue in placeholder_issues:
                score = 38 if issue.severity == "medium" else 18
                session.add(
                    RiskFinding(
                        document_id=document.id,
                        clause_id=None,
                        risk_category="blank_placeholder_risk",
                        risk_level="medium" if issue.severity == "medium" else "low",
                        risk_score=score,
                        summary=f"Unfilled template field detected: {issue.field}.",
                        why_risky=(
                            "The document appears to contain a blank placeholder. This usually means the field exists "
                            "but has not been completed, so commercial or legal terms may be unresolved."
                        ),
                        suggested_question=f"Can the {issue.field} be completed before signing or relying on this document?",
                        evidence_text=issue.evidence_text,
                        page_number=issue.page_number,
                        confidence_score=issue.confidence_score,
                    )
                )

            document.status = DocumentStatus.analyzed
            document.processed_at = datetime.now(UTC)
            document.error_message = None
            await session.commit()
            await session.refresh(document)
            return document, len(chunks), len(clause_rows), len(risk_analysis.findings)

        except Exception as exc:
            logger.exception("Document processing failed for %s", document_id)
            document.status = DocumentStatus.failed
            document.error_message = str(exc)
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Processing failed: {exc}",
            ) from exc

    async def list_documents(self, session: AsyncSession, *, owner_user_id: str) -> list[Document]:
        rows = await session.execute(
            select(Document)
            .where(Document.owner_user_id == owner_user_id)
            .order_by(Document.uploaded_at.desc())
        )
        return rows.scalars().all()

    async def get_document(
        self, session: AsyncSession, document_id: str, *, owner_user_id: str
    ) -> Document:
        document = await session.get(Document, document_id)
        if document is None or document.owner_user_id != owner_user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document

    @staticmethod
    def _normalize_clause_text(text: str) -> str:
        return " ".join(text.lower().split()).strip()
