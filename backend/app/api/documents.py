from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.document_schema import DocumentSummary, DocumentUploadResponse, ProcessResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])
service = DocumentService()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    document = await service.upload_document(session, file, owner_user_id=current_user.id)
    return DocumentUploadResponse(document_id=document.id, status=document.status.value)


@router.post("/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProcessResponse:
    document, total_chunks, clauses_extracted, risk_findings = await service.process_document(
        session,
        document_id,
        owner_user_id=current_user.id,
    )
    return ProcessResponse(
        document_id=document.id,
        status=document.status.value,
        contract_type=document.contract_type or "unknown",
        total_pages=document.total_pages,
        total_chunks=total_chunks,
        clauses_extracted=clauses_extracted,
        risk_findings=risk_findings,
    )


@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[DocumentSummary]:
    documents = await service.list_documents(session, owner_user_id=current_user.id)
    return [
        DocumentSummary(
            id=document.id,
            title=document.title,
            file_name=document.file_name,
            file_type=document.file_type,
            contract_type=document.contract_type,
            status=document.status.value,
            total_pages=document.total_pages,
            uploaded_at=document.uploaded_at,
            processed_at=document.processed_at,
        )
        for document in documents
    ]
