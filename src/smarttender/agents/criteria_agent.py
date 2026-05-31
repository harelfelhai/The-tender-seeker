"""Criteria Agent — extracts תנאי סף from a tender document into a validated
TenderAnalysisOutput.

Despite the name "agent", this is a *deterministic structured-extraction step*,
not an autonomous runtime: one schema-enforced LLM call (via instructor) with a
mock fallback.  It is intentionally framework-free.  See ARCHITECTURE.md §1.2.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from ..schemas.tender import (
    CriteriaCategory,
    Operator,
    TenderAnalysisOutput,
    TenderCriteriaPredicate,
)

# A no-op status sink; callers (e.g. the CLI) can pass their own printer.
StatusFn = Callable[[str], None]


def _noop(_: str) -> None:  # pragma: no cover - trivial
    pass


_EXTRACTION_SYSTEM = """\
אתה מומחה לניתוח מכרזים ממשלתיים ועירוניים בישראל.
תפקידך לחלץ את כל תנאי הסף (ותנאים נוספים) ממסמך המכרז ולמלא את הסכמה המובנית במדויק.

כללים:
• חלץ כל תנאי בנפרד — פיננסי, סיווג קבלני, ניסיון, תעודות, ביטוח.
• עבור מחזור כספי — קבע lookback_years ו-aggregation (each_year / any_year / cumulative / latest).
• עבור סיווג קבלני — השתמש באופרטור satisfies_classification עם מילון {branch_code, min_group_letter, min_financial_tier}.
• עבור ביטוח — השתמש בשם שדה insurance_{type} (למשל insurance_third_party_liability).
• עבור מניין פרויקטים — השתמש באופרטור count>= עם qualifier {client_type, lookback_years}.
• ציין מספר עמוד וציטוט מדויק לכל תנאי.
• mandatory=true עבור תנאי סף שלילי (פסילה), false עבור יתרון בלבד.
"""

_EXTRACTION_USER = """\
חלץ את תנאי הסף מהמכרז הבא ומלא את הסכמה המובנית:

