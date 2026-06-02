"""Unit tests for eval/criteria_eval.py — zero API calls."""
from __future__ import annotations

import pytest

from src.smarttender.eval.criteria_eval import _matches, _value_match, evaluate_against_golden
from src.smarttender.schemas.tender import Operator

from .conftest import make_predicate


# ══════════════════════════════════════════════════════════════════════════════
# _value_match
# ══════════════════════════════════════════════════════════════════════════════

class TestValueMatch:
    def test_numeric_exact(self):
        assert _value_match(5_000_000, 5_000_000) is True

    def test_numeric_string_vs_int(self):
        assert _value_match("5000000", 5_000_000) is True

    def test_numeric_with_commas(self):
        assert _value_match("5,000,000", 5_000_000) is True

    def test_numeric_mismatch(self):
        assert _value_match(3_000_000, 5_000_000) is False

    def test_dict_match(self):
        a = {"branch_code": "170", "min_group_letter": "ג"}
        b = {"branch_code": "170", "min_group_letter": "ג"}
        assert _value_match(a, b) is True

    def test_dict_mismatch(self):
        a = {"branch_code": "170", "min_group_letter": "ג"}
        b = {"branch_code": "200", "min_group_letter": "ג"}
        assert _value_match(a, b) is False

    def test_string_match_normalized(self):
        assert _value_match("ISO 9001", "ISO 9001") is True

    def test_string_mismatch(self):
        assert _value_match("ISO 9001", "ISO 45001") is False


# ══════════════════════════════════════════════════════════════════════════════
# _matches
# ══════════════════════════════════════════════════════════════════════════════

class TestMatches:
    def _gold(self, **kwargs) -> dict:
        base = {
            "field": "annual_turnover_ils",
            "operator": ">=",
            "value": 5_000_000,
            "description_he": "מחזור כספי שנתי של לפחות 5,000,000 ש\"ח בכל אחת מ-3 השנים האחרונות",
            "key_terms": ["מחזור", "5,000,000", "3 השנים"],
        }
        base.update(kwargs)
        return base

    def test_strong_match_field_op_value(self):
        pred = make_predicate(
            field="annual_turnover_ils", operator=Operator.GTE, value=5_000_000,
            description_he="מחזור כספי שנתי של לפחות 5,000,000 ש\"ח",
        )
        assert _matches(pred, self._gold()) is True

    def test_strong_mismatch_value(self):
        pred = make_predicate(
            field="annual_turnover_ils", operator=Operator.GTE, value=3_000_000,
            description_he="תיאור שונה לחלוטין",
        )
        # value differs AND description very different → no match
        assert _matches(pred, self._gold()) is False

    def test_fallback_description_similarity(self):
        pred = make_predicate(
            field="other_field", operator=Operator.GTE, value=999,
            description_he="מחזור כספי שנתי של לפחות 5,000,000 ש\"ח בכל אחת מ-3 השנים האחרונות",
        )
        # Field/value don't match, but description is identical → fallback hits
        assert _matches(pred, self._gold()) is True

    def test_fallback_key_terms(self):
        pred = make_predicate(
            field="other_field", operator=Operator.GTE, value=999,
            description_he="נדרש מחזור של 5,000,000 לפחות לכל אחת מ-3 השנים",
        )
        # "מחזור", "5,000,000", "3 השנים" all present → key_terms overlap ≥ 0.67
        assert _matches(pred, self._gold()) is True

    def test_no_match_different_everything(self):
        pred = make_predicate(
            field="certifications", operator=Operator.CONTAINS, value="ISO 9001",
            description_he="תקן ISO 9001 בתוקף",
        )
        gold = {
            "field": "annual_turnover_ils",
            "operator": ">=",
            "value": 5_000_000,
            "description_he": "מחזור כספי שנתי של לפחות 5,000,000 ש\"ח",
            "key_terms": ["מחזור", "5,000,000"],
        }
        assert _matches(pred, gold) is False


# ══════════════════════════════════════════════════════════════════════════════
# evaluate_against_golden
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateAgainstGolden:
    def _make_preds(self):
        return [
            make_predicate(field="annual_turnover_ils", operator=Operator.GTE, value=5_000_000,
                           description_he="מחזור כספי שנתי של לפחות 5,000,000 ש\"ח"),
            make_predicate(field="certifications", operator=Operator.CONTAINS, value="ISO 9001",
                           description_he="תקן ISO 9001 בתוקף"),
        ]

    def _golden(self):
        return [
            {"field": "annual_turnover_ils", "operator": ">=", "value": 5_000_000,
             "description_he": "מחזור כספי שנתי של לפחות 5,000,000 ש\"ח", "key_terms": ["מחזור"]},
            {"field": "certifications", "operator": "contains", "value": "ISO 9001",
             "description_he": "תקן ISO 9001 בתוקף", "key_terms": ["ISO 9001"]},
        ]

    def test_perfect_match(self):
        from .conftest import make_analysis
        analysis = make_analysis(self._make_preds())
        report = evaluate_against_golden(analysis, self._golden())
        assert report.tp == 2
        assert report.fp == 0
        assert report.fn == 0
        assert report.precision == pytest.approx(1.0)
        assert report.recall == pytest.approx(1.0)
        assert report.f1 == pytest.approx(1.0)

    def test_extra_pred_is_fp(self):
        from .conftest import make_analysis
        extra = make_predicate(field="insurance_professional", operator=Operator.GTE, value=1_000_000,
                               description_he="ביטוח מקצועי שאינו בgolden")
        analysis = make_analysis(self._make_preds() + [extra])
        report = evaluate_against_golden(analysis, self._golden())
        assert report.fp == 1
        assert report.fn == 0
        assert report.precision < 1.0
        assert report.recall == pytest.approx(1.0)

    def test_missing_pred_is_fn(self):
        from .conftest import make_analysis
        analysis = make_analysis(self._make_preds()[:1])  # only first pred
        report = evaluate_against_golden(analysis, self._golden())
        assert report.fn == 1
        assert report.tp == 1
        assert report.recall < 1.0
        assert report.precision == pytest.approx(1.0)

    def test_f1_zero_when_no_preds(self):
        from .conftest import make_analysis
        report = evaluate_against_golden(make_analysis([]), self._golden())
        assert report.tp == 0
        assert report.f1 == 0.0

    def test_f1_zero_when_no_golden(self):
        from .conftest import make_analysis
        report = evaluate_against_golden(make_analysis(self._make_preds()), [])
        assert report.fn == 0
        assert report.fp == 2
        assert report.recall == pytest.approx(0.0)
