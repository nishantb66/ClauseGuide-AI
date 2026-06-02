from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def send_otp(self, *, to_email: str, otp: str) -> None:
        if not self.settings.smtp_enabled:
            logger.warning("SMTP disabled. OTP for %s is %s", to_email, otp)
            return

        message = EmailMessage()
        message["Subject"] = "ClauseGuide AI verification code"
        message["From"] = self.settings.smtp_from_email
        message["To"] = to_email
        message.set_content(
            "Welcome to ClauseGuide AI.\n\n"
            f"Your verification code is: {otp}\n\n"
            f"This code expires in {self.settings.otp_expiry_minutes} minutes. "
            "If you did not request this, you can ignore this email."
        )

        with smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
            smtp.login(self.settings.smtp_username, self.settings.smtp_app_password)
            smtp.send_message(message)
