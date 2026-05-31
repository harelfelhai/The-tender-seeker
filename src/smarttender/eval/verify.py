"""Citation-grounding verification for extracted tender criteria.

Answers the question: *"How do I know the extraction is faithful to a 100+ page
document without reading it myself?"*

Every TenderCriteriaPredicate carries a `page` and a verbatim `quote_he`. This
module re-opens the source PDF and checks, for each criterion, that the quote
actually appears on (or near) the cited page. It also reports COVERAGE — how
much of the document was actually fed to the LLM — so silent truncation can't
hide missed criteria.

No LLM, no network: pure text comparison against the source. The output is a
trust metric you can assert on in tests.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

import fitz  # PyMuPDF

from ..schemas.tender import TenderAnalysisOutput

# Thresholds for classifying a quote's fuzzy match against the source page.
GROUNDED_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.60


# ── text normalisation ───────────────────────────────────────────────────────

_NIQQUD = re.compile(r"[֑-ׇ]")           # Hebrew vowel/cantillation marks
_DIRECTIONAL = re.compile(r"[‎‏‪-‮⁦-⁩]")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonicalise Hebrew text so quotes compare robustly to extracted PDF text."""
    text = unicodedata.normalize("NFKC", text)
    text = _NIQQUD.sub("", text)
    text = _DIRECTIONAL.sub("", text)
    for a, b in (("״", '"'), ("“", '"'), ("”", '"'), ("׳", "'"), ("’", "'"), ("–", "-")):
        text = text.replace(a, b)
    return _WS.sub(" ", text).strip()


def best_match_ratio(quote: str, page_text: str) -> float:
    """Best fuzzy-match ratio of `quote` within `page_text` (0..1).

    Exact (normalised) containment short-circuits to 1.0; otherwise a sliding
    window over the page is scored with difflib and the maximum is returned.
    """
    q = normalize(quote)
    p = normalize(page_text)
    if not q or not p:
        return 0.0
    if q in p:
        return 1.0

    n = len(q)
    window = int(n * 1.3)
    step = max(1, n // 4)
    best = 0.0
    for i in range(0, max(1, len(p) - n + 1), step):
        ratio = SequenceMatcher(None, q, p[i : i + window]).ratio()
        if ratio > best:
            best = ratio
            if best >= 0.999:
                break
    return best


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class CriterionGrounding:
    criterion_id: str
    description_he: str
    cited_page: Optional[int]
    quote_he: Optional[str]
    score: float
    status: str  # "grounded" | "partial" | "not_found" | "no_citation"
    matched_page: Optional[int] = None  # page where the best match was actually found


@dataclass
class VerificationReport:
    total_criteria: int
    grounded: int
    partial: int
    not_found: int
    no_citation: int
    # coverage
    total_pages: int
    pages_with_text: int
    pages_sent_to_llm: int
    chars_total: int
    chars_sent: int
    results: list[CriterionGrounding] = field(default_factory=list)

    @property
    def grounding_rate(self) -> float:
        scorable = self.total_criteria - self.no_citation
        return (self.grounded / scorable) if scorable else 0.0

    @property
    def coverage_rate(self) -> float:
        return (self.chars_sent / self.chars_total) if self.chars_total else 0.0


# ── core ─────────────────────────────────────────────────────────────────────

def _page_texts(pdf_path: str) -> list[str]:
    doc = fitz.open(pdf_path)
    texts = [page.get_text("text") for page in doc]
    doc.close()
    return texts


def verify_extraction(
    pdf_path: str,
    analysis: TenderAnalysisOutput,
    *,
    max_chars_sent: int = 80_000,
    search_radius: int = 1,
) -> VerificationReport:
    """Verify each criterion's quote against the source PDF and report coverage.

    search_radius: how many pages on each side of the cited page to also search
    (LLM page attribution can be off by one near boundaries).
    """
    pages = _page_texts(pdf_path)
    total_pages = len(pages)
    pages_with_text = sum(1 for t in pages if t.strip())

    # Reconstruct exactly what the agent would have sent (see CriteriaAgent).
    nonempty = [(i + 1, t.strip()) for i, t in enumerate(pages) if t.strip()]
    full_text = "\n\n".join(f"[עמוד {n}]\n{t}" for n, t in nonempty)
    chars_total = len(full_text)
    sent = full_text[:max_chars_sent]
    chars_sent = len(sent)
    pages_sent = len(re.findall(r"\[עמוד \d+\]", sent))

    results: list[CriterionGrounding] = []
    counts = {"grounded": 0, "partial": 0, "not_found": 0, "no_citation": 0}

    for c in analysis.criteria:
        if not c.quote_he:
            results.append(
                CriterionGrounding(c.id, c.description_he, c.page, None, 0.0, "no_citation")
            )
            counts["no_citation"] += 1
            continue

        # Search the cited page first, then a small window around it; if no page
        # was cited, scan the whole document.
        if c.page and 1 <= c.page <= total_pages:
            lo = max(1, c.page - search_radius)
            hi = min(total_pages, c.page + search_radius)
            candidate_pages = range(lo, hi + 1)
        else:
            candidate_pages = range(1, total_pages + 1)

        best_score, best_page = 0.0, None
        for pno in candidate_pages:
            score = best_match_ratio(c.quote_he, pages[pno - 1])
            if score > best_score:
                best_score, best_page = score, pno
                if best_score >= 0.999:
                    break

        if best_score >= GROUNDED_THRESHOLD:
            status = "grounded"
        elif best_score >= PARTIAL_THRESHOLD:
            status = "partial"
        else:
            status = "not_found"
        counts[status] += 1

        results.append(
            CriterionGrounding(
                c.id, c.description_he, c.page, c.quote_he,
                round(best_score, 3), status, best_page,
            )
        )

    return VerificationReport(
        total_criteria=len(analysis.criteria),
        grounded=counts["grounded"],
        partial=counts["partial"],
        not_found=counts["not_found"],
        no_citation=counts["no_citation"],
        total_pages=total_pages,
        pages_with_text=pages_with_text,
        pages_sent_to_llm=pages_sent,
        chars_total=chars_total,
        chars_sent=chars_sent,
        results=results,
    )
