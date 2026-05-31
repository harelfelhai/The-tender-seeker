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
from src.smarttender.agents.graph import PipelineState, TenderPipeline
from src.smarttender.eval.verify import VerificationReport, verify_extraction
from src.smarttender.schemas.company_profile import (
    CompanyProfile,
    ContractorClassification,
    ExperienceRecord,
    InsuranceCoverage,
)
from src.smarttender.schemas.match import MatchReport
from src.smarttender.schemas.tender import TenderAnalysisOutput

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
        # ── characterization (drives the RELEVANCE axis) ────────────────────
        operating_regions=["מרכז", "שרון"],
        domains=["מיזוג אוויר", "מערכות קירור"],
        min_project_value_ils=500_000,
        max_project_value_ils=3_000_000,
        preferred_client_types=["municipal", "government"],
        available_capacity_pct=60,
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
    if report.unverifiable_mandatory:
        stats.add_row(
            "בדיקה ידנית 🔵",
            f"[blue]{report.unverifiable_mandatory}[/blue]",
            "",
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
        if r.unverifiable:
            status = "🔵"
            row_style = "blue"
        elif r.passed:
            status = "✅"
            row_style = ""
        elif r.mandatory:
            status = "❌"
            row_style = "red"
        else:
            status = "⚠️"
            row_style = "yellow"

        finding = r.reason_he
        if r.gap and not r.passed and not r.unverifiable:
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

    # ── actionable gap list (verifiable failures only) ──────────────────────
    failures = [r for r in report.breakdown if not r.passed and r.mandatory and not r.unverifiable]
    if failures:
        console.print("\n[bold red]פעולות נדרשות לפני הגשה:[/bold red]")
        for i, r in enumerate(failures, 1):
            console.print(f"  [bold]{i}.[/bold] {r.description_he}")
            console.print(f"     [dim]→ {r.reason_he}[/dim]")
            if r.gap:
                console.print(f"     [dim]פער: {r.gap}[/dim]")

    review = [r for r in report.breakdown if r.unverifiable and r.mandatory]
    if review:
        console.print(f"\n[bold blue]🔵 {len(review)} דרישות לבדיקה ידנית[/bold blue] "
                      "[dim](תיעודיות/נוהליות — לא ניתנות לאימות מול פרופיל החברה):[/dim]")
        for i, r in enumerate(review[:8], 1):
            console.print(f"  {i}. {r.description_he[:80]}")
        if len(review) > 8:
            console.print(f"  [dim]... ועוד {len(review) - 8}[/dim]")
    console.print()


# ══════════════════════════════════════════════════════════════════════════════
# 4a. RELEVANCE + DUAL-AXIS SCORE
# ══════════════════════════════════════════════════════════════════════════════

def print_relevance(relevance, report: MatchReport, final_score: float, analysis: TenderAnalysisOutput) -> None:
    console.print()
    tp = analysis.tender_profile

    # Dual-axis headline: eligibility gate × relevance.
    gate = "✅ עבר תנאי סף" if report.is_eligible else "❌ נכשל בתנאי סף → ציון 0"
    gate_style = "green" if report.is_eligible else "red"
    fs_style = "green" if final_score >= 70 else ("yellow" if final_score >= 40 else "red")
    console.print(
        Panel(
            f"כשירות: [bold {gate_style}]{gate}[/bold {gate_style}]\n"
            f"רלוונטיות (התאמה לאופי החברה): [bold]{relevance.relevance_score}/100[/bold]\n"
            f"[dim]פרופיל מכרז: אזור={tp.region or '?'} · תחום={', '.join(tp.domains) or '?'} · "
            f"היקף={('₪%s' % format(int(tp.estimated_value_ils),',')) if tp.estimated_value_ils else '?'} · "
            f"מזמין={tp.publisher_type or '?'}[/dim]\n\n"
            f"ציון סופי: [bold {fs_style}]{final_score} / 100[/bold {fs_style}]",
            title="[bold magenta]ציון משולב: כשירות × רלוונטיות[/bold magenta]",
            border_style="magenta",
            padding=(1, 2),
        )
    )

    tbl = Table(box=box.ROUNDED, header_style="bold white on purple4", show_lines=False)
    tbl.add_column("גורם", min_width=16)
    tbl.add_column("ציון", width=6, justify="center")
    tbl.add_column("משקל", width=6, justify="center")
    tbl.add_column("החברה", min_width=16)
    tbl.add_column("המכרז", min_width=16)
    tbl.add_column("הסבר", min_width=30)
    for f in relevance.factors:
        if f.is_neutral:
            sc_style = "dim"
        elif f.score >= 0.8:
            sc_style = "green"
        elif f.score <= 0.3:
            sc_style = "red"
        else:
            sc_style = "yellow"
        tbl.add_row(
            f.label_he,
            f"[{sc_style}]{f.score:.2f}[/{sc_style}]",
            f"{f.weight:.0%}",
            f.company_value,
            f.tender_value,
            f.explanation_he,
        )
    console.print(tbl)
    console.print(f"[dim]{relevance.summary_he}[/dim]\n")


# ══════════════════════════════════════════════════════════════════════════════
# 4b. CITATION-GROUNDING VERIFICATION REPORT
# ══════════════════════════════════════════════════════════════════════════════

_VERIFY_STATUS = {
    "grounded":    ("✅", "מעוגן במקור", "green"),
    "partial":     ("🟡", "התאמה חלקית", "yellow"),
    "not_found":   ("❌", "לא נמצא במקור", "red"),
    "no_citation": ("➖", "ללא ציטוט", "dim"),
}


def print_verification(report: VerificationReport) -> None:
    console.print()

    cov_pct = report.coverage_rate * 100
    cov_style = "green" if cov_pct >= 95 else ("yellow" if cov_pct >= 60 else "red")
    ground_pct = report.grounding_rate * 100
    g_style = "green" if ground_pct >= 90 else ("yellow" if ground_pct >= 70 else "red")

    console.print(
        Panel(
            f"עיגון ציטוטים: [bold {g_style}]{report.grounded}/"
            f"{report.total_criteria - report.no_citation}[/bold {g_style}] "
            f"מעוגנים במקור ({ground_pct:.0f}%)   "
            f"[dim]חלקי: {report.partial} · לא נמצא: {report.not_found} · "
            f"ללא ציטוט: {report.no_citation}[/dim]\n"
            f"כיסוי מסמך: [bold {cov_style}]{report.pages_sent_to_llm}/"
            f"{report.pages_with_text}[/bold {cov_style}] עמודים נשלחו ל-LLM "
            f"([{cov_style}]{cov_pct:.0f}%[/{cov_style}] מהטקסט; "
            f"{report.chars_sent:,}/{report.chars_total:,} תווים)",
            title="[bold blue]אימות נאמנות למקור (Citation Grounding)[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    if cov_pct < 95:
        console.print(
            f"[bold red]⚠ אזהרת כיסוי:[/bold red] רק {cov_pct:.0f}% מהמסמך נשלח ל-LLM — "
            f"קריטריונים בעמודים {report.pages_sent_to_llm + 1}–{report.pages_with_text} "
            f"[bold]לא נקראו[/bold]. נדרשת שכבת RAG כדי לכסות את כל המסמך."
        )

    tbl = Table(box=box.ROUNDED, show_lines=False, header_style="bold white on dark_blue")
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("דרישה", min_width=34)
    tbl.add_column("עמ׳ צוין", width=8, justify="center")
    tbl.add_column("נמצא בעמ׳", width=9, justify="center")
    tbl.add_column("ציון", width=6, justify="center")
    tbl.add_column("אימות", width=16)

    for r in report.results:
        icon, label, style = _VERIFY_STATUS[r.status]
        matched = str(r.matched_page) if r.matched_page else "–"
        flag = ""
        if r.matched_page and r.cited_page and r.matched_page != r.cited_page:
            flag = " [dim](שונה)[/dim]"
        tbl.add_row(
            r.criterion_id,
            r.description_he[:60],
            str(r.cited_page) if r.cited_page else "–",
            matched + flag,
            f"{r.score:.2f}",
            f"[{style}]{icon} {label}[/{style}]",
        )
    console.print(tbl)
    console.print(
        "[dim]איך לקרוא: 'ציון' = דמיון הציטוט שחולץ לטקסט שבעמוד המצוין ב-PDF. "
        "ציון ≥0.85 = הציטוט קיים במקור (לא הוזיה).[/dim]\n"
    )


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
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify each extracted criterion's quote against the source PDF (requires --pdf)",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Single-shot extraction (truncated) instead of full-coverage map-reduce",
    )
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=40_000,
        help="Max characters per chunk in full-coverage mode (default 40000)",
    )
    args = parser.parse_args()

    console.rule("[bold blue]SmartTender AI — PoC Runner[/bold blue]")

    # ── Step 1: build company profile ───────────────────────────────────────
    company = build_test_company()
    console.print(f"[green]✓[/green] פרופיל חברה: [bold]{company.company_name}[/bold]")

    if args.pdf and not Path(args.pdf).exists():
        console.print(f"[red]קובץ לא נמצא: {args.pdf}[/red]")
        sys.exit(1)
    if not args.pdf:
        console.print("[yellow]⚡ אין PDF — משתמש ב-mock extraction[/yellow]")

    # ── Step 2: run the deterministic pipeline (extract → match) ────────────
    def status(msg: str) -> None:
        console.print(f"[dim cyan]·[/dim cyan] {msg}")

    pipeline = TenderPipeline()
    state = pipeline.node_extract_criteria(
        PipelineState(
            company=company,
            pdf_path=args.pdf,
            full_coverage=not args.single,
            max_chunk_chars=args.max_chunk_chars,
        ),
        on_status=status,
    )
    analysis = state.analysis
    assert analysis is not None  # node guarantees this on success
    console.print(f"[green]✓[/green] נטענו {len(analysis.criteria)} קריטריונים")

    if args.dump_criteria:
        console.print_json(json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2))
        return

    # ── Step 2b: verify extraction faithfulness against the source PDF ───────
    if args.verify:
        if not args.pdf:
            console.print("[yellow]⚠ --verify מחייב --pdf (אין מקור לאימות מול mock)[/yellow]")
        else:
            console.print("[dim cyan]·[/dim cyan] מאמת ציטוטים מול ה-PDF המקורי...")
            # In full-coverage mode the whole document is processed, so coverage
            # should reflect that (no 80K truncation window).
            sent_window = 80_000 if args.single else 10**12
            print_verification(verify_extraction(args.pdf, analysis, max_chars_sent=sent_window))

    # ── Step 3: eligibility (match) then relevance, gated by eligibility ─────
    state = pipeline.node_run_match(state, on_status=status)
    state = pipeline.node_score_relevance(state, on_status=status)
    report = state.report
    assert report is not None and state.relevance is not None and state.final_score is not None
    console.print("[green]✓[/green] כשירות + רלוונטיות חושבו")

    # ── Step 4: render reports ───────────────────────────────────────────────
    print_report(report, analysis)
    print_relevance(state.relevance, report, state.final_score, analysis)


if __name__ == "__main__":
    main()
