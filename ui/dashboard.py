"""Executive screening dashboard for TalentMatch AI.

Renders real-time platform telemetry, candidate pipeline distribution,
skill detection frequency analysis, requisition progress, and governance audit events.
"""

from collections import Counter
from datetime import datetime, timedelta
import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
import streamlit as st

from database.connection import get_session
from database.models import (
    Candidate,
    CandidateMatch,
    JobDescription,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)
from services.audit_service import AuditService
from ui.styles import render_badge, render_stat_card

logger = logging.getLogger(__name__)


def render_dashboard() -> None:
    """Render the TalentMatch AI Executive Screening Dashboard."""
    audit_service = AuditService()

    # =========================================================================
    # 1. HEADER & DATE FILTER
    # =========================================================================
    header_col, filter_col = st.columns([3, 1])

    with header_col:
        st.markdown(
            """
            <div style="margin-bottom: 0.5rem;">
                <h2 style="color: #1E3A8A; margin: 0 0 0.25rem 0; font-weight: 700;">Executive Screening Dashboard</h2>
                <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                    Platform-wide intelligence overview: candidate throughput, semantic match score distributions,
                    top detected competencies, and real-time recruitment audit trail.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with filter_col:
        time_filter = st.selectbox(
            "📅 Reporting Window",
            options=["All Time", "Today", "Last 7 Days", "Last 30 Days", "Last 90 Days"],
            index=0,
            key="dashboard_time_filter",
        )

    # Calculate cutoff datetime
    now = datetime.utcnow()
    cutoff_date: Optional[datetime] = None
    if time_filter == "Today":
        cutoff_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_filter == "Last 7 Days":
        cutoff_date = now - timedelta(days=7)
    elif time_filter == "Last 30 Days":
        cutoff_date = now - timedelta(days=30)
    elif time_filter == "Last 90 Days":
        cutoff_date = now - timedelta(days=90)

    # =========================================================================
    # 2. DATABASE METRICS QUERY
    # =========================================================================
    with get_session() as session:
        # JD metrics
        jd_base = select(JobDescription)
        if cutoff_date:
            jd_base = jd_base.where(JobDescription.created_at >= cutoff_date)

        total_jds = session.scalar(select(func.count()).select_from(jd_base.subquery())) or 0
        active_jds = session.scalar(
            select(func.count())
            .select_from(JobDescription)
            .where(JobDescription.status == "Active", *([JobDescription.created_at >= cutoff_date] if cutoff_date else []))
        ) or 0
        inactive_jds = total_jds - active_jds

        # Candidate metrics
        cand_base = select(Candidate)
        if cutoff_date:
            cand_base = cand_base.where(Candidate.created_at >= cutoff_date)

        total_candidates = session.scalar(select(func.count()).select_from(cand_base.subquery())) or 0
        parsed_candidates = session.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.parsing_status == "parsed", *([Candidate.created_at >= cutoff_date] if cutoff_date else []))
        ) or 0
        failed_candidates = session.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.parsing_status == "failed", *([Candidate.created_at >= cutoff_date] if cutoff_date else []))
        ) or 0
        warning_candidates = session.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.parsing_status == "warning", *([Candidate.created_at >= cutoff_date] if cutoff_date else []))
        ) or 0

        # Screening runs and matches
        run_base = select(ScreeningRun)
        if cutoff_date:
            run_base = run_base.where(ScreeningRun.started_at >= cutoff_date)
        total_runs = session.scalar(select(func.count()).select_from(run_base.subquery())) or 0

        match_base = select(CandidateMatch)
        if cutoff_date:
            match_base = match_base.where(CandidateMatch.last_screened_at >= cutoff_date)
        total_matches = session.scalar(select(func.count()).select_from(match_base.subquery())) or 0

        pending_reviews = session.scalar(
            select(func.count())
            .select_from(CandidateMatch)
            .where(CandidateMatch.human_review_status == "pending", *([CandidateMatch.last_screened_at >= cutoff_date] if cutoff_date else []))
        ) or 0

        # Match Scores for distribution
        match_scores_stmt = select(CandidateMatch.match_score)
        if cutoff_date:
            match_scores_stmt = match_scores_stmt.where(CandidateMatch.last_screened_at >= cutoff_date)
        match_scores = [float(s) for s in session.scalars(match_scores_stmt).all() if s is not None]

        # Candidate skills
        skills_stmt = select(Candidate.skills_json)
        if cutoff_date:
            skills_stmt = skills_stmt.where(Candidate.created_at >= cutoff_date)
        skills_raw = session.scalars(skills_stmt).all()

        # Shortlists per JD
        sl_stmt = (
            select(
                JobDescription.title,
                func.count(Shortlist.id.distinct()).label("shortlist_count"),
                func.count(ShortlistCandidate.id).label("candidate_count"),
            )
            .select_from(JobDescription)
            .outerjoin(Shortlist, Shortlist.jd_id == JobDescription.id)
            .outerjoin(ShortlistCandidate, ShortlistCandidate.shortlist_id == Shortlist.id)
            .group_by(JobDescription.id, JobDescription.title)
            .order_by(func.count(ShortlistCandidate.id).desc())
            .limit(10)
        )
        shortlist_distribution = session.execute(sl_stmt).all()

    # =========================================================================
    # 3. METRIC CARDS ROW (Bootstrap 5 Styled KPI Cards)
    # =========================================================================
    st.markdown("<div style='margin-top: 0.35rem;'></div>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.markdown(
            render_stat_card(
                title="Job Requisitions",
                value=total_jds,
                icon_class="bi bi-briefcase-fill",
                subtitle=f'<span style="color: #15803D; font-weight:600;"><i class="bi bi-circle-fill" style="font-size:0.5rem;"></i> {active_jds} Active</span> &nbsp;•&nbsp; {inactive_jds} Other',
                color_scheme="blue",
            ),
            unsafe_allow_html=True,
        )

    with m2:
        st.markdown(
            render_stat_card(
                title="Candidate Pool",
                value=total_candidates,
                icon_class="bi bi-people-fill",
                subtitle=f'<span style="color: #15803D; font-weight:600;"><i class="bi bi-check-lg"></i> {parsed_candidates} Parsed</span> &nbsp;•&nbsp; <span style="color: #DC2626;">{failed_candidates} Failed</span>',
                color_scheme="indigo",
            ),
            unsafe_allow_html=True,
        )

    with m3:
        st.markdown(
            render_stat_card(
                title="Screening Matches",
                value=total_matches,
                icon_class="bi bi-lightning-charge-fill",
                subtitle=f"Across {total_runs} batch run(s)",
                color_scheme="green",
            ),
            unsafe_allow_html=True,
        )

    with m4:
        p_color = "amber" if pending_reviews > 0 else "blue"
        p_icon = "bi bi-clock-history" if pending_reviews > 0 else "bi bi-check2-all"
        p_sub = f'<span style="color: {"#B45309" if pending_reviews > 0 else "#64748B"}; font-weight: 600;">{pending_reviews} Awaiting Review</span>'
        st.markdown(
            render_stat_card(
                title="Human Reviews",
                value=pending_reviews,
                icon_class=p_icon,
                subtitle=p_sub,
                color_scheme=p_color,
            ),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # EMPTY STATE CHECK (Zero data in database)
    # =========================================================================
    if total_jds == 0 and total_candidates == 0:
        st.markdown(
            """
            <div style="text-align: center; padding: 3rem 1.5rem; background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 12px; margin: 1rem 0 2rem 0;">
                <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🎯</div>
                <h3 style="color: #1E3A8A; margin: 0 0 0.5rem 0;">Welcome to TalentMatch AI</h3>
                <p style="color: #64748B; max-width: 620px; margin: 0 auto 1.5rem auto; line-height: 1.6;">
                    Your talent intelligence workspace is ready. To get started, create your first Job Description requisition,
                    upload candidate resumes, and trigger automated AI-powered screening.
                </p>
                <div style="display: flex; justify-content: center; gap: 1rem;">
                    <span style="background-color: #DBEAFE; color: #1E40AF; padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 0.9rem;">
                        1. Job Descriptions ➔ Add Requisition
                    </span>
                    <span style="background-color: #DCFCE7; color: #15803D; padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 0.9rem;">
                        2. Resume Upload ➔ Ingest Resumes
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # =========================================================================
    # 4. TWO-COLUMN LAYOUT: CHARTS & INTELLIGENCE
    # =========================================================================
    col_left, col_right = st.columns(2)

    # -------------------------------------------------------------------------
    # LEFT COLUMN: Match Score Distribution & Shortlists per JD
    # -------------------------------------------------------------------------
    with col_left:
        st.markdown("#### 📊 Match Score Distribution")
        if match_scores:
            bands = {
                "90-100% (Exceptional)": sum(1 for s in match_scores if s >= 90.0),
                "80-89% (Strong)": sum(1 for s in match_scores if 80.0 <= s < 90.0),
                "60-79% (Potential)": sum(1 for s in match_scores if 60.0 <= s < 80.0),
                "40-59% (Needs Review)": sum(1 for s in match_scores if 40.0 <= s < 60.0),
                "< 40% (Insufficient)": sum(1 for s in match_scores if s < 40.0),
            }
            df_dist = pd.DataFrame(list(bands.items()), columns=["Score Band", "Candidate Count"]).set_index("Score Band")
            st.bar_chart(df_dist, color="#1E40AF", use_container_width=True)
            st.caption(f"Based on {len(match_scores)} evaluated candidate matches.")
        else:
            st.info("No candidate matches evaluated yet. Run screening to generate score distributions.")

        st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("#### 📑 Shortlists & Requisition Pipeline")

        active_shortlist_rows = [r for r in shortlist_distribution if r.shortlist_count > 0 or r.candidate_count > 0]
        if active_shortlist_rows:
            sl_table = []
            for row in active_shortlist_rows:
                sl_table.append({
                    "Requisition": row.title,
                    "Shortlists": row.shortlist_count,
                    "Shortlisted Candidates": row.candidate_count,
                })
            st.dataframe(
                sl_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Requisition": st.column_config.TextColumn("Requisition", width="large"),
                    "Shortlists": st.column_config.NumberColumn("Shortlists", width="small"),
                    "Shortlisted Candidates": st.column_config.NumberColumn("Candidates", width="medium"),
                },
            )
        else:
            st.info("No active shortlists created. Navigate to Shortlists & Export to create your first pipeline.")

    # -------------------------------------------------------------------------
    # RIGHT COLUMN: Top Skills Detected & Recent Activity
    # -------------------------------------------------------------------------
    with col_right:
        st.markdown("#### 🏷️ Top 10 Detected Candidate Skills")
        skill_counter: Counter = Counter()
        for raw in skills_raw:
            if raw:
                try:
                    s_list = json.loads(raw)
                    if isinstance(s_list, list):
                        for s in s_list:
                            if s and isinstance(s, str) and s.strip():
                                skill_counter[s.strip().title()] += 1
                except Exception:
                    pass

        top_skills = skill_counter.most_common(10)
        if top_skills:
            df_skills = pd.DataFrame(top_skills, columns=["Skill", "Candidates"]).set_index("Skill")
            st.bar_chart(df_skills, color="#3B82F6", use_container_width=True)
            st.caption(f"Recognized across {total_candidates} ingested candidates.")
        else:
            st.info("No extracted skills detected yet. Upload resumes to populate technical skill analytics.")

        st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("#### ⏱️ Recent Platform Activity")

        recent_events = audit_service.get_recent_activity(limit=7)
        if recent_events:
            for ev in recent_events:
                st.markdown(
                    f"""
                    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-left: 3px solid #3B82F6; border-radius: 6px; padding: 0.55rem 0.85rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-size: 1rem; margin-right: 0.35rem;">{ev['icon']}</span>
                            <span style="color: #0F172A; font-size: 0.88rem; font-weight: 500;">{ev['summary']}</span>
                        </div>
                        <div style="color: #94A3B8; font-size: 0.78rem; white-space: nowrap; margin-left: 0.75rem;">
                            {ev['time_ago']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("No recorded activity logs yet.")
