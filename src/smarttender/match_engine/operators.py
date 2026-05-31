"""Deterministic, pure-Python evaluation of individual tender criteria predicates.

Each public function returns an EvalResult — never raises, never calls an LLM.
The routing function `evaluate()` is the single entry point used by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..schemas.company_profile import CompanyProfile
from ..schemas.tender import Operator, TenderCriteriaPredicate


# Hebrew group ordering: א (weakest) → ה (strongest)
_GROUP_ORDER: dict[str, int] = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5}

# client_type values considered "public" for experience matching
_PUBLIC_CLIENT_TYPES = {"public", "municipal", "government"}

# Maps the many ways a client type can be expressed (Hebrew from the LLM,
# English from the profile) to a canonical category. The Criteria Agent emits
# whatever wording appears in the tender ("רשות מקומית"), so normalisation here
# is what lets deterministic matching survive real, multilingual extraction.
_CLIENT_TYPE_ALIASES: dict[str, str] = {
    # public (umbrella)
    "public": "public", "ציבורי": "public", "גוף ציבורי": "public", "גופים ציבוריים": "public",
    # municipal
    "municipal": "municipal", "רשות מקומית": "municipal", "רשויות מקומיות": "municipal",
    "עירייה": "municipal", "מועצה מקומית": "municipal", "מועצה אזורית": "municipal",
    # government
    "government": "government", "ממשלתי": "government", "גוף ממשלתי": "government",
    "גופים ממשלתיים": "government", "משרד ממשלתי": "government", "משרדי ממשלה": "government",
    # private
    "private": "private", "פרטי": "private", "גוף פרטי": "private",
}


def _canon_client_type(value: str) -> str:
    """Normalise a raw client-type label to a canonical category."""
    return _CLIENT_TYPE_ALIASES.get(value.strip(), value.strip().lower())


@dataclass
class EvalResult:
    passed: bool
    reason_he: str
    company_value_str: str
    required_value_str: str
    gap: Optional[str] = None
    # True when the engine cannot deterministically decide (documentary/procedural
    # requirement, unmodeled field, or non-comparable value). Such criteria are
    # surfaced for MANUAL REVIEW and do NOT disqualify the company.
    unverifiable: bool = False


# ── helpers ─────────────────────────────────────────────────────────────────

def _fmt_ils(amount: float) -> str:
    return f"₪{amount:,.0f}"


def _current_year() -> int:
    return date.today().year


def _to_number(value) -> Optional[float]:
    """Best-effort parse of an LLM-provided value to a number.

    Real extractions return things like '5% מהוצאות הפיתוח' or '50,000 ש"ח' for
    fields we expected to be numeric. We salvage an embedded number when one is
    clearly present, else return None so the caller can mark it unverifiable.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.replace(",", "")
    # Reject values carrying a unit/percent that changes meaning (e.g. "5%").
    if "%" in cleaned:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


def _unverifiable(desc: str, required: str) -> "EvalResult":
    return EvalResult(
        False,
        f"דרישה שאינה ניתנת לאימות אוטומטי — בדיקה ידנית: {desc[:60]}",
        "—",
        required,
        unverifiable=True,
    )


# ── per-operator evaluators ──────────────────────────────────────────────────

