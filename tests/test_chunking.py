"""Unit tests for rag/chunking.py — zero API calls."""
from __future__ import annotations

import io
import types
from unittest.mock import MagicMock, patch

import pytest

from src.smarttender.rag.chunking import (
    DocChunk,
    ExtractionStats,
    _MIN_DIGITAL_CHARS,
    _ocr_page,
    chunk_document,
    extract_page_texts,
    extract_page_texts_with_stats,
)


def _pages(n: int, chars_each: int = 500) -> list[tuple[int, str]]:
    """Generate n synthetic pages of `chars_each` characters each."""
    return [(i + 1, f"[עמוד {i + 1}]\n" + "א" * chars_each) for i in range(n)]


class TestChunkDocument:
    def test_single_chunk_when_small(self):
        pages = _pages(3, chars_each=1_000)
        chunks = chunk_document(pages, max_chars=20_000)
        assert len(chunks) == 1
        assert chunks[0].start_page == 1
        assert chunks[0].end_page == 3

    def test_multiple_chunks_when_large(self):
        pages = _pages(10, chars_each=5_000)
        chunks = chunk_document(pages, max_chars=12_000)
        assert len(chunks) > 1

    def test_all_pages_covered(self):
        pages = _pages(10, chars_each=5_000)
        chunks = chunk_document(pages, max_chars=12_000, overlap_pages=0)
        covered = set()
        for ch in chunks:
            covered.update(range(ch.start_page, ch.end_page + 1))
        assert covered == set(range(1, 11))

    def test_overlap_repeats_boundary_page(self):
        pages = _pages(6, chars_each=4_000)
        chunks = chunk_document(pages, max_chars=10_000, overlap_pages=1)
        # With overlap, adjacent chunks share at least one page
        for i in range(len(chunks) - 1):
            assert chunks[i].end_page >= chunks[i + 1].start_page

    def test_chunk_indices_sequential(self):
        pages = _pages(8, chars_each=4_000)
        chunks = chunk_document(pages, max_chars=10_000)
        for i, ch in enumerate(chunks):
            assert ch.index == i

    def test_page_markers_in_text(self):
        pages = [(1, "שלום"), (2, "עולם")]
        chunks = chunk_document(pages, max_chars=10_000)
        assert "[עמוד 1]" in chunks[0].text
        assert "[עמוד 2]" in chunks[0].text

    def test_single_oversized_page_forms_one_chunk(self):
        """A page larger than max_chars must still appear in a chunk (not dropped)."""
        pages = [(1, "א" * 100_000)]
        chunks = chunk_document(pages, max_chars=10_000)
        assert len(chunks) == 1
        assert chunks[0].start_page == 1

    def test_empty_pages_returns_empty(self):
        chunks = chunk_document([], max_chars=10_000)
        assert chunks == []

    def test_page_range_str_format(self):
        pages = _pages(5, chars_each=4_000)
        chunks = chunk_document(pages, max_chars=10_000)
        for ch in chunks:
            assert "–" in ch.page_range_str or ch.start_page == ch.end_page


# ---------------------------------------------------------------------------
# ExtractionStats
# ---------------------------------------------------------------------------

class TestExtractionStats:
    def test_scan_ratio_zero_when_no_pages(self):
        s = ExtractionStats()
        assert s.scan_ratio == 0.0

    def test_scan_ratio_calculation(self):
        s = ExtractionStats(total_pages=10, ocr_pages=3)
        assert s.scan_ratio == pytest.approx(0.3)

    def test_summary_digital_only(self):
        s = ExtractionStats(total_pages=5, digital_pages=5)
        assert "דיגיטלי" in s.summary()
        assert "OCR" not in s.summary()

    def test_summary_includes_ocr_count(self):
        s = ExtractionStats(total_pages=5, digital_pages=3, ocr_pages=2)
        assert "OCR" in s.summary()
        assert "2" in s.summary()

    def test_summary_warns_when_tesseract_missing(self):
        s = ExtractionStats(total_pages=3, ocr_pages=1, ocr_available=False)
        assert "Tesseract" in s.summary()

    def test_summary_no_tesseract_warning_when_no_ocr_pages(self):
        s = ExtractionStats(total_pages=3, digital_pages=3, ocr_available=False)
        assert "Tesseract" not in s.summary()

    def test_summary_no_pages(self):
        assert ExtractionStats().summary() == "אין עמודים"


# ---------------------------------------------------------------------------
# _ocr_page
# ---------------------------------------------------------------------------

