"""Core types for the notification layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol, runtime_checkable


@dataclass
class NotificationEvent:
    """Everything a notifier needs to describe one tender to one company."""

    company_id: str
    company_name: str
    recipient_email: Optional[str]

    raw_tender_id: str
    title_he: str
    publisher_he: Optional[str]
    tender_type: Optional[str]
    deadline: Optional[date]
    estimated_budget_ils: Optional[float]
    subjects: list[str] = field(default_factory=list)
    pdf_urls: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)


@runtime_checkable
class Notifier(Protocol):
    channel: str  # unique identifier, e.g. "email" or "console"

    async def send(self, event: NotificationEvent) -> None: ...
