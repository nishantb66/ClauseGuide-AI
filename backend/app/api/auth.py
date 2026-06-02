from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.auth_schema import (
    AuthResponse,
    GoogleAuthRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendOTPRequest,
    UserProfile,
    VerifyOTPRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
service = AuthService()


@router.post("/register", response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> RegisterResponse:
    user = await service.register(
        session,
        email=str(payload.email),
        password=payload.password,
        full_name=payload.full_name,
    )
    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        otp_required=True,
        message="Verification OTP sent to your email.",
    )


@router.post("/verify-otp", response_model=AuthResponse)
async def verify_otp(
    payload: VerifyOTPRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    return AuthResponse(
        **await service.verify_otp(session, email=str(payload.email), otp=payload.otp)
    )


@router.post("/resend-otp", response_model=MessageResponse)
async def resend_otp(
    payload: ResendOTPRequest,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    await service.resend_otp(session, email=str(payload.email))
    return MessageResponse(message="A new verification OTP has been sent.")


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    return AuthResponse(
        **await service.login(session, email=str(payload.email), password=payload.password)
    )


@router.post("/google", response_model=AuthResponse)
async def google_auth(
    payload: GoogleAuthRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    return AuthResponse(
        **await service.google_auth(
            session,
            code=payload.code,
            id_token=payload.id_token,
            redirect_uri=payload.redirect_uri,
        )
    )


@router.get("/me", response_model=UserProfile)
async def me(current_user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile(**service.user_profile(current_user))