class TestOcrPage:
    def test_returns_false_when_pytesseract_missing(self, monkeypatch):
        """When pytesseract is not installed, _ocr_page returns ("", False)."""
        import builtins
        real_import = builtins.__import__

        def block_import(name, *args, **kwargs):
            if name in ("pytesseract", "PIL"):
                raise ImportError(f"Mocked missing: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", block_import)
        page = MagicMock()
        text, available = _ocr_page(page)
        assert text == ""
        assert available is False

    def test_returns_text_when_tesseract_available(self, monkeypatch):
        """When pytesseract works, extracted text and available=True are returned."""
        # Build minimal fake modules
        fake_pytesseract = types.ModuleType("pytesseract")
        fake_pytesseract.image_to_string = MagicMock(return_value="  מכרז מס' 123  ")

        fake_pil = types.ModuleType("PIL")
        fake_image_mod = types.ModuleType("PIL.Image")

        fake_img = MagicMock()
        fake_image_mod.open = MagicMock(return_value=fake_img)
        fake_pil.Image = fake_image_mod

        # Fake fitz Pixmap
        fake_pix = MagicMock()
        fake_pix.tobytes = MagicMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        fake_page = MagicMock()
        fake_page.get_pixmap.return_value = fake_pix

        with patch.dict("sys.modules", {"pytesseract": fake_pytesseract, "PIL": fake_pil, "PIL.Image": fake_image_mod}):
            text, available = _ocr_page(fake_page)

        assert available is True
        assert text == "מכרז מס' 123"

    def test_available_true_when_ocr_runtime_error(self, monkeypatch):
        """If Tesseract is installed but throws at runtime, available should still be True."""
        fake_pytesseract = types.ModuleType("pytesseract")
        fake_pytesseract.image_to_string = MagicMock(side_effect=RuntimeError("lang error"))

        fake_pil = types.ModuleType("PIL")
        fake_image_mod = types.ModuleType("PIL.Image")
        fake_image_mod.open = MagicMock(return_value=MagicMock())
        fake_pil.Image = fake_image_mod

        fake_pix = MagicMock()
        fake_pix.tobytes = MagicMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        fake_page = MagicMock()
        fake_page.get_pixmap.return_value = fake_pix

        with patch.dict("sys.modules", {"pytesseract": fake_pytesseract, "PIL": fake_pil, "PIL.Image": fake_image_mod}):
            text, available = _ocr_page(fake_page)

        assert text == ""
        assert available is True


# ---------------------------------------------------------------------------
# extract_page_texts / extract_page_texts_with_stats (using real PDFs via fitz)
# ---------------------------------------------------------------------------

def _make_pdf_bytes(text: str) -> bytes:
    """Create a minimal in-memory PDF with one text page using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestExtractPageTexts:
    def test_digital_page_extracted(self, tmp_path):
        pdf = tmp_path / "digital.pdf"
        pdf.write_bytes(_make_pdf_bytes("Hello Israel " * 10))
        pages = extract_page_texts(str(pdf), use_ocr=False)
        assert len(pages) == 1
        page_no, text = pages[0]
        assert page_no == 1
        assert "Hello" in text

    def test_empty_pdf_returns_empty_list(self, tmp_path):
        import fitz
        doc = fitz.open()
        doc.new_page()  # blank page
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        pdf = tmp_path / "blank.pdf"
        pdf.write_bytes(buf.getvalue())
        # blank page < _MIN_DIGITAL_CHARS, no OCR → empty list
        pages = extract_page_texts(str(pdf), use_ocr=False)
        assert pages == []

    def test_ocr_disabled_keeps_sparse_digital_text(self, tmp_path):
        """Sparse page (< threshold) with some digital text is still included as fallback."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        # Insert very little text (below threshold)
        page.insert_text((50, 100), "Hi", fontsize=12)
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        pdf = tmp_path / "sparse.pdf"
        pdf.write_bytes(buf.getvalue())
        pages = extract_page_texts(str(pdf), use_ocr=False)
        # "Hi" is 2 chars < 50 — below OCR threshold, but kept as fallback when no OCR
        assert len(pages) == 1
        assert "Hi" in pages[0][1]

    def test_digital_page_counted_in_stats(self, tmp_path):
        pdf = tmp_path / "d.pdf"
        pdf.write_bytes(_make_pdf_bytes("Hello Israel " * 10))
        _, stats = extract_page_texts_with_stats(str(pdf), use_ocr=False)
        assert stats.total_pages == 1
        assert stats.digital_pages == 1
        assert stats.ocr_pages == 0

    def test_min_digital_chars_constant(self):
        assert _MIN_DIGITAL_CHARS == 50

    def test_stats_empty_page_counted(self, tmp_path):
        import fitz
        doc = fitz.open()
        doc.new_page()  # completely blank
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        pdf = tmp_path / "blank2.pdf"
        pdf.write_bytes(buf.getvalue())
        _, stats = extract_page_texts_with_stats(str(pdf), use_ocr=False)
        assert stats.empty_pages == 1