def _eval_annual_turnover(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Check annual_revenues with lookback and aggregation logic."""
    required = _to_number(predicate.value)
    if required is None:
        return _unverifiable(predicate.description_he, str(predicate.value))
    lookback = predicate.lookback_years or 1
    aggregation = predicate.aggregation or "each_year"
    base_year = _current_year()

    # Most recent N complete fiscal years (current year excluded — not filed yet)
    years = [base_year - i for i in range(1, lookback + 1)]
    revenues = {yr: profile.annual_revenues.get(yr, 0.0) for yr in years}

    req_str = _format_ils_req(required, lookback, aggregation)
    company_str = ", ".join(f"{yr}: {_fmt_ils(v)}" for yr, v in sorted(revenues.items()))

    if aggregation == "each_year":
        failing = {yr: v for yr, v in revenues.items() if v < required}
        if failing:
            details = "; ".join(f"{yr}: {_fmt_ils(v)}" for yr, v in sorted(failing.items()))
            worst_gap = required - min(failing.values())
            return EvalResult(
                False,
                f"מחזור כספי נמוך מהנדרש ב-{len(failing)} שנים ({details})",
                company_str,
                req_str,
                f"חסר לפחות {_fmt_ils(worst_gap)} לשנה החלשה ביותר",
            )
        min_rev = min(revenues.values())
        return EvalResult(
            True,
            f"מחזור כספי עמד בדרישה בכל {lookback} השנים (מינימום {_fmt_ils(min_rev)})",
            company_str,
            req_str,
        )

    if aggregation == "any_year":
        best = max(revenues.values(), default=0.0)
        passed = best >= required
        if passed:
            return EvalResult(True, f"מחזור שנתי הגיע ל-{_fmt_ils(best)}", company_str, req_str)
        return EvalResult(
            False,
            f"מחזור כספי לא הגיע לנדרש אף בשנה אחת (גבוה ביותר: {_fmt_ils(best)})",
            company_str,
            req_str,
            _fmt_ils(required - best),
        )

    if aggregation == "latest":
        latest_yr = max(revenues) if revenues else base_year - 1
        latest_v = revenues.get(latest_yr, 0.0)
        passed = latest_v >= required
        gap = None if passed else _fmt_ils(required - latest_v)
        verb = "עמד בדרישה" if passed else "נמוך מהנדרש"
        return EvalResult(
            passed,
            f"מחזור {latest_yr}: {_fmt_ils(latest_v)} — {verb}",
            company_str,
            req_str,
            gap,
        )

    # cumulative
    cumulative = sum(revenues.values())
    passed = cumulative >= required
    gap = None if passed else _fmt_ils(required - cumulative)
    return EvalResult(
        passed,
        f"מחזור מצטבר {lookback} שנים: {_fmt_ils(cumulative)}",
        company_str,
        req_str,
        gap,
    )


def _format_ils_req(required: float, lookback: int, aggregation: str) -> str:
    agg_map = {
        "each_year": f"לפחות {_fmt_ils(required)} בכל שנה ({lookback} שנים)",
        "any_year": f"לפחות {_fmt_ils(required)} בשנה אחת מתוך {lookback}",
        "cumulative": f"מצטבר {_fmt_ils(required)} על {lookback} שנים",
        "latest": f"לפחות {_fmt_ils(required)} בשנה האחרונה",
    }
    return agg_map.get(aggregation, _fmt_ils(required))


def _eval_classification(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Validate contractor classification (סיווג קבלני) against the requirement."""
    req = predicate.value
    if not isinstance(req, dict):
        return EvalResult(
            False, "מבנה דרישת הסיווג אינו תקני — בדיקה ידנית", "–", str(req),
            unverifiable=True,
        )

    req_branch = str(req.get("branch_code", ""))
    req_group = req.get("min_group_letter")
    req_tier = req.get("min_financial_tier")

    parts = [f"ענף {req_branch}"]
    if req_group:
        parts.append(f"קבוצה {req_group} ומעלה")
    if req_tier:
        parts.append(f"היקף כספי {req_tier}+")
    required_str = " · ".join(parts)

    matching_branch = [c for c in profile.contractor_classifications if c.branch_code == req_branch]

    if not matching_branch:
        return EvalResult(
            False,
            f"חסר סיווג קבלני בענף {req_branch}",
            "אין סיווג מתאים",
            required_str,
            f"נדרש רישום לענף {req_branch}",
        )

    for cls in matching_branch:
        group_ok = (
            _GROUP_ORDER.get(cls.group_letter, 0) >= _GROUP_ORDER.get(req_group, 0)
            if req_group
            else True
        )
        tier_ok = cls.financial_tier >= req_tier if req_tier is not None else True

        if group_ok and tier_ok:
            company_str = f"ענף {cls.branch_code} קבוצה {cls.group_letter} היקף {cls.financial_tier}"
            return EvalResult(True, f"סיווג קבלני תקין: {company_str}", company_str, required_str)

    best = max(matching_branch, key=lambda c: (_GROUP_ORDER.get(c.group_letter, 0), c.financial_tier))
    company_str = f"ענף {best.branch_code} קבוצה {best.group_letter} היקף {best.financial_tier}"
    return EvalResult(
        False,
        f"סיווג קבלני בענף {req_branch} קיים אך נמוך מהנדרש: {company_str}",
        company_str,
        required_str,
        "נדרש שדרוג קבוצה / היקף כספי",
    )


def _eval_count_gte(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Count filtered items in a list field and compare against a minimum."""
    _rc = _to_number(predicate.value)
    if _rc is None:
        return _unverifiable(predicate.description_he, str(predicate.value))
    required_count = int(_rc)
    qualifier = predicate.qualifier or {}
    lookback = predicate.lookback_years
    base_year = _current_year()

    if predicate.field != "similar_public_projects":
        return EvalResult(
            False, f"מניין '{predicate.field}' אינו נתמך — בדיקה ידנית", "–",
            str(required_count), unverifiable=True,
        )

    projects = list(profile.similar_public_projects)

    # client_type may arrive as a string or a list, in Hebrew or English.
    client_filter = qualifier.get("client_type")
    requested_public = False
    if client_filter:
        raw = client_filter if isinstance(client_filter, list) else [client_filter]
        requested = {_canon_client_type(str(v)) for v in raw}
        # If any requested type is public-sector, accept any public-sector project
        # (the "ציבורי" umbrella covers municipal + government).
        requested_public = bool(requested & _PUBLIC_CLIENT_TYPES)
        allowed = _PUBLIC_CLIENT_TYPES if requested_public else requested
        projects = [p for p in projects if _canon_client_type(p.client_type) in allowed]

    if lookback:
        cutoff = base_year - lookback
        projects = [p for p in projects if p.year >= cutoff]

    min_value = qualifier.get("min_project_value_ils")
    if min_value:
        projects = [p for p in projects if (p.value_ils or 0) >= float(min_value)]

    count = len(projects)
    passed = count >= required_count

    labels = []
    if requested_public:
        labels.append("לגופים ציבוריים")
    if lookback:
        labels.append(f"ב-{lookback} השנים האחרונות")
    label_str = " ".join(labels)

    if passed:
        reason = f"נמצאו {count} פרויקטים דומים {label_str}".strip()
    else:
        reason = f"נמצאו {count} מתוך {required_count} פרויקטים דומים {label_str} — חסרים {required_count - count}".strip()

    gap = None if passed else f"חסרים {required_count - count} פרויקטים"
    return EvalResult(passed, reason, str(count), str(required_count), gap)


def _eval_contains(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Check that a required value exists in a list field (e.g. certifications)."""
    required_val = str(predicate.value)

    if predicate.field == "certifications":
        # Normalise: remove spaces and hyphens, uppercase — "ISO 9001" == "ISO9001"
        def norm(s: str) -> str:
            return s.upper().replace(" ", "").replace("-", "")

        norm_req = norm(required_val)
        passed = any(norm(c) == norm_req for c in profile.certifications)
        company_str = ", ".join(profile.certifications) if profile.certifications else "אין תעודות"
        if passed:
            return EvalResult(True, f"תעודת {required_val} קיימת", company_str, required_val)
        return EvalResult(
            False,
            f"חסרה תעודת {required_val}",
            company_str,
            required_val,
            f"נדרש קבלת אישור {required_val}",
        )

    if not hasattr(profile, predicate.field):
        return EvalResult(
            False, f"שדה '{predicate.field}' אינו מנוהל בפרופיל — בדיקה ידנית", "–",
            required_val, unverifiable=True,
        )
    field_val = getattr(profile, predicate.field)
    if field_val is None:
        return EvalResult(False, f"שדה {predicate.field} לא קיים בפרופיל", "–", required_val)
    items = [str(v) for v in field_val] if isinstance(field_val, list) else [str(field_val)]
    passed = required_val in items
    return EvalResult(
        passed,
        f"{'נמצא' if passed else 'חסר'}: {required_val}",
        str(field_val),
        required_val,
    )


def _eval_insurance(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Evaluate insurance coverage. Field format: insurance_{type}."""
    required = _to_number(predicate.value)
    if required is None:
        return _unverifiable(predicate.description_he, str(predicate.value))
    ins_type = predicate.field[len("insurance_"):]  # strip "insurance_" prefix

    coverage = next(
        (ins.coverage_ils for ins in profile.insurances if ins.insurance_type == ins_type), None
    )

    type_label_map = {
        "third_party_liability": "אחריות כלפי צד שלישי",
        "professional": "אחריות מקצועית",
        "employer": "חבות מעסיקים",
    }
    type_he = type_label_map.get(ins_type, ins_type)
    required_str = _fmt_ils(required)

    if coverage is None:
        return EvalResult(
            False,
            f"חסר ביטוח {type_he}",
            "לא קיים",
            required_str,
            f"נדרשת פוליסת {type_he} על סך {required_str}",
        )

    passed = coverage >= required
    gap = None if passed else _fmt_ils(required - coverage)
    verb = "עומד בדרישה" if passed else "נמוך מהנדרש"
    return EvalResult(
        passed,
        f"ביטוח {type_he}: {_fmt_ils(coverage)} — {verb} ({required_str} נדרש)",
        _fmt_ils(coverage),
        required_str,
        gap,
    )


def _eval_numeric(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    """Direct numeric comparison on a scalar profile attribute."""
    # Non-numeric value → this isn't really a numeric threshold (often a
    # documentary/identity requirement). Flag for manual review, don't crash.
    try:
        required = float(predicate.value)
    except (TypeError, ValueError):
        return EvalResult(
            False,
            f"דרישה שאינה ניתנת לאימות אוטומטי — בדיקה ידנית: {predicate.description_he[:60]}",
            "—",
            str(predicate.value),
            unverifiable=True,
        )

    fmt = _fmt_ils if required >= 1_000 else str

    # Field the profile schema does not model at all → manual review (not a fail).
    if not hasattr(profile, predicate.field):
        return EvalResult(
            False,
            f"שדה '{predicate.field}' אינו מנוהל בפרופיל החברה — בדיקה ידנית",
            "—",
            fmt(required),
            unverifiable=True,
        )

    field_val = getattr(profile, predicate.field)
    if field_val is None:
        return EvalResult(
            False,
            f"שדה {predicate.field} לא הוגדר בפרופיל",
            "לא מוגדר",
            fmt(required),
        )

    company = float(field_val)
    op = predicate.operator
    if op == Operator.GTE:
        passed = company >= required
    elif op == Operator.LTE:
        passed = company <= required
    else:  # EQ
        passed = company == required

    gap = _fmt_ils(required - company) if not passed and op == Operator.GTE and required >= 1_000 else None
    verb = "עמד בדרישה" if passed else "לא עמד בדרישה"
    op_label = {">=": "לפחות", "<=": "לכל היותר", "==": "בדיוק"}.get(op.value, op.value)
    return EvalResult(
        passed,
        f"{predicate.description_he}: {fmt(company)} ({verb}; נדרש {op_label} {fmt(required)})",
        fmt(company),
        fmt(required),
        gap,
    )


def _eval_exists(
    predicate: TenderCriteriaPredicate, profile: CompanyProfile
) -> EvalResult:
    # Documentary "must submit X" requirements usually map to fields the profile
    # doesn't model → manual review rather than a fabricated pass/fail.
    if not hasattr(profile, predicate.field):
        return EvalResult(
            False,
            f"דרישה תיעודית/נוהלית — בדיקה ידנית: {predicate.description_he[:60]}",
            "—",
            "נדרש",
            unverifiable=True,
        )
    val = getattr(profile, predicate.field)
    passed = val is not None and val not in ([], {}, "")
    return EvalResult(
        passed,
        f"{'קיים' if passed else 'חסר'}: {predicate.description_he}",
        str(val) if passed else "לא מוגדר",
        "נדרש",
    )


# ── public router ────────────────────────────────────────────────────────────

def evaluate(predicate: TenderCriteriaPredicate, profile: CompanyProfile) -> EvalResult:
    """Route a predicate to the correct evaluator and return an EvalResult."""
    field = predicate.field
    op = predicate.operator

    if field == "annual_turnover_ils":
        return _eval_annual_turnover(predicate, profile)

    if field == "contractor_classification" or op == Operator.SATISFIES_CLASSIFICATION:
        return _eval_classification(predicate, profile)

    if op == Operator.COUNT_GTE:
        return _eval_count_gte(predicate, profile)

    if op == Operator.CONTAINS:
        return _eval_contains(predicate, profile)

    if op == Operator.EXISTS:
        return _eval_exists(predicate, profile)

    if field.startswith("insurance_"):
        return _eval_insurance(predicate, profile)

    if op in (Operator.GTE, Operator.LTE, Operator.EQ):
        return _eval_numeric(predicate, profile)

    return EvalResult(
        False, f"אופרטור לא נתמך ({op.value}) — בדיקה ידנית", "–", str(predicate.value),
        unverifiable=True,
    )
