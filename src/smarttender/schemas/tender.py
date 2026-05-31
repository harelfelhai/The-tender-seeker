from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from enum import Enum


class CriteriaCategory(str, Enum):
    FINANCIAL = "financial"
    CLASSIFICATION = "classification"
    EXPERIENCE = "experience"
    CERTIFICATION = "certification"
    INSURANCE = "insurance"
    LEGAL = "legal"
    PERSONNEL = "personnel"
    OTHER = "other"


class Operator(str, Enum):
    """Operators used in machine-comparable predicates.

    Operator symbols are the enum *values* so the LLM can output them verbatim.
    """

    GTE = ">="
    LTE = "<="
    EQ = "=="
    CONTAINS = "contains"
    SATISFIES_CLASSIFICATION = "satisfies_classification"
    EXISTS = "exists"
    COUNT_GTE = "count>="


class TenderCriteriaPredicate(BaseModel):
    """A single machine-comparable requirement extracted from a tender document.

    Field naming convention used in `field`:
      - "annual_turnover_ils"               → profile.annual_revenues (with lookback)
      - "contractor_classification"          → profile.contractor_classifications
      - "certifications"                     → profile.certifications (list[str])
      - "similar_public_projects"            → profile.similar_public_projects (with qualifier)
      - "equity_ils"                         → profile.equity_ils (direct)
      - "insurance_{type}"                   → profile.insurances matched by type
      - "experience_years"                   → profile.experience_years (direct)
      - "employees_count"                    → profile.employees_count (direct)
    """

    id: str
    category: CriteriaCategory
    description_he: str = Field(description="Full Hebrew description of the requirement")

    # machine-comparable predicate ───────────────────────────────────────────
    field: str = Field(description="Profile field key (see naming convention above)")
    operator: Operator
    value: Any = Field(description="Required value; type depends on operator")

    # qualifier / context ────────────────────────────────────────────────────
    mandatory: bool = Field(
        default=True,
        description="True = תנאי סף (disqualifying); False = advantage / scored",
    )
    lookback_years: Optional[int] = Field(
        default=None, description="For financial/experience fields"
    )
    aggregation: Optional[Literal["each_year", "any_year", "cumulative", "latest"]] = None
    qualifier: Optional[dict[str, Any]] = Field(
        default=None, description="Extra filter conditions (e.g. client_type, min_project_value_ils)"
    )

    # provenance ─────────────────────────────────────────────────────────────
    page: Optional[int] = None
    quote_he: Optional[str] = Field(
        default=None, description="Verbatim Hebrew quote from source document"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    needs_review: bool = False


class TenderAnalysisOutput(BaseModel):
    """Complete structured output produced by the Criteria Agent."""

    tender_id: str
    title_he: str
    publisher_he: str
    submission_deadline: Optional[str] = None
    estimated_budget_ils: Optional[float] = None

    criteria: list[TenderCriteriaPredicate]

    raw_summary_he: str = Field(description="One-paragraph Hebrew summary of the tender")
    extraction_meta: dict[str, Any] = Field(default_factory=dict)
