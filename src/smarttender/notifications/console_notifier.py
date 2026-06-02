"""Console notifier — logs notifications instead of sending email.

Used in development and tests. Zero configuration required.
"""
from __future__ import annotations

import logging

from .base import NotificationEvent

log = logging.getLogger(__name__)


class ConsoleNotifier:
    channel = "console"

    async def send(self, event: NotificationEvent) -> None:
        budget = (
            f"₪{event.estimated_budget_ils:,.0f}"
            if event.estimated_budget_ils
            else "לא צוין"
        )
        deadline = event.deadline.isoformat() if event.deadline else "לא צוין"
        keywords = ", ".join(event.matched_keywords) if event.matched_keywords else "—"

        log.info(
            "\n"
            "═══ מכרז חדש רלוונטי ═══\n"
            "חברה    : %s (%s)\n"
            "מכרז    : %s\n"
            "מפרסם  : %s\n"
            "תקציב  : %s\n"
            "דדליין : %s\n"
            "מילות מפתח שהתאמו: %s\n"
            "═══════════════════════",
            event.company_name,
            event.company_id,
            event.title_he,
            event.publisher_he or "—",
            budget,
            deadline,
            keywords,
        )
