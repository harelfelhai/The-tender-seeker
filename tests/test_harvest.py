"""Unit tests for the harvest layer — zero network calls, zero LLM calls."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.smarttender.harvest.base import RawTenderRecord, TenderSource, TenderStatus
from src.smarttender.harvest.filter import AcceptAllFilter, BasicMetadataFilter
from src.smarttender.harvest.sources.budgetkey import (
    BudgetKeySource,
    _parse_date,
    _parse_pdf_urls,
    _parse_subjects,
    _safe_float,
)
from src.smarttender.harvest.sources.manual import ManualSource
from src.smarttender.schemas.company_profile import CompanyProfile


# ── fixtures ──────────────────────────────────────────────────────────────────

def _company(**kwargs) -> CompanyProfile:
    defaults = dict(
        company_name="טסט בע\"מ",
        company_reg_id="123456789",
        harvest_keywords=["מיזוג אוויר"],
        preferred_tender_types=[],
        min_days_to_deadline=7,
        min_project_value_ils=500_000,
        max_project_value_ils=10_000_000,
    )
    return CompanyProfile(**{**defaults, **kwargs})


def _raw(
    title="מכרז מיזוג אוויר לבניין עירייה",
    deadline_days=30,
    budget=3_000_000,
    tender_type="office",
    subjects=None,
    source_id="budgetkey",
    external_id="bk_001",
) -> RawTenderRecord:
    return RawTenderRecord(
        source_id=source_id,
        external_id=external_id,
        title_he=title,
        subjects=subjects if subjects is not None else ["מיזוג אוויר"],
        tender_type=tender_type,
        deadline=date.today() + timedelta(days=deadline_days),
        estimated_budget_ils=budget,
    )


# ── BasicMetadataFilter ────────────────────────────────────────────────────────

class TestBasicMetadataFilter:
    def setup_method(self):
        self.f = BasicMetadataFilter()

    def _check(self, raw, company) -> bool:
        return self.f.should_analyze(raw, [company])

    def test_keyword_match_passes(self):
        assert self._check(_raw(title="מכרז מיזוג אוויר"), _company(harvest_keywords=["מיזוג אוויר"]))

    def test_keyword_no_match_rejects(self):
        raw = _raw(title="מכרז כביש ושיפוץ", subjects=[])
        assert not self._check(raw, _company(harvest_keywords=["מיזוג אוויר"]))

    def test_empty_keywords_accepts_all(self):
        assert self._check(_raw(title="כל מכרז"), _company(harvest_keywords=[]))

    def test_keyword_case_insensitive(self):
        assert self._check(_raw(title="HVAC מערכת"), _company(harvest_keywords=["hvac"]))

    def test_keyword_matched_in_subjects(self):
        raw = _raw(title="מכרז כללי", subjects=["מיזוג אוויר", "אינסטלציה"])
        assert self._check(raw, _company(harvest_keywords=["מיזוג אוויר"]))

    def test_deadline_too_soon_rejects(self):
        raw = _raw(deadline_days=3)
        assert not self._check(raw, _company(min_days_to_deadline=7))

    def test_deadline_exactly_at_threshold_passes(self):
        raw = _raw(deadline_days=7)
        assert self._check(raw, _company(min_days_to_deadline=7))

    def test_no_deadline_always_passes_deadline_check(self):
        raw = _raw()
        raw.deadline = None
        assert self._check(raw, _company(min_days_to_deadline=7))

    def test_budget_too_small_rejects(self):
        raw = _raw(budget=100_000)  # well below 0.5 * 500K = 250K
        assert not self._check(raw, _company(min_project_value_ils=500_000))

    def test_budget_too_large_rejects(self):
        raw = _raw(budget=50_000_000)  # above 2 * 10M = 20M
        assert not self._check(raw, _company(max_project_value_ils=10_000_000))

    def test_budget_in_range_passes(self):
        raw = _raw(budget=3_000_000)
        assert self._check(raw, _company(min_project_value_ils=500_000, max_project_value_ils=10_000_000))

    def test_no_budget_skips_budget_check(self):
        raw = _raw()
        raw.estimated_budget_ils = None
        assert self._check(raw, _company())

    def test_preferred_tender_type_match(self):
        raw = _raw(tender_type="office")
        assert self._check(raw, _company(preferred_tender_types=["office"]))

    def test_preferred_tender_type_mismatch_rejects(self):
        raw = _raw(tender_type="exemptions")
        assert not self._check(raw, _company(preferred_tender_types=["office"]))

    def test_empty_preferred_types_accepts_all(self):
        raw = _raw(tender_type="exemptions")
        assert self._check(raw, _company(preferred_tender_types=[]))

    def test_no_tender_type_skips_type_check(self):
        raw = _raw()
        raw.tender_type = None
        assert self._check(raw, _company(preferred_tender_types=["office"]))

    def test_any_matching_company_passes(self):
        """Tender rejected by company A but accepted by company B → should_analyze=True."""
        company_a = _company(harvest_keywords=["כביש"])  # won't match
        company_b = _company(harvest_keywords=["מיזוג אוויר"])  # will match
        assert self.f.should_analyze(_raw(), [company_a, company_b])

    def test_all_companies_reject_returns_false(self):
        company_a = _company(harvest_keywords=["כביש"])
        company_b = _company(harvest_keywords=["ביוב"])
        assert not self.f.should_analyze(_raw(), [company_a, company_b])

    def test_no_companies_returns_false(self):
        assert not self.f.should_analyze(_raw(), [])


class TestAcceptAllFilter:
    def test_always_true(self):
        f = AcceptAllFilter()
        assert f.should_analyze(_raw(), [])
        assert f.should_analyze(_raw(title="irrelevant"), [_company(harvest_keywords=["other"])])


# ── TenderSource protocol ──────────────────────────────────────────────────────

class TestTenderSourceProtocol:
    def test_budgetkey_satisfies_protocol(self):
        assert isinstance(BudgetKeySource(), TenderSource)

    def test_manual_satisfies_protocol(self):
        assert isinstance(ManualSource(), TenderSource)


# ── BudgetKeySource parsing helpers ───────────────────────────────────────────

class TestBudgetKeyParsers:
    def test_parse_date_iso(self):
        assert _parse_date("2025-06-15") == date(2025, 6, 15)

    def test_parse_date_with_time(self):
        assert _parse_date("2025-06-15T00:00:00") == date(2025, 6, 15)

    def test_parse_date_none(self):
        assert _parse_date(None) is None

    def test_parse_date_empty(self):
        assert _parse_date("") is None

    def test_parse_date_invalid(self):
        assert _parse_date("not-a-date") is None

    def test_safe_float_valid(self):
        assert _safe_float(1_500_000) == 1_500_000.0

    def test_safe_float_string(self):
        assert _safe_float("3500000") == 3_500_000.0

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_parse_subjects_semicolon(self):
        result = _parse_subjects("מיזוג אוויר;אינסטלציה;חשמל")
        assert result == ["מיזוג אוויר", "אינסטלציה", "חשמל"]

    def test_parse_subjects_comma(self):
        result = _parse_subjects("מיזוג אוויר,חשמל")
        assert result == ["מיזוג אוויר", "חשמל"]

    def test_parse_subjects_empty(self):
        assert _parse_subjects(None) == []
        assert _parse_subjects("") == []

    def test_parse_pdf_urls_list_of_dicts(self):
        docs = [{"link": "https://example.com/a.pdf"}, {"link": "https://example.com/b.pdf"}]
        assert _parse_pdf_urls(docs) == ["https://example.com/a.pdf", "https://example.com/b.pdf"]

    def test_parse_pdf_urls_json_string(self):
        import json
        docs = json.dumps([{"link": "https://example.com/c.pdf"}])
        assert _parse_pdf_urls(docs) == ["https://example.com/c.pdf"]

    def test_parse_pdf_urls_none(self):
        assert _parse_pdf_urls(None) == []

    def test_parse_pdf_urls_missing_link_key(self):
        assert _parse_pdf_urls([{"description": "no link here"}]) == []


def _mock_httpx(fake_response: dict):
    """Context manager that patches httpx.AsyncClient to return fake_response."""
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = fake_response

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    return patch("httpx.AsyncClient", return_value=ctx)


class TestBudgetKeySourceFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_records(self):
        fake_response = {
            "rows": [
                {
                    "publication_id": "42",
                    "tender_id": "T42",
                    "tender_type": "office",
                    "description": "מכרז מיזוג אוויר",
                    "publisher": "עיריית תל אביב",
                    "publication_date": "2025-05-01",
                    "claim_date": "2025-07-01",
                    "volume": 2_500_000,
                    "subjects": "מיזוג אוויר;תחזוקה",
                    "documents": [{"link": "https://example.com/42.pdf"}],
                }
            ]
        }

        with _mock_httpx(fake_response):
            records = await BudgetKeySource().fetch_new()

        assert len(records) == 1
        r = records[0]
        assert r.source_id == "budgetkey"
        assert r.external_id == "office_42"
        assert r.title_he == "מכרז מיזוג אוויר"
        assert r.publisher_he == "עיריית תל אביב"
        assert r.tender_type == "office"
        assert r.deadline == date(2025, 7, 1)
        assert r.estimated_budget_ils == 2_500_000.0
        assert r.subjects == ["מיזוג אוויר", "תחזוקה"]
        assert r.pdf_urls == ["https://example.com/42.pdf"]

    @pytest.mark.asyncio
    async def test_fetch_empty_response(self):
        with _mock_httpx({"rows": []}):
            records = await BudgetKeySource().fetch_new()
        assert records == []


# ── ManualSource ───────────────────────────────────────────────────────────────

class TestManualSource:
    @pytest.mark.asyncio
    async def test_fetch_new_always_empty(self):
        records = await ManualSource().fetch_new()
        assert records == []

    def test_make_record(self):
        rec = ManualSource.make_record("tender.pdf", b"%PDF", "COMPANY-1")
        assert rec.source_id == "manual"
        assert rec.uploaded_by == "COMPANY-1"
        assert rec.pdf_blob == b"%PDF"
        assert "tender.pdf" in rec.external_id


# ── CompanyProfile new fields ──────────────────────────────────────────────────

class TestCompanyProfileHarvestFields:
    def test_defaults(self):
        p = CompanyProfile(company_name="חברה", company_reg_id="123456789")
        assert p.harvest_keywords == []
        assert p.preferred_tender_types == []
        assert p.min_days_to_deadline == 7

    def test_harvest_keywords_set(self):
        p = CompanyProfile(
            company_name="חברה",
            company_reg_id="123456789",
            harvest_keywords=["HVAC", "מיזוג"],
        )
        assert "HVAC" in p.harvest_keywords

    def test_preferred_tender_types_validated(self):
        p = CompanyProfile(
            company_name="חברה",
            company_reg_id="123456789",
            preferred_tender_types=["office", "central"],
        )
        assert "office" in p.preferred_tender_types

    def test_min_days_to_deadline_non_negative(self):
        with pytest.raises(Exception):
            CompanyProfile(
                company_name="חברה",
                company_reg_id="123456789",
                min_days_to_deadline=-1,
            )
