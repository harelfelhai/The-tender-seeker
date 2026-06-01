"""BudgetKey harvest source — free Israeli government procurement data.

API: https://next.obudget.org/api/query (no auth, SQL over ~191k tender records)
Schema reference: github.com/OpenBudget/budgetkey-data-pipelines

Metadata available without PDF download:
  description, publisher, subjects, tender_type, publication_date,
  claim_date (deadline), volume (estimated budget), documents (PDF links)
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from ..base import RawTenderRecord

log = logging.getLogger(__name__)

_API_URL = "https://next.obudget.org/api/query"
_PAGE_SIZE = 500

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

    async def fetch_new(
        self,
        since: Optional[datetime] = None,
    ) -> list[RawTenderRecord]:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx is required for BudgetKeySource: pip install httpx"
            ) from exc

        since_date = since.date() if since else date(2020, 1, 1)
        query = self._build_query(since_date)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_API_URL, params={"query": query})
            resp.raise_for_status()
            data = resp.json()

        rows = data.get("rows", [])
        log.info("BudgetKey returned %d rows since %s", len(rows), since_date)
        return [self._to_record(row) for row in rows]

    # ── overridable ────────────────────────────────────────────────────────────

    def _build_query(self, since: date) -> str:
        return (
            "SELECT publication_id, tender_id, tender_type, description, "
            "publisher, publication_date, claim_date, volume, subjects, documents "
            f"FROM tenders "
            f"WHERE publication_date > '{since}' "
            f"ORDER BY publication_date DESC "
            f"LIMIT {self._page_size}"
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    def _to_record(self, row: dict) -> RawTenderRecord:
        return RawTenderRecord(
            source_id=self.source_id,
            external_id=f"{row.get('tender_type', 'unknown')}_{row.get('publication_id', '')}",
            title_he=row.get("description") or "",
            publisher_he=row.get("publisher"),
            subjects=_parse_subjects(row.get("subjects")),
            tender_type=row.get("tender_type"),
            publication_date=_parse_date(row.get("publication_date")),
            deadline=_parse_date(row.get("claim_date")),
            estimated_budget_ils=_safe_float(row.get("volume")),
            pdf_urls=_parse_pdf_urls(row.get("documents")),
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
