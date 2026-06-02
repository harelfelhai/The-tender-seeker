"""NotificationDispatcher: decides who to notify and records what was sent.

After each harvest run, call dispatch_for_tender() for every newly
PENDING_ANALYSIS raw tender.  The dispatcher:
  1. Loads all companies with notifications enabled
  2. Checks which companies matched the tender (via BasicMetadataFilter)
  3. Builds NotificationEvent with matched keywords
  4. Calls each registered Notifier
  5. Persists a NotificationRow so we never send duplicates
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import timezone, datetime

from sqlalchemy.orm import Session

from ..api.database import CompanyRow, NotificationRow, RawTenderRow
from ..harvest.filter import BasicMetadataFilter
from ..schemas.company_profile import CompanyProfile
from .base import NotificationEvent, Notifier

log = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, notifiers: list[Notifier]) -> None:
        self._notifiers = notifiers
        self._filter = BasicMetadataFilter()

    async def dispatch_for_tender(
        self, raw_row: RawTenderRow, db: Session
    ) -> int:
        """Notify all matching companies about a new tender. Returns count sent."""
        companies = self._load_notifiable_companies(db)
        if not companies:
            return 0

        subjects = json.loads(raw_row.subjects_json or "[]")
        pdf_urls = json.loads(raw_row.pdf_urls_json or "[]")

        sent = 0
        for company in companies:
            if self._already_notified(raw_row.id, company.company_reg_id, db):
                continue

            # Re-use harvest filter to confirm match and collect matched keywords
            if not self._filter.should_analyze(_row_to_record(raw_row), [company]):
                continue

            matched_kw = _find_matched_keywords(raw_row, subjects, company)
            event = NotificationEvent(
                company_id=company.company_reg_id,
                company_name=company.company_name,
                recipient_email=company.notification_email,
                raw_tender_id=raw_row.id,
                title_he=raw_row.title_he or "",
                publisher_he=raw_row.publisher_he,
                tender_type=raw_row.tender_type,
                deadline=raw_row.deadline,
                estimated_budget_ils=raw_row.estimated_budget_ils,
                subjects=subjects,
                pdf_urls=pdf_urls,
                matched_keywords=matched_kw,
            )

            for notifier in self._notifiers:
                await self._notify_one(notifier, event, db)
                sent += 1

        return sent

    # ── internals ──────────────────────────────────────────────────────────────

    async def _notify_one(
        self, notifier: Notifier, event: NotificationEvent, db: Session
    ) -> None:
        status = "sent"
        error_msg = None
        try:
            await notifier.send(event)
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)
            log.warning(
                "Notifier %s failed for company %s: %s",
                notifier.channel, event.company_id, exc,
            )

        db.add(NotificationRow(
            id=str(uuid.uuid4()),
            company_id=event.company_id,
            raw_tender_id=event.raw_tender_id,
            channel=notifier.channel,
            recipient=event.recipient_email,
            status=status,
            error_msg=error_msg,
            sent_at=datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()

    @staticmethod
    def _load_notifiable_companies(db: Session) -> list[CompanyProfile]:
        rows = db.query(CompanyRow).all()
        result = []
        for row in rows:
            try:
                p = CompanyProfile.model_validate_json(row.profile_json)
                if p.notification_enabled:
                    result.append(p)
            except Exception:
                pass
        return result

    @staticmethod
    def _already_notified(raw_tender_id: str, company_id: str, db: Session) -> bool:
        return (
            db.query(NotificationRow)
            .filter_by(raw_tender_id=raw_tender_id, company_id=company_id, status="sent")
            .first()
        ) is not None


def _row_to_record(row: RawTenderRow):
    """Convert a RawTenderRow back to RawTenderRecord for filter reuse."""
    from ..harvest.base import RawTenderRecord
    import json
    return RawTenderRecord(
        source_id=row.source_id,
        external_id=row.external_id or "",
        title_he=row.title_he or "",
        subjects=json.loads(row.subjects_json or "[]"),
        tender_type=row.tender_type,
        deadline=row.deadline,
        estimated_budget_ils=row.estimated_budget_ils,
    )


def _find_matched_keywords(
    row: RawTenderRow, subjects: list[str], company: CompanyProfile
) -> list[str]:
    if not company.harvest_keywords:
        return []
    search_text = " ".join(filter(None, [row.title_he, *subjects])).lower()
    return [kw for kw in company.harvest_keywords if kw.lower() in search_text]
