#!/usr/bin/env python3
"""
SmartTender AI — PoC Runner
============================
Proves the core capability end-to-end:
  PDF (or mock) → Criteria extraction (Claude) → Match Engine → Rich CLI report

Usage
-----
  # No API key needed — uses mock extraction
  python run_poc.py

  # Extract criteria from a real Hebrew tender PDF via Claude
  python run_poc.py --pdf path/to/tender.pdf

  # Pretty-print the raw extracted JSON and exit
  python run_poc.py --pdf path/to/tender.pdf --dump-criteria
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# ── Rich is required for the report; fail fast with a friendly message ──────
try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.exit("Missing dependency.  Run:  pip install -r requirements.txt")

from dotenv import load_dotenv

load_dotenv()

# ── project imports ──────────────────────────────────────────────────────────
from src.smarttender.match_engine.engine import evaluate_match
from src.smarttender.schemas.company_profile import (
    CompanyProfile,
    ContractorClassification,
    ExperienceRecord,
    InsuranceCoverage,
)
from src.smarttender.schemas.match import MatchReport
from src.smarttender.schemas.tender import (
    CriteriaCategory,
    Operator,
    TenderAnalysisOutput,
    TenderCriteriaPredicate,
)

console = Console()


# ══════════════════════════════════════════════════════════════════════════════
# 1.  HARDCODED TEST COMPANY
#     Edit these values to simulate different company profiles.
# ══════════════════════════════════════════════════════════════════════════════

def build_test_company() -> CompanyProfile:
    """Fictional Israeli SMB — 'טק-קול שירותים בע"מ' (HVAC contractor)."""
    y = date.today().year
    return CompanyProfile(
        company_name='טק-קול שירותים בע"מ',
        company_reg_id="514123456",
        # Turnover is below the 5M/yr threshold — intentional for demo
        annual_revenues={
            y - 3: 3_800_000,
            y - 2: 4_200_000,
            y - 1: 4_900_000,
        },
        equity_ils=1_200_000,
        contractor_classifications=[
            ContractorClassification(
                branch_code="170",    # מיזוג אוויר
                group_letter="ב",     # company has ב; tender requires ג — will FAIL
                financial_tier=2,     # company has 2; tender requires 3 — will FAIL
                valid_until=date(y + 2, 12, 31),
            )
        ],
        certifications=["ISO 9001", "ISO 14001"],  # 9001 ✓, 45001 missing — optional
        experience_years=8,
        similar_public_projects=[
            ExperienceRecord(
                project_name="מיזוג אוויר בית הספר אלון",
                client_type="municipal",
                value_ils=1_200_000,
                year=y - 2,
                domain_tags=["HVAC"],
            ),
            ExperienceRecord(
                project_name="מערכות קירור משרד הבינוי",
                client_type="government",
                value_ils=800_000,
                year=y - 4,
                domain_tags=["HVAC"],
            ),
            # 2 public projects found; tender requires 3 — will FAIL
        ],
        insurances=[
            InsuranceCoverage(
                insurance_type="third_party_liability",
                coverage_ils=5_000_000,   # company has 5M; tender requires 10M — FAIL
                valid_until=date(y + 1, 6, 30),
            )
        ],
        employees_count=22,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2.  MOCK EXTRACTION
#     Simulates the Criteria Agent output for a typical Israeli HVAC tender.
#     Runs with zero external dependencies.
# ══════════════════════════════════════════════════════════════════════════════

def mock_extraction() -> TenderAnalysisOutput:
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
            # C1 — financial (FAIL: revenues are below 5M in all 3 years)
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
            # C2 — classification (FAIL: company has ב/2, needs ג/3)
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
            # C3 — experience (FAIL: company has 2 public projects; 3 required)
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
            # C4 — certification (PASS: company has ISO 9001)
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
            # C5 — insurance (FAIL: company has 5M; 10M required)
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
            # C6 — optional certification (FAIL/optional: company missing ISO 45001)
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


# ══════════════════════════════════════════════════════════════════════════════
# 3.  REAL PDF EXTRACTION via Claude + instructor
# ══════════════════════════════════════════════════════════════════════════════

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


def extract_from_pdf(pdf_path: str) -> TenderAnalysisOutput:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        console.print("[red]PyMuPDF לא מותקן. הרץ: pip install pymupdf[/red]")
        return mock_extraction()

    try:
        import anthropic
        import instructor
    except ImportError:
        console.print("[red]anthropic / instructor לא מותקן. הרץ: pip install anthropic instructor[/red]")
        return mock_extraction()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[yellow]ANTHROPIC_API_KEY לא מוגדר — משתמש ב-mock.[/yellow]")
        return mock_extraction()

    console.print(f"[cyan]קורא PDF: {pdf_path}[/cyan]")
    doc = fitz.open(pdf_path)
    pages: list[str] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages.append(f"[עמוד {i + 1}]\n{text}")
    doc.close()
    full_text = "\n\n".join(pages)

    if not full_text.strip():
        console.print("[yellow]לא חולץ טקסט (PDF סרוק?) — OCR לא מיושם ב-PoC. משתמש ב-mock.[/yellow]")
        return mock_extraction()

    console.print(
        f"[cyan]חולץ {len(full_text):,} תווים מ-{len(pages)} עמודים. שולח ל-Claude...[/cyan]"
    )

    client = instructor.from_anthropic(anthropic.Anthropic(api_key=api_key))

    return client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8_192,
        system=_EXTRACTION_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _EXTRACTION_USER.format(text=full_text[:80_000]),
            }
        ],
        response_model=TenderAnalysisOutput,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4.  RICH CLI REPORT
# ══════════════════════════════════════════════════════════════════════════════

_CATEGORY_HE = {
    "financial":       "פיננסי 💰",
    "classification":  "סיווג קבלני 🏗",
    "experience":      "ניסיון 📋",
    "certification":   "תעודות 📜",
    "insurance":       "ביטוח 🛡",
    "legal":           "משפטי ⚖",
    "personnel":       "כוח אדם 👷",
    "other":           "אחר",
}


def print_report(report: MatchReport, analysis: TenderAnalysisOutput) -> None:
    console.print()

    # ── header panel ────────────────────────────────────────────────────────
    verdict = Text()
    if report.is_eligible:
        verdict.append("✅  כשיר להגשה", style="bold green")
    else:
        verdict.append("❌  לא כשיר — תנאי סף אינם מתקיימים", style="bold red")

    console.print(
        Panel(
            f"[bold]{analysis.title_he}[/bold]\n"
            f"[dim]מפרסם: {analysis.publisher_he}  |  "
            f"מועד הגשה: {analysis.submission_deadline or 'לא ידוע'}[/dim]\n\n"
            f"חברה: [bold cyan]{report.company_name}[/bold cyan]\n\n"
            f"{verdict}\n"
            f"ציון התאמה: [bold yellow]{report.compatibility_score} / 100[/bold yellow]",
            title="[bold blue]SmartTender AI — דוח התאמה[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # ── summary stats row ────────────────────────────────────────────────────
    stats = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    stats.add_column("", style="dim", min_width=10)
    stats.add_column("תנאי סף מחייבים", justify="center", min_width=22)
    stats.add_column("תנאים רצויים", justify="center", min_width=16)
    stats.add_row(
        "עברו ✅",
        f"[green]{report.passed_mandatory}[/green]",
        f"[green]{report.passed_optional}[/green]",
    )
    stats.add_row(
        "נכשלו ❌",
        f"[red]{report.failed_mandatory}[/red]",
        f"[yellow]{report.failed_optional}[/yellow]",
    )
    console.print(stats)

    # ── per-criterion breakdown table ────────────────────────────────────────
    tbl = Table(
        title="פירוט קריטריונים",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold white",
        header_style="bold white on dark_blue",
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("קטגוריה", min_width=16)
    tbl.add_column("דרישה", min_width=36)
    tbl.add_column("סטטוס", width=6, justify="center")
    tbl.add_column("ממצא וסיבה", min_width=38)
    tbl.add_column("עמ׳", width=4, justify="right")

    for r in report.breakdown:
        if r.passed:
            status = "✅"
            row_style = ""
        elif r.mandatory:
            status = "❌"
            row_style = "red"
        else:
            status = "⚠️"
            row_style = "yellow"

        finding = r.reason_he
        if r.gap and not r.passed:
            finding += f"\n[dim italic]פער: {r.gap}[/dim italic]"

        tbl.add_row(
            r.criterion_id,
            _CATEGORY_HE.get(r.category, r.category),
            r.description_he,
            status,
            finding,
            str(r.page) if r.page else "–",
            style=row_style,
        )

    console.print(tbl)

    # ── verdict summary ──────────────────────────────────────────────────────
    border = "green" if report.is_eligible else "red"
    console.print(Panel(report.summary_he, title="[bold]סיכום[/bold]", border_style=border))

    # ── actionable gap list ──────────────────────────────────────────────────
    failures = [r for r in report.breakdown if not r.passed and r.mandatory]
    if failures:
        console.print("\n[bold red]פעולות נדרשות לפני הגשה:[/bold red]")
        for i, r in enumerate(failures, 1):
            console.print(f"  [bold]{i}.[/bold] {r.description_he}")
            console.print(f"     [dim]→ {r.reason_he}[/dim]")
            if r.gap:
                console.print(f"     [dim]פער: {r.gap}[/dim]")
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# 5.  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SmartTender AI PoC — Hebrew tender match engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pdf", type=str, default=None, help="Path to a Hebrew tender PDF")
    parser.add_argument(
        "--dump-criteria",
        action="store_true",
        help="Print the raw extracted TenderAnalysisOutput JSON and exit",
    )
    args = parser.parse_args()

    console.rule("[bold blue]SmartTender AI — PoC Runner[/bold blue]")

    # ── Step 1: build company profile ───────────────────────────────────────
    company = build_test_company()
    console.print(f"[green]✓[/green] פרופיל חברה: [bold]{company.company_name}[/bold]")

    # ── Step 2: extract (or mock) criteria ──────────────────────────────────
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            console.print(f"[red]קובץ לא נמצא: {args.pdf}[/red]")
            sys.exit(1)
        analysis = extract_from_pdf(str(pdf_path))
        console.print(f"[green]✓[/green] חולצו {len(analysis.criteria)} קריטריונים מ-PDF")
    else:
        console.print("[yellow]⚡ אין PDF — משתמש ב-mock extraction[/yellow]")
        analysis = mock_extraction()
        console.print(f"[green]✓[/green] נטענו {len(analysis.criteria)} קריטריונים (mock)")

    if args.dump_criteria:
        console.print_json(json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2))
        return

    # ── Step 3: run match engine ─────────────────────────────────────────────
    report = evaluate_match(company, analysis)
    console.print("[green]✓[/green] מנוע ההתאמה הושלם")

    # ── Step 4: render report ────────────────────────────────────────────────
    print_report(report, analysis)


if __name__ == "__main__":
    main()
