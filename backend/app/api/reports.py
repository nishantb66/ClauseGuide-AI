from fastapi import APIRouter, Depends, HTTPException, status
from urllib.parse import quote
from fastapi.responses import StreamingResponse
from app.core.mongo import MongoStore

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.mongo import file_chunks
from app.models.user import User
from app.schemas.report_schema import (
    ReportGenerateRequest,
    ReportGenerateResponse,
    ReportListResponse,
    ReportSummaryResponse,
)
from app.services.report_service import ReportService

router = APIRouter(tags=["reports"])
service = ReportService()


@router.post("/documents/{document_id}/report", response_model=ReportGenerateResponse)
async def generate_report(
    document_id: str,
    payload: ReportGenerateRequest | None = None,
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReportGenerateResponse:
    output_format = payload.output_format if payload else "markdown"
    try:
        result = await service.generate_report(
            session,
            document_id=document_id,
            output_format=output_format,
            owner_user_id=current_user.id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            code = status.HTTP_404_NOT_FOUND
        elif "not processed" in detail.lower():
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc

    return ReportGenerateResponse(**result)


@router.get("/documents/{document_id}/reports", response_model=ReportListResponse)
async def list_reports(
    document_id: str,
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReportListResponse:
    try:
        result = await service.list_reports(
            session, document_id=document_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ReportListResponse(**result)


@router.get("/reports/{report_id}", response_model=ReportSummaryResponse)
async def get_report_summary(
    report_id: str,
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ReportSummaryResponse:
    try:
        result = await service.get_report_summary(
            session, report_id=report_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ReportSummaryResponse(**result)


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    session: MongoStore = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    try:
        report = await service.get_report_file(
            session, report_id=report_id, owner_user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    media_type = "text/markdown" if report.report_format == "markdown" else "text/plain"
    return StreamingResponse(
        file_chunks(report.id),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(report.file_name, safe='')}"},
    )
