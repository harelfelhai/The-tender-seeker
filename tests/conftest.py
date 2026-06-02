"""Shared fixtures — zero API calls, zero cost."""
from __future__ import annotations

import pytest
from datetime import date

from src.smarttender.schemas.company_profile import (
    CompanyProfile,
    ContractorClassification,
    ExperienceRecord,
    InsuranceCoverage,
)
from src.smarttender.schemas.tender import (
    CriteriaCategory,
    Operator,
    TenderAnalysisOutput,
    TenderCriteriaPredicate,
    TenderProfile,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def make_predicate(
    *,
    field: str = "annual_turnover_ils",
    operator: Operator = Operator.GTE,
    value=5_000_000,
    mandatory: bool = True,
    description_he: str = "תנאי בדיקה",
    lookback_years: int | None = None,
    aggregation: str | None = None,
    qualifier: dict | None = None,
    page: int | None = 5,
    confidence: float = 0.9,
) -> TenderCriteriaPredicate:
    return TenderCriteriaPredicate(
        id="C1",
        category=CriteriaCategory.FINANCIAL,
        description_he=description_he,
        field=field,
        operator=operator,
        value=value,
        mandatory=mandatory,
        lookback_years=lookback_years,
        aggregation=aggregation,
        qualifier=qualifier,
        page=page,
        quote_he="ציטוט לדוגמה",
        confidence=confidence,
    )


def make_company(
    *,
    revenues: dict | None = None,
    classifications: list | None = None,
    certifications: list | None = None,
    projects: list | None = None,
    insurances: list | None = None,
    regions: list | None = None,
    domains: list | None = None,
    min_project: float | None = None,
    max_project: float | None = None,
    preferred_clients: list | None = None,
    capacity: float | None = None,
) -> CompanyProfile:
    y = date.today().year
    return CompanyProfile(
        company_name="חברת בדיקה בע\"מ",
        company_reg_id="500000001",
        annual_revenues=revenues or {y - 1: 6_000_000, y - 2: 6_000_000, y - 3: 6_000_000},
        contractor_classifications=classifications or [],
        certifications=certifications or [],
        similar_public_projects=projects or [],
        insurances=insurances or [],
        operating_regions=regions if regions is not None else ["מרכז"],
        domains=domains if domains is not None else ["מיזוג אוויר"],
        min_project_value_ils=min_project,
        max_project_value_ils=max_project,
        preferred_client_types=preferred_clients if preferred_clients is not None else ["municipal"],
        available_capacity_pct=capacity,
    )


def make_analysis(criteria: list[TenderCriteriaPredicate], profile: TenderProfile | None = None) -> TenderAnalysisOutput:
    return TenderAnalysisOutput(
        tender_id="TEST-001",
        title_he="מכרז בדיקה",
        publisher_he="עיריית בדיקה",
        criteria=criteria,
        tender_profile=profile or TenderProfile(),
        raw_summary_he="מכרז לצורכי בדיקות אוטומטיות.",
    )
