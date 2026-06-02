"""Deterministic Match Engine.

evaluate_match() is the single public function.  It never calls an LLM —
all comparisons are performed by operators.py using exact arithmetic and
rules.  The resulting MatchReport carries per-criterion pass/fail with
explicit Hebrew mismatch reasons.
"""

from __future__ import annotations

from ..schemas.company_profile import CompanyProfile
from ..schemas.match import MatchCriterionResult, MatchReport
from ..schemas.tender import TenderAnalysisOutput
from .operators import evaluate


def evaluate_match(profile: CompanyProfile, analysis: TenderAnalysisOutput) -> MatchReport:
    breakdown: list[MatchCriterionResult] = []

    for predicate in analysis.criteria:
        result = evaluate(predicate, profile)
        breakdown.append(
            MatchCriterionResult(
                criterion_id=predicate.id,
                description_he=predicate.description_he,
                category=predicate.category.value,
                mandatory=predicate.mandatory,
                passed=result.passed,
                unverifiable=result.unverifiable,
                reason_he=result.reason_he,
                company_value=result.company_value_str,
                required_value=result.required_value_str,
                gap=result.gap,
                confidence=predicate.confidence,
                page=predicate.page,
            )
        )

    mandatory = [r for r in breakdown if r.mandatory]
    optional = [r for r in breakdown if not r.mandatory]

    # Unverifiable criteria are excluded from pass/fail: they neither disqualify
    # nor count toward the score — they are surfaced for manual review.
    passed_m = sum(1 for r in mandatory if r.passed and not r.unverifiable)
    failed_m = sum(1 for r in mandatory if not r.passed and not r.unverifiable)
    unver_m = sum(1 for r in mandatory if r.unverifiable)
    passed_o = sum(1 for r in optional if r.passed and not r.unverifiable)
    failed_o = sum(1 for r in optional if not r.passed and not r.unverifiable)

    # Eligibility depends only on *verifiable* mandatory criteria.
    is_eligible = failed_m == 0

    # Score over verifiable criteria only.
    verifiable = [r for r in breakdown if not r.unverifiable]
    ver_mandatory = [r for r in mandatory if not r.unverifiable]
    if not verifiable:
        score = 0.0
    else:
        m_rate = passed_m / len(ver_mandatory) if ver_mandatory else 1.0
        all_rate = (passed_m + passed_o) / len(verifiable)
        score = round((0.6 * m_rate + 0.4 * all_rate) * 100, 1)

    review_note = f" {unver_m} דרישות לבדיקה ידנית." if unver_m else ""
    if is_eligible:
        summary_he = (
            f"החברה עומדת בכל {passed_m} תנאי הסף הניתנים לאימות אוטומטי.{review_note} "
            f"ציון כשירות: {score}/100."
        )
    else:
        failed_items = [r for r in mandatory if not r.passed and not r.unverifiable]
        short_descs = "; ".join(r.description_he[:35] + "…" for r in failed_items[:3])
        suffix = f" (+{len(failed_items) - 3} נוספים)" if len(failed_items) > 3 else ""
        summary_he = (
            f"החברה אינה עומדת ב-{failed_m} תנאי סף מחייבים: {short_descs}{suffix}.{review_note} "
            f"ציון כשירות: {score}/100."
        )

    return MatchReport(
        tender_id=analysis.tender_id,
        tender_title_he=analysis.title_he,
        publisher_he=analysis.publisher_he,
        company_name=profile.company_name,
        is_eligible=is_eligible,
        compatibility_score=score,
        passed_mandatory=passed_m,
        failed_mandatory=failed_m,
        passed_optional=passed_o,
        failed_optional=failed_o,
        unverifiable_mandatory=unver_m,
        breakdown=breakdown,
        summary_he=summary_he,
    )
