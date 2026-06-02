"""Domain taxonomy for harvest filtering.

Instead of requiring users to manually enter keywords, the system maps
company domains to known related terms automatically.

Structure:
  DOMAIN_TERMS      — domain → list of Hebrew/English terms indicating that domain
  SUBJECT_DOMAIN_MAP — BudgetKey subject category → domains it implies
  NEGATIVE_PATTERNS  — terms that, if present, indicate the tender is NOT relevant
                       to HVAC/mechanical-services companies (system-wide)
"""
from __future__ import annotations

# ── Domain → terms ────────────────────────────────────────────────────────────

DOMAIN_TERMS: dict[str, list[str]] = {
    "מיזוג אויר": [
        "מיזוג", "מיזוג אויר", "מיזוג אוויר", "מזגן", "מזגנים",
        "VRF", "VRV", "מיני מרכזי", "מיזוג מרכזי",
        "משאבת חום", "משאבות חום", "heat pump",
        "fan coil", "צ'ילר", "צ'יילר", "chiller",
        "תחזוקת מזגן", "תחזוקת מיזוג", "שירות מיזוג",
        "אינוורטר", "מרכזיות קירור",
        # Additional terms from audit FN analysis
        "בקרה למיזוג", "בקרת מיזוג", "מערכת בקרה לאקלים",
        "התקנת מיזוג", "התקנת מזגן", "חיבור מזגן",
        "יחידות פנימיות", "יחידות חיצוניות",
        "גז קירור", "פריאון", "גז R410", "גז R32",
        "מעגלי קירור", "צנרת קירור",
        "שירות עבור מערכות", "HVAC",
    ],
    "קירור": [
        "קירור", "חדרי קירור", "חדר קירור", "מגדל קירור", "מגדלי קירור",
        "מקרר", "מקררים", "שיפוץ מקרר", "תחזוקת מקרר",
        "מערכות קירור", "מערכת קירור", "מדחס", "אחסון קר",
        "cold room", "refrigeration",
        # Additional terms
        "קירור תעשייתי", "מערכות קירור תעשייתי",
        "שיפוץ מקררים", "שיפוץ חדרי קור", "שדרוג מערכות קירור",
        "תא קור", "תא מקרר", "מכל קר",
        "בדיקת דליפות", "בדיקת דליפה",
    ],
    "אוורור": [
        "אוורור", "מערכת אוורור", "מערכות אוורור",
        "מאוורר", "מאווררים", "ventilation",
        "סינון אויר", "סינון אוויר", "מערכת סינון", "מערכות סינון",
        "פלטת אוורור", "תעלת אוורור",
        # Additional terms
        "תעלות אוורור", "ערוצי אוורור", "שטיפת תעלות",
        "סינון אבק", "מסנני HEPA", "סינון חלקיקים",
        "מערכת הכלרה", "הכלרה למים", "מי הכלרה",
        "שדרוג מערכות אוורור", "בדיקת אוורור",
    ],
    "פינוי עשן": [
        "פינוי עשן", "מערכת פינוי עשן", "לחץ יתר", "over pressure",
        "smoke extraction", "מאוורר פינוי",
        "סינון אב\"כ", "מערכות אב\"כ", "NBC filter",
        # Additional terms
        "תחזוקת מערכות פינוי", "בדיקת פינוי עשן", "בדיקה שנתית פינוי",
        "מפוח פינוי", "שסתומי עשן", "דמפרים",
        "ביקורות כבאות", "בדיקות כבאות",
        "מערכות בקרת עשן",
    ],
}

# ── BudgetKey subject → domains ───────────────────────────────────────────────

SUBJECT_DOMAIN_MAP: dict[str, list[str]] = {
    "שירותי תחזוקת ציוד":                    ["מיזוג אויר", "קירור", "אוורור"],
    "שירותי שיפוץ ואחזקה":                   ["מיזוג אויר", "קירור", "אוורור"],
    "שירותי בנייה ואחזקת מבנים":             ["מיזוג אויר", "קירור", "אוורור", "פינוי עשן"],
    "ציוד לתעשייה ולמחקר":                   ["קירור", "מיזוג אויר"],
    "אנרגיה":                                 ["מיזוג אויר"],
    "שירותי ניהול ותפעול":                    ["מיזוג אויר", "קירור"],
    # New mappings from audit FN analysis
    "שירות ותיקון מזגנים":                    ["מיזוג אויר"],
    "מיזוג אוויר":                            ["מיזוג אויר"],
    "שירותי בטיחות ובקרה":                   ["פינוי עשן", "מיזוג אויר"],
    "שירותי בדיקה ותחזוקה תקופתית":          ["פינוי עשן", "מיזוג אויר", "קירור", "אוורור"],
    "עבודות בנייה והתקנה":                    ["מיזוג אויר", "קירור", "אוורור", "פינוי עשן"],
    "שירותי שדרוג וחידוש":                    ["מיזוג אויר", "קירור", "אוורור", "פינוי עשן"],
}

# ── Negative patterns (system-wide) ──────────────────────────────────────────
# If the tender title contains any of these, it is likely NOT an HVAC tender
# regardless of keyword overlap (e.g. "חשמל" matching electric vehicles).

NEGATIVE_PATTERNS: list[str] = [
    # Vehicle / transport
    "רכב חשמלי",
    "כלי רכב",
    "אספקת רכב",
    "תחנות טעינה",
    # Electrical / lighting (not HVAC)
    "עמודי תאורה",
    "אספקת תאורה",
    "לוחות חשמל",
    "כבלי חשמל",
    "גנרטור",
    # Solar / renewable (not HVAC)
    "פאנלים סולאריים",
    "מערכת סולארית",
    "התקנת פאנלים",
    # Medical equipment (false-positive sources from audit)
    "אוטוקלאב",
    "מכונות שטיפה רפואי",
    "ציוד רפואי",
    "מדחסי אוויר רפואי",
    "מייבשות ספיחה",
    # Fire doors / construction (not HVAC service)
    "דלתות אש",
    "מחיצות וריצוף",
    "עבודות גמר",
    # General admin / consulting (not HVAC work)
    "תקציב מינהל",
    "יעוץ הנדסי כללי",
    "ניהול פרויקטים",
    "ייעוץ בניהול",
    # Fire suppression (not HVAC — firefighting, not smoke extraction)
    "מערכות כיבוי אש",
    "מערכות גילוי אש",
]


def terms_for_domains(domains: list[str]) -> list[str]:
    """Return all taxonomy terms for the given domain list (deduped)."""
    seen: set[str] = set()
    result: list[str] = []
    for domain in domains:
        for term in DOMAIN_TERMS.get(domain, []):
            if term not in seen:
                seen.add(term)
                result.append(term)
    return result


def domains_for_subject(subject: str) -> list[str]:
    """Return domains implied by a BudgetKey subject category string."""
    return SUBJECT_DOMAIN_MAP.get(subject.strip(), [])
