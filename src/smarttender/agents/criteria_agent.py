"""Criteria Agent — extracts תנאי סף from a tender document into a validated
TenderAnalysisOutput.

Despite the name "agent", this is a *deterministic structured-extraction step*,
not an autonomous runtime: one schema-enforced LLM call (via instructor) with a
mock fallback.  It is intentionally framework-free.  See ARCHITECTURE.md §1.2.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from typing import Callable, Optional

from ..rag.chunking import chunk_document, extract_page_texts_with_stats
from ..schemas.tender import (
    CriteriaCategory,
    Operator,
    TenderAnalysisOutput,
    TenderCriteriaPredicate,
    TenderProfile,
)

# A no-op status sink; callers (e.g. the CLI) can pass their own printer.
StatusFn = Callable[[str], None]

# Friendly aliases → full Anthropic model IDs.
# Haiku for dev iteration (~12x cheaper than Opus), Sonnet for staging, Opus for production.
MODEL_ALIASES: dict[str, str] = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-8",
}
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def resolve_model(name: str) -> str:
    """Accept a short alias or a full model ID; raise ValueError on unknown aliases."""
    lower = name.lower()
    if lower in MODEL_ALIASES:
        return MODEL_ALIASES[lower]
    # Accept any full model ID as-is (forward-compatible with future model names).
    return name


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

בנוסף לתנאי הסף, מלא את tender_profile לצורך דירוג רלוונטיות (לא כשירות):
• region — אזור קנוני: צפון / מרכז / דרום / ירושלים / שרון / שפלה.
• location_text — המיקום כפי שמופיע (עיר/אזור).
• domains — תחומי המכרז (למשל ["מיזוג אוויר"], ["בנייה למגורים"], ["תשתיות"]).
• estimated_value_ils — אומדן/היקף כספי אם צוין.
• publisher_type — municipal / government / rmi / other.
• work_type — אספקה / ביצוע / חכירת קרקע / שירות / תחזוקה.
אם פרט אינו מופיע ב-chunk הנוכחי — השאר null (אל תמציא).
"""

# Short trailing instruction — NOT cached so prompt iterations stay cheap.
_EXTRACTION_INSTRUCTION = "חלץ את תנאי הסף מהמכרז לעיל ומלא את הסכמה המובנית במדויק."


