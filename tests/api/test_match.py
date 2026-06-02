"""Tests for /match endpoints — zero LLM calls."""
from __future__ import annotations

from src.smarttender.agents.criteria_agent import CriteriaAgent
from src.smarttender.schemas.tender import (
    CriteriaCategory,
    Operator,
    TenderAnalysisOutput,
    TenderCriteriaPredicate,
    TenderProfile,
)

from .conftest import company_payload, seed_tender


class TestMatchSingle:
    def test_requires_auth(self, client):
        assert client.get("/match/SOME-TENDER").status_code == 401

    def test_tender_not_found_404(self, authed):
        client, _ = authed
        assert client.get("/match/NONEXISTENT").status_code == 404

    def test_eligible_company_returns_score(self, authed_with_tender):
        client, company_id, analysis = authed_with_tender
        resp = client.get(f"/match/{analysis.tender_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_id"] == company_id
        assert data["tender_id"] == analysis.tender_id
        assert data["is_eligible"] is True
        assert data["final_score"] > 0
        assert data["compatibility_score"] > 0
        assert "breakdown" in data
        assert "relevance_factors" in data

    def test_ineligible_company_final_score_zero(self, client):
        """Company that fails תנאי סף gets final_score=0 regardless of relevance."""
        from datetime import date
        from src.smarttender.schemas.company_profile import CompanyProfile

        y = date.today().year
        weak = CompanyProfile(
            company_name="חברה חלשה",
            company_reg_id="999999999",
            annual_revenues={y - 1: 100_000},  # far below 5M threshold
            contractor_classifications=[],
            certifications=[],
            similar_public_projects=[],
            insurances=[],
            operating_regions=["מרכז"],
            domains=["מיזוג אוויר"],
            preferred_client_types=["municipal"],
        )
        key = client.post("/auth/register", json=weak.model_dump(mode="json")).json()["api_key"]
        analysis = seed_tender(client)

        resp = client.get(f"/match/{analysis.tender_id}", headers={"X-API-Key": key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_eligible"] is False
        assert data["final_score"] == 0.0

    def test_response_has_hebrew_summary(self, authed_with_tender):
        client, _, analysis = authed_with_tender
        data = client.get(f"/match/{analysis.tender_id}").json()
        assert data["summary_he"] and len(data["summary_he"]) > 10

    def test_breakdown_length_matches_criteria_count(self, authed_with_tender):
        client, _, analysis = authed_with_tender
        data = client.get(f"/match/{analysis.tender_id}").json()
        assert len(data["breakdown"]) == len(analysis.criteria)

    def test_five_relevance_factors(self, authed_with_tender):
        client, _, analysis = authed_with_tender
        data = client.get(f"/match/{analysis.tender_id}").json()
        assert len(data["relevance_factors"]) == 5


class TestMatchAll:
    def test_requires_auth(self, client):
        assert client.get("/match").status_code == 401

    def test_empty_when_no_tenders(self, authed):
        client, _ = authed
        data = client.get("/match").json()
        assert data["matches"] == []

    def test_returns_one_result_for_one_tender(self, authed_with_tender):
        client, company_id, _ = authed_with_tender
        data = client.get("/match").json()
        assert data["company_id"] == company_id
        assert data["total"] == 1

    def test_sorted_by_final_score_descending(self, authed):
        """Eligible tender ranks above ineligible tender."""
        client, _ = authed

        # Eligible tender (mock — company passes all criteria)
        seed_tender(client, CriteriaAgent.mock())

        # Ineligible tender — one impossible financial criterion
        hard = TenderAnalysisOutput(
            tender_id="HARD-001",
            title_he="מכרז קשה",
            publisher_he="גוף ממשלתי",
            raw_summary_he="מכרז עם תנאי סף גבוהים מאוד",
            criteria=[
                TenderCriteriaPredicate(
                    id="C1",
                    category=CriteriaCategory.FINANCIAL,
                    description_he="מחזור שנתי לפחות 500,000,000 ש\"ח",
                    field="annual_turnover_ils",
                    operator=Operator.GTE,
                    value=500_000_000,
                    mandatory=True,
                    lookback_years=1,
                    aggregation="each_year",
                    confidence=0.99,
                )
            ],
            tender_profile=TenderProfile(region="מרכז", domains=["מיזוג אוויר"], publisher_type="government"),
        )
        seed_tender(client, hard)

        matches = client.get("/match").json()["matches"]
        assert len(matches) == 2
        assert matches[0]["final_score"] >= matches[1]["final_score"]
        assert matches[0]["is_eligible"] is True
        assert matches[1]["is_eligible"] is False
        assert matches[1]["final_score"] == 0.0

    def test_company_isolation(self, client):
        """Each company's /match uses their own profile, returns their own company_id."""
        key_a = client.post("/auth/register", json=company_payload("AAA", "חברה א")).json()["api_key"]
        key_b = client.post("/auth/register", json=company_payload("BBB", "חברה ב")).json()["api_key"]

        seed_tender(client)

        # Both see the shared tender list
        assert len(client.get("/tenders", headers={"X-API-Key": key_a}).json()) == 1
        assert len(client.get("/tenders", headers={"X-API-Key": key_b}).json()) == 1

        # Each /match response is scoped to the authenticated company
        assert client.get("/match", headers={"X-API-Key": key_a}).json()["company_id"] == "AAA"
        assert client.get("/match", headers={"X-API-Key": key_b}).json()["company_id"] == "BBB"


class TestCompanyProfile:
    def test_get_my_company_requires_auth(self, client):
        assert client.get("/companies/me").status_code == 401

    def test_get_my_company_returns_profile(self, authed):
        client, company_id = authed
        resp = client.get("/companies/me")
        assert resp.status_code == 200
        assert resp.json()["company_reg_id"] == company_id

    def test_update_my_company(self, authed):
        client, _ = authed
        profile = client.get("/companies/me").json()
        profile["company_name"] = "שם חדש"
        resp = client.put("/companies/me", json=profile)
        assert resp.status_code == 200
        assert client.get("/companies/me").json()["company_name"] == "שם חדש"
