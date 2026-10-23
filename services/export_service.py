"""Export service for TalentMatch AI.

Generates formatted Excel workbooks, CSV exports, candidate shortlist reports,
and multi-sheet batch screening analytics using pandas and openpyxl.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from config.settings import get_settings
from database.connection import get_session
from database.models import (
    Candidate,
    CandidateMatch,
    JobDescription,
    MatchEvidence,
    ScreeningBatch,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """Sanitize strings for filesystem-safe filenames."""
    clean = re.sub(r'[\\/*?:"<>|]', "_", name.strip())
    clean = re.sub(r"\s+", "_", clean)
    return clean[:80]


class ExportService:
    """Service handling structured exports to Excel and CSV formats."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.exports_dir = self.settings.EXPORTS_DIR
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        # Styling constants
        self._navy_header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        self._header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        self._sub_header_fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
        self._sub_header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")

        self._thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1"),
        )

        self._fill_score_strong = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        self._font_score_strong = Font(name="Segoe UI", size=10, bold=True, color="15803D")

        self._fill_score_potential = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
        self._font_score_potential = Font(name="Segoe UI", size=10, bold=True, color="1E40AF")

        self._fill_score_review = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
        self._font_score_review = Font(name="Segoe UI", size=10, bold=True, color="B45309")

        self._fill_score_insufficient = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        self._font_score_insufficient = Font(name="Segoe UI", size=10, bold=True, color="B91C1C")

    def _normalize_match_item(self, item: Any, default_jd_title: str) -> Dict[str, Any]:
        """Convert a CandidateMatch model or dictionary into a normalized record."""
        if isinstance(item, dict):
            name = item.get("candidate_name") or item.get("name") or "Unknown Candidate"
            jd_title = item.get("jd_title") or default_jd_title
            match_score = float(item.get("match_score", item.get("score", 0.0)))
            match_category = item.get("match_category", "needs_review")
            m_met = item.get("mandatory_met", 0)
            m_tot = item.get("mandatory_total", 0)
            mandatory_met_str = f"{m_met}/{m_tot}" if m_tot > 0 else str(m_met)

            missing_raw = item.get("mandatory_missing") or item.get("mandatory_missing_json")
            if isinstance(missing_raw, list):
                missing_str = ", ".join(str(x) for x in missing_raw)
            elif isinstance(missing_raw, str) and missing_raw.startswith("["):
                try:
                    parsed = json.loads(missing_raw)
                    missing_str = ", ".join(str(x) for x in parsed) if isinstance(parsed, list) else missing_raw
                except Exception:
                    missing_str = missing_raw
            else:
                missing_str = str(missing_raw or "None")

            p_met = item.get("preferred_met", 0)
            p_tot = item.get("preferred_total", 0)
            preferred_str = f"{p_met}/{p_tot}" if p_tot > 0 else str(p_met)

            exp_score = float(item.get("experience_score", 0.0))
            qual_score = float(item.get("qualification_score", 0.0))
            review_status = item.get("human_review_status") or item.get("review_status") or "pending"
            notes = item.get("reviewer_notes") or item.get("notes") or ""
            date_val = item.get("screening_date") or item.get("last_screened_at") or ""
            method = item.get("matching_method") or "Hybrid"

            return {
                "Candidate Name": name,
                "JD Title": jd_title,
                "Match Score": match_score,
                "Match Category": match_category.replace("_", " ").title(),
                "Mandatory Met": mandatory_met_str,
                "Mandatory Missing": missing_str,
                "Preferred Skills": preferred_str,
                "Experience Score": exp_score,
                "Qualification Score": qual_score,
                "Review Status": review_status.replace("_", " ").title(),
                "Reviewer Notes": notes,
                "Screening Date": str(date_val)[:19] if date_val else "",
                "Matching Method": method,
            }

        # Handling ORM CandidateMatch model
        name = item.candidate.name if getattr(item, "candidate", None) else f"Candidate #{item.candidate_id}"
        jd_title = item.job_description.title if getattr(item, "job_description", None) else default_jd_title
        match_score = float(item.match_score)
        match_category = item.match_category or "needs_review"
        mandatory_met_str = f"{item.mandatory_met}/{item.mandatory_total}" if item.mandatory_total > 0 else str(item.mandatory_met)

        missing_raw = item.mandatory_missing_json
        missing_str = "None"
        if missing_raw:
            try:
                parsed = json.loads(missing_raw)
                missing_str = ", ".join(str(x) for x in parsed) if isinstance(parsed, list) else str(missing_raw)
            except Exception:
                missing_str = str(missing_raw)

        preferred_str = f"{item.preferred_met}/{item.preferred_total}" if item.preferred_total > 0 else str(item.preferred_met)
        date_str = item.last_screened_at.strftime("%Y-%m-%d %H:%M") if item.last_screened_at else ""
        method = "Hybrid"
        if getattr(item, "screening_run", None) and item.screening_run.matching_method:
            method = item.screening_run.matching_method

        return {
            "Candidate Name": name,
            "JD Title": jd_title,
            "Match Score": match_score,
            "Match Category": match_category.replace("_", " ").title(),
            "Mandatory Met": mandatory_met_str,
            "Mandatory Missing": missing_str,
            "Preferred Skills": preferred_str,
            "Experience Score": float(item.experience_score),
            "Qualification Score": float(item.qualification_score),
            "Review Status": (item.human_review_status or "pending").replace("_", " ").title(),
            "Reviewer Notes": item.reviewer_notes or "",
            "Screening Date": date_str,
            "Matching Method": method,
        }

    def _apply_table_formatting(self, ws: Any, score_col_index: int = 3) -> None:
        """Apply professional fonts, borders, alternating colors, and column auto-widths."""
        for col_idx, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row), start=1):
            max_len = 0
            col_letter = get_column_letter(col_idx)

            for cell_idx, cell in enumerate(col, start=1):
                # Header row
                if cell_idx == 1:
                    cell.fill = self._navy_header_fill
                    cell.font = self._header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                else:
                    cell.border = self._thin_border
                    cell.alignment = Alignment(vertical="center")

                    # Highlight score cell
                    if col_idx == score_col_index:
                        try:
                            score_val = float(str(cell.value).replace("%", "").strip())
                            if score_val >= 80.0:
                                cell.fill = self._fill_score_strong
                                cell.font = self._font_score_strong
                            elif score_val >= 60.0:
                                cell.fill = self._fill_score_potential
                                cell.font = self._font_score_potential
                            elif score_val >= 40.0:
                                cell.fill = self._fill_score_review
                                cell.font = self._font_score_review
                            else:
                                cell.fill = self._fill_score_insufficient
                                cell.font = self._font_score_insufficient
                            cell.alignment = Alignment(horizontal="center", vertical="center")
                        except (ValueError, TypeError):
                            pass

                val_str = str(cell.value or "")
                lines = val_str.split("\n")
                line_max = max(len(l) for l in lines) if lines else 0
                if line_max > max_len:
                    max_len = line_max

            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 48)

    def export_matches_to_excel(
        self, matches: List[Any], jd_title: str, filename: Optional[str] = None
    ) -> str:
        """Create a formatted Excel file containing candidate matches.

        Args:
            matches: List of CandidateMatch models or match dictionaries.
            jd_title: Target Job Description title.
            filename: Optional custom filename.

        Returns:
            str: Path to the generated Excel file.
        """
        rows = [self._normalize_match_item(m, jd_title) for m in matches]
        df = pd.DataFrame(rows)

        if not filename:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_title = _sanitize_filename(jd_title or "Requisition")
            filename = f"match_results_{safe_title}_{ts}.xlsx"

        file_path = self.exports_dir / filename

        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Match Results", index=False)
            ws = writer.sheets["Match Results"]
            ws.views.sheetView[0].showGridLines = True
            ws.row_dimensions[1].height = 26
            self._apply_table_formatting(ws, score_col_index=3)

        logger.info("Exported %d matches to Excel: %s", len(rows), file_path)
        return str(file_path)

    def export_matches_to_csv(
        self, matches: List[Any], jd_title: str, filename: Optional[str] = None
    ) -> str:
        """Export candidate matches to standard CSV format.

        Args:
            matches: List of CandidateMatch models or match dictionaries.
            jd_title: Target Job Description title.
            filename: Optional custom filename.

        Returns:
            str: Path to the generated CSV file.
        """
        rows = [self._normalize_match_item(m, jd_title) for m in matches]
        df = pd.DataFrame(rows)

        if not filename:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_title = _sanitize_filename(jd_title or "Requisition")
            filename = f"match_results_{safe_title}_{ts}.csv"

        file_path = self.exports_dir / filename
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        logger.info("Exported %d matches to CSV: %s", len(rows), file_path)
        return str(file_path)

    def export_shortlist_to_excel(
        self, shortlist_data: Dict[str, Any], filename: Optional[str] = None
    ) -> str:
        """Export shortlist collection with candidates and metadata to Excel.

        Args:
            shortlist_data: Shortlist dictionary containing metadata and candidates list.
            filename: Optional custom filename.

        Returns:
            str: Path to generated Excel file.
        """
        name = shortlist_data.get("name", "Shortlist")
        jd_title = shortlist_data.get("jd_title", "Requisition")
        candidates = shortlist_data.get("candidates", [])

        if not filename:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = _sanitize_filename(name)
            filename = f"shortlist_{safe_name}_{ts}.xlsx"

        file_path = self.exports_dir / filename
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Shortlist Candidates"
        ws.views.sheetView[0].showGridLines = True

        # Header Title Banner
        ws.merge_cells("A1:I1")
        title_cell = ws["A1"]
        title_cell.value = f"TALENTMATCH AI — SHORTLIST: {name.upper()}"
        title_cell.font = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
        title_cell.fill = self._navy_header_fill
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 36

        # Shortlist Metadata Block
        meta_items = [
            ("Requisition:", jd_title, "Status:", shortlist_data.get("status", "Active").capitalize()),
            ("Created At:", str(shortlist_data.get("created_at", "—"))[:16], "Candidate Count:", str(len(candidates))),
            ("Description:", shortlist_data.get("description") or "No description provided.", "", ""),
        ]

        meta_font_bold = Font(name="Segoe UI", size=9, bold=True, color="1E3A8A")
        meta_font_val = Font(name="Segoe UI", size=9, color="334155")
        meta_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        current_row = 3
        for k1, v1, k2, v2 in meta_items:
            ws.cell(row=current_row, column=1, value=k1).font = meta_font_bold
            ws.cell(row=current_row, column=2, value=v1).font = meta_font_val
            ws.cell(row=current_row, column=4, value=k2).font = meta_font_bold
            ws.cell(row=current_row, column=5, value=v2).font = meta_font_val
            for c in range(1, 10):
                ws.cell(row=current_row, column=c).fill = meta_fill
            current_row += 1

        current_row += 1  # blank gap row

        # Table Column Headers
        headers = [
            "Candidate ID",
            "Candidate Name",
            "Email Address",
            "Phone Number",
            "Match Score",
            "Match Category",
            "Shortlist Status",
            "Recruiter Notes",
            "Added Date",
        ]

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=current_row, column=col_idx, value=h)
            cell.font = self._header_font
            cell.fill = self._sub_header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = self._thin_border

        ws.row_dimensions[current_row].height = 24
        header_row_index = current_row
        current_row += 1

        # Populate Candidate Rows
        for cand in candidates:
            score_val = cand.get("match_score", 0.0)
            score_str = f"{score_val:.1f}%" if score_val is not None else "N/A"
            cat_str = (cand.get("match_category") or "needs_review").replace("_", " ").title()
            status_str = (cand.get("status") or "shortlisted").replace("_", " ").title()

            row_data = [
                cand.get("candidate_id") or cand.get("id"),
                cand.get("candidate_name") or cand.get("name") or "Unknown",
                cand.get("email") or "—",
                cand.get("phone") or "—",
                score_str,
                cat_str,
                status_str,
                cand.get("recruiter_notes") or cand.get("notes") or "",
                str(cand.get("added_at") or "")[:16],
            ]

            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=val)
                cell.border = self._thin_border
                cell.font = Font(name="Segoe UI", size=9, color="0F172A")
                cell.alignment = Alignment(vertical="center")

                # Match score highlight
                if col_idx == 5:
                    if score_val >= 80.0:
                        cell.fill = self._fill_score_strong
                        cell.font = self._font_score_strong
                    elif score_val >= 60.0:
                        cell.fill = self._fill_score_potential
                        cell.font = self._font_score_potential
                    elif score_val >= 40.0:
                        cell.fill = self._fill_score_review
                        cell.font = self._font_score_review
                    else:
                        cell.fill = self._fill_score_insufficient
                        cell.font = self._font_score_insufficient
                    cell.alignment = Alignment(horizontal="center", vertical="center")

            current_row += 1

        # Adjust Column Widths
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                # ignore banner merged row
                if cell.row == 1:
                    continue
                if cell.value:
                    line_len = max(len(l) for l in str(cell.value).split("\n"))
                    if line_len > max_len:
                        max_len = line_len
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

        wb.save(file_path)
        logger.info("Exported shortlist '%s' to Excel: %s", name, file_path)
        return str(file_path)

    def generate_screening_report(self, batch_id: int) -> str:
        """Generate a comprehensive multi-sheet screening audit report for a batch run.

        Includes Summary, Detailed Results, Score Distribution, and Requirement Analysis.

        Args:
            batch_id: Primary key of the ScreeningBatch.

        Returns:
            str: Absolute file path to the generated Excel report.
        """
        with get_session() as session:
            stmt = (
                select(ScreeningBatch)
                .where(ScreeningBatch.id == batch_id)
                .options(
                    selectinload(ScreeningBatch.runs).selectinload(ScreeningRun.candidate_matches).selectinload(CandidateMatch.candidate),
                    selectinload(ScreeningBatch.runs).selectinload(ScreeningRun.candidate_matches).selectinload(CandidateMatch.job_description),
                    selectinload(ScreeningBatch.runs).selectinload(ScreeningRun.candidate_matches).selectinload(CandidateMatch.match_evidences),
                )
            )
            batch = session.scalars(stmt).unique().first()
            if not batch:
                raise ValueError(f"Screening batch with ID {batch_id} not found.")

            # Collect matches across all runs
            matches: List[CandidateMatch] = []
            for r in batch.runs:
                matches.extend(r.candidate_matches)

            # Pre-calculate batch metrics
            total_screened = len(matches)
            scores = [float(m.match_score) for m in matches]
            avg_score = (sum(scores) / len(scores)) if scores else 0.0

            strong_count = sum(1 for s in scores if s >= 80.0)
            potential_count = sum(1 for s in scores if 60.0 <= s < 80.0)
            review_count = sum(1 for s in scores if 40.0 <= s < 60.0)
            insufficient_count = sum(1 for s in scores if s < 40.0)

            # Target JD Titles
            jd_titles = sorted(list({m.job_description.title for m in matches if m.job_description}))
            jd_titles_str = ", ".join(jd_titles) if jd_titles else "General Requisition"

            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = _sanitize_filename(batch.name)
            filename = f"screening_report_{safe_name}_{batch_id}_{ts}.xlsx"
            file_path = self.exports_dir / filename

            wb = openpyxl.Workbook()
            # Remove default sheet
            wb.remove(wb.active)

            # -----------------------------------------------------------------
            # SHEET 1: SUMMARY
            # -----------------------------------------------------------------
            ws_summary = wb.create_sheet(title="Executive Summary")
            ws_summary.views.sheetView[0].showGridLines = True

            ws_summary.merge_cells("A1:G1")
            banner = ws_summary["A1"]
            banner.value = "TALENTMATCH AI — SCREENING BATCH AUDIT REPORT"
            banner.font = Font(name="Segoe UI", size=14, bold=True, color="FFFFFF")
            banner.fill = self._navy_header_fill
            banner.alignment = Alignment(horizontal="center", vertical="center")
            ws_summary.row_dimensions[1].height = 36

            # Batch Parameters
            params = [
                ("Batch Identifier:", f"#{batch.id} — {batch.name}", "Created Date:", batch.created_at.strftime("%Y-%m-%d %H:%M")),
                ("Status:", batch.status.upper(), "Completed Date:", batch.completed_at.strftime("%Y-%m-%d %H:%M") if batch.completed_at else "In Progress"),
                ("Matching Algorithm:", batch.matching_method or "Hybrid Semantic & Rule-Based", "Screened Candidate Count:", str(total_screened)),
                ("Target Requisition(s):", jd_titles_str, "Initiated By:", batch.created_by or "Recruiter"),
            ]

            curr_row = 3
            for l_lbl, l_val, r_lbl, r_val in params:
                ws_summary.cell(row=curr_row, column=1, value=l_lbl).font = Font(name="Segoe UI", size=9, bold=True, color="1E3A8A")
                ws_summary.cell(row=curr_row, column=2, value=l_val).font = Font(name="Segoe UI", size=9, color="334155")
                ws_summary.cell(row=curr_row, column=4, value=r_lbl).font = Font(name="Segoe UI", size=9, bold=True, color="1E3A8A")
                ws_summary.cell(row=curr_row, column=5, value=r_val).font = Font(name="Segoe UI", size=9, color="334155")
                for c in range(1, 7):
                    ws_summary.cell(row=curr_row, column=c).fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
                curr_row += 1

            curr_row += 2

            # Section: Screening KPIs
            ws_summary.merge_cells(f"A{curr_row}:E{curr_row}")
            sec_header = ws_summary.cell(row=curr_row, column=1, value="Screening Performance Key Metrics")
            sec_header.font = self._header_font
            sec_header.fill = self._sub_header_fill
            sec_header.alignment = Alignment(horizontal="left", vertical="center")
            ws_summary.row_dimensions[curr_row].height = 24
            curr_row += 1

            kpis = [
                ("Total Candidate Matches Evaluated", total_screened),
                ("Mean Match Score Across Pool", f"{avg_score:.1f}%"),
                ("Strong Matches (≥ 80%)", f"{strong_count} ({strong_count/max(1, total_screened)*100:.1f}%)"),
                ("Potential Matches (60% – 79%)", f"{potential_count} ({potential_count/max(1, total_screened)*100:.1f}%)"),
                ("Candidates Requiring Review (40% – 59%)", f"{review_count} ({review_count/max(1, total_screened)*100:.1f}%)"),
                ("Insufficient Evidence (< 40%)", f"{insufficient_count} ({insufficient_count/max(1, total_screened)*100:.1f}%)"),
            ]

            for label, value in kpis:
                c1 = ws_summary.cell(row=curr_row, column=1, value=label)
                c2 = ws_summary.cell(row=curr_row, column=3, value=str(value))
                c1.font = Font(name="Segoe UI", size=9, color="0F172A")
                c2.font = Font(name="Segoe UI", size=9, bold=True, color="1E3A8A")
                c1.border = self._thin_border
                c2.border = self._thin_border
                c2.alignment = Alignment(horizontal="center", vertical="center")
                curr_row += 1

            for col in ws_summary.columns:
                max_len = max(len(str(cell.value or "")) for cell in col if cell.row > 1)
                ws_summary.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 3, 14)

            # -----------------------------------------------------------------
            # SHEET 2: DETAILED RESULTS
            # -----------------------------------------------------------------
            ws_details = wb.create_sheet(title="Detailed Results")
            ws_details.views.sheetView[0].showGridLines = True

            detail_headers = [
                "Candidate Name",
                "Email Address",
                "Job Description",
                "Match Score",
                "Match Category",
                "Mandatory Met",
                "Mandatory Missing",
                "Preferred Met",
                "Experience Score",
                "Qualification Score",
                "Domain Score",
                "Confidence",
                "Human Review Status",
                "Recruiter Decision Notes",
                "Evaluated Date",
            ]

            ws_details.row_dimensions[1].height = 26
            for col_idx, h in enumerate(detail_headers, start=1):
                cell = ws_details.cell(row=1, column=col_idx, value=h)
                cell.font = self._header_font
                cell.fill = self._navy_header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            d_row = 2
            for m in matches:
                cand_name = m.candidate.name if m.candidate else f"Candidate #{m.candidate_id}"
                cand_email = m.candidate.email if m.candidate and m.candidate.email else "—"
                job_title = m.job_description.title if m.job_description else f"JD #{m.jd_id}"
                m_missing = "None"
                if m.mandatory_missing_json:
                    try:
                        parsed = json.loads(m.mandatory_missing_json)
                        m_missing = ", ".join(str(x) for x in parsed) if isinstance(parsed, list) else str(m.mandatory_missing_json)
                    except Exception:
                        m_missing = str(m.mandatory_missing_json)

                row_vals = [
                    cand_name,
                    cand_email,
                    job_title,
                    float(m.match_score),
                    m.match_category.replace("_", " ").title(),
                    f"{m.mandatory_met}/{m.mandatory_total}",
                    m_missing,
                    f"{m.preferred_met}/{m.preferred_total}",
                    float(m.experience_score),
                    float(m.qualification_score),
                    float(m.domain_score),
                    f"{float(m.confidence):.2f}",
                    m.human_review_status.replace("_", " ").title(),
                    m.reviewer_notes or "",
                    m.last_screened_at.strftime("%Y-%m-%d %H:%M") if m.last_screened_at else "",
                ]

                for col_idx, val in enumerate(row_vals, start=1):
                    cell = ws_details.cell(row=d_row, column=col_idx, value=val)
                    cell.border = self._thin_border
                    cell.font = Font(name="Segoe UI", size=9, color="0F172A")
                    cell.alignment = Alignment(vertical="center")

                    # Score formatting
                    if col_idx == 4:
                        cell.value = f"{val:.1f}%"
                        if val >= 80.0:
                            cell.fill = self._fill_score_strong
                            cell.font = self._font_score_strong
                        elif val >= 60.0:
                            cell.fill = self._fill_score_potential
                            cell.font = self._font_score_potential
                        elif val >= 40.0:
                            cell.fill = self._fill_score_review
                            cell.font = self._font_score_review
                        else:
                            cell.fill = self._fill_score_insufficient
                            cell.font = self._font_score_insufficient
                        cell.alignment = Alignment(horizontal="center", vertical="center")

                d_row += 1

            self._apply_table_formatting(ws_details, score_col_index=4)

            # -----------------------------------------------------------------
            # SHEET 3: SCORE DISTRIBUTION
            # -----------------------------------------------------------------
            ws_dist = wb.create_sheet(title="Score Distribution")
            ws_dist.views.sheetView[0].showGridLines = True

            dist_headers = ["Score Range", "Category Bracket", "Candidate Count", "Percentage of Evaluated Pool"]
            ws_dist.row_dimensions[1].height = 24
            for col_idx, h in enumerate(dist_headers, start=1):
                cell = ws_dist.cell(row=1, column=col_idx, value=h)
                cell.font = self._header_font
                cell.fill = self._navy_header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            bands = [
                ("90.0% – 100.0%", "Exceptional Match", sum(1 for s in scores if s >= 90.0)),
                ("80.0% – 89.9%", "Strong Match", sum(1 for s in scores if 80.0 <= s < 90.0)),
                ("60.0% – 79.9%", "Potential Match", sum(1 for s in scores if 60.0 <= s < 80.0)),
                ("40.0% – 59.9%", "Needs Review", sum(1 for s in scores if 40.0 <= s < 60.0)),
                ("0.0% – 39.9%", "Insufficient Evidence", sum(1 for s in scores if s < 40.0)),
            ]

            b_row = 2
            total_matches_cnt = max(1, len(scores))
            for rng, cat, cnt in bands:
                pct_str = f"{(cnt / total_matches_cnt) * 100:.1f}%"
                vals = [rng, cat, cnt, pct_str]
                for col_idx, val in enumerate(vals, start=1):
                    cell = ws_dist.cell(row=b_row, column=col_idx, value=val)
                    cell.border = self._thin_border
                    cell.font = Font(name="Segoe UI", size=9, color="0F172A")
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                b_row += 1

            for col in ws_dist.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                ws_dist.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 4, 16)

            # -----------------------------------------------------------------
            # SHEET 4: REQUIREMENT ANALYSIS
            # -----------------------------------------------------------------
            ws_req = wb.create_sheet(title="Requirement Analysis")
            ws_req.views.sheetView[0].showGridLines = True

            req_headers = ["Requirement Name", "Category", "Importance", "Matched", "Partial", "Missing", "Match Rate (%)"]
            ws_req.row_dimensions[1].height = 24
            for col_idx, h in enumerate(req_headers, start=1):
                cell = ws_req.cell(row=1, column=col_idx, value=h)
                cell.font = self._header_font
                cell.fill = self._navy_header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Aggregate match evidence items across all matches
            evidence_summary: Dict[int, Dict[str, Any]] = {}
            for m in matches:
                for ev in getattr(m, "match_evidences", []):
                    req_id = ev.requirement_id
                    if req_id not in evidence_summary:
                        r_name = ev.requirement.requirement_name if ev.requirement else f"Requirement #{req_id}"
                        r_cat = ev.requirement.category if ev.requirement else "skill"
                        r_imp = ev.requirement.importance if ev.requirement else "mandatory"
                        evidence_summary[req_id] = {
                            "name": r_name,
                            "category": r_cat.replace("_", " ").title(),
                            "importance": r_imp.capitalize(),
                            "matched": 0,
                            "partial": 0,
                            "missing": 0,
                        }

                    if ev.match_status == "matched":
                        evidence_summary[req_id]["matched"] += 1
                    elif ev.match_status == "partial":
                        evidence_summary[req_id]["partial"] += 1
                    else:
                        evidence_summary[req_id]["missing"] += 1

            r_row = 2
            if evidence_summary:
                for req_stat in evidence_summary.values():
                    tot = req_stat["matched"] + req_stat["partial"] + req_stat["missing"]
                    rate = ((req_stat["matched"] + 0.5 * req_stat["partial"]) / max(1, tot)) * 100
                    row_vals = [
                        req_stat["name"],
                        req_stat["category"],
                        req_stat["importance"],
                        req_stat["matched"],
                        req_stat["partial"],
                        req_stat["missing"],
                        f"{rate:.1f}%",
                    ]
                    for col_idx, val in enumerate(row_vals, start=1):
                        cell = ws_req.cell(row=r_row, column=col_idx, value=val)
                        cell.border = self._thin_border
                        cell.font = Font(name="Segoe UI", size=9, color="0F172A")
                        cell.alignment = Alignment(horizontal="center" if col_idx >= 4 else "left", vertical="center")
                    r_row += 1
            else:
                # Fallback if MatchEvidence is not populated
                empty_cell = ws_req.cell(row=2, column=1, value="No atomic requirement evidence records present for this batch run.")
                ws_req.merge_cells("A2:G2")
                empty_cell.font = Font(name="Segoe UI", size=10, italic=True, color="64748B")
                empty_cell.alignment = Alignment(horizontal="center", vertical="center")

            for col in ws_req.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                ws_req.column_dimensions[get_column_letter(col[0].column)].width = max(max_len + 3, 14)

            wb.save(file_path)
            logger.info("Generated screening report for batch #%d: %s", batch_id, file_path)
            return str(file_path)
