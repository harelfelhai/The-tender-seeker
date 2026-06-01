"""Unit tests for match_engine/operators.py — zero API calls."""
from __future__ import annotations

import pytest
from datetime import date

from src.smarttender.match_engine.operators import (
    _to_number,
    _eval_annual_turnover,
    _eval_classification,
    _eval_contains,
    _eval_count_gte,
    _eval_insurance,
    _eval_numeric,
    evaluate,
)
from src.smarttender.schemas.company_profile import ContractorClassification, ExperienceRecord, InsuranceCoverage
from src.smarttender.schemas.tender import Operator

from .conftest import make_company, make_predicate


# ══════════════════════════════════════════════════════════════════════════════
# _to_number
# ══════════════════════════════════════════════════════════════════════════════

class TestToNumber:
    def test_int(self):
        assert _to_number(5_000_000) == 5_000_000.0

    def test_float(self):
        assert _to_number(3.14) == pytest.approx(3.14)

    def test_string_plain(self):
        assert _to_number("1000") == 1000.0

    def test_string_with_commas(self):
        assert _to_number("5,000,000") == 5_000_000.0

    def test_string_embedded(self):
        assert _to_number("50,000 ש\"ח") == 50_000.0

    def test_percent_returns_none(self):
        assert _to_number("5% מהוצאות") is None

    def test_non_numeric_string(self):
        assert _to_number("זהה לשם ולמספר המזהה") is None

    def test_none_input(self):
        assert _to_number(None) is None

    def test_dict_input(self):
        assert _to_number({"a": 1}) is None


# ══════════════════════════════════════════════════════════════════════════════
# annual_turnover
# ══════════════════════════════════════════════════════════════════════════════

class TestAnnualTurnover:
    def _pred(self, value=5_000_000, lookback=3, aggregation="each_year"):
        return make_predicate(
            field="annual_turnover_ils", value=value,
            lookback_years=lookback, aggregation=aggregation,
        )

    def test_each_year_pass(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 6_000_000, y - 2: 6_000_000, y - 3: 6_000_000})
        result = _eval_annual_turnover(self._pred(), co)
        assert result.passed is True

    def test_each_year_fail_one(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 4_000_000, y - 2: 6_000_000, y - 3: 6_000_000})
        result = _eval_annual_turnover(self._pred(), co)
        assert result.passed is False
        assert result.gap is not None

    def test_each_year_all_fail(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 1_000_000, y - 2: 1_000_000, y - 3: 1_000_000})
        result = _eval_annual_turnover(self._pred(), co)
        assert result.passed is False

    def test_any_year_pass(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 2_000_000, y - 2: 6_000_000, y - 3: 2_000_000})
        result = _eval_annual_turnover(self._pred(aggregation="any_year"), co)
        assert result.passed is True

    def test_any_year_fail(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 1_000_000, y - 2: 2_000_000, y - 3: 3_000_000})
        result = _eval_annual_turnover(self._pred(aggregation="any_year"), co)
        assert result.passed is False

    def test_cumulative_pass(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 2_000_000, y - 2: 2_000_000, y - 3: 2_000_000})
        result = _eval_annual_turnover(self._pred(value=5_000_000, aggregation="cumulative"), co)
        assert result.passed is True  # 6M cumulative >= 5M

    def test_cumulative_fail(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 1_000_000, y - 2: 1_000_000, y - 3: 1_000_000})
        result = _eval_annual_turnover(self._pred(value=5_000_000, aggregation="cumulative"), co)
        assert result.passed is False

    def test_latest_pass(self):
        y = date.today().year
        co = make_company(revenues={y - 1: 7_000_000, y - 2: 2_000_000})
        result = _eval_annual_turnover(self._pred(lookback=1, aggregation="latest"), co)
        assert result.passed is True

    def test_non_numeric_value_unverifiable(self):
        pred = make_predicate(field="annual_turnover_ils", value="לא ידוע")
        co = make_company()
        result = _eval_annual_turnover(pred, co)
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# contractor_classification
# ══════════════════════════════════════════════════════════════════════════════

class TestClassification:
    def _pred(self, value=None):
        return make_predicate(
            field="contractor_classification",
            operator=Operator.SATISFIES_CLASSIFICATION,
            value=value or {"branch_code": "170", "min_group_letter": "ג", "min_financial_tier": 3},
        )

    def _co(self, branch="170", group="ג", tier=3):
        return make_company(classifications=[
            ContractorClassification(branch_code=branch, group_letter=group, financial_tier=tier)
        ])

    def test_exact_match(self):
        assert _eval_classification(self._pred(), self._co()).passed is True

    def test_higher_group_passes(self):
        assert _eval_classification(self._pred(), self._co(group="ד")).passed is True

    def test_lower_group_fails(self):
        assert _eval_classification(self._pred(), self._co(group="ב")).passed is False

    def test_higher_tier_passes(self):
        assert _eval_classification(self._pred(), self._co(tier=5)).passed is True

    def test_lower_tier_fails(self):
        assert _eval_classification(self._pred(), self._co(tier=2)).passed is False

    def test_wrong_branch_fails(self):
        assert _eval_classification(self._pred(), self._co(branch="200")).passed is False

    def test_no_classifications_fails(self):
        assert _eval_classification(self._pred(), make_company(classifications=[])).passed is False

    def test_bad_value_unverifiable(self):
        pred = make_predicate(
            field="contractor_classification",
            operator=Operator.SATISFIES_CLASSIFICATION,
            value="not-a-dict",
        )
        result = _eval_classification(pred, self._co())
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# count_gte (experience)
# ══════════════════════════════════════════════════════════════════════════════

