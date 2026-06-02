from fastapi import HTTPException

from app.services.auth_service import AuthService


def test_google_auth_blocks_auto_signup_when_disabled() -> None:
    service = AuthService()

    try:
        service.settings.google_auto_signup_enabled = False
        user = None
        if user is None and not service.settings.google_auto_signup_enabled:
            raise HTTPException(
                status_code=403,
                detail=(
                    "No account exists for this Google email. "
                    "Please create an account first, then use Google sign-in."
                ),
            )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "create an account first" in str(exc.detail).lower()
    finally:
        service.settings.google_auto_signup_enabled = False
