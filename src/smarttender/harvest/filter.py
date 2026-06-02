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
from .taxonomy import NEGATIVE_PATTERNS, domains_for_subject, terms_for_domains


@runtime_checkable
class TenderFilter(Protocol):
    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool: ...


class FilterResult:
    """Result of a filter decision — pass/reject with reason."""
    __slots__ = ("passed", "reason")

    def __init__(self, passed: bool, reason: str | None = None):
        self.passed = passed
        self.reason = reason  # None when passed; one of: "deadline"|"budget"|"type"|"relevance"

    def __bool__(self) -> bool:
        return self.passed


class BasicMetadataFilter:
    """Rule-based filter using only the fields available from harvest APIs.

    A tender passes if it satisfies ALL active rules for at least one company.
    Rules are applied cheaply in order (fast failures first).

    Use should_analyze() for a simple bool, or filter_result() to get the
    rejection reason (used by HarvestService to persist rejection_reason).
    """

    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool:
        return any(self._matches_company(raw, c).passed for c in companies)

    def filter_result(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> FilterResult:
        """Return FilterResult with reason so callers can record WHY it was rejected."""
        results = [self._matches_company(raw, c) for c in companies]
        # Pass if any company matches
        if any(r.passed for r in results):
            return FilterResult(True)
        # All rejected — return the least-specific rejection reason
        # (prefer "relevance" > "deadline" > "budget" > "type" for reporting)
        reasons = [r.reason for r in results if r.reason]
        priority = ["relevance", "deadline", "budget", "type"]
        for p in priority:
            if p in reasons:
                return FilterResult(False, p)
        return FilterResult(False, "relevance")

    def _matches_company(self, raw: RawTenderRecord, company: CompanyProfile) -> FilterResult:
        # 1. Deadline proximity — skip tenders closing too soon
        if raw.deadline is not None and company.min_days_to_deadline > 0:
            days_left = (raw.deadline - date.today()).days
            if days_left < company.min_days_to_deadline:
                return FilterResult(False, "deadline")

        # 2. Budget range — skip if clearly outside comfortable project size
        if raw.estimated_budget_ils is not None:
            if (
                company.min_project_value_ils is not None
                and raw.estimated_budget_ils < company.min_project_value_ils * 0.5
            ):
                return FilterResult(False, "budget")
            if (
                company.max_project_value_ils is not None
                and raw.estimated_budget_ils > company.max_project_value_ils * 2.0
            ):
                return FilterResult(False, "budget")

        # 3. Tender type — skip if company only wants specific types
        if company.preferred_tender_types and raw.tender_type:
            if raw.tender_type not in company.preferred_tender_types:
                return FilterResult(False, "type")

        search_text = " ".join(filter(None, [raw.title_he, *raw.subjects])).lower()

        # 4. Negative patterns — system-level rejection regardless of keywords
        if any(neg.lower() in search_text for neg in NEGATIVE_PATTERNS):
            return FilterResult(False, "relevance")

        # 5. Relevance match — at least one of the following must hit:
        #    a) user-defined harvest_keywords
        #    b) taxonomy terms derived from company domains (system-defined)
        #    c) BudgetKey subject category mapped to a company domain (+ title corroboration)
        matched = False

        if company.harvest_keywords:
            matched = any(kw.lower() in search_text for kw in company.harvest_keywords)

        if not matched and company.domains:
            taxonomy_terms = terms_for_domains(list(company.domains))
            matched = any(t.lower() in search_text for t in taxonomy_terms)

        if not matched and company.domains:
            # Subject-category match requires corroboration from the title.
            # A broad category like "שירותי בנייה" covers thousands of unrelated
            # tenders; we only accept it when the title also contains at least one
            # domain term — reducing false positives without harming recall for
            # tenders that mention HVAC explicitly.
            title_lower = (raw.title_he or "").lower()
            taxonomy_terms = terms_for_domains(list(company.domains))
            title_has_domain_term = any(t.lower() in title_lower for t in taxonomy_terms)
            if title_has_domain_term:
                for subject in raw.subjects:
                    implied = domains_for_subject(subject)
                    if any(d in company.domains for d in implied):
                        matched = True
                        break

        if not matched:
            return FilterResult(False, "relevance")

        return FilterResult(True)


class AcceptAllFilter:
    """No-op filter — accepts every tender. Useful in tests and dev mode."""

    def should_analyze(
        self,
        raw: RawTenderRecord,
        companies: list[CompanyProfile],
    ) -> bool:
        return True