class TestCountGte:
    def _projects(self, n: int, year_offset: int = 1, client_type: str = "municipal"):
        y = date.today().year
        return [
            ExperienceRecord(
                project_name=f"פרויקט {i}",
                client_type=client_type,
                year=y - year_offset,
                value_ils=500_000,
            )
            for i in range(n)
        ]

    def test_enough_projects_pass(self):
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value=3, lookback_years=5, qualifier={"client_type": "public"},
        )
        co = make_company(projects=self._projects(4))
        assert _eval_count_gte(pred, co).passed is True

    def test_too_few_projects_fail(self):
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value=3, lookback_years=5, qualifier={"client_type": "public"},
        )
        co = make_company(projects=self._projects(2))
        result = _eval_count_gte(pred, co)
        assert result.passed is False
        assert "חסרים" in result.gap

    def test_hebrew_client_type_alias(self):
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value=2, lookback_years=5, qualifier={"client_type": "רשות מקומית"},
        )
        co = make_company(projects=self._projects(3, client_type="municipal"))
        assert _eval_count_gte(pred, co).passed is True

    def test_lookback_filters_old_projects(self):
        y = date.today().year
        old = [ExperienceRecord(project_name="ישן", client_type="municipal", year=y - 10)]
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value=1, lookback_years=5, qualifier={"client_type": "public"},
        )
        co = make_company(projects=old)
        assert _eval_count_gte(pred, co).passed is False

    def test_private_client_not_counted_for_public(self):
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value=1, lookback_years=5, qualifier={"client_type": "public"},
        )
        co = make_company(projects=self._projects(3, client_type="private"))
        assert _eval_count_gte(pred, co).passed is False

    def test_non_numeric_value_unverifiable(self):
        pred = make_predicate(
            field="similar_public_projects", operator=Operator.COUNT_GTE,
            value="מספר פרויקטים",
        )
        result = _eval_count_gte(pred, make_company())
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# contains (certifications)
# ══════════════════════════════════════════════════════════════════════════════

class TestContains:
    def test_cert_present_pass(self):
        pred = make_predicate(field="certifications", operator=Operator.CONTAINS, value="ISO 9001")
        co = make_company(certifications=["ISO 9001", "ISO 45001"])
        assert _eval_contains(pred, co).passed is True

    def test_cert_missing_fail(self):
        pred = make_predicate(field="certifications", operator=Operator.CONTAINS, value="ISO 9001")
        co = make_company(certifications=["ISO 45001"])
        assert _eval_contains(pred, co).passed is False

    def test_cert_normalized_match(self):
        # "ISO9001" == "ISO 9001" after normalization
        pred = make_predicate(field="certifications", operator=Operator.CONTAINS, value="ISO9001")
        co = make_company(certifications=["ISO 9001"])
        assert _eval_contains(pred, co).passed is True

    def test_empty_certifications_fail(self):
        pred = make_predicate(field="certifications", operator=Operator.CONTAINS, value="ISO 9001")
        co = make_company(certifications=[])
        assert _eval_contains(pred, co).passed is False

    def test_unknown_field_unverifiable(self):
        pred = make_predicate(field="nonexistent_field", operator=Operator.CONTAINS, value="X")
        result = _eval_contains(pred, make_company())
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# insurance
# ══════════════════════════════════════════════════════════════════════════════

class TestInsurance:
    def _pred(self, value=10_000_000):
        return make_predicate(
            field="insurance_third_party_liability", operator=Operator.GTE, value=value,
        )

    def test_sufficient_coverage_pass(self):
        co = make_company(insurances=[InsuranceCoverage(insurance_type="third_party_liability", coverage_ils=15_000_000)])
        assert _eval_insurance(self._pred(), co).passed is True

    def test_exact_coverage_pass(self):
        co = make_company(insurances=[InsuranceCoverage(insurance_type="third_party_liability", coverage_ils=10_000_000)])
        assert _eval_insurance(self._pred(), co).passed is True

    def test_insufficient_coverage_fail(self):
        co = make_company(insurances=[InsuranceCoverage(insurance_type="third_party_liability", coverage_ils=5_000_000)])
        result = _eval_insurance(self._pred(), co)
        assert result.passed is False
        assert result.gap is not None

    def test_missing_insurance_type_fail(self):
        co = make_company(insurances=[InsuranceCoverage(insurance_type="professional", coverage_ils=20_000_000)])
        assert _eval_insurance(self._pred(), co).passed is False

    def test_no_insurance_fail(self):
        co = make_company(insurances=[])
        assert _eval_insurance(self._pred(), co).passed is False

    def test_non_numeric_value_unverifiable(self):
        pred = make_predicate(field="insurance_third_party_liability", value="5% מהחוזה")
        result = _eval_insurance(pred, make_company())
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# numeric (generic GTE/LTE/EQ)
# ══════════════════════════════════════════════════════════════════════════════

class TestNumeric:
    def test_unmodeled_field_unverifiable(self):
        pred = make_predicate(field="nonexistent_score", operator=Operator.GTE, value=50)
        result = _eval_numeric(pred, make_company())
        assert result.unverifiable is True

    def test_non_numeric_string_unverifiable(self):
        pred = make_predicate(field="annual_turnover_ils", operator=Operator.GTE, value="זהה לשם המציע")
        result = _eval_numeric(pred, make_company())
        assert result.unverifiable is True


# ══════════════════════════════════════════════════════════════════════════════
# evaluate() router — unsupported operator
# ══════════════════════════════════════════════════════════════════════════════

class TestRouter:
    def test_unsupported_operator_is_unverifiable(self):
        pred = make_predicate(field="some_field", operator=Operator.EXISTS, value=None)
        pred.field = "completely_unknown_field_xyz"
        result = evaluate(pred, make_company())
        assert result.unverifiable is True
