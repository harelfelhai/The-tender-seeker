from __future__ import annotations

from pydantic import BaseModel, Field


class FactorResult(BaseModel):
    """One relevance dimension's contribution to the fit score.

    `score` is 0..1; `weight` is its share of the total. `score`, `weight` and
    the company/tender values together form exactly the feature a future ML
    model would learn weights for — so today's transparent rules become
    tomorrow's training features.
    """

    name: str                       # geo_fit | domain_fit | size_fit | client_fit | capacity_fit
    label_he: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    company_value: str
    tender_value: str
    explanation_he: str
    is_neutral: bool = Field(
        default=False, description="True when data was missing and we neither rewarded nor penalized"
    )


class RelevanceReport(BaseModel):
    """How interesting a (qualifying) tender is to the company, 0..100."""

    relevance_score: float = Field(ge=0.0, le=100.0)
    factors: list[FactorResult]
    summary_he: str
