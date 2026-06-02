from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


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
