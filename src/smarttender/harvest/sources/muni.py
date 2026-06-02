"""Municipal tenders harvest source — BudgetKey muni_tenders table.

583 municipal tenders from Israeli city councils (Kfar Saba, etc.).
Schema differs slightly from procurement_tenders_all: no volume/documents,
but has page_url and publisher_unit.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from ..base import RawTenderRecord

log = logging.getLogger(__name__)

_API_URL = "https://next.obudget.org/api/query"
_PAGE_SIZE = 1000


class MuniTendersSource:
    """Fetches municipal tenders from BudgetKey muni_tenders table."""

    source_id = "budgetkey_muni"

    def __init__(self, page_size: int = _PAGE_SIZE) -> None:
        self._page_size = page_size

    async def fetch_new(
        self,
        since: Optional[datetime] = None,
    ) -> list[RawTenderRecord]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install httpx") from exc

        since_date = since.date() if since else date(2020, 1, 1)
        query = (
            "SELECT tender_id, tender_type, description, publisher, publisher_unit, "
            "page_url, publication_date, last_update_date, claim_date, status "
            f"FROM muni_tenders "
            f"WHERE (last_update_date > '{since_date}' OR publication_date > '{since_date}') "
            f"ORDER BY last_update_date DESC NULLS LAST "
            f"LIMIT {self._page_size}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_API_URL, params={"query": query})
            resp.raise_for_status()
            data = resp.json()

        rows = data.get("rows", [])
        log.info("MuniTenders returned %d rows since %s", len(rows), since_date)
        return [self._to_record(row) for row in rows]

    def _to_record(self, row: dict) -> RawTenderRecord:
        return RawTenderRecord(
            source_id=self.source_id,
            external_id=f"muni_{row.get('tender_id', '')}",
            title_he=row.get("description") or "",
            publisher_he=row.get("publisher"),
            publisher_unit=row.get("publisher_unit"),
            subjects=[],
            tender_type=row.get("tender_type"),
            publication_date=_parse_date(row.get("publication_date") or row.get("last_update_date")),
            deadline=_parse_date(row.get("claim_date")),
            estimated_budget_ils=None,
            pdf_urls=[],
            page_url=row.get("page_url"),
            raw_metadata=row,
        )


def _parse_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
