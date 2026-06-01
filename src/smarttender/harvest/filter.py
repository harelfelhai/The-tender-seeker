"""Tender pre-filter: decide whether a raw tender deserves LLM analysis.

The filter runs on metadata only (no PDF download).  A raw tender is promoted
to PENDING_ANALYSIS if it matches at least one registered company's harvest
preferences.  Unmatched tenders are marked REJECTED — cheap to store, never
billed for LLM extraction.

Adding richer filter logic later (e.g. ML classifier, NLP category matching)
only requires implementing the TenderFilter Protocol and passing it to
HarvestService — no other code changes needed.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from ..schemas.company_profile import CompanyProfile
from .base import RawTenderRecord


@runtime_checkable
class TenderFilter(Protocol):
    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool: ...


class BasicMetadataFilter:
    """Rule-based filter using only the fields available from harvest APIs.

    A tender passes if it satisfies ALL active rules for at least one company.
    Rules are applied cheaply in order (fast failures first).
    """

    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool:
        return any(self._matches_company(raw, c) for c in companies)

    def _matches_company(self, raw: RawTenderRecord, company: CompanyProfile) -> bool:
        # 1. Deadline proximity — skip tenders closing too soon
        if raw.deadline is not None and company.min_days_to_deadline > 0:
            days_left = (raw.deadline - date.today()).days
            if days_left < company.min_days_to_deadline:
                return False

        # 2. Budget range — skip if clearly outside comfortable project size
        if raw.estimated_budget_ils is not None:
            if (
                company.min_project_value_ils is not None
                and raw.estimated_budget_ils < company.min_project_value_ils * 0.5
            ):
                return False
            if (
                company.max_project_value_ils is not None
                and raw.estimated_budget_ils > company.max_project_value_ils * 2.0
            ):
                return False

        # 3. Tender type — skip if company only wants specific types
        if company.preferred_tender_types and raw.tender_type:
            if raw.tender_type not in company.preferred_tender_types:
                return False

        # 4. Keyword match — title + subjects must contain at least one keyword
        if company.harvest_keywords:
            search_text = " ".join(
                filter(None, [raw.title_he, *raw.subjects])
            ).lower()
            if not any(kw.lower() in search_text for kw in company.harvest_keywords):
                return False

        return True


class AcceptAllFilter:
    """No-op filter — accepts every tender. Useful in tests and dev mode."""

    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool:
        return True
