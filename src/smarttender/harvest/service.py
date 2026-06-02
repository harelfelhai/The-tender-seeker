"""HarvestService: orchestrates sources, deduplication, filtering, and persistence."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..api.database import CompanyRow, RawTenderRow
from ..schemas.company_profile import CompanyProfile
from .base import RawTenderRecord, TenderSource, TenderStatus
from .filter import BasicMetadataFilter, TenderFilter

log = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    source_id: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    pending_analysis: int = 0
    rejected: int = 0
    errors: int = 0

    def summary(self) -> str:
        return (
            f"[{self.source_id}] fetched={self.fetched} new={self.new} "
            f"dup={self.duplicates} → analysis={self.pending_analysis} "
            f"rejected={self.rejected} errors={self.errors}"
        )


class HarvestService:
    """Runs one or more TenderSources and persists results.

    To add a new source, register it in the SOURCES class variable.
    The service handles deduplication, filtering, and status transitions
    automatically — sources only need to implement fetch_new().
    """

    def __init__(
        self,
        sources: list[TenderSource],
        filter: TenderFilter | None = None,
    ) -> None:
        self._sources = {s.source_id: s for s in sources}
        self._filter: TenderFilter = filter or BasicMetadataFilter()

    # ── public API ─────────────────────────────────────────────────────────────

    async def run_source(
        self,
        source_id: str,
        db: Session,
        *,
        since: Optional[datetime] = None,
    ) -> HarvestResult:
        source = self._sources.get(source_id)
        if source is None:
            raise ValueError(f"Unknown source: {source_id!r}")
        return await self._harvest_one(source, db, since=since)

    async def run_all(
        self,
        db: Session,
        *,
        since: Optional[datetime] = None,
    ) -> list[HarvestResult]:
        results = []
        for source in self._sources.values():
            result = await self._harvest_one(source, db, since=since)
            results.append(result)
        return results

    def list_sources(self) -> list[str]:
        return list(self._sources.keys())

    # ── internals ──────────────────────────────────────────────────────────────

    async def _harvest_one(
        self,
        source: TenderSource,
        db: Session,
        *,
        since: Optional[datetime],
    ) -> HarvestResult:
        result = HarvestResult(source_id=source.source_id)
        companies = self._load_all_companies(db)

        try:
            records = await source.fetch_new(since=since)
        except Exception as exc:
            log.error("Source %s fetch failed: %s", source.source_id, exc)
            result.errors += 1
            return result

        result.fetched = len(records)

        for rec in records:
            try:
                self._persist_record(rec, db, companies, result)
            except Exception as exc:
                log.warning("Failed to persist record %s: %s", rec.external_id, exc)
                result.errors += 1

        db.commit()
        log.info(result.summary())
        return result

    def _persist_record(
        self,
        rec: RawTenderRecord,
        db: Session,
        companies: list[CompanyProfile],
        result: HarvestResult,
    ) -> None:
        # Deduplication: (source_id, external_id) must be unique
        existing = (
            db.query(RawTenderRow)
            .filter_by(source_id=rec.source_id, external_id=rec.external_id)
            .first()
        )
        if existing is not None:
            result.duplicates += 1
            return

        status = self._decide_status(rec, companies)
        if status == TenderStatus.PENDING_ANALYSIS:
            result.pending_analysis += 1
        else:
            result.rejected += 1

        row = RawTenderRow(
            id=str(uuid.uuid4()),
            source_id=rec.source_id,
            external_id=rec.external_id,
            title_he=rec.title_he,
            publisher_he=rec.publisher_he,
            publisher_unit=rec.publisher_unit,
            subjects_json=json.dumps(rec.subjects, ensure_ascii=False),
            tender_type=rec.tender_type,
            tender_type_he=rec.tender_type_he,
            publication_date=rec.publication_date,
            deadline=rec.deadline,
            contract_start=rec.contract_start,
            contract_end=rec.contract_end,
            estimated_budget_ils=rec.estimated_budget_ils,
            pdf_urls_json=json.dumps(rec.pdf_urls, ensure_ascii=False),
            uploaded_by=rec.uploaded_by,
            page_url=rec.page_url,
            tender_status=rec.tender_status,
            decision=rec.decision,
            status=status.value,
            raw_metadata_json=json.dumps(rec.raw_metadata, ensure_ascii=False, default=str),
            harvested_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(row)
        result.new += 1

    def _decide_status(
        self,
        rec: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> TenderStatus:
        if self._filter.should_analyze(rec, companies):
            return TenderStatus.PENDING_ANALYSIS
        return TenderStatus.REJECTED

    @staticmethod
    def _load_all_companies(db: Session) -> list[CompanyProfile]:
        rows = db.query(CompanyRow).all()
        profiles = []
        for row in rows:
            try:
                profiles.append(CompanyProfile.model_validate_json(row.profile_json))
            except Exception:
                pass
        return profiles
