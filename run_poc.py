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
        PipelineState(company=company, pdf_path=args.pdf),
        on_status=status,
    )
    analysis = state.analysis
    assert analysis is not None  # node guarantees this on success
    console.print(f"[green]✓[/green] נטענו {len(analysis.criteria)} קריטריונים")

    if args.dump_criteria:
        console.print_json(json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2))
        return

    # ── Step 3: run match engine ─────────────────────────────────────────────
    state = pipeline.node_run_match(state, on_status=status)
    report = state.report
    assert report is not None
    console.print("[green]✓[/green] מנוע ההתאמה הושלם")

    # ── Step 4: render report ────────────────────────────────────────────────
    print_report(report, analysis)


if __name__ == "__main__":
    main()
