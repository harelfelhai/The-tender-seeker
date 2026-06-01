from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ContractorClassification(BaseModel):
    """Israeli contractor classification (סיווג קבלני).

    branch_code maps to the רשם הקבלנים ענף number (e.g. "100" = general building,
    "170" = HVAC, "260" = electrical).  group_letter is the capability group
    (א = lowest … ה = highest); financial_tier is 1–5.
    """

    branch_code: str
    group_letter: str  # "א" | "ב" | "ג" | "ד" | "ה"
    financial_tier: int = Field(ge=1, le=5)
    valid_until: Optional[date] = None


class ExperienceRecord(BaseModel):
    """A single completed project used to prove relevant experience."""

    project_name: str
    client_type: str  # "public" | "municipal" | "government" | "private"
    value_ils: Optional[float] = Field(default=None, ge=0)
    year: int  # year the project was completed
    domain_tags: list[str] = Field(default_factory=list)


class InsuranceCoverage(BaseModel):
    insurance_type: str  # "third_party_liability" | "professional" | "employer" | ...
    coverage_ils: float = Field(ge=0)
    valid_until: Optional[date] = None


class CompanyProfile(BaseModel):
    """Complete profile of an Israeli SMB used for eligibility evaluation."""

    company_name: str
    company_reg_id: Optional[str] = None  # ח.פ / ע.מ

    # ── financials ──────────────────────────────────────────────────────────
    annual_revenues: dict[int, float] = Field(
        default_factory=dict,
        description="Fiscal year → annual turnover in ILS. E.g. {2023: 4_200_000}",
    )
    equity_ils: Optional[float] = None

    # ── Israeli-specific registrations ──────────────────────────────────────
    contractor_classifications: list[ContractorClassification] = Field(default_factory=list)

    # ── credentials ─────────────────────────────────────────────────────────
    certifications: list[str] = Field(
        default_factory=list,
        description='E.g. ["ISO 9001", "ISO 14001"]',
    )

    # ── track record ────────────────────────────────────────────────────────
    experience_years: int = Field(default=0, ge=0)
    similar_public_projects: list[ExperienceRecord] = Field(default_factory=list)

    # ── insurance ───────────────────────────────────────────────────────────
    insurances: list[InsuranceCoverage] = Field(default_factory=list)

    employees_count: Optional[int] = Field(default=None, ge=0)

    # ── characterization (for RELEVANCE scoring, not eligibility) ────────────
    # These describe the *nature* of the company so we can score how interesting
    # a (qualifying) tender is — not whether it qualifies. Each field mirrors a
    # field extracted from the tender (see TenderProfile) → one relevance factor.
    operating_regions: list[str] = Field(
        default_factory=list,
        description='Regions the company works in, e.g. ["צפון", "מרכז"]',
    )
    domains: list[str] = Field(
        default_factory=list,
        description='Specialties, e.g. ["מיזוג אוויר", "תשתיות"]',
    )
    min_project_value_ils: Optional[float] = Field(
        default=None, ge=0, description="Smallest comfortable project size"
    )
    max_project_value_ils: Optional[float] = Field(
        default=None, ge=0, description="Largest comfortable project size"
    )
    preferred_client_types: list[str] = Field(
        default_factory=list,
        description='e.g. ["municipal", "government", "rmi"]',
    )
    available_capacity_pct: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="How much free capacity to take on new work (0-100)",
    )

    # ── harvest pre-filters ──────────────────────────────────────────────────
    # Used to filter RAW tenders by metadata BEFORE LLM extraction (no PDF).
    # A tender must match at least one active company's filters to be analyzed.
    harvest_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Hebrew keywords matched against tender titles and subject tags from "
            "source APIs. E.g. ['מיזוג אוויר', 'HVAC', 'מערכות קירור']. "
            "Empty = no keyword filter (accept all)."
        ),
    )
    preferred_tender_types: list[Literal["office", "central", "exemptions"]] = Field(
        default_factory=list,
        description=(
            "BudgetKey tender types to track: 'office' (משרדי), 'central' (מרכזי), "
            "'exemptions' (פטור ממכרז). Empty = all types."
        ),
    )
    min_days_to_deadline: int = Field(
        default=7,
        ge=0,
        description=(
            "Ignore tenders whose submission deadline is fewer than this many days away. "
            "Prevents wasting analysis cost on tenders the company can't realistically bid on."
        ),
    )
