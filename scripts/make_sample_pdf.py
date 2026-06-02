#!/usr/bin/env python3
"""Generate a synthetic Hebrew tender PDF for testing the extraction pipeline.

DEV/TEST utility — produces a clean, digital (non-scanned) Hebrew tender so we
can validate the Claude + instructor extraction path end-to-end without a real,
possibly-sensitive municipal document.

RTL handling: reportlab does not run the bidi algorithm, so we pre-shape each
line with python-bidi's get_display() and right-align it. PyMuPDF then extracts
the Hebrew in (near-)logical order, which Claude parses correctly. Real-world
*scanned* RTL PDFs remain the harder OCR problem flagged in ARCHITECTURE.md.

Requires (test-only): reportlab, python-bidi.

Usage:
    python scripts/make_sample_pdf.py [output_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

from bidi.algorithm import get_display
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PAGE_W, PAGE_H = A4
RIGHT_MARGIN = PAGE_W - 50  # right edge for drawRightString

# (text, font_size). Empty string = blank line.
PAGES: list[list[tuple[str, int]]] = [
    [
        ("עיריית תל אביב-יפו", 18),
        ("מכרז פומבי מס' 2026/142", 14),
        ("לאספקה, התקנה ותחזוקה של מערכות מיזוג אוויר במבני העירייה", 13),
        ("", 11),
        ("מועד אחרון להגשת הצעות: 15.07.2026 בשעה 12:00", 11),
        ('אומדן היקף ההתקשרות: כ-6,000,000 ש"ח לשלוש שנים.', 11),
        ("", 11),
        ("כללי", 14),
        ("העירייה מזמינה בזאת הצעות לאספקה, התקנה ותחזוקה שוטפת של מערכות", 11),
        ("מיזוג אוויר במבני העירייה, לתקופה של שלוש (3) שנים עם אופציה", 11),
        ("להארכה בשנתיים נוספות, והכל בהתאם לתנאי המכרז.", 11),
    ],
    [
        ("פרק 4 — תנאי סף להשתתפות במכרז", 14),
        ("רשאי להגיש הצעה מציע העומד במועד ההגשה בכל התנאים המצטברים הבאים:", 11),
        ("", 11),
        ("4.1 סיווג קבלני", 12),
        ("על המציע להחזיק בסיווג קבלנים בענף 170 (מיזוג אוויר), בקבוצה ג'", 11),
        ("ובהיקף כספי 3 לפחות, בתוקף ביום הגשת ההצעה.", 11),
        ("", 11),
        ("4.2 מחזור כספי", 12),
        ('על המציע להוכיח מחזור כספי שנתי של לפחות 5,000,000 ש"ח בכל אחת', 11),
        ("משלוש השנים הקלנדריות (2023, 2024, 2025) שקדמו לפרסום המכרז.", 11),
        ("", 11),
        ("4.3 ניסיון קודם", 12),
        ("על המציע להוכיח ניסיון בביצוע של לפחות 3 פרויקטים דומים עבור", 11),
        ("רשויות מקומיות או גופים ממשלתיים, בחמש (5) השנים שקדמו להגשה.", 11),
    ],
    [
        ("4.4 תקנים ואישורים", 12),
        ("על המציע להחזיק בתעודת ISO 9001 בתוקף ביום הגשת ההצעה.", 11),
        ("", 11),
        ("4.5 ביטוח", 12),
        ("על המציע להמציא אישור קיום ביטוח אחריות כלפי צד שלישי בסכום", 11),
        ('של לפחות 10,000,000 ש"ח, בתוקף לכל תקופת ההתקשרות.', 11),
        ("", 11),
        ("4.6 ערבות מכרז", 12),
        ('להצעה תצורף ערבות בנקאית אוטונומית על סך 50,000 ש"ח.', 11),
        ("", 11),
        ("פרק 5 — תנאים מועדפים (אינם תנאי סף)", 14),
        ("תינתן עדיפות למציעים המחזיקים בתעודת ISO 45001 (בטיחות וגהות", 11),
        ("תעסוקתית) בתוקף.", 11),
    ],
]


def build(output_path: str) -> None:
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
    c = canvas.Canvas(output_path, pagesize=A4)
    for lines in PAGES:
        y = PAGE_H - 70
        for text, size in lines:
            if text:
                c.setFont("DejaVu", size)
                c.drawRightString(RIGHT_MARGIN, y, get_display(text))
            y -= size + 8
        c.showPage()
    c.save()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sample_tender_he.pdf"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    build(out)
    print(f"Wrote {out}")
