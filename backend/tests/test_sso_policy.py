import uuid

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.services.auth_service import AuthService


class AuthStore:
    """Minimal persistence double for Google sign-in policy tests."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.pending: list[User] = []

    async def one(self, model_type: type, filters: dict) -> User | None:
        assert model_type is User
        return next(
            (user for user in self.users.values() if all(getattr(user, key) == value for key, value in filters.items())),
            None,
        )

    async def get(self, model_type: type, user_id: str) -> User | None:
        assert model_type is User
        return self.users.get(user_id)

    def add(self, user: User) -> None:
        self.pending.append(user)

    async def flush(self) -> None:
        for user in self.pending:
            if user.id is None:
                user.id = str(uuid.uuid4())

    async def commit(self) -> None:
        await self.flush()
        for user in self.pending:
            self.users[user.id] = user
        self.pending.clear()

    async def refresh(self, user: User) -> None:
        return None


@pytest.mark.asyncio
async def test_google_auth_creates_user_when_auto_signup_enabled() -> None:
    service = AuthService()
    session = AuthStore()
    previous_setting = service.settings.google_auto_signup_enabled
    service.settings.google_auto_signup_enabled = True
    service._verify_google_id_token = lambda _: {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "google-user-1",
        "name": "New User",
    }
    try:
        result = await service.google_auth(
            session, code=None, id_token="verified-token", redirect_uri=None
        )
        assert result["user"]["email"] == "new@example.com"
        assert result["user"]["auth_provider"] == "google"
        assert await session.get(User, result["user"]["id"]) is not None
    finally:
        service.settings.google_auto_signup_enabled = previous_setting


@pytest.mark.asyncio
async def test_google_auth_blocks_auto_signup_when_disabled() -> None:
    service = AuthService()
    session = AuthStore()
    previous_setting = service.settings.google_auto_signup_enabled
    service.settings.google_auto_signup_enabled = False
    service._verify_google_id_token = lambda _: {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "google-user-1",
    }
    try:
        with pytest.raises(HTTPException) as error:
            await service.google_auth(
                session, code=None, id_token="verified-token", redirect_uri=None
            )
        assert error.value.status_code == 403
    finally:
        service.settings.google_auto_signup_enabled = previous_setting
