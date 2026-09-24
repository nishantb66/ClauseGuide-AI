import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_google_auth_creates_user_when_auto_signup_enabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = AuthService()
    previous_setting = service.settings.google_auto_signup_enabled
    service.settings.google_auto_signup_enabled = True
    service._verify_google_id_token = lambda _: {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "google-user-1",
        "name": "New User",
    }
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await service.google_auth(
                session, code=None, id_token="verified-token", redirect_uri=None
            )
            assert result["user"]["email"] == "new@example.com"
            assert result["user"]["auth_provider"] == "google"
            assert await session.get(User, result["user"]["id"]) is not None
    finally:
        service.settings.google_auto_signup_enabled = previous_setting
        await engine.dispose()


@pytest.mark.asyncio
async def test_google_auth_blocks_auto_signup_when_disabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = AuthService()
    previous_setting = service.settings.google_auto_signup_enabled
    service.settings.google_auto_signup_enabled = False
    service._verify_google_id_token = lambda _: {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "google-user-1",
    }
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with pytest.raises(HTTPException) as error:
                await service.google_auth(
                    session, code=None, id_token="verified-token", redirect_uri=None
                )
            assert error.value.status_code == 403
    finally:
        service.settings.google_auto_signup_enabled = previous_setting
        await engine.dispose()