{text}
"""


class CriteriaAgent:
    """Wraps PDF→text extraction and the schema-enforced LLM call."""

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-8",
        api_key: Optional[str] = None,
        max_tokens: int = 8_192,
        max_chars: int = 80_000,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.max_chars = max_chars

    # ── public entry point ──────────────────────────────────────────────────
    def extract(
        self,
        *,
        pdf_path: Optional[str] = None,
        text: Optional[str] = None,
        fallback_to_mock: bool = True,
        on_status: StatusFn = _noop,
    ) -> TenderAnalysisOutput:
        """Extract criteria from a PDF path or raw text.

        Falls back to a representative mock when dependencies/keys are missing
        (so the PoC always runs).  Set fallback_to_mock=False to surface errors.
        """
        if text is None and pdf_path is None:
            if not fallback_to_mock:
                raise ValueError("Provide either pdf_path or text")
            on_status("אין מקור — משתמש בנתוני mock")
            return self.mock()

        try:
            if text is None:
                text = self._pdf_to_text(pdf_path, on_status=on_status)
            return self._call_llm(text, on_status=on_status)
        except Exception as exc:  # noqa: BLE001 - PoC: degrade gracefully
            if not fallback_to_mock:
                raise
            on_status(f"חילוץ אמיתי נכשל ({exc}); נופל חזרה ל-mock.")
            return self.mock()

    # ── steps ───────────────────────────────────────────────────────────────
    def _pdf_to_text(self, pdf_path: str, *, on_status: StatusFn) -> str:
        import fitz  # PyMuPDF

        on_status(f"קורא PDF: {pdf_path}")
        doc = fitz.open(pdf_path)
        pages: list[str] = []
        for i, page in enumerate(doc):
            page_text = page.get_text("text").strip()
            if page_text:
                pages.append(f"[עמוד {i + 1}]\n{page_text}")
        doc.close()

        full_text = "\n\n".join(pages)
        if not full_text.strip():
            raise ValueError("לא חולץ טקסט (PDF סרוק?) — OCR לא מיושם ב-PoC")
        on_status(f"חולצו {len(full_text):,} תווים מ-{len(pages)} עמודים")
        return full_text

    def _call_llm(self, text: str, *, on_status: StatusFn) -> TenderAnalysisOutput:
        import os

        import anthropic
        import instructor

        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY לא מוגדר")

        on_status("שולח ל-Claude עם אכיפת schema (instructor)...")
        client = instructor.from_anthropic(anthropic.Anthropic(api_key=api_key))
        return client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=_EXTRACTION_SYSTEM,
            messages=[
                {"role": "user", "content": _EXTRACTION_USER.format(text=text[: self.max_chars])}
            ],
            response_model=TenderAnalysisOutput,
        )

    # ── mock (zero-dependency demo data) ────────────────────────────────────
    @staticmethod
    def mock() -> TenderAnalysisOutput:
        """Representative output for a typical Israeli HVAC tender."""
        y = date.today().year
        return TenderAnalysisOutput(
            tender_id="MUN-TLV-2026-0142",
            title_he="מכרז לאספקת, התקנת ותחזוקת מערכות מיזוג אוויר — עיריית תל אביב-יפו",
            publisher_he="עיריית תל אביב-יפו",
            submission_deadline=f"{y}-07-15T12:00:00+03:00",
            estimated_budget_ils=6_000_000,
            raw_summary_he=(
                "מכרז לאספקה, התקנה ותחזוקה של מערכות מיזוג אוויר במבני העירייה לתקופה של שלוש שנים "
                "עם אופציה להארכה בשנתיים נוספות. נדרש ניסיון מוכח בפרויקטים דומים לגופים ציבוריים "
                "וסיווג קבלני מתאים."
            ),
            criteria=[
                TenderCriteriaPredicate(
                    id="C1",
                    category=CriteriaCategory.FINANCIAL,
                    description_he="מחזור כספי שנתי של לפחות 5,000,000 ₪ בכל אחת מ-3 השנים האחרונות",
                    field="annual_turnover_ils",
                    operator=Operator.GTE,
                    value=5_000_000,
                    mandatory=True,
                    lookback_years=3,
                    aggregation="each_year",
                    page=12,
                    quote_he=(
                        "על המציע להוכיח מחזור כספי שנתי של לפחות 5,000,000 ₪ "
                        "בכל אחת משלוש השנים הקלנדריות שקדמו לפרסום המכרז"
                    ),
                    confidence=0.95,
                ),
                TenderCriteriaPredicate(
                    id="C2",
                    category=CriteriaCategory.CLASSIFICATION,
                    description_he="סיווג קבלני ענף 170 (מיזוג אוויר), קבוצה ג׳ והיקף כספי 3 לפחות",
                    field="contractor_classification",
                    operator=Operator.SATISFIES_CLASSIFICATION,
                    value={"branch_code": "170", "min_group_letter": "ג", "min_financial_tier": 3},
                    mandatory=True,
                    page=11,
                    quote_he=(
                        "על המציע להחזיק בסיווג קבלנים בענף 170 (מיזוג אוויר) "
                        "קבוצה ג׳ היקף כספי 3 לפחות, בתוקף ביום ההגשה"
                    ),
                    confidence=0.97,
                ),
                TenderCriteriaPredicate(
                    id="C3",
                    category=CriteriaCategory.EXPERIENCE,
                    description_he="ביצוע לפחות 3 פרויקטים דומים לגופים ציבוריים ב-5 השנים האחרונות",
                    field="similar_public_projects",
                    operator=Operator.COUNT_GTE,
                    value=3,
                    mandatory=True,
                    lookback_years=5,
                    qualifier={"client_type": "public"},
                    page=13,
                    quote_he=(
                        "על המציע להוכיח ניסיון בביצוע לפחות 3 פרויקטים דומים "
                        "לרשויות מקומיות או גופים ממשלתיים בחמש השנים שקדמו להגשה"
                    ),
                    confidence=0.90,
                ),
                TenderCriteriaPredicate(
                    id="C4",
                    category=CriteriaCategory.CERTIFICATION,
                    description_he="תקן ISO 9001 בתוקף",
                    field="certifications",
                    operator=Operator.CONTAINS,
                    value="ISO 9001",
                    mandatory=True,
                    page=14,
                    quote_he="על המציע להחזיק בתעודת ISO 9001 בתוקף ביום הגשת ההצעה",
                    confidence=0.98,
                ),
                TenderCriteriaPredicate(
                    id="C5",
                    category=CriteriaCategory.INSURANCE,
                    description_he="ביטוח אחריות כלפי צד שלישי בסכום של לפחות 10,000,000 ₪",
                    field="insurance_third_party_liability",
                    operator=Operator.GTE,
                    value=10_000_000,
                    mandatory=True,
                    page=15,
                    quote_he=(
                        "על המציע להמציא פוליסת ביטוח אחריות כלפי צד שלישי "
                        "על סך 10,000,000 ₪ לפחות, בתוקף לכל תקופת ההסכם"
                    ),
                    confidence=0.92,
                ),
                TenderCriteriaPredicate(
                    id="C6",
                    category=CriteriaCategory.CERTIFICATION,
                    description_he="תקן ISO 45001 (בטיחות וגהות תעסוקתית) — יתרון",
                    field="certifications",
                    operator=Operator.CONTAINS,
                    value="ISO 45001",
                    mandatory=False,
                    page=16,
                    quote_he="עדיפות תינתן לחברות המחזיקות בתקן ISO 45001 בתוקף",
                    confidence=0.85,
                ),
            ],
            extraction_meta={
                "source": "mock (PoC demo — no real PDF)",
                "model": "n/a",
                "schema_version": "1.0",
            },
        )
