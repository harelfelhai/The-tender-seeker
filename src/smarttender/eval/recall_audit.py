"""Recall (completeness) audit — *"did we miss any requirement?"*

Citation grounding (verify.py) proves PRECISION: what we extracted is real.
This module attacks RECALL from two independent angles so manual review shrinks
from 100+ pages to a handful of suspects:

1. Heuristic safety net (deterministic, no LLM): scan every page for obligation
   language ("יפסל", "תנאי סף", "על המציע"...). A page that carries such language
   but is cited by NO extracted criterion is a suspect for manual review.

2. Second-model judge (optional, LLM): an independent pass that re-reads each
   chunk and lists binding requirements NOT already in the extracted set. Two
   independent models missing the *same* requirement is far less likely than one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..schemas.tender import TenderAnalysisOutput
from .verify import normalize

# Strong cues: a single occurrence on an uncovered page is enough to flag it.
_STRONG_CUES = [
    "תנאי סף", "תנאי הסף", "תנאי השתתפות", "רשאי להגיש", "רשאי להשתתף",
    "יפסל", "תיפסל", "תפסל", "מנוע מלהשתתף", "כשירות המציע", "על הסף",
]
# Weak cues: need at least two distinct ones to flag (reduces false positives).
_WEAK_CUES = [
    "על המציע", "המציע נדרש", "המציע יידרש", "חייב", "נדרש", "יש לצרף",
    "יש להגיש", "אי עמידה", "בכפוף ל", "לא יוכל", "מתחייב",
]


@dataclass
class SuspectPage:
    page: int
    strong_hits: list[str]
    weak_hits: list[str]
    snippet: str


@dataclass
class RecallAuditReport:
    total_pages: int
    obligation_pages: int            # pages carrying obligation language
    covered_obligation_pages: int    # ...of which are cited by ≥1 criterion
    suspect_pages: list[SuspectPage] = field(default_factory=list)

    @property
    def obligation_coverage_rate(self) -> float:
        return (self.covered_obligation_pages / self.obligation_pages) if self.obligation_pages else 1.0


def _find_cues(text: str, cues: list[str]) -> list[str]:
    norm = normalize(text)
    return [c for c in cues if normalize(c) in norm]


def audit_recall_heuristic(pdf_path: str, analysis: TenderAnalysisOutput) -> RecallAuditReport:
    """Flag pages with obligation language that no extracted criterion cites."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    page_texts = [p.get_text("text") for p in doc]
    doc.close()

    cited_pages = {c.page for c in analysis.criteria if c.page}

    obligation_pages = 0
    covered = 0
    suspects: list[SuspectPage] = []
    for idx, text in enumerate(page_texts):
        page_no = idx + 1
        strong = _find_cues(text, _STRONG_CUES)
        weak = _find_cues(text, _WEAK_CUES)
        has_obligation = bool(strong) or len(weak) >= 2
        if not has_obligation:
            continue

        obligation_pages += 1
        if page_no in cited_pages:
            covered += 1
            continue

        # uncovered obligation page → suspect
        snippet = normalize(text)[:160]
        suspects.append(SuspectPage(page_no, strong, weak, snippet))

    suspects.sort(key=lambda s: (len(s.strong_hits), len(s.weak_hits)), reverse=True)
    return RecallAuditReport(
        total_pages=len(page_texts),
        obligation_pages=obligation_pages,
        covered_obligation_pages=covered,
        suspect_pages=suspects,
    )


# ── second-model judge (optional, LLM) ───────────────────────────────────────

try:  # pydantic model only needed when the LLM judge is used
    from pydantic import BaseModel, Field

    class MissedCandidate(BaseModel):
        description_he: str = Field(description="הדרישה המחייבת שאולי הוחמצה")
        page: Optional[int] = None
        quote_he: Optional[str] = None
        why_binding_he: str = Field(description="מדוע זו דרישה מחייבת/תנאי סף")

    class MissedList(BaseModel):
        missed: list[MissedCandidate] = Field(default_factory=list)
except ImportError:  # pragma: no cover
    pass


_JUDGE_SYSTEM = """\
אתה מבקר איכות עצמאי לניתוח מכרזים. קיבלת קטע ממסמך מכרז ורשימת דרישות שכבר חולצו.
תפקידך היחיד: לזהות דרישות מחייבות (תנאי סף, תנאי השתתפות, תנאים שאי-עמידה בהם פוסלת)
שמופיעות בקטע אך *אינן* מכוסות ברשימה שחולצה. אם הכל מכוסה — החזר רשימה ריקה.
אל תמציא; כלול רק דרישות שמופיעות מפורשות בטקסט, עם ציטוט קצר ומספר עמוד."""

_JUDGE_USER = """\
דרישות שכבר חולצו (אל תחזור עליהן):
{known}

קטע המסמך לבדיקה:
{chunk}

החזר רק דרישות מחייבות שחסרות מהרשימה."""


def audit_recall_llm(
    pdf_path: str,
    analysis: TenderAnalysisOutput,
    *,
    api_key: str,
    model: str = "claude-opus-4-8",
    max_chunk_chars: int = 60_000,
    on_status=lambda _m: None,
) -> list["MissedCandidate"]:
    """Independent second-model completeness pass over the whole document."""
    import anthropic
    import instructor

    from ..rag.chunking import chunk_document, extract_page_texts

    pages = extract_page_texts(pdf_path)
    chunks = chunk_document(pages, max_chars=max_chunk_chars, overlap_pages=1)
    known = "\n".join(f"- {c.description_he}" for c in analysis.criteria) or "(אין)"

    client = instructor.from_anthropic(anthropic.Anthropic(api_key=api_key))
    missed: list[MissedCandidate] = []
    for ch in chunks:
        on_status(f"שופט עצמאי: בודק chunk {ch.index + 1}/{len(chunks)} (עמ' {ch.page_range_str})...")
        result = client.messages.create(
            model=model,
            max_tokens=4_096,
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": _JUDGE_USER.format(known=known, chunk=ch.text)}],
            response_model=MissedList,
        )
        missed.extend(result.missed)
    return missed
