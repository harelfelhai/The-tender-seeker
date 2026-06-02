"""Deterministic RELEVANCE scoring — how interesting a qualifying tender is.

This is the second axis (the first is eligibility / תנאי סף). It is transparent
and rule-based on purpose: every factor returns a score, a weight and a Hebrew
explanation. That same (score, weight, value) triple is exactly the feature a
future ML model would learn from — so the rules now are the training scaffold
later. Weights live in DEFAULT_WEIGHTS and are meant to be tuned.
"""

from __future__ import annotations

import re
import unicodedata

from ..schemas.company_profile import CompanyProfile
from ..schemas.relevance import FactorResult, RelevanceReport
from ..schemas.tender import TenderProfile

# Hand-tuned starting weights (sum need not be 1; we normalize). Domain dominates.
DEFAULT_WEIGHTS: dict[str, float] = {
    "domain_fit": 0.35,
    "geo_fit": 0.25,
    "size_fit": 0.20,
    "client_fit": 0.10,
    "capacity_fit": 0.10,
}

# Map common locations to canonical regions so geo matching survives free text.
_REGION_HINTS: dict[str, str] = {
    "נוף הגליל": "צפון", "נצרת": "צפון", "חיפה": "צפון", "עכו": "צפון", "כרמיאל": "צפון",
    "טבריה": "צפון", "צפת": "צפון", "גליל": "צפון", "עמק": "צפון",
    "תל אביב": "מרכז", "רמת גן": "מרכז", "פתח תקווה": "מרכז", "חולון": "מרכז", "גוש דן": "מרכז",
    "ירושלים": "ירושלים",
    "באר שבע": "דרום", "אשדוד": "דרום", "אשקלון": "דרום", "אילת": "דרום", "נגב": "דרום",
    "הרצליה": "שרון", "כפר סבא": "שרון", "רעננה": "שרון", "נתניה": "שרון",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[֑-ׇ]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _neutral(name: str, label: str, weight: float, tender_val: str, why: str) -> FactorResult:
    return FactorResult(
        name=name, label_he=label, score=0.5, weight=weight,
        company_value="—", tender_value=tender_val or "לא זוהה",
        explanation_he=why, is_neutral=True,
    )


# ── factors ──────────────────────────────────────────────────────────────────

def _geo_fit(company: CompanyProfile, tp: TenderProfile, w: float) -> FactorResult:
    regions = [_norm(r) for r in company.operating_regions]
    if not regions:
        return _neutral("geo_fit", "התאמה גאוגרפית", w, tp.region or tp.location_text or "",
                        "לא הוגדרו אזורי פעילות לחברה")

    # Resolve tender region from explicit field, then from location hints.
    t_region = _norm(tp.region) if tp.region else ""
    loc = _norm(tp.location_text) if tp.location_text else ""
    if not t_region and loc:
        for hint, reg in _REGION_HINTS.items():
            if _norm(hint) in loc:
                t_region = _norm(reg)
                break
    if not t_region:
        return _neutral("geo_fit", "התאמה גאוגרפית", w, tp.location_text or "",
                        "אזור המכרז לא זוהה")

    company_str = ", ".join(company.operating_regions)
    tender_str = tp.region or tp.location_text or "—"
    matched = any(r in t_region or t_region in r for r in regions)
    if matched:
        return FactorResult(
            name="geo_fit", label_he="התאמה גאוגרפית", score=1.0, weight=w,
            company_value=company_str, tender_value=tender_str,
            explanation_he=f"המכרז באזור פעילות של החברה ({tender_str})",
        )
    return FactorResult(
        name="geo_fit", label_he="התאמה גאוגרפית", score=0.0, weight=w,
        company_value=company_str, tender_value=tender_str,
        explanation_he=f"המכרז ב{tender_str} — מחוץ לאזורי הפעילות של החברה",
    )


def _domain_fit(company: CompanyProfile, tp: TenderProfile, w: float) -> FactorResult:
    comp = [_norm(d) for d in company.domains]
    tend = [_norm(d) for d in tp.domains]
    if not comp:
        return _neutral("domain_fit", "התאמת תחום", w, ", ".join(tp.domains),
                        "לא הוגדרו תחומי התמחות לחברה")
    if not tend:
        return _neutral("domain_fit", "התאמת תחום", w, "", "תחום המכרז לא זוהה")

    company_str, tender_str = ", ".join(company.domains), ", ".join(tp.domains)
    # substring match either direction handles "מיזוג" vs "מיזוג אוויר"
    overlap = [t for t in tend if any(c in t or t in c for c in comp)]
    if len(overlap) == len(tend):
        score, why = 1.0, f"התחום תואם במלואו ({tender_str})"
    elif overlap:
        score, why = 0.6, f"התאמה חלקית בתחום ({', '.join(overlap)})"
    else:
        score, why = 0.0, f"תחום המכרז ({tender_str}) אינו בהתמחות החברה"
    return FactorResult(
        name="domain_fit", label_he="התאמת תחום", score=score, weight=w,
        company_value=company_str, tender_value=tender_str, explanation_he=why,
    )


def _size_fit(company: CompanyProfile, tp: TenderProfile, w: float) -> FactorResult:
    value = tp.estimated_value_ils
    lo, hi = company.min_project_value_ils, company.max_project_value_ils
    company_str = (
        f"₪{lo:,.0f}–₪{hi:,.0f}" if lo is not None and hi is not None
        else "טווח לא הוגדר"
    )
    if value is None:
        return _neutral("size_fit", "התאמת היקף", w, "", "היקף המכרז לא זוהה")
    if lo is None and hi is None:
        return _neutral("size_fit", "התאמת היקף", w, f"₪{value:,.0f}",
                        "טווח גודל פרויקט לא הוגדר לחברה")

    tender_str = f"₪{value:,.0f}"
    if lo is not None and value < lo:
        ratio = value / lo
        return FactorResult(
            name="size_fit", label_he="התאמת היקף", score=round(max(0.0, ratio), 2),
            weight=w, company_value=company_str, tender_value=tender_str,
            explanation_he=f"המכרז קטן מהמינימום הנוח לחברה ({tender_str} < ₪{lo:,.0f})",
        )
    if hi is not None and value > hi:
        ratio = hi / value
        return FactorResult(
            name="size_fit", label_he="התאמת היקף", score=round(max(0.0, ratio), 2),
            weight=w, company_value=company_str, tender_value=tender_str,
            explanation_he=f"המכרז גדול מהמקסימום הנוח לחברה ({tender_str} > ₪{hi:,.0f})",
        )
    return FactorResult(
        name="size_fit", label_he="התאמת היקף", score=1.0, weight=w,
        company_value=company_str, tender_value=tender_str,
        explanation_he=f"היקף המכרז בטווח הנוח לחברה ({tender_str})",
    )


def _client_fit(company: CompanyProfile, tp: TenderProfile, w: float) -> FactorResult:
    prefs = [_norm(c) for c in company.preferred_client_types]
    if not prefs:
        return _neutral("client_fit", "התאמת מזמין", w, tp.publisher_type or "",
                        "לא הוגדרו סוגי מזמין מועדפים")
    if not tp.publisher_type:
        return _neutral("client_fit", "התאמת מזמין", w, "", "סוג המזמין לא זוהה")

    company_str = ", ".join(company.preferred_client_types)
    pt = _norm(tp.publisher_type)
    if any(p in pt or pt in p for p in prefs):
        return FactorResult(
            name="client_fit", label_he="התאמת מזמין", score=1.0, weight=w,
            company_value=company_str, tender_value=tp.publisher_type,
            explanation_he=f"המזמין ({tp.publisher_type}) מסוג מועדף",
        )
    return FactorResult(
        name="client_fit", label_he="התאמת מזמין", score=0.3, weight=w,
        company_value=company_str, tender_value=tp.publisher_type,
        explanation_he=f"המזמין ({tp.publisher_type}) אינו מסוג מועדף (אך לא פוסל)",
    )


def _capacity_fit(company: CompanyProfile, tp: TenderProfile, w: float) -> FactorResult:
    cap = company.available_capacity_pct
    if cap is None:
        return _neutral("capacity_fit", "קיבולת פנויה", w, "—",
                        "קיבולת פנויה לא הוגדרה")
    score = round(cap / 100.0, 2)
    return FactorResult(
        name="capacity_fit", label_he="קיבולת פנויה", score=score, weight=w,
        company_value=f"{cap:.0f}% פנוי", tender_value="—",
        explanation_he=(
            f"לחברה {cap:.0f}% קיבולת פנויה לעבודה חדשה"
            if cap >= 50 else f"קיבולת פנויה נמוכה ({cap:.0f}%) — עומס קיים"
        ),
    )


# ── engine ───────────────────────────────────────────────────────────────────

def score_relevance(
    company: CompanyProfile,
    tp: TenderProfile,
    weights: dict[str, float] | None = None,
) -> RelevanceReport:
    w = weights or DEFAULT_WEIGHTS
    factors = [
        _domain_fit(company, tp, w["domain_fit"]),
        _geo_fit(company, tp, w["geo_fit"]),
        _size_fit(company, tp, w["size_fit"]),
        _client_fit(company, tp, w["client_fit"]),
        _capacity_fit(company, tp, w["capacity_fit"]),
    ]

    total_w = sum(f.weight for f in factors)
    weighted = sum(f.score * f.weight for f in factors)
    score = round((weighted / total_w) * 100, 1) if total_w else 0.0

    strong = [f.label_he for f in factors if f.score >= 0.8 and not f.is_neutral]
    weak = [f.label_he for f in factors if f.score <= 0.3 and not f.is_neutral]
    neutral_n = sum(1 for f in factors if f.is_neutral)
    parts = [f"ציון רלוונטיות {score}/100."]
    if strong:
        parts.append(f"חזק ב: {', '.join(strong)}.")
    if weak:
        parts.append(f"חלש ב: {', '.join(weak)}.")
    if neutral_n:
        parts.append(f"{neutral_n} גורמים ניטרליים (חסר מידע).")
    return RelevanceReport(relevance_score=score, factors=factors, summary_he=" ".join(parts))
