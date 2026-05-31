from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MatchCriterionResult(BaseModel):
    criterion_id: str
    description_he: str
    category: str
    mandatory: bool
    passed: bool
    unverifiable: bool = Field(
        default=False,
        description="Engine could not auto-decide (documentary/unmodeled) → manual review, not a disqualification",
    )
    reason_he: str = Field(description="Human-readable Hebrew explanation of pass/fail")
    company_value: Optional[str] = Field(default=None, description="What the company currently holds")
    required_value: str = Field(description="What the tender requires")
    gap: Optional[str] = Field(default=None, description="Quantified shortfall when failed")
    confidence: float = 1.0
    page: Optional[int] = None


class MatchReport(BaseModel):
    tender_id: str
    tender_title_he: str
    publisher_he: str
    company_name: str

    is_eligible: bool = Field(description="True only when all mandatory criteria pass")
    compatibility_score: float = Field(ge=0.0, le=100.0)

    passed_mandatory: int
    failed_mandatory: int
    passed_optional: int
    failed_optional: int
    unverifiable_mandatory: int = 0

    breakdown: list[MatchCriterionResult]
    summary_he: str = Field(description="One-sentence Hebrew verdict")
