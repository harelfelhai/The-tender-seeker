"""Unit tests for match_engine/engine.py — zero API calls."""
from __future__ import annotations

from src.smarttender.match_engine.engine import evaluate_match
from src.smarttender.schemas.company_profile import ContractorClassification, InsuranceCoverage
from src.smarttender.schemas.tender import Operator

from .conftest import make_analysis, make_company, make_predicate


def _passing_company():
    """Company that satisfies every criterion in _full_analysis()."""
    from datetime import date
    y = date.today().year
    return make_company(
        revenues={y - 1: 6_000_000, y - 2: 6_000_000, y - 3: 6_000_000},
        classifications=[ContractorClassification(branch_code="170", group_letter="ג", financial_tier=3)],
        certifications=["ISO 9001"],
        insurances=[InsuranceCoverage(insurance_type="third_party_liability", coverage_ils=12_000_000)],
    )


def _full_analysis():
    """Analysis with financial + classification + certification + insurance criteria."""
    return make_analysis([
        make_predicate(
            field="annual_turnover_ils", value=5_000_000,
            lookback_years=3, aggregation="each_year", mandatory=True,
        ),
        make_predicate(
            field="contractor_classification",
            operator=Operator.SATISFIES_CLASSIFICATION,
            value={"branch_code": "170", "min_group_letter": "ג", "min_financial_tier": 3},
            mandatory=True,
        ),
        make_predicate(
            field="certifications", operator=Operator.CONTAINS, value="ISO 9001",
            mandatory=True,
        ),
        make_predicate(
            field="insurance_third_party_liability", value=10_000_000,
            mandatory=True,
        ),
    ])


class TestEvaluateMatch:
    def test_all_pass_eligible(self):
        report = evaluate_match(_passing_company(), _full_analysis())
        assert report.is_eligible is True
        assert report.failed_mandatory == 0
        assert report.passed_mandatory == 4

    def test_all_pass_score_100(self):
        report = evaluate_match(_passing_company(), _full_analysis())
        assert report.compatibility_score == 100.0

    def test_one_mandatory_fail_not_eligible(self):
        from datetime import date
        y = date.today().year
        co = _passing_company()
        # Revenue drops below threshold in all years
        co.annual_revenues = {y - 1: 1_000_000, y - 2: 1_000_000, y - 3: 1_000_000}
        report = evaluate_match(co, _full_analysis())
        assert report.is_eligible is False
        assert report.failed_mandatory >= 1

    def test_optional_fail_still_eligible(self):
        analysis = make_analysis([
            make_predicate(field="annual_turnover_ils", value=5_000_000,
                           lookback_years=1, aggregation="each_year", mandatory=True),
            make_predicate(field="certifications", operator=Operator.CONTAINS,
                           value="ISO 45001", mandatory=False),
        ])
        from datetime import date
        y = date.today().year
        co = make_company(
            revenues={y - 1: 7_000_000},
            certifications=[],  # missing optional cert
        )
        report = evaluate_match(co, analysis)
        assert report.is_eligible is True
        assert report.failed_optional == 1
        assert report.passed_mandatory == 1

    def test_unverifiable_mandatory_does_not_disqualify(self):
        analysis = make_analysis([
            make_predicate(field="annual_turnover_ils", value=5_000_000,
                           lookback_years=1, aggregation="each_year", mandatory=True),
            # Non-numeric value → unverifiable
            make_predicate(field="annual_turnover_ils", value="זהה לשם המציע",
                           mandatory=True, description_he="דרישה תיעודית"),
        ])
        from datetime import date
        y = date.today().year
        co = make_company(revenues={y - 1: 7_000_000})
        report = evaluate_match(co, analysis)
        assert report.is_eligible is True
        assert report.unverifiable_mandatory == 1
        assert report.passed_mandatory == 1

    def test_score_zero_when_no_verifiable_criteria(self):
        analysis = make_analysis([
            make_predicate(field="annual_turnover_ils", value="לא ידוע", mandatory=True),
        ])
        report = evaluate_match(make_company(), analysis)
        assert report.compatibility_score == 0.0

    def test_breakdown_length_matches_criteria(self):
        analysis = _full_analysis()
        report = evaluate_match(_passing_company(), analysis)
        assert len(report.breakdown) == len(analysis.criteria)

    def test_empty_criteria_eligible_score_zero(self):
        report = evaluate_match(make_company(), make_analysis([]))
        assert report.is_eligible is True
        assert report.compatibility_score == 0.0
