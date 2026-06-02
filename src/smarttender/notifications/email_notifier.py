"""SMTP email notifier — sends Hebrew tender alerts via email.

Configuration (environment variables):
  SMTP_HOST          default: localhost
  SMTP_PORT          default: 587
  SMTP_USER          optional (leave empty for unauthenticated relay)
  SMTP_PASSWORD      optional
  SMTP_FROM_EMAIL    default: noreply@smarttender.co.il
  SMTP_USE_TLS       default: true
"""
from __future__ import annotations

import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .base import NotificationEvent

log = logging.getLogger(__name__)

_SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
_SMTP_FROM = os.getenv("SMTP_FROM_EMAIL", "noreply@smarttender.co.il")
_SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"


class EmailNotifier:
    channel = "email"

    async def send(self, event: NotificationEvent) -> None:
        if not event.recipient_email:
            log.debug("No email for company %s — skipping", event.company_id)
            return

        msg = self._build_message(event)
        await self._send_smtp(msg, event.recipient_email)

    # ── message building ───────────────────────────────────────────────────────

    def _build_message(self, event: NotificationEvent) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"מכרז חדש רלוונטי: {event.title_he}"
        msg["From"] = _SMTP_FROM
        msg["To"] = event.recipient_email

        msg.attach(MIMEText(self._plain_text(event), "plain", "utf-8"))
        msg.attach(MIMEText(self._html(event), "html", "utf-8"))
        return msg

    @staticmethod
    def _plain_text(e: NotificationEvent) -> str:
        budget = f"₪{e.estimated_budget_ils:,.0f}" if e.estimated_budget_ils else "לא צוין"
        deadline = e.deadline.isoformat() if e.deadline else "לא צוין"
        keywords = ", ".join(e.matched_keywords) if e.matched_keywords else "—"
        subjects = ", ".join(e.subjects) if e.subjects else "—"
        pdf_line = f"\nקישור למסמך: {e.pdf_urls[0]}" if e.pdf_urls else ""

        return (
            f"שלום {e.company_name},\n\n"
            f"זיהינו מכרז חדש שעשוי להתאים לכם:\n\n"
            f"כותרת:  {e.title_he}\n"
            f"מפרסם:  {e.publisher_he or '—'}\n"
            f"נושאים: {subjects}\n"
            f"תקציב:  {budget}\n"
            f"הגשה עד: {deadline}\n"
            f"מילות מפתח שהתאמו: {keywords}"
            f"{pdf_line}\n\n"
            f"בברכה,\nSmartTender AI"
        )

    @staticmethod
    def _html(e: NotificationEvent) -> str:
        budget = f"₪{e.estimated_budget_ils:,.0f}" if e.estimated_budget_ils else "לא צוין"
        deadline = e.deadline.isoformat() if e.deadline else "לא צוין"
        keywords = ", ".join(e.matched_keywords) if e.matched_keywords else "—"
        subjects = ", ".join(e.subjects) if e.subjects else "—"
        pdf_link = (
            f'<p><a href="{e.pdf_urls[0]}">📄 פתח מסמך מכרז</a></p>'
            if e.pdf_urls else ""
        )

        return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;direction:rtl;max-width:600px;margin:auto;padding:20px">
  <h2 style="color:#1a56db">🔔 מכרז חדש רלוונטי</h2>
  <p>שלום <strong>{e.company_name}</strong>,</p>
  <p>זיהינו מכרז חדש שעשוי להתאים לכם:</p>
  <table style="border-collapse:collapse;width:100%">
    <tr><td style="padding:8px;font-weight:bold;width:130px">כותרת</td>
        <td style="padding:8px">{e.title_he}</td></tr>
    <tr style="background:#f9fafb"><td style="padding:8px;font-weight:bold">מפרסם</td>
        <td style="padding:8px">{e.publisher_he or "—"}</td></tr>
    <tr><td style="padding:8px;font-weight:bold">נושאים</td>
        <td style="padding:8px">{subjects}</td></tr>
    <tr style="background:#f9fafb"><td style="padding:8px;font-weight:bold">תקציב משוער</td>
        <td style="padding:8px">{budget}</td></tr>
    <tr><td style="padding:8px;font-weight:bold">הגשה עד</td>
        <td style="padding:8px">{deadline}</td></tr>
    <tr style="background:#f9fafb"><td style="padding:8px;font-weight:bold">התאמה לפי</td>
        <td style="padding:8px">{keywords}</td></tr>
  </table>
  {pdf_link}
  <hr style="margin:20px 0;border:none;border-top:1px solid #e5e7eb">
  <p style="color:#6b7280;font-size:12px">
    SmartTender AI — מכרזים ממשלתיים רלוונטיים, אוטומטית.<br>
    לביטול התראות עדכן את הפרופיל שלך.
  </p>
</body>
</html>"""

    # ── SMTP send ──────────────────────────────────────────────────────────────

    async def _send_smtp(self, msg: MIMEMultipart, to: str) -> None:
        try:
            import aiosmtplib
        except ImportError as exc:
            raise RuntimeError(
                "aiosmtplib is required for EmailNotifier: pip install aiosmtplib"
            ) from exc

        kwargs: dict = dict(
            hostname=_SMTP_HOST,
            port=_SMTP_PORT,
            start_tls=_SMTP_USE_TLS,
        )
        if _SMTP_USER:
            kwargs["username"] = _SMTP_USER
            kwargs["password"] = _SMTP_PASSWORD

        await aiosmtplib.send(msg, **kwargs)
        log.info("Email sent to %s: %s", to, msg["Subject"])
