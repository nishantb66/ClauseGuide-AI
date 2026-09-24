from __future__ import annotations

import logging
import math
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from app.core.mongo import (
    MongoStore, create_upload, delete_file_chunks, file_chunks, finish_upload,
    get_upload, has_file_chunk, put_file_chunk,
)
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
from app.services.title_report_analyzer import TitleReportAnalyzer

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
        self.title_report_analyzer = TitleReportAnalyzer()

    async def upload_document(
        self, session: MongoStore, upload: UploadFile, *, owner_user_id: str
    ) -> Document:
        if not upload.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name")

        extension = Path(upload.filename).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {extension}. Allowed: {sorted(self.settings.allowed_extensions)}",
            )

        file_id = uuid.uuid4().hex
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        total_bytes = 0
        index = 0
        try:
            while chunk := await upload.read(2 * 1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"File exceeds the {self.settings.max_upload_mb} MB upload limit.",
                    )
                await put_file_chunk(file_id, index, chunk)
                index += 1
        except Exception:
            await delete_file_chunks(file_id)
            raise
        if total_bytes == 0:
            await delete_file_chunks(file_id)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

        title = Path(upload.filename).stem
        document = Document(
            id=file_id,
            owner_user_id=owner_user_id,
            title=title,
            file_name=upload.filename,
            file_type=extension,
            file_path=f"mongo:{file_id}",
            status=DocumentStatus.uploaded,
        )
        session.add(document)
        try:
            await session.commit()
        except Exception:
            await delete_file_chunks(file_id)
            raise
        await session.refresh(document)
        return document

    async def start_chunked_upload(self, *, owner_user_id: str, file_name: str, size: int) -> dict:
        extension = Path(file_name).suffix.lower()
        if extension not in self.settings.allowed_extensions:
            raise HTTPException(status_code=400, detail="Unsupported file type")
        if size < 1 or size > self.settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Invalid file size")
        file_id = await create_upload(owner_user_id, file_name, size)
        return {"upload_id": file_id, "chunk_size": 2 * 1024 * 1024}

    async def add_upload_chunk(self, *, owner_user_id: str, upload_id: str, index: int, data: bytes) -> None:
        upload = await get_upload(upload_id, owner_user_id)
        if not upload or upload["complete"]:
            raise HTTPException(status_code=404, detail="Upload not found")
        chunk_size = 2 * 1024 * 1024
        count = math.ceil(upload["size"] / chunk_size)
        expected = chunk_size if index < count - 1 else upload["size"] - chunk_size * (count - 1)
        if index < 0 or index >= count or len(data) != expected:
            raise HTTPException(status_code=400, detail="Invalid chunk size or index")
        await put_file_chunk(upload_id, index, data, expires_at=upload["expires_at"])

    async def finish_chunked_upload(self, session: MongoStore, *, owner_user_id: str, upload_id: str) -> Document:
        upload = await get_upload(upload_id, owner_user_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        existing = await session.get(Document, upload_id)
        if existing:
            return existing
        count = math.ceil(upload["size"] / (2 * 1024 * 1024))
        for index in range(count):
            if not await has_file_chunk(upload_id, index):
                raise HTTPException(status_code=409, detail=f"Missing chunk {index}")
        await finish_upload(upload_id, owner_user_id)
        document = Document(
            id=upload_id,
            owner_user_id=owner_user_id,
            title=Path(upload["file_name"]).stem,
            file_name=upload["file_name"],
            file_type=Path(upload["file_name"]).suffix.lower(),
            file_path=f"mongo:{upload_id}",
            status=DocumentStatus.uploaded,
        )
        session.add(document)
        await session.commit()
        return document

    async def process_document(
        self,
        session: MongoStore,
        document_id: str,
        *,
        owner_user_id: str,
    ) -> tuple[Document, int, int, int]:
        document = await self.get_document(session, document_id, owner_user_id=owner_user_id)

        if not await has_file_chunk(document.id, 0):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded file not found"
            )

        await session.delete_many(DocumentPage, {"document_id": document_id})
        await session.delete_many(DocumentChunk, {"document_id": document_id})
        await session.delete_many(Clause, {"document_id": document_id})
        await session.delete_many(RiskFinding, {"document_id": document_id})

        try:
            document.status = DocumentStatus.parsing
            await session.commit()

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = Path(temp_dir) / f"source{document.file_type}"
                with file_path.open("wb") as target:
                    async for data in file_chunks(document.id):
                        target.write(data)
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

            is_title_report = document.contract_type == "legal_title_report"
            clause_drafts = [] if is_title_report else self.clause_extractor.extract(chunks)
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
            risk_analysis = (
                self.title_report_analyzer.analyze(cleaned_pages)
                if is_title_report
                else self.risk_engine.analyze(
                    document.contract_type or "unknown",
                    risk_inputs,
                    document_confidence=document_classification.confidence_score,
                )
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

            placeholder_issues = (
                [] if is_title_report else self.placeholder_detector.detect_pages(
                    [(page.page_number, page.cleaned_text) for page in cleaned_pages]
                )
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

    async def list_documents(self, session: MongoStore, *, owner_user_id: str) -> list[Document]:
        return await session.find(
            Document, {"owner_user_id": owner_user_id}, sort=[("uploaded_at", -1)]
        )

    async def get_document(
        self, session: MongoStore, document_id: str, *, owner_user_id: str
    ) -> Document:
        document = await session.get(Document, document_id)
        if document is None or document.owner_user_id != owner_user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return document

    @staticmethod
    def _normalize_clause_text(text: str) -> str:
        return " ".join(text.lower().split()).strip()
