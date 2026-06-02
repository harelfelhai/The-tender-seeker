"""Unit tests for the notification layer — zero network, zero email sends."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.smarttender.notifications.base import NotificationEvent, Notifier
from src.smarttender.notifications.console_notifier import ConsoleNotifier
from src.smarttender.notifications.email_notifier import EmailNotifier
from src.smarttender.notifications.dispatcher import (
    NotificationDispatcher,
    _find_matched_keywords,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _event(**kwargs) -> NotificationEvent:
    defaults = dict(
        company_id="514123456",
        company_name="טק-קול בע\"מ",
        recipient_email="test@example.com",
        raw_tender_id="raw-001",
        title_he="מכרז מיזוג אוויר לעירייה",
        publisher_he="עיריית תל אביב",
        tender_type="office",
        deadline=date.today() + timedelta(days=30),
        estimated_budget_ils=3_000_000,
        subjects=["מיזוג אוויר", "תחזוקה"],
        pdf_urls=["https://example.com/tender.pdf"],
        matched_keywords=["מיזוג אוויר"],
    )
    return NotificationEvent(**{**defaults, **kwargs})


# ── Protocol conformance ──────────────────────────────────────────────────────

class TestNotifierProtocol:
    def test_console_satisfies_protocol(self):
        assert isinstance(ConsoleNotifier(), Notifier)

    def test_email_satisfies_protocol(self):
        assert isinstance(EmailNotifier(), Notifier)


# ── ConsoleNotifier ───────────────────────────────────────────────────────────

class TestConsoleNotifier:
    @pytest.mark.asyncio
    async def test_send_does_not_raise(self):
        notifier = ConsoleNotifier()
        await notifier.send(_event())   # should complete without error

    @pytest.mark.asyncio
    async def test_send_no_budget(self):
        notifier = ConsoleNotifier()
        await notifier.send(_event(estimated_budget_ils=None))

    @pytest.mark.asyncio
    async def test_send_no_deadline(self):
        notifier = ConsoleNotifier()
        await notifier.send(_event(deadline=None))

    def test_channel_is_console(self):
        assert ConsoleNotifier().channel == "console"


# ── EmailNotifier ─────────────────────────────────────────────────────────────

class TestEmailNotifier:
    def test_channel_is_email(self):
        assert EmailNotifier().channel == "email"

    @pytest.mark.asyncio
    async def test_skips_if_no_recipient(self):
        notifier = EmailNotifier()
        # Should silently skip without calling SMTP at all
        with patch("aiosmtplib.send") as mock_send:
            await notifier.send(_event(recipient_email=None))
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_aiosmtplib_send(self):
        notifier = EmailNotifier()
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send(_event())
        mock_send.assert_called_once()

    def test_plain_text_contains_title(self):
        e = _event()
        text = EmailNotifier._plain_text(e)
        assert e.title_he in text

    def test_plain_text_contains_budget(self):
        e = _event(estimated_budget_ils=3_000_000)
        text = EmailNotifier._plain_text(e)
        assert "3,000,000" in text

    def test_plain_text_no_budget(self):
        text = EmailNotifier._plain_text(_event(estimated_budget_ils=None))
        assert "לא צוין" in text

    def test_html_contains_title(self):
        e = _event()
        html = EmailNotifier._html(e)
        assert e.title_he in html

    def test_html_contains_pdf_link(self):
        e = _event(pdf_urls=["https://example.com/a.pdf"])
        html = EmailNotifier._html(e)
        assert "https://example.com/a.pdf" in html

    def test_html_no_pdf_link_when_empty(self):
        html = EmailNotifier._html(_event(pdf_urls=[]))
        assert "פתח מסמך" not in html


# ── keyword matching helper ───────────────────────────────────────────────────

class TestFindMatchedKeywords:
    def _make_row(self, title="מכרז מיזוג אוויר", subjects=None):
        row = MagicMock()
        row.title_he = title
        row.subjects_json = json.dumps(subjects or [])
        return row

    def _company(self, keywords):
        from src.smarttender.schemas.company_profile import CompanyProfile
        return CompanyProfile(
            company_name="חברה",
            company_reg_id="123456789",
            harvest_keywords=keywords,
        )

    def test_finds_keyword_in_title(self):
        row = self._make_row(title="מכרז מיזוג אוויר")
        kw = _find_matched_keywords(row, [], self._company(["מיזוג אוויר"]))
        assert "מיזוג אוויר" in kw

    def test_finds_keyword_in_subjects(self):
        row = self._make_row(title="מכרז כללי")
        kw = _find_matched_keywords(row, ["HVAC"], self._company(["hvac"]))
        assert "hvac" in kw

    def test_empty_keywords_returns_empty(self):
        row = self._make_row()
        kw = _find_matched_keywords(row, [], self._company([]))
        assert kw == []

    def test_no_match_returns_empty(self):
        row = self._make_row(title="מכרז כביש")
        kw = _find_matched_keywords(row, [], self._company(["מיזוג אוויר"]))
        assert kw == []


# ── NotificationDispatcher ────────────────────────────────────────────────────

class TestNotificationDispatcher:
    def _make_raw_row(self, status="pending_analysis"):
        row = MagicMock()
        row.id = "raw-001"
        row.source_id = "budgetkey"
        row.external_id = "bk_001"
        row.title_he = "מכרז מיזוג אוויר"
        row.publisher_he = "עיריית תל אביב"
        row.tender_type = "office"
        row.deadline = date.today() + timedelta(days=30)
        row.estimated_budget_ils = 3_000_000
        row.subjects_json = json.dumps(["מיזוג אוויר"])
        row.pdf_urls_json = json.dumps(["https://example.com/t.pdf"])
        row.status = status
        return row

    def _make_company_row(self, email="co@example.com", keywords=None):
        from src.smarttender.schemas.company_profile import CompanyProfile
        profile = CompanyProfile(
            company_name="טק-קול",
            company_reg_id="514123456",
            notification_email=email,
            notification_enabled=True,
            harvest_keywords=keywords or ["מיזוג אוויר"],
        )
        row = MagicMock()
        row.profile_json = profile.model_dump_json()
        return row

    @pytest.mark.asyncio
    async def test_sends_to_matching_company(self):
        mock_notifier = AsyncMock()
        mock_notifier.channel = "mock"
        dispatcher = NotificationDispatcher([mock_notifier])

        db = MagicMock()
        db.query.return_value.all.return_value = [self._make_company_row()]
        db.query.return_value.filter_by.return_value.first.return_value = None  # not already notified
        db.add = MagicMock()
        db.commit = MagicMock()

        count = await dispatcher.dispatch_for_tender(self._make_raw_row(), db)
        assert count == 1
        mock_notifier.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_already_notified(self):
        mock_notifier = AsyncMock()
        mock_notifier.channel = "mock"
        dispatcher = NotificationDispatcher([mock_notifier])

        db = MagicMock()
        db.query.return_value.all.return_value = [self._make_company_row()]
        # Simulate already notified
        db.query.return_value.filter_by.return_value.first.return_value = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()

        count = await dispatcher.dispatch_for_tender(self._make_raw_row(), db)
        assert count == 0
        mock_notifier.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_companies_returns_zero(self):
        mock_notifier = AsyncMock()
        mock_notifier.channel = "mock"
        dispatcher = NotificationDispatcher([mock_notifier])

        db = MagicMock()
        db.query.return_value.all.return_value = []

        count = await dispatcher.dispatch_for_tender(self._make_raw_row(), db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_failed_notifier_still_records(self):
        """A notifier that throws should be recorded as 'failed', not crash."""
        failing_notifier = AsyncMock()
        failing_notifier.channel = "failing"
        failing_notifier.send.side_effect = RuntimeError("SMTP down")

        dispatcher = NotificationDispatcher([failing_notifier])

        db = MagicMock()
        db.query.return_value.all.return_value = [self._make_company_row()]
        db.query.return_value.filter_by.return_value.first.return_value = None
        added_rows = []
        db.add.side_effect = added_rows.append
        db.commit = MagicMock()

        await dispatcher.dispatch_for_tender(self._make_raw_row(), db)

        assert any(getattr(r, "status", None) == "failed" for r in added_rows)
