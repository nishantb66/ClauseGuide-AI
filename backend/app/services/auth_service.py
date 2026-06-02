from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    generate_otp,
    hash_otp,
    hash_password,
    verify_password,
)
from app.core.settings import get_settings
from app.models.user import AuthProvider, EmailOTP, User
from app.services.email_service import EmailService


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.email_service = EmailService()

    async def register(
        self, session: AsyncSession, *, email: str, password: str, full_name: str | None
    ) -> User:
        normalized_email = self._normalize_email(email)
        existing = await self._user_by_email(session, normalized_email)
        if existing and existing.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account already exists for this email.",
            )

        if existing:
            existing.password_hash = hash_password(password)
            existing.full_name = full_name or existing.full_name
            existing.auth_provider = AuthProvider.email
            user = existing
        else:
            user = User(
                email=normalized_email,
                full_name=full_name,
                password_hash=hash_password(password),
                auth_provider=AuthProvider.email,
                is_active=False,
                is_email_verified=False,
            )
            session.add(user)
            await session.flush()

        await self._issue_signup_otp(session, user)
        await session.commit()
        await session.refresh(user)
        return user

    async def resend_otp(self, session: AsyncSession, *, email: str) -> None:
        user = await self._user_by_email(session, self._normalize_email(email))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        if user.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already verified.",
            )
        await self._issue_signup_otp(session, user)
        await session.commit()

    async def verify_otp(self, session: AsyncSession, *, email: str, otp: str) -> dict:
        user = await self._user_by_email(session, self._normalize_email(email))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

        otp_row = await self._latest_active_otp(session, user.id)
        if otp_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code expired. Request a new OTP.",
            )
        if otp_row.attempts >= self.settings.otp_max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP attempts. Request a new OTP.",
            )

        otp_row.attempts += 1
        if otp_row.otp_hash != hash_otp(otp.strip()):
            await session.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

        now = datetime.now(UTC)
        otp_row.consumed_at = now
        user.is_active = True
        user.is_email_verified = True
        user.last_login_at = now
        await session.commit()
        await session.refresh(user)
        return self._auth_payload(user)

    async def login(self, session: AsyncSession, *, email: str, password: str) -> dict:
        user = await self._user_by_email(session, self._normalize_email(email))
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not user.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email OTP before logging in.",
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

        user.last_login_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(user)
        return self._auth_payload(user)

    async def google_auth(
        self,
        session: AsyncSession,
        *,
        code: str | None,
        id_token: str | None,
        redirect_uri: str | None,
    ) -> dict:
        if not code and not id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide a Google authorization code or ID token.",
            )
        token = id_token or await asyncio.to_thread(
            self._exchange_google_code,
            code,
            redirect_uri or self.settings.google_redirect_uri,
        )
        claims = await asyncio.to_thread(self._verify_google_id_token, token)
        email = self._normalize_email(str(claims.get("email", "")))
        if not email or not claims.get("email_verified"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google account email is not verified.",
            )

        user = await self._user_by_email(session, email)
        if user is None:
            if not self.settings.google_auto_signup_enabled:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "No account exists for this Google email. "
                        "Please create an account first, then use Google sign-in."
                    ),
                )
            user = User(
                email=email,
                full_name=claims.get("name"),
                auth_provider=AuthProvider.google,
                google_sub=str(claims.get("sub")),
                is_active=True,
                is_email_verified=True,
            )
            session.add(user)
        else:
            user.google_sub = user.google_sub or str(claims.get("sub"))
            user.full_name = user.full_name or claims.get("name")
            user.is_active = True
            user.is_email_verified = True

        user.last_login_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(user)
        return self._auth_payload(user)

    async def _issue_signup_otp(self, session: AsyncSession, user: User) -> None:
        await session.execute(
            update(EmailOTP)
            .where(EmailOTP.user_id == user.id, EmailOTP.consumed_at.is_(None))
            .values(consumed_at=datetime.now(UTC))
        )
        otp = generate_otp()
        session.add(
            EmailOTP(
                user_id=user.id,
                otp_hash=hash_otp(otp),
                purpose="signup",
                expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.otp_expiry_minutes),
            )
        )
        await asyncio.to_thread(self.email_service.send_otp, to_email=user.email, otp=otp)

    async def _latest_active_otp(self, session: AsyncSession, user_id: str) -> EmailOTP | None:
        rows = await session.execute(
            select(EmailOTP)
            .where(
                EmailOTP.user_id == user_id,
                EmailOTP.purpose == "signup",
                EmailOTP.consumed_at.is_(None),
                EmailOTP.expires_at > datetime.now(UTC),
            )
            .order_by(EmailOTP.created_at.desc())
            .limit(1)
        )
        return rows.scalar_one_or_none()

    async def _user_by_email(self, session: AsyncSession, email: str) -> User | None:
        rows = await session.execute(select(User).where(User.email == email))
        return rows.scalar_one_or_none()

    def _auth_payload(self, user: User) -> dict:
        token, expires_in = create_access_token(user.id, email=user.email)
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": self.user_profile(user),
        }

    @staticmethod
    def user_profile(user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "auth_provider": user.auth_provider.value,
            "is_email_verified": user.is_email_verified,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        }

    def _exchange_google_code(self, code: str | None, redirect_uri: str) -> str:
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Google code"
            )
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google SSO is not configured",
            )
        body = urllib.parse.urlencode(
            {
                "code": code,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode()
        request = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        id_token = payload.get("id_token")
        if not id_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token exchange failed"
            )
        return str(id_token)

    def _verify_google_id_token(self, id_token: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"id_token": id_token})
        with urllib.request.urlopen(
            f"https://oauth2.googleapis.com/tokeninfo?{query}", timeout=15
        ) as response:
            claims = json.loads(response.read().decode("utf-8"))
        if claims.get("aud") != self.settings.google_client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token audience"
            )
        if int(claims.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token expired"
            )
        return claims

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()
