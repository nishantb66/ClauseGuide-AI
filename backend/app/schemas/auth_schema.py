from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=160)


class RegisterResponse(BaseModel):
    user_id: str
    email: EmailStr
    otp_required: bool
    message: str


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=4, max_length=10)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthRequest(BaseModel):
    code: str | None = None
    id_token: str | None = None
    redirect_uri: str | None = None


class ResendOTPRequest(BaseModel):
    email: EmailStr


class UserProfile(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None
    auth_provider: str
    is_email_verified: bool
    created_at: datetime
    last_login_at: datetime | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile


class MessageResponse(BaseModel):
    message: str
