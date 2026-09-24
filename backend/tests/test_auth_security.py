from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService


def test_password_hash_and_verify() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_access_token_round_trip() -> None:
    token, expires_in = create_access_token("user-123", email="user@example.com")
    payload = decode_access_token(token)

    assert expires_in > 0
    assert payload["sub"] == "user-123"
    assert payload["email"] == "user@example.com"


def test_google_code_exchange_rejects_unconfigured_redirect() -> None:
    service = AuthService()
    old_client_id = service.settings.google_client_id
    old_client_secret = service.settings.google_client_secret
    old_redirect_uri = service.settings.google_redirect_uri
    service.settings.google_client_id = "client-id"
    service.settings.google_client_secret = "client-secret"
    service.settings.google_redirect_uri = "https://example.com/google/callback/"
    try:
        with pytest.raises(HTTPException) as error:
            service._exchange_google_code("test-code", "https://attacker.example/callback/")
        assert error.value.status_code == 400
    finally:
        service.settings.google_client_id = old_client_id
        service.settings.google_client_secret = old_client_secret
        service.settings.google_redirect_uri = old_redirect_uri


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file_and_removes_partial_copy(tmp_path) -> None:
    service = DocumentService()
    old_upload_dir = service.settings.upload_dir
    old_limit = service.settings.max_upload_mb
    service.settings.upload_dir = str(tmp_path)
    service.settings.max_upload_mb = 1
    try:
        upload = UploadFile(filename="contract.pdf", file=BytesIO(b"x" * (1024 * 1024 + 1)))
        with pytest.raises(HTTPException) as error:
            await service.upload_document(None, upload, owner_user_id="user-id")
        assert error.value.status_code == 413
        assert list(tmp_path.iterdir()) == []
    finally:
        service.settings.upload_dir = old_upload_dir
        service.settings.max_upload_mb = old_limit
