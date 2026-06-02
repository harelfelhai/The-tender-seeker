"""BudgetKey harvest source — free Israeli government procurement data.

API: https://next.obudget.org/api/query (no auth, SQL over ~228k tender records)
Schema reference: github.com/OpenBudget/budgetkey-data-pipelines

Metadata fetched:
  description, publisher, publisher_unit, subjects, tender_type, tender_type_he,
  publication_date, claim_date (deadline), start_date, end_date (contract period),
  volume (estimated budget), documents (PDF links), page_url, status, decision

Only ACTIVE statuses are fetched (פורסם, בעדכון, עתידי, etc.) — closed/cancelled
tenders are excluded to avoid indexing irrelevant historical data.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from ..base import RawTenderRecord

log = logging.getLogger(__name__)

_API_URL = "https://next.obudget.org/api/query"
# BudgetKey API returns at most 1000 rows per request regardless of LIMIT.
_PAGE_SIZE = 1000

# All tender types available in BudgetKey
TENDER_TYPES = ("office", "central", "exemptions")


class BudgetKeySource:
    """Fetches tenders from the BudgetKey open-data SQL API.

    To add filtering (e.g. only specific publisher names or subjects),
    subclass and override _build_query().
    """

    source_id = "budgetkey"

    def __init__(self, page_size: int = _PAGE_SIZE) -> None:
        self._page_size = page_size

    # Max concurrent requests — BudgetKey is a free public API, be polite.
    _CONCURRENCY = 5

    async def fetch_new(
        self,
        since: Optional[datetime] = None,
    ) -> list[RawTenderRecord]:
        """Fetch all active tenders, with paginated parallel requests.

        BudgetKey caps responses at 1000 rows regardless of LIMIT.  We probe
        the first page to discover total row count, then fetch all remaining
        pages in parallel (up to _CONCURRENCY at a time).

        since=None → full backfill (all active tenders, ~200K rows, ~2 min)
        since=datetime → delta (only rows updated after that date, much faster)
        """
        try:
            import asyncio
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required for BudgetKeySource: pip install httpx"
            ) from exc

        since_date = since.date() if since else None

        async with httpx.AsyncClient(timeout=60) as client:
            # Probe page 0 to get actual count and first batch
            first_page = await self._fetch_page(client, since_date, offset=0)
            if len(first_page) < self._page_size:
                log.info("BudgetKey: %d rows (single page)", len(first_page))
                return [self._to_record(r) for r in first_page]

            # Estimate remaining pages from count query
            total = await self._fetch_count(client, since_date)
            offsets = list(range(self._page_size, total + self._page_size, self._page_size))
            log.info("BudgetKey: ~%d total rows, fetching %d more pages", total, len(offsets))

            semaphore = asyncio.Semaphore(self._CONCURRENCY)

            async def fetch_with_sem(offset: int) -> list[dict]:
                async with semaphore:
                    return await self._fetch_page(client, since_date, offset)

            remaining = await asyncio.gather(*[fetch_with_sem(o) for o in offsets])

        all_rows = first_page + [row for page in remaining for row in page]
        log.info("BudgetKey fetched %d total rows", len(all_rows))
        return [self._to_record(row) for row in all_rows]

    async def _fetch_page(
        self,
        client,
        since_date: Optional[date],
        offset: int,
    ) -> list[dict]:
        query = self._build_query(since_date, offset=offset)
        resp = await client.get(_API_URL, params={"query": query})
        resp.raise_for_status()
        page = resp.json().get("rows", [])
        log.debug("BudgetKey offset=%d → %d rows", offset, len(page))
        return page

    async def _fetch_count(self, client, since_date: Optional[date]) -> int:
        status_list = ", ".join(f"'{s}'" for s in self.ACTIVE_STATUSES)
        date_clause = f"AND last_update_date > '{since_date}' " if since_date else ""
        query = (
            f"SELECT COUNT(*) as cnt FROM procurement_tenders_all "
            f"WHERE status IN ({status_list}) {date_clause}"
        )
        resp = await client.get(_API_URL, params={"query": query})
        resp.raise_for_status()
        return int(resp.json()["rows"][0]["cnt"])

    # Statuses representing active open tenders — exclude closed/cancelled.
    ACTIVE_STATUSES = (
        "פורסם",
        "פורסם ולא התקבלו השגות",
        "פורסם והתקבלו השגות",
        "בעדכון",
        "עתידי",
        "חדש",
    )

    # ── overridable ────────────────────────────────────────────────────────────

    def _build_query(self, since: Optional[date], offset: int = 0) -> str:
        status_list = ", ".join(f"'{s}'" for s in self.ACTIVE_STATUSES)
        date_clause = f"AND last_update_date > '{since}' " if since else ""
        return (
            "SELECT publication_id, tender_id, tender_type, tender_type_he, description, "
            "publisher, publisher_unit, page_url, status, decision, "
            "publication_date, last_update_date, claim_date, start_date, end_date, "
            "volume, subjects, documents "
            f"FROM procurement_tenders_all "
            f"WHERE status IN ({status_list}) "
            f"{date_clause}"
            f"ORDER BY last_update_date DESC "
            f"LIMIT {self._page_size} OFFSET {offset}"
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    def _to_record(self, row: dict) -> RawTenderRecord:
        return RawTenderRecord(
            source_id=self.source_id,
            external_id=f"{row.get('tender_type', 'unknown')}_{row.get('publication_id', '')}",
            title_he=row.get("description") or "",
            publisher_he=row.get("publisher"),
            publisher_unit=row.get("publisher_unit"),
            subjects=_parse_subjects(row.get("subjects")),
            tender_type=row.get("tender_type"),
            tender_type_he=row.get("tender_type_he"),
            publication_date=_parse_date(row.get("publication_date") or row.get("last_update_date")),
            deadline=_parse_date(row.get("claim_date")),
            contract_start=_parse_date(row.get("start_date")),
            contract_end=_parse_date(row.get("end_date")),
            estimated_budget_ils=_safe_float(row.get("volume")),
            pdf_urls=_parse_pdf_urls(row.get("documents")),
            page_url=row.get("page_url"),
            tender_status=row.get("status"),
            decision=row.get("decision"),
            raw_metadata=row,
        )


# ── parsing helpers ────────────────────────────────────────────────────────────

def _parse_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_subjects(value: object) -> list[str]:
    """BudgetKey subjects field is a semicolon- or comma-separated string."""
    if not value:
        return []
    text = str(value)
    sep = ";" if ";" in text else ","
    return [s.strip() for s in text.split(sep) if s.strip()]


def _parse_pdf_urls(documents: object) -> list[str]:
    """documents is a list of dicts with a 'link' key, or None."""
    if not documents:
        return []
    if isinstance(documents, str):
        import json as _json
        try:
            documents = _json.loads(documents)
        except Exception:
            return []
    if isinstance(documents, list):
        return [d["link"] for d in documents if isinstance(d, dict) and d.get("link")]
    return []
