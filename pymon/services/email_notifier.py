"""Email notifier for skill completion events.

Sends SMTP emails when skills finish training or the queue
becomes empty, as an alternative to tray notifications.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications via SMTP."""

    def __init__(
        self,
        smtp_server: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        email_to: str = "",
        use_tls: bool = True,
    ) -> None:
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_to = email_to
        self.use_tls = use_tls

    @property
    def is_configured(self) -> bool:
        """Return True if all required fields are set."""
        return bool(
            self.smtp_server
            and self.smtp_user
            and self.smtp_password
            and self.email_to
        )

    def update_settings(
        self,
        smtp_server: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        email_to: str,
        use_tls: bool = True,
    ) -> None:
        """Update SMTP settings."""
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_to = email_to
        self.use_tls = use_tls

    def send_skill_completed(
        self,
        character_name: str,
        skill_name: str,
        level: int,
    ) -> bool:
        """Send notification that a skill has finished training."""
        subject = f"[PyMon] {character_name}: {skill_name} Level {level} abgeschlossen"
        body_html = f"""
        <html><body style="background:#0d1117;color:#c9d1d9;font-family:Arial,sans-serif;padding:20px">
        <h2 style="color:#4ecca3">✅ Skill abgeschlossen</h2>
        <table style="border-collapse:collapse">
            <tr><td style="padding:4px 12px;color:#8b949e">Character:</td>
                <td style="padding:4px 12px"><b>{character_name}</b></td></tr>
            <tr><td style="padding:4px 12px;color:#8b949e">Skill:</td>
                <td style="padding:4px 12px"><b>{skill_name}</b></td></tr>
            <tr><td style="padding:4px 12px;color:#8b949e">Level:</td>
                <td style="padding:4px 12px"><b>{level}</b></td></tr>
            <tr><td style="padding:4px 12px;color:#8b949e">Zeitpunkt:</td>
                <td style="padding:4px 12px">{datetime.now():%Y-%m-%d %H:%M:%S}</td></tr>
        </table>
        <p style="color:#8b949e;margin-top:20px">— PyMon (EVEMon in Python)</p>
        </body></html>
        """
        return self._send(subject, body_html)

    def send_queue_empty(self, character_name: str) -> bool:
        """Send notification that the skill queue is empty."""
        subject = f"[PyMon] {character_name}: Skill Queue leer!"
        body_html = f"""
        <html><body style="background:#0d1117;color:#c9d1d9;font-family:Arial,sans-serif;padding:20px">
        <h2 style="color:#e74c3c">⚠️ Skill Queue leer</h2>
        <p>The character <b>{character_name}</b> has no more skills in the training queue!</p>
        <p style="color:#8b949e">Please log in and add new skills to the queue.</p>
        <p style="color:#8b949e;margin-top:20px">— PyMon (EVEMon in Python)</p>
        </body></html>
        """
        return self._send(subject, body_html)

    def send_test(self) -> bool:
        """Send a test email to verify settings."""
        subject = "[PyMon] Test-E-Mail"
        body_html = """
        <html><body style="background:#0d1117;color:#c9d1d9;font-family:Arial,sans-serif;padding:20px">
        <h2 style="color:#4ecca3">✅ Test erfolgreich</h2>
        <p>Email notifications are configured correctly.</p>
        <p style="color:#8b949e;margin-top:20px">— PyMon (EVEMon in Python)</p>
        </body></html>
        """
        return self._send(subject, body_html)

    def _send(self, subject: str, body_html: str) -> bool:
        """Send an email via SMTP."""
        if not self.is_configured:
            logger.warning("Email not configured, skipping send")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to
            msg.attach(MIMEText(body_html, "html", "utf-8"))

            if self.use_tls:
                ctx = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(self.smtp_user, self.smtp_password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15) as s:
                    s.login(self.smtp_user, self.smtp_password)
                    s.send_message(msg)

            logger.info("Email sent: %s", subject)
            return True
        except Exception:
            logger.error("Failed to send email: %s", subject, exc_info=True)
            return False
