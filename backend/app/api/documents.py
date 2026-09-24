from fastapi import APIRouter, Depends, File, UploadFile, Request
from pydantic import BaseModel, Field
from app.core.mongo import MongoStore

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.document_schema import DocumentSummary, DocumentUploadResponse, ProcessResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])
service = DocumentService()


class UploadStart(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)


@router.post("/uploads")
async def start_upload(
    payload: UploadStart,
    current_user: User = Depends(get_current_user),
) -> dict:
    return await service.start_chunked_upload(
        owner_user_id=current_user.id, file_name=payload.file_name, size=payload.size
    )


@router.put("/uploads/{upload_id}/chunks/{index}", status_code=204)
async def upload_chunk(
    upload_id: str,
    index: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 2 * 1024 * 1024:
        from fastapi import HTTPException
        raise HTTPException(status_code=413, detail="Chunk too large")
    data = await request.body()
    await service.add_upload_chunk(
        owner_user_id=current_user.id, upload_id=upload_id, index=index, data=data
    )


@router.post("/uploads/{upload_id}/complete", response_model=DocumentUploadResponse)
async def complete_upload(
    upload_id: str,
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    document = await service.finish_chunked_upload(
        session, owner_user_id=current_user.id, upload_id=upload_id
    )
    return DocumentUploadResponse(document_id=document.id, status=document.status.value)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DocumentUploadResponse:
    document = await service.upload_document(session, file, owner_user_id=current_user.id)
    return DocumentUploadResponse(document_id=document.id, status=document.status.value)


@router.post("/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    session: MongoStore = Depends(get_session),
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
    session: MongoStore = Depends(get_session),
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
