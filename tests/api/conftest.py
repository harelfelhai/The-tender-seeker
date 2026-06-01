"""Shared fixtures for API tests — in-memory SQLite, zero LLM calls."""
from __future__ import annotations

import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.smarttender.api.database as db_mod
from src.smarttender.agents.criteria_agent import CriteriaAgent
from src.smarttender.api.app import app
from src.smarttender.api.database import Base, TenderRow, get_db
from src.smarttender.schemas.company_profile import (
    CompanyProfile,
    ContractorClassification,
    ExperienceRecord,
    InsuranceCoverage,
)


# ── in-memory DB per test ─────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    """TestClient wired to a fresh in-memory SQLite DB for each test.

    StaticPool ensures all connections share the same in-memory DB so that
    Base.metadata.create_all() and subsequent queries see the same tables.
    """
    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(mem_engine)
    TestSession = sessionmaker(bind=mem_engine, autocommit=False, autoflush=False)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # Prevent lifespan init_db() from touching the real file-based engine
    monkeypatch.setattr(db_mod, "init_db", lambda: None)
    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as c:
        # Expose the session factory so helpers can seed data in the same DB
        c._test_session = TestSession
        yield c

    app.dependency_overrides.clear()


def seed_tender(client: TestClient, analysis=None):
    """Insert a tender directly into the test DB (no PDF upload, no LLM)."""
    if analysis is None:
        analysis = CriteriaAgent.mock()
    db = client._test_session()
    try:
        row = TenderRow(
            id=analysis.tender_id,
            title_he=analysis.title_he,
            publisher_he=analysis.publisher_he,
            source_pdf="mock.pdf",
            analysis_json=analysis.model_dump_json(),
            model_used="mock",
        )
        db.merge(row)
        db.commit()
    finally:
        db.close()
    return analysis


# ── company payload ───────────────────────────────────────────────────────────

def company_payload(reg_id: str = "514123456", name: str = "טק-קול בע\"מ") -> dict:
    y = date.today().year
    return CompanyProfile(
        company_name=name,
        company_reg_id=reg_id,
        annual_revenues={y - 1: 6_000_000, y - 2: 6_500_000, y - 3: 5_800_000},
        contractor_classifications=[
            ContractorClassification(branch_code="170", group_letter="ג", financial_tier=3)
        ],
        certifications=["ISO 9001"],
        similar_public_projects=[
            ExperienceRecord(project_name="פרויקט א", client_type="municipal", year=y - 1, value_ils=1_200_000),
            ExperienceRecord(project_name="פרויקט ב", client_type="government", year=y - 2, value_ils=900_000),
            ExperienceRecord(project_name="פרויקט ג", client_type="municipal", year=y - 3, value_ils=750_000),
        ],
        insurances=[InsuranceCoverage(insurance_type="third_party_liability", coverage_ils=12_000_000)],
        operating_regions=["מרכז"],
        domains=["מיזוג אוויר"],
        min_project_value_ils=500_000,
        max_project_value_ils=8_000_000,
        preferred_client_types=["municipal"],
        available_capacity_pct=65,
    ).model_dump(mode="json")


# ── compound fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def registered(client):
    """Register a company and return (client, api_key, company_id)."""
    resp = client.post("/auth/register", json=company_payload())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return client, data["api_key"], data["company_id"]


@pytest.fixture()
def authed(registered):
    """TestClient with X-API-Key already set in default headers."""
    c, api_key, company_id = registered
    c.headers = {**c.headers, "X-API-Key": api_key}
    return c, company_id


@pytest.fixture()
def authed_with_tender(authed):
    """Authed client + one mock tender seeded in the test DB."""
    c, company_id = authed
    analysis = seed_tender(c)
    return c, company_id, analysis
