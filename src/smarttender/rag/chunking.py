"""Page-aware chunking for *exhaustive* (map-reduce) criteria extraction.

For the chat/Q&A feature you would embed + retrieve top-k. But for extracting
*every* תנאי סף, top-k retrieval re-introduces recall risk — a chunk that isn't
retrieved is a requirement that is silently lost. So here we sweep the WHOLE
document: split it into context-sized chunks (with page overlap so a criterion
straddling a boundary still lands intact in at least one chunk), run extraction
on each, then merge. Coverage becomes 100% and trivially measurable.

Page numbers are preserved as `[עמוד N]` markers inside each chunk so the LLM's
citations stay valid (global) document page numbers.

OCR: pages with fewer than _MIN_DIGITAL_CHARS characters are considered scanned/
image-based and are automatically sent through Tesseract (heb+eng). Requires the
`pytesseract` Python package and the `tesseract-ocr` + `tesseract-ocr-heb` system
packages. Falls back gracefully if Tesseract is not installed.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

log = logging.getLogger(__name__)

# Pages with fewer chars than this threshold are assumed scanned → try OCR.
_MIN_DIGITAL_CHARS = 50


@dataclass
class DocChunk:
    index: int
    start_page: int
    end_page: int
    text: str  # includes [עמוד N] markers

    @property
    def page_range_str(self) -> str:
        return f"{self.start_page}–{self.end_page}"


@dataclass
class ExtractionStats:
    total_pages: int = 0
    digital_pages: int = 0
    ocr_pages: int = 0
    empty_pages: int = 0
    ocr_available: bool = True

    @property
    def scan_ratio(self) -> float:
        return self.ocr_pages / self.total_pages if self.total_pages else 0.0

    def summary(self) -> str:
        if not self.total_pages:
            return "אין עמודים"
        parts = [f"{self.digital_pages} דיגיטלי"]
        if self.ocr_pages:
            parts.append(f"{self.ocr_pages} OCR")
        if self.empty_pages:
            parts.append(f"{self.empty_pages} ריקים")
        if self.ocr_pages and not self.ocr_available:
            parts.append("⚠ Tesseract לא מותקן — עמודים סרוקים לא חולצו")
        return " | ".join(parts)


def _ocr_page(page: fitz.Page, *, dpi: int = 300, lang: str = "heb+eng") -> tuple[str, bool]:
    """Render a page to image and run Tesseract OCR.

    Returns (text, ocr_was_available). ocr_was_available=False means Tesseract
    is not installed — caller should warn the user once.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "", False

    try:
        # Render page at target DPI (PyMuPDF default is 72 DPI)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        # PSM 6: assume a single uniform block of text (works well for Hebrew documents)
        text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
        return text.strip(), True
    except Exception as exc:
        log.debug("OCR failed on page: %s", exc)
        return "", True  # Tesseract IS installed, OCR just failed on this page


def extract_page_texts(
    pdf_path: str,
    *,
    use_ocr: bool = True,
    ocr_dpi: int = 300,
    ocr_lang: str = "heb+eng",
) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for pages that contain text (1-indexed).

    For each page, digital extraction (PyMuPDF) is tried first. Pages with fewer
    than _MIN_DIGITAL_CHARS characters are considered scanned and — when use_ocr
    is True — sent through Tesseract OCR automatically.
    """
    doc = fitz.open(pdf_path)
    out: list[tuple[int, str]] = []
    stats = ExtractionStats(total_pages=len(doc))
    ocr_warned = False

    for i, page in enumerate(doc):
        digital_text = page.get_text("text").strip()

        if len(digital_text) >= _MIN_DIGITAL_CHARS:
            out.append((i + 1, digital_text))
            stats.digital_pages += 1
            continue

        # Page is sparse — try OCR
        if use_ocr:
            ocr_text, available = _ocr_page(page, dpi=ocr_dpi, lang=ocr_lang)
            if not available and not ocr_warned:
                log.warning(
                    "Tesseract לא מותקן — עמודים סרוקים לא יחולצו. "
                    "התקן: apt install tesseract-ocr tesseract-ocr-heb"
                )
                stats.ocr_available = False
                ocr_warned = True
            if ocr_text:
                out.append((i + 1, f"[OCR]\n{ocr_text}"))
                stats.ocr_pages += 1
                continue

        # Fall back to whatever digital text exists (could be empty)
        if digital_text:
            out.append((i + 1, digital_text))
            stats.digital_pages += 1
        else:
            stats.empty_pages += 1

    doc.close()
    log.info("PDF חולץ: %s", stats.summary())
    return out


def extract_page_texts_with_stats(
    pdf_path: str,
    **kwargs,
) -> tuple[list[tuple[int, str]], ExtractionStats]:
    """Same as extract_page_texts but also returns ExtractionStats."""
    doc = fitz.open(pdf_path)
    out: list[tuple[int, str]] = []
    stats = ExtractionStats(total_pages=len(doc))
    use_ocr = kwargs.get("use_ocr", True)
    ocr_dpi = kwargs.get("ocr_dpi", 300)
    ocr_lang = kwargs.get("ocr_lang", "heb+eng")
    ocr_warned = False

    for i, page in enumerate(doc):
        digital_text = page.get_text("text").strip()

        if len(digital_text) >= _MIN_DIGITAL_CHARS:
            out.append((i + 1, digital_text))
            stats.digital_pages += 1
            continue

        if use_ocr:
            ocr_text, available = _ocr_page(page, dpi=ocr_dpi, lang=ocr_lang)
            if not available and not ocr_warned:
                stats.ocr_available = False
                ocr_warned = True
            if ocr_text:
                out.append((i + 1, f"[OCR]\n{ocr_text}"))
                stats.ocr_pages += 1
                continue

        if digital_text:
            out.append((i + 1, digital_text))
            stats.digital_pages += 1
        else:
            stats.empty_pages += 1

    doc.close()
    return out, stats


def _page_block(page_no: int, text: str) -> str:
    return f"[עמוד {page_no}]\n{text}"


def chunk_document(
    pages: list[tuple[int, str]],
    *,
    max_chars: int = 40_000,
    overlap_pages: int = 1,
) -> list[DocChunk]:
    """Greedily group consecutive pages into chunks up to `max_chars`.

    `overlap_pages` re-includes the last N pages of a chunk at the start of the
    next, so a criterion spanning a page boundary is fully present in at least
    one chunk. A single page larger than `max_chars` becomes its own chunk.
    """
    if not pages:
        return []

    chunks: list[DocChunk] = []
    i = 0
    n = len(pages)
    while i < n:
        cur: list[tuple[int, str]] = []
        size = 0
        j = i
        while j < n:
            block = _page_block(*pages[j])
            add = len(block) + 2  # account for the "\n\n" join
            if cur and size + add > max_chars:
                break
            cur.append(pages[j])
            size += add
            j += 1

        text = "\n\n".join(_page_block(p, t) for p, t in cur)
        chunks.append(
            DocChunk(
                index=len(chunks),
                start_page=cur[0][0],
                end_page=cur[-1][0],
                text=text,
            )
        )

        if j >= n:
            break
        # next chunk starts `overlap_pages` before where this one ended
        i = max(j - overlap_pages, i + 1)

    return chunks
