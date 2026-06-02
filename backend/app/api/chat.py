from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.chat_schema import ChatRequest, ChatResponse, ChatSource
from app.services.chat_service import ChatService

router = APIRouter(prefix="/documents", tags=["chat"])
service = ChatService()


@router.post("/{document_id}/chat", response_model=ChatResponse)
async def ask_contract(
    document_id: str,
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    result = await service.ask(
        session,
        document_id=document_id,
        question=payload.question,
        session_id=payload.session_id,
        owner_user_id=current_user.id,
    )

    return ChatResponse(
        answer=result["answer"],
        confidence_score=float(result["confidence_score"]),
        confidence_label=result["confidence_label"],
        sources=[ChatSource(**source) for source in result.get("sources", [])],
        disclaimer=result["disclaimer"],
        intent=result["intent"],
        required_clause_types=result.get("required_clause_types", []),
        session_id=result["session_id"],
        verification=result.get("verification"),
    )
