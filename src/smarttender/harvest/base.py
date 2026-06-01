"""Core data types for the harvest layer.

Adding a new source:
  1. Create src/smarttender/harvest/sources/mysource.py
  2. Implement the TenderSource protocol (source_id + fetch_new)
  3. Register it in HarvestService.SOURCES

That's it — no changes needed anywhere else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional, Protocol, runtime_checkable


class TenderStatus(str, Enum):
    DISCOVERED = "discovered"
    PENDING_FILTER = "pending_filter"
    PENDING_ANALYSIS = "pending_analysis"
    ANALYZED = "analyzed"
    REJECTED = "rejected"


@dataclass
class RawTenderRecord:
    """Normalised tender record as returned by any TenderSource."""

    source_id: str
    external_id: str                        # unique key within the source (for dedup)
    title_he: str
    publisher_he: Optional[str] = None
    subjects: list[str] = field(default_factory=list)
    tender_type: Optional[str] = None       # "office" | "central" | "exemptions"
    publication_date: Optional[date] = None
    deadline: Optional[date] = None         # submission deadline (claim_date)
    estimated_budget_ils: Optional[float] = None
    pdf_urls: list[str] = field(default_factory=list)
    pdf_blob: Optional[bytes] = None        # populated by ManualSource
    uploaded_by: Optional[str] = None       # company_id — manual uploads only
    raw_metadata: dict = field(default_factory=dict)


@runtime_checkable
class TenderSource(Protocol):
    """Protocol every harvest source must satisfy.

    Implement `source_id` (unique string) and `fetch_new` (async generator of
    RawTenderRecord).  `since` is the last successful harvest timestamp so the
    source can fetch only new records; None means fetch everything available.
    """

    source_id: str

    async def fetch_new(
        self,
        since: Optional[datetime] = None,
    ) -> list[RawTenderRecord]: ...