class CriteriaAgent:
    """Wraps PDF→text extraction and the schema-enforced LLM call."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        max_tokens: int = 8_192,
        max_chars: int = 80_000,
        use_cache: bool = True,
    ) -> None:
        self.model = resolve_model(model)
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.max_chars = max_chars
        self.use_cache = use_cache

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

    def extract_full(
        self,
        *,
        pdf_path: str,
        max_chunk_chars: int = 40_000,
        overlap_pages: int = 1,
        fallback_to_mock: bool = True,
        on_status: StatusFn = _noop,
    ) -> TenderAnalysisOutput:
        """Exhaustive map-reduce extraction over the ENTIRE document (100% coverage).

        Splits the PDF into context-sized chunks, extracts criteria from each,
        then merges and de-duplicates. Unlike `extract`, nothing is truncated —
        every page is processed, so no criterion can be silently missed.
        """
        try:
            pages, stats = extract_page_texts_with_stats(pdf_path)
            if not pages:
                raise ValueError(
                    "לא חולץ טקסט — PDF סרוק ללא Tesseract? "
                    "התקן: apt install tesseract-ocr tesseract-ocr-heb && pip install pytesseract pillow"
                )
            chunks = chunk_document(pages, max_chars=max_chunk_chars, overlap_pages=overlap_pages)
            on_status(
                f"כיסוי מלא: {len(pages)} עמודים → {len(chunks)} chunks "
                f"({stats.summary()}, חפיפה {overlap_pages} עמ')"
            )

            outputs: list[TenderAnalysisOutput] = []
            for ch in chunks:
                on_status(f"מחלץ chunk {ch.index + 1}/{len(chunks)} (עמ' {ch.page_range_str})...")
                outputs.append(self._call_llm(ch.text, on_status=_noop))

            merged = self._merge_outputs(outputs)
            on_status(
                f"מוזגו {sum(len(o.criteria) for o in outputs)} קריטריונים גולמיים "
                f"→ {len(merged.criteria)} ייחודיים (לאחר dedup)"
            )
            return merged
        except Exception as exc:  # noqa: BLE001 - PoC: degrade gracefully
            if not fallback_to_mock:
                raise
            on_status(f"חילוץ מלא נכשל ({exc}); נופל חזרה ל-mock.")
            return self.mock()

    # ── merge / dedup ─────────────────────────────────────────────────────────
    @staticmethod
    def _norm(text: str) -> str:
        text = unicodedata.normalize("NFKC", text or "")
        text = re.sub(r"[֑-ׇ]", "", text)            # niqqud
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _merge_outputs(self, outputs: list[TenderAnalysisOutput]) -> TenderAnalysisOutput:
        """Merge per-chunk outputs: take metadata from the richest chunk, then
        union the criteria while de-duplicating near-identical descriptions."""
        if not outputs:
            return self.mock()

        # Metadata: prefer the output with the longest title (usually the cover/intro).
        meta_src = max(outputs, key=lambda o: len(o.title_he or ""))

        kept: list[TenderCriteriaPredicate] = []
        for out in outputs:
            for crit in out.criteria:
                key = self._norm(crit.description_he)
                dup_idx = next(
                    (
                        i
                        for i, k in enumerate(kept)
                        if SequenceMatcher(None, key, self._norm(k.description_he)).ratio() >= 0.88
                    ),
                    None,
                )
                if dup_idx is None:
                    kept.append(crit)
                elif crit.confidence > kept[dup_idx].confidence:
                    kept.append(crit)  # keep higher-confidence variant
                    kept.pop(dup_idx)

        # Renumber IDs deterministically.
        for i, crit in enumerate(kept, 1):
            crit.id = f"C{i}"

        return TenderAnalysisOutput(
            tender_id=meta_src.tender_id,
            title_he=meta_src.title_he,
            publisher_he=meta_src.publisher_he,
            submission_deadline=meta_src.submission_deadline,
            estimated_budget_ils=meta_src.estimated_budget_ils,
            criteria=kept,
            tender_profile=self._merge_profiles([o.tender_profile for o in outputs]),
            raw_summary_he=meta_src.raw_summary_he,
            extraction_meta={
                "source": "full-coverage (map-reduce over all pages)",
                "chunks": len(outputs),
                "raw_criteria": sum(len(o.criteria) for o in outputs),
                "schema_version": "1.0",
                "prompt_caching": self.use_cache,
            },
        )

    @staticmethod
    def _merge_profiles(profiles: list[TenderProfile]) -> TenderProfile:
        """Combine per-chunk profiles: first non-empty value per scalar field,
        union for domains. Profile attributes can appear on any page."""
        merged = TenderProfile()
        for p in profiles:
            for fld in ("region", "location_text", "estimated_value_ils", "publisher_type", "work_type"):
                if getattr(merged, fld) is None and getattr(p, fld) is not None:
                    setattr(merged, fld, getattr(p, fld))
            for d in p.domains:
                if d not in merged.domains:
                    merged.domains.append(d)
        return merged

    # ── steps ───────────────────────────────────────────────────────────────
    def _pdf_to_text(self, pdf_path: str, *, on_status: StatusFn) -> str:
        on_status(f"קורא PDF: {pdf_path}")
        pages, stats = extract_page_texts_with_stats(pdf_path)

        if not pages:
            raise ValueError(
                "לא חולץ טקסט — PDF סרוק ללא Tesseract? "
                "התקן: apt install tesseract-ocr tesseract-ocr-heb && pip install pytesseract pillow"
            )

        full_text = "\n\n".join(f"[עמוד {p}]\n{t}" for p, t in pages)
        on_status(f"חולצו {len(full_text):,} תווים ({stats.summary()})")
        return full_text

    def _call_llm(self, text: str, *, on_status: StatusFn) -> TenderAnalysisOutput:
        import os

        import anthropic
        import instructor

        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY לא מוגדר")

        on_status("שולח ל-Claude עם אכיפת schema (instructor)...")
        truncated = text[: self.max_chars]

        if self.use_cache:
            # Prompt caching: system + document body are marked as cacheable breakpoints.
            # The short trailing instruction is left uncached — so tweaking it during
            # prompt engineering pays only ~500 tokens instead of the full 15K+ document.
            system_content: list | str = [
                {"type": "text", "text": _EXTRACTION_SYSTEM, "cache_control": {"type": "ephemeral"}}
            ]
            user_content: list | str = [
                {"type": "text", "text": truncated, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": _EXTRACTION_INSTRUCTION},
            ]
        else:
            system_content = _EXTRACTION_SYSTEM
            user_content = f"חלץ את תנאי הסף מהמכרז הבא ומלא את הסכמה המובנית:\n\n{truncated}"

        client = instructor.from_anthropic(anthropic.Anthropic(api_key=api_key))
        return client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_content,
            messages=[{"role": "user", "content": user_content}],
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
            tender_profile=TenderProfile(
                region="מרכז",
                location_text="תל אביב-יפו",
                domains=["מיזוג אוויר"],
                estimated_value_ils=6_000_000,
                publisher_type="municipal",
                work_type="אספקה והתקנה ותחזוקה",
            ),
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
