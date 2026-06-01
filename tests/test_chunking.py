"""Unit tests for rag/chunking.py — zero API calls."""
from __future__ import annotations

import pytest

from src.smarttender.rag.chunking import chunk_document, DocChunk


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
