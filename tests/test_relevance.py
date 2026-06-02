"""Unit tests for match_engine/relevance.py — zero API calls."""
from __future__ import annotations

import pytest

from src.smarttender.match_engine.relevance import (
    DEFAULT_WEIGHTS,
    _domain_fit,
    _geo_fit,
    _size_fit,
    _client_fit,
    _capacity_fit,
    score_relevance,
)
from src.smarttender.schemas.tender import TenderProfile

from .conftest import make_company

W = DEFAULT_WEIGHTS


def _tp(**kwargs) -> TenderProfile:
    return TenderProfile(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# geo_fit
# ══════════════════════════════════════════════════════════════════════════════

class TestGeoFit:
    def test_exact_region_match(self):
        co = make_company(regions=["מרכז"])
        r = _geo_fit(co, _tp(region="מרכז"), W["geo_fit"])
        assert r.score == 1.0
        assert r.is_neutral is False

    def test_region_mismatch(self):
        co = make_company(regions=["מרכז"])
        r = _geo_fit(co, _tp(region="דרום"), W["geo_fit"])
        assert r.score == 0.0

    def test_location_hint_resolves(self):
        co = make_company(regions=["דרום"])
        r = _geo_fit(co, _tp(location_text="באר שבע"), W["geo_fit"])
        assert r.score == 1.0

    def test_no_company_regions_neutral(self):
        co = make_company(regions=[])
        r = _geo_fit(co, _tp(region="מרכז"), W["geo_fit"])
        assert r.is_neutral is True
        assert r.score == pytest.approx(0.5)

    def test_no_tender_region_neutral(self):
        co = make_company(regions=["מרכז"])
        r = _geo_fit(co, _tp(), W["geo_fit"])
        assert r.is_neutral is True


# ══════════════════════════════════════════════════════════════════════════════
# domain_fit
# ══════════════════════════════════════════════════════════════════════════════

class TestDomainFit:
    def test_full_match(self):
        co = make_company(domains=["מיזוג אוויר"])
        r = _domain_fit(co, _tp(domains=["מיזוג אוויר"]), W["domain_fit"])
        assert r.score == 1.0

    def test_substring_match(self):
        co = make_company(domains=["מיזוג"])
        r = _domain_fit(co, _tp(domains=["מיזוג אוויר"]), W["domain_fit"])
        assert r.score == 1.0

    def test_partial_match(self):
        co = make_company(domains=["מיזוג אוויר"])
        r = _domain_fit(co, _tp(domains=["מיזוג אוויר", "חשמל"]), W["domain_fit"])
        assert r.score == pytest.approx(0.6)

    def test_no_match(self):
        co = make_company(domains=["אינסטלציה"])
        r = _domain_fit(co, _tp(domains=["בנייה"]), W["domain_fit"])
        assert r.score == 0.0

    def test_no_company_domains_neutral(self):
        co = make_company(domains=[])
        r = _domain_fit(co, _tp(domains=["מיזוג אוויר"]), W["domain_fit"])
        assert r.is_neutral is True

    def test_no_tender_domains_neutral(self):
        co = make_company(domains=["מיזוג אוויר"])
        r = _domain_fit(co, _tp(), W["domain_fit"])
        assert r.is_neutral is True


# ══════════════════════════════════════════════════════════════════════════════
# size_fit
# ══════════════════════════════════════════════════════════════════════════════

class TestSizeFit:
    def test_in_range(self):
        co = make_company(min_project=500_000, max_project=5_000_000)
        r = _size_fit(co, _tp(estimated_value_ils=2_000_000), W["size_fit"])
        assert r.score == 1.0

    def test_below_min_partial(self):
        co = make_company(min_project=1_000_000, max_project=5_000_000)
        r = _size_fit(co, _tp(estimated_value_ils=500_000), W["size_fit"])
        assert 0.0 < r.score < 1.0

    def test_above_max_partial(self):
        co = make_company(min_project=500_000, max_project=2_000_000)
        r = _size_fit(co, _tp(estimated_value_ils=10_000_000), W["size_fit"])
        assert 0.0 < r.score < 1.0

    def test_no_tender_value_neutral(self):
        co = make_company(min_project=500_000, max_project=5_000_000)
        r = _size_fit(co, _tp(), W["size_fit"])
        assert r.is_neutral is True

    def test_no_company_range_neutral(self):
        co = make_company(min_project=None, max_project=None)
        r = _size_fit(co, _tp(estimated_value_ils=2_000_000), W["size_fit"])
        assert r.is_neutral is True


# ══════════════════════════════════════════════════════════════════════════════
# client_fit
# ══════════════════════════════════════════════════════════════════════════════

class TestClientFit:
    def test_preferred_type_match(self):
        co = make_company(preferred_clients=["municipal"])
        r = _client_fit(co, _tp(publisher_type="municipal"), W["client_fit"])
        assert r.score == 1.0

    def test_non_preferred_partial(self):
        co = make_company(preferred_clients=["municipal"])
        r = _client_fit(co, _tp(publisher_type="private"), W["client_fit"])
        assert r.score == pytest.approx(0.3)

    def test_no_prefs_neutral(self):
        co = make_company(preferred_clients=[])
        r = _client_fit(co, _tp(publisher_type="municipal"), W["client_fit"])
        assert r.is_neutral is True

    def test_no_publisher_neutral(self):
        co = make_company(preferred_clients=["municipal"])
        r = _client_fit(co, _tp(), W["client_fit"])
        assert r.is_neutral is True


# ══════════════════════════════════════════════════════════════════════════════
# capacity_fit
# ══════════════════════════════════════════════════════════════════════════════

class TestCapacityFit:
    def test_full_capacity(self):
        co = make_company(capacity=100.0)
        r = _capacity_fit(co, _tp(), W["capacity_fit"])
        assert r.score == 1.0

    def test_half_capacity(self):
        co = make_company(capacity=50.0)
        r = _capacity_fit(co, _tp(), W["capacity_fit"])
        assert r.score == pytest.approx(0.5)

    def test_zero_capacity(self):
        co = make_company(capacity=0.0)
        r = _capacity_fit(co, _tp(), W["capacity_fit"])
        assert r.score == 0.0

    def test_no_capacity_neutral(self):
        co = make_company(capacity=None)
        r = _capacity_fit(co, _tp(), W["capacity_fit"])
        assert r.is_neutral is True


# ══════════════════════════════════════════════════════════════════════════════
# score_relevance (integration)
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreRelevance:
    def test_perfect_match_near_100(self):
        co = make_company(
            regions=["מרכז"], domains=["מיזוג אוויר"],
            min_project=1_000_000, max_project=10_000_000,
            preferred_clients=["municipal"], capacity=100.0,
        )
        tp = _tp(region="מרכז", domains=["מיזוג אוויר"],
                 estimated_value_ils=5_000_000, publisher_type="municipal")
        report = score_relevance(co, tp)
        assert report.relevance_score >= 90.0

    def test_complete_mismatch_low_score(self):
        co = make_company(
            regions=["דרום"], domains=["אינסטלציה"],
            min_project=100_000, max_project=500_000,
            preferred_clients=["private"], capacity=10.0,
        )
        tp = _tp(region="צפון", domains=["בנייה"],
                 estimated_value_ils=50_000_000, publisher_type="government")
        report = score_relevance(co, tp)
        assert report.relevance_score < 40.0

    def test_all_neutral_score_around_50(self):
        co = make_company(regions=[], domains=[], preferred_clients=[], capacity=None,
                          min_project=None, max_project=None)
        tp = _tp()  # no info on tender side either
        report = score_relevance(co, tp)
        assert report.relevance_score == pytest.approx(50.0)

    def test_report_has_five_factors(self):
        report = score_relevance(make_company(), _tp())
        assert len(report.factors) == 5
