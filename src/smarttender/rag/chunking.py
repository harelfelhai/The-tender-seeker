"""Page-aware chunking for *exhaustive* (map-reduce) criteria extraction.

For the chat/Q&A feature you would embed + retrieve top-k. But for extracting
*every* תנאי סף, top-k retrieval re-introduces recall risk — a chunk that isn't
retrieved is a requirement that is silently lost. So here we sweep the WHOLE
document: split it into context-sized chunks (with page overlap so a criterion
straddling a boundary still lands intact in at least one chunk), run extraction
on each, then merge. Coverage becomes 100% and trivially measurable.

Page numbers are preserved as `[עמוד N]` markers inside each chunk so the LLM's
citations stay valid (global) document page numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass
class DocChunk:
    index: int
    start_page: int
    end_page: int
    text: str  # includes [עמוד N] markers

    @property
    def page_range_str(self) -> str:
        return f"{self.start_page}–{self.end_page}"


def extract_page_texts(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for pages that contain text (1-indexed)."""
    doc = fitz.open(pdf_path)
    out: list[tuple[int, str]] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            out.append((i + 1, text))
    doc.close()
    return out


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
