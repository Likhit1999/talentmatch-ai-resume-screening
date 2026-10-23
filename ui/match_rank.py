"""Streamlit UI component for candidate matching, scoring, and ranking in TalentMatch AI.

Provides job description selection, candidate targeting, configurable scoring weights,
real-time batch screening, interactive ranking table, detailed requirement evidence cards,
recruiter review overrides, side-by-side comparisons, and shortlist/CSV/Excel exports.
"""

from datetime import datetime
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
import streamlit as st

from config.settings import get_settings
from database.connection import get_session
from database.models import (
    Candidate,
    CandidateMatch,
    JobDescription,
    Shortlist,
    ShortlistCandidate,
)
from services.candidate_service import CandidateService
from services.jd_service import JDService
from services.matching_service import MatchingService
from services.scoring_service import ScoringService
from services.whatsapp_service import WhatsAppService
from ui.styles import get_custom_css

logger = logging.getLogger(__name__)


def _render_score_badge(score: float) -> str:
    """Format and color-code screening match scores with custom badges."""
    if score >= 70.0:
        bg, fg, border = "#dcfce7", "#15803d", "#86efac"
    elif score >= 50.0:
        bg, fg, border = "#fef3c7", "#92400e", "#fcd34d"
    elif score >= 30.0:
        bg, fg, border = "#ffedd5", "#c2410c", "#fdba74"
    else:
        bg, fg, border = "#fee2e2", "#991b1b", "#fca5a5"
    return (
        f"<span style='background-color: {bg}; color: {fg}; border: 1px solid {border}; "
        f"padding: 3px 9px; border-radius: 9999px; font-weight: 700; font-size: 0.85rem; display: inline-block;'>"
        f"{score:.1f}%</span>"
    )


def _render_category_badge(category: str) -> str:
    """Format match categories with distinctive colored badges."""
    cat_clean = (category or "").lower()
    if cat_clean == "strong_match":
        return "<span style='background-color: #dcfce7; color: #15803d; border: 1px solid #86efac; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.8rem;'>🌟 Strong Match</span>"
    elif cat_clean == "potential_match":
        return "<span style='background-color: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.8rem;'>⚡ Potential Match</span>"
    elif cat_clean == "needs_review":
        return "<span style='background-color: #fef3c7; color: #92400e; border: 1px solid #fcd34d; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.8rem;'>⚠️ Needs Review</span>"
    else:
        return "<span style='background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.8rem;'>❌ Insufficient Evidence</span>"


def _render_review_status_badge(status: str) -> str:
    """Format recruiter review status badges."""
    st_clean = (status or "pending").lower()
    if st_clean == "shortlisted":
        return "<span style='background-color: #dcfce7; color: #15803d; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.78rem;'>Shortlisted</span>"
    elif st_clean == "reviewed":
        return "<span style='background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.78rem;'>Reviewed</span>"
    elif st_clean == "on_hold":
        return "<span style='background-color: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.78rem;'>On Hold</span>"
    elif st_clean == "not_selected":
        return "<span style='background-color: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.78rem;'>Not Selected</span>"
    else:
        return "<span style='background-color: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.78rem;'>Pending Review</span>"


def render_match_rank() -> None:
    """Render the Screening, Matching, and Ranking workspace for recruiters."""
    st.markdown(get_custom_css(), unsafe_allow_html=True)
    settings = get_settings()
    jd_service = JDService()
    cand_service = CandidateService()
    matching_service = MatchingService()
    scoring_service = ScoringService()

    # Session State Initialization
    if "mr_selected_jd_id" not in st.session_state:
        st.session_state["mr_selected_jd_id"] = None
    if "mr_include_inactive" not in st.session_state:
        st.session_state["mr_include_inactive"] = False
    if "mr_cand_mode" not in st.session_state:
        st.session_state["mr_cand_mode"] = "All Candidates"
    if "mr_selected_batch" not in st.session_state:
        st.session_state["mr_selected_batch"] = "All"
    if "mr_selected_cand_ids" not in st.session_state:
        st.session_state["mr_selected_cand_ids"] = []
    if "mr_method" not in st.session_state:
        st.session_state["mr_method"] = "Rule-based (Heuristic & Taxonomy)"
    if "mr_w_mand" not in st.session_state:
        st.session_state["mr_w_mand"] = 50
    if "mr_w_exp" not in st.session_state:
        st.session_state["mr_w_exp"] = 20
    if "mr_w_pref" not in st.session_state:
        st.session_state["mr_w_pref"] = 15
    if "mr_w_dom" not in st.session_state:
        st.session_state["mr_w_dom"] = 10
    if "mr_w_qual" not in st.session_state:
        st.session_state["mr_w_qual"] = 5
    if "mr_page" not in st.session_state:
        st.session_state["mr_page"] = 1
    if "mr_filter_category" not in st.session_state:
        st.session_state["mr_filter_category"] = "All"
    if "mr_filter_review" not in st.session_state:
        st.session_state["mr_filter_review"] = "All"
    if "mr_filter_min_score" not in st.session_state:
        st.session_state["mr_filter_min_score"] = 0
    if "mr_filter_search" not in st.session_state:
        st.session_state["mr_filter_search"] = ""
    if "mr_inspect_match_id" not in st.session_state:
        st.session_state["mr_inspect_match_id"] = None
    if "mr_compare_match_ids" not in st.session_state:
        st.session_state["mr_compare_match_ids"] = []
    if "mr_screening_active" not in st.session_state:
        st.session_state["mr_screening_active"] = False

    # Top Header
    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h2 style="color: #1e3a5f; margin: 0 0 0.35rem 0; font-weight: 700;">
                🎯 Screening, Matching & Candidate Ranking
            </h2>
            <p style="color: #64748b; margin: 0; font-size: 0.95rem;">
                Evaluate candidate resumes against atomic job description requirements with transparent,
                configurable scoring, verified evidence quotes, and recruiter review workflows.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # =========================================================================
    # 1. JOB DESCRIPTION SELECTION
    # =========================================================================
    st.markdown("### 1. Select Target Job Requisition")

    # Fetch available JDs
    all_jds, _ = jd_service.get_all_jds(limit=200)
    if not st.session_state["mr_include_inactive"]:
        all_jds = [j for j in all_jds if j.status in ("Open", "In Progress", "Active")]

    if not all_jds:
        st.warning(
            "⚠️ No open job requisitions found. Please create an open Job Description in **Job Descriptions** first."
        )
        return

    col_jd_sel, col_jd_opt = st.columns([3, 1])
    with col_jd_opt:
        st.markdown("<div style='height: 1.8rem;'></div>", unsafe_allow_html=True)
        include_inactive = st.checkbox(
            "Include Closed / Draft JDs",
            value=st.session_state["mr_include_inactive"],
            key="cb_include_inactive",
        )
        if include_inactive != st.session_state["mr_include_inactive"]:
            st.session_state["mr_include_inactive"] = include_inactive
            st.rerun()

    jd_options = {jd.id: f"#{jd.id} - {jd.title} ({jd.department or 'General'})" for jd in all_jds}
    default_jd_id = st.session_state["mr_selected_jd_id"]
    if default_jd_id not in jd_options:
        default_jd_id = all_jds[0].id
        st.session_state["mr_selected_jd_id"] = default_jd_id

    with col_jd_sel:
        selected_jd_id = st.selectbox(
            "Target Job Description:",
            options=list(jd_options.keys()),
            format_func=lambda x: jd_options.get(x, f"JD #{x}"),
            index=list(jd_options.keys()).index(default_jd_id),
            key="sb_target_jd",
        )
        if selected_jd_id != st.session_state["mr_selected_jd_id"]:
            st.session_state["mr_selected_jd_id"] = selected_jd_id
            st.session_state["mr_inspect_match_id"] = None
            st.session_state["mr_compare_match_ids"] = []
            st.session_state["mr_page"] = 1
            st.rerun()

    # Display selected JD Summary Card
    selected_jd = next((j for j in all_jds if j.id == selected_jd_id), None)
    if selected_jd:
        reqs = jd_service.get_jd_requirements(selected_jd.id, enabled_only=True)
        mand_count = sum(1 for r in reqs if r.importance == "mandatory" or r.category == "mandatory_skill")
        pref_count = sum(1 for r in reqs if r.importance == "preferred" or r.category == "preferred_skill")
        exp_range = "Any"
        if selected_jd.experience_min is not None and selected_jd.experience_max is not None:
            exp_range = f"{selected_jd.experience_min:.0f} - {selected_jd.experience_max:.0f} yrs"
        elif selected_jd.experience_min is not None:
            exp_range = f"≥ {selected_jd.experience_min:.0f} yrs"

        st.markdown(
            f"""
            <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-left: 5px solid #1e3a5f;
                        border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
                    <div>
                        <span style="font-weight: 700; font-size: 1.15rem; color: #1e3a5f;">{selected_jd.title}</span>
                        <span style="color: #64748b; font-size: 0.9rem; margin-left: 0.75rem;">Department: <strong>{selected_jd.department or 'N/A'}</strong></span>
                        <span style="color: #64748b; font-size: 0.9rem; margin-left: 0.75rem;">Status: <span style="font-weight: 600; color: #15803d;">{selected_jd.status}</span></span>
                    </div>
                    <div style="display: flex; gap: 1rem; align-items: center;">
                        <span style="background-color: #dbeafe; color: #1e40af; padding: 3px 10px; border-radius: 6px; font-size: 0.82rem; font-weight: 600;">
                            Mandatory: {mand_count}
                        </span>
                        <span style="background-color: #f1f5f9; color: #334155; padding: 3px 10px; border-radius: 6px; font-size: 0.82rem; font-weight: 600;">
                            Preferred: {pref_count}
                        </span>
                        <span style="background-color: #fef3c7; color: #92400e; padding: 3px 10px; border-radius: 6px; font-size: 0.82rem; font-weight: 600;">
                            Exp: {exp_range}
                        </span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # =========================================================================
    # 2. CANDIDATE SELECTION
    # =========================================================================
    st.markdown("### 2. Target Candidates for Evaluation")

    c_mode_col1, c_mode_col2 = st.columns([1.2, 1.8])
    with c_mode_col1:
        cand_scope_options = ["All Candidates", "By Role / Category Tag", "Specific Batch", "Select Candidates"]
        cur_mode = st.session_state["mr_cand_mode"]
        mode_idx = cand_scope_options.index(cur_mode) if cur_mode in cand_scope_options else 0
        cand_mode = st.radio(
            "Evaluation Scope:",
            options=cand_scope_options,
            index=mode_idx,
            key="rb_cand_mode",
            help="Filter candidate pool by target role (e.g. only QA profiles for QA positions) to avoid screening irrelevant resumes.",
        )
        st.session_state["mr_cand_mode"] = cand_mode

    target_candidate_ids: List[int] = []

    with c_mode_col2:
        if cand_mode == "All Candidates":
            with get_session() as session:
                all_cands = session.scalars(select(Candidate).order_by(Candidate.id.asc())).all()
                target_candidate_ids = [c.id for c in all_cands]
            st.info(f"👥 Ready to evaluate all **{len(target_candidate_ids)}** candidate profile(s) in the database.")

        elif cand_mode == "By Role / Category Tag":
            with get_session() as session:
                stmt_roles = select(Candidate.job_category).distinct().where(Candidate.job_category.isnot(None))
                roles = [r for r in session.scalars(stmt_roles).all() if r and r.strip()]
            if roles:
                sel_role = st.selectbox("Select Target Role Tag:", options=roles, key="sb_target_role")
                with get_session() as session:
                    role_cands = session.scalars(
                        select(Candidate.id).where(Candidate.job_category == sel_role)
                    ).all()
                    target_candidate_ids = list(role_cands)
                st.success(f"🎯 Role tag `{sel_role}` selected — screening **{len(target_candidate_ids)}** relevant candidate(s). Unrelated profiles excluded.")
            else:
                st.info("No role tags found. Upload resumes with a role tag (e.g., 'QA Engineer') to use this filter.")

        elif cand_mode == "Specific Batch":
            with get_session() as session:
                stmt_batches = select(Candidate.upload_batch_id).distinct().where(Candidate.upload_batch_id.isnot(None))
                batches = [b for b in session.scalars(stmt_batches).all() if b]
            if batches:
                sel_batch = st.selectbox("Select Upload Batch:", options=batches, key="sb_target_batch")
                st.session_state["mr_selected_batch"] = sel_batch
                with get_session() as session:
                    batch_cands = session.scalars(
                        select(Candidate.id).where(Candidate.upload_batch_id == sel_batch)
                    ).all()
                    target_candidate_ids = list(batch_cands)
                st.info(f"📦 Batch `{sel_batch}` contains **{len(target_candidate_ids)}** candidate(s).")
            else:
                st.warning("No upload batches found.")

        elif cand_mode == "Select Candidates":
            with get_session() as session:
                candidates_list = session.scalars(select(Candidate).order_by(Candidate.name.asc())).all()
                cand_map = {c.id: f"{c.name} ({c.email or 'No email'})" for c in candidates_list}

            sel_cands = st.multiselect(
                "Choose Specific Candidates:",
                options=list(cand_map.keys()),
                format_func=lambda x: cand_map.get(x, f"Candidate #{x}"),
                default=st.session_state["mr_selected_cand_ids"],
                key="ms_target_cands",
            )
            st.session_state["mr_selected_cand_ids"] = sel_cands
            target_candidate_ids = sel_cands
            st.info(f"🎯 Selected **{len(target_candidate_ids)}** candidate(s).")

    # =========================================================================
    # 3. MATCHING CONFIGURATION & WEIGHT TUNING
    # =========================================================================
    st.markdown("### 3. Matching Configuration & Component Weights")

    with st.expander("⚙️ Customize Scoring Weights & AI Method", expanded=False):
        cfg_col1, cfg_col2 = st.columns([1, 2])

        with cfg_col1:
            if settings.is_ai_available:
                method_opts = ["AI-Assisted (Semantic & LLM)", "Rule-based (Heuristic & Taxonomy)"]
            else:
                method_opts = ["Rule-based (Heuristic & Taxonomy)"]

            default_idx = 0
            if "mr_method" in st.session_state and st.session_state["mr_method"] in method_opts:
                default_idx = method_opts.index(st.session_state["mr_method"])

            screening_method = st.radio(
                "Screening Algorithm:",
                options=method_opts,
                index=default_idx,
                key="rb_method_selector",
            )
            st.session_state["mr_method"] = screening_method

            if settings.is_ai_available:
                st.caption(f"✨ *Using Google Gemini (`{settings.get_model()}`) for semantic screening.*")
            else:
                st.caption("ℹ️ *AI-Assisted screening requires Gemini API key in configuration.*")

        with cfg_col2:
            st.markdown("**Scoring Weights Allocation:**")
            w1 = st.slider("Mandatory Skills Weight (%)", 0, 100, st.session_state["mr_w_mand"], step=5, key="sl_mand")
            w2 = st.slider("Experience Duration & Scope (%)", 0, 100, st.session_state["mr_w_exp"], step=5, key="sl_exp")
            w3 = st.slider("Preferred Skills Weight (%)", 0, 100, st.session_state["mr_w_pref"], step=5, key="sl_pref")
            w4 = st.slider("Domain & Responsibilities (%)", 0, 100, st.session_state["mr_w_dom"], step=5, key="sl_dom")
            w5 = st.slider("Qualifications & Certifications (%)", 0, 100, st.session_state["mr_w_qual"], step=5, key="sl_qual")

            st.session_state["mr_w_mand"] = w1
            st.session_state["mr_w_exp"] = w2
            st.session_state["mr_w_pref"] = w3
            st.session_state["mr_w_dom"] = w4
            st.session_state["mr_w_qual"] = w5

            weight_total = w1 + w2 + w3 + w4 + w5
            if weight_total == 100:
                st.markdown(f"<span style='color: #15803d; font-weight: 700;'>✅ Total Weight: {weight_total}% (Balanced)</span>", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<span style='color: #b45309; font-weight: 700;'>⚠️ Total Weight: {weight_total}% (Will be auto-normalized to 100% during execution)</span>",
                    unsafe_allow_html=True,
                )

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("⚡ Auto-Normalize to 100%", use_container_width=True):
                    normalized = scoring_service.validate_weights({
                        "mandatory_skills": w1,
                        "experience": w2,
                        "preferred_skills": w3,
                        "domain_responsibilities": w4,
                        "qualifications_certifications": w5,
                    })
                    st.session_state["mr_w_mand"] = int(round(normalized["mandatory_skills"]))
                    st.session_state["mr_w_exp"] = int(round(normalized["experience"]))
                    st.session_state["mr_w_pref"] = int(round(normalized["preferred_skills"]))
                    st.session_state["mr_w_dom"] = int(round(normalized["domain_responsibilities"]))
                    st.session_state["mr_w_qual"] = int(round(normalized["qualifications_certifications"]))
                    st.rerun()

            with btn_col2:
                if st.button("🔄 Reset to Defaults", use_container_width=True):
                    st.session_state["mr_w_mand"] = 50
                    st.session_state["mr_w_exp"] = 20
                    st.session_state["mr_w_pref"] = 15
                    st.session_state["mr_w_dom"] = 10
                    st.session_state["mr_w_qual"] = 5
                    st.rerun()

    active_weights = {
        "mandatory_skills": float(st.session_state["mr_w_mand"]),
        "experience": float(st.session_state["mr_w_exp"]),
        "preferred_skills": float(st.session_state["mr_w_pref"]),
        "domain_responsibilities": float(st.session_state["mr_w_dom"]),
        "qualifications_certifications": float(st.session_state["mr_w_qual"]),
    }

    # =========================================================================
    # 4. RUN SCREENING BUTTON & PROGRESS EXECUTION
    # =========================================================================
    run_col1, run_col2 = st.columns([1.5, 3])
    with run_col1:
        start_screening = st.button(
            "🚀 Start Screening Run",
            type="primary",
            use_container_width=True,
            disabled=len(target_candidate_ids) == 0,
        )
    with run_col2:
        is_ai_mode = "AI-Assisted" in st.session_state.get("mr_method", "")
        if is_ai_mode:
            st.markdown(
                f"<div style='padding-top: 0.45rem;'><span style='background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; padding: 0.35rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.85rem;'>⚡ AI Engine Active: Google Gemini ({settings.get_model()})</span></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='padding-top: 0.45rem;'><span style='background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 0.35rem 0.75rem; border-radius: 9999px; font-weight: 600; font-size: 0.85rem;'>⚙️ Rule-Based Engine Active</span></div>",
                unsafe_allow_html=True,
            )

    if start_screening:
        if not target_candidate_ids:
            st.error("No candidates selected for screening.")
        else:
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            total_items = len(target_candidate_ids)

            def update_progress(current: int, total: int, msg: str):
                ratio = min(1.0, current / max(1, total))
                progress_bar.progress(ratio)
                status_text.text(f"Processing ({current}/{total}): {msg}")

            start_time = datetime.now()
            batch_result = matching_service.run_batch_matching(
                jd_ids=[selected_jd_id],
                candidate_ids=target_candidate_ids,
                method="rule_based" if "Rule-based" in st.session_state["mr_method"] else "ai_assisted",
                weights=active_weights,
                progress_callback=update_progress,
            )
            elapsed = (datetime.now() - start_time).total_seconds()

            progress_bar.progress(1.0)
            status_text.empty()
            st.success(
                f"🎉 Screening completed! Processed **{batch_result['completed']}** candidate(s) "
                f"in **{elapsed:.1f}s** (Failed: {batch_result['failed']})."
            )
            st.session_state["mr_page"] = 1
            st.rerun()

    # =========================================================================
    # 5. SUMMARY METRICS FOR SELECTED JD
    # =========================================================================
    with get_session() as session:
        all_matches_for_jd = (
            session.scalars(
                select(CandidateMatch).where(CandidateMatch.jd_id == selected_jd_id)
            ).all()
        )
        total_eval_count = len(all_matches_for_jd)
        strong_count = sum(1 for m in all_matches_for_jd if m.match_category == "strong_match")
        potential_count = sum(1 for m in all_matches_for_jd if m.match_category == "potential_match")
        review_count = sum(1 for m in all_matches_for_jd if m.match_category == "needs_review")
        insufficient_count = sum(1 for m in all_matches_for_jd if m.match_category == "insufficient_evidence")

    st.markdown("---")
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Total Screened", total_eval_count)
    with m2:
        st.metric("🌟 Strong Matches", strong_count)
    with m3:
        st.metric("⚡ Potential", potential_count)
    with m4:
        st.metric("⚠️ Needs Review", review_count)
    with m5:
        st.metric("❌ Insufficient", insufficient_count)

    if total_eval_count == 0:
        st.markdown(
            """
            <div style="text-align: center; padding: 2.5rem; background-color: #ffffff; border: 2px dashed #cbd5e1; border-radius: 8px; margin: 1rem 0;">
                <div style="font-size: 2.5rem;">🔍</div>
                <h3 style="color: #1e3a5f; margin: 0.5rem 0;">No Screening Results Available Yet</h3>
                <p style="color: #64748b; font-size: 0.95rem;">
                    Click <strong>'Start Screening Run'</strong> above to match candidates against this requisition.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # =========================================================================
    # 6. FILTERS & SEARCH BAR
    # =========================================================================
    st.markdown("### 4. Candidate Screening Rankings")

    f_col1, f_col2, f_col3, f_col4 = st.columns([2, 1.5, 1.5, 2])
    with f_col1:
        search_query = st.text_input(
            "Search Name / Email / Skills:",
            value=st.session_state["mr_filter_search"],
            placeholder="e.g. Alice, Python, AWS...",
            key="ti_filter_search",
        )
        st.session_state["mr_filter_search"] = search_query

    with f_col2:
        cat_filter = st.selectbox(
            "Category Filter:",
            options=["All", "strong_match", "potential_match", "needs_review", "insufficient_evidence"],
            index=["All", "strong_match", "potential_match", "needs_review", "insufficient_evidence"].index(
                st.session_state["mr_filter_category"]
            ),
            key="sb_filter_cat",
        )
        st.session_state["mr_filter_category"] = cat_filter

    with f_col3:
        rev_filter = st.selectbox(
            "Review Status:",
            options=["All", "pending", "reviewed", "shortlisted", "on_hold", "not_selected"],
            index=["All", "pending", "reviewed", "shortlisted", "on_hold", "not_selected"].index(
                st.session_state["mr_filter_review"]
            ),
            key="sb_filter_rev",
        )
        st.session_state["mr_filter_review"] = rev_filter

    with f_col4:
        min_score = st.slider(
            "Minimum Score:",
            0,
            100,
            st.session_state["mr_filter_min_score"],
            step=5,
            key="sl_filter_min_score",
        )
        st.session_state["mr_filter_min_score"] = min_score

    # Fetch paginated results
    page_size = 10
    current_page = st.session_state["mr_page"]
    offset = (current_page - 1) * page_size

    matches, total_filtered = matching_service.get_match_results(
        jd_id=selected_jd_id,
        filters={
            "search": search_query,
            "category": cat_filter,
            "human_review_status": rev_filter,
            "min_score": min_score,
        },
        offset=offset,
        limit=page_size,
    )

    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    if current_page > total_pages:
        st.session_state["mr_page"] = 1
        current_page = 1

    # =========================================================================
    # 7. RESULTS TABLE
    # =========================================================================
    st.markdown(
        f"<div style='margin-bottom: 0.5rem; color: #475569; font-size: 0.9rem;'>Showing <strong>{len(matches)}</strong> of <strong>{total_filtered}</strong> evaluated candidate(s) (Page {current_page} of {total_pages})</div>",
        unsafe_allow_html=True,
    )

    # Multi-select comparison picker
    compare_options = {m["id"]: f"#{m['id']} {m['candidate_name']} ({m['match_score']:.1f}%)" for m in matches}
    st.session_state["mr_compare_match_ids"] = st.multiselect(
        "⚖️ Select 2 or 3 candidates for side-by-side comparison:",
        options=list(compare_options.keys()),
        format_func=lambda x: compare_options.get(x, f"Match #{x}"),
        default=[m_id for m_id in st.session_state["mr_compare_match_ids"] if m_id in compare_options],
        key="ms_compare_candidates",
    )

    # Render candidate ranking cards/table
    for rank_idx, match in enumerate(matches, start=offset + 1):
        m_id = match["id"]
        cand_name = match["candidate_name"]
        cand_email = match["candidate_email"] or "No email"
        score = match["match_score"]
        category = match["match_category"]
        m_met = match["mandatory_met"]
        m_total = match["mandatory_total"]
        m_missing = match["mandatory_missing"]
        p_met = match["preferred_met"]
        p_total = match["preferred_total"]
        exp_score = match["experience_score"]
        rev_status = match["human_review_status"]

        # Color-coded left border based on category
        border_color = (
            "#15803d"
            if category == "strong_match"
            else ("#2563eb" if category == "potential_match" else ("#b45309" if category == "needs_review" else "#991b1b"))
        )

        missing_pills = (
            " ".join([f"<span style='background-color: #fee2e2; color: #991b1b; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem;'>{sk}</span>" for sk in m_missing[:3]])
            if m_missing
            else "<span style='color: #15803d; font-size: 0.8rem; font-weight: 600;'>None</span>"
        )

        with st.container():
            st.markdown(
                f"""
                <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-left: 6px solid {border_color};
                            border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 0.75rem; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.5rem;">
                        <div style="flex: 2; min-width: 250px;">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span style="font-weight: 700; color: #64748b; font-size: 1rem;">#{rank_idx}</span>
                                <span style="font-weight: 700; color: #1e3a5f; font-size: 1.15rem;">{cand_name}</span>
                                {_render_category_badge(category)}
                                {_render_review_status_badge(rev_status)}
                            </div>
                            <div style="color: #64748b; font-size: 0.85rem; margin-top: 0.25rem;">
                                📧 {cand_email} | 📄 Resume: <code>{match['candidate_resume_filename']}</code>
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 1.5rem; text-align: right;">
                            <div>
                                <div style="font-size: 0.75rem; text-transform: uppercase; color: #64748b; font-weight: 600;">Match Score</div>
                                <div>{_render_score_badge(score)}</div>
                            </div>
                            <div>
                                <div style="font-size: 0.75rem; text-transform: uppercase; color: #64748b; font-weight: 600;">Mandatory Met</div>
                                <div style="font-weight: 700; color: {'#15803d' if m_met == m_total else '#b45309'}; font-size: 1.05rem;">
                                    {m_met} / {m_total}
                                </div>
                            </div>
                            <div>
                                <div style="font-size: 0.75rem; text-transform: uppercase; color: #64748b; font-weight: 600;">Preferred Met</div>
                                <div style="font-weight: 700; color: #1e40af; font-size: 1.05rem;">
                                    {p_met} / {p_total}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div style="margin-top: 0.65rem; padding-top: 0.5rem; border-top: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; color: #475569;">
                        <div>
                            <strong>Missing Mandatory:</strong> {missing_pills}
                        </div>
                        <div>
                            <strong>Experience Match:</strong> {exp_score:.0f}%
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Action row
            act_col1, act_col2, act_col3 = st.columns([1, 1, 4])
            with act_col1:
                is_inspecting = st.session_state["mr_inspect_match_id"] == m_id
                btn_label = "Hide Details" if is_inspecting else "🔍 View Evidence"
                if st.button(btn_label, key=f"btn_inspect_{m_id}", use_container_width=True):
                    st.session_state["mr_inspect_match_id"] = None if is_inspecting else m_id
                    st.rerun()

            with act_col2:
                if rev_status != "shortlisted":
                    if st.button("⭐ Shortlist", key=f"btn_short_{m_id}", use_container_width=True):
                        matching_service.update_review_status(m_id, status="shortlisted", reviewer="Recruiter")
                        st.success(f"{cand_name} added to shortlist!")
                        st.rerun()

            # Expandable Inspection View
            if st.session_state["mr_inspect_match_id"] == m_id:
                _render_match_detail(m_id, matching_service)

    # Pagination controls
    p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
    with p_col1:
        if current_page > 1:
            if st.button("⬅️ Previous Page", key="btn_prev_page", use_container_width=True):
                st.session_state["mr_page"] -= 1
                st.rerun()
    with p_col2:
        st.markdown(
            f"<div style='text-align: center; color: #64748b; padding-top: 0.5rem;'>Page <strong>{current_page}</strong> of <strong>{total_pages}</strong></div>",
            unsafe_allow_html=True,
        )
    with p_col3:
        if current_page < total_pages:
            if st.button("Next Page ➡️", key="btn_next_page", use_container_width=True):
                st.session_state["mr_page"] += 1
                st.rerun()

    # =========================================================================
    # 8. SIDE-BY-SIDE CANDIDATE COMPARISON
    # =========================================================================
    sel_compare_ids = st.session_state["mr_compare_match_ids"]
    if 2 <= len(sel_compare_ids) <= 3:
        st.markdown("---")
        _render_candidate_comparison(sel_compare_ids, matching_service)

    # =========================================================================
    # 9. BATCH ACTIONS & EXPORT HUB
    # =========================================================================
    st.markdown("---")
    st.markdown("### 5. Shortlist & Export Actions")

    b_col1, b_col2 = st.columns(2)

    with b_col1:
        with st.expander("📑 Create Shortlist from Results", expanded=False):
            shortlist_name = st.text_input(
                "Shortlist Name:",
                value=f"{selected_jd.title} - Shortlist {datetime.now().strftime('%b %d')}",
                key="ti_shortlist_name",
            )
            shortlist_desc = st.text_area("Description (optional):", key="ta_shortlist_desc")
            filter_mode = st.radio(
                "Candidates to Include:",
                options=["All Screened Candidates", "Strong Matches Only", "Shortlisted Status Only"],
                key="rb_shortlist_scope",
            )

            if st.button("Save as New Shortlist", type="primary", key="btn_save_shortlist"):
                with get_session() as session:
                    # Filter target matches
                    base_q = select(CandidateMatch).where(CandidateMatch.jd_id == selected_jd_id)
                    if filter_mode == "Strong Matches Only":
                        base_q = base_q.where(CandidateMatch.match_category == "strong_match")
                    elif filter_mode == "Shortlisted Status Only":
                        base_q = base_q.where(CandidateMatch.human_review_status == "shortlisted")

                    target_matches = session.scalars(base_q).all()
                    if not target_matches:
                        st.warning("No candidates fit the chosen shortlist criteria.")
                    else:
                        new_sl = Shortlist(
                            name=shortlist_name,
                            jd_id=selected_jd_id,
                            description=shortlist_desc or None,
                            status="active",
                            created_by="Recruiter",
                        )
                        session.add(new_sl)
                        session.flush()

                        for m in target_matches:
                            sl_cand = ShortlistCandidate(
                                shortlist_id=new_sl.id,
                                candidate_id=m.candidate_id,
                                candidate_match_id=m.id,
                                status="shortlisted",
                            )
                            session.add(sl_cand)

                        session.flush()
                        st.success(f"🎉 Saved shortlist '{shortlist_name}' with {len(target_matches)} candidate(s)!")

    with b_col2:
        with st.expander("📥 Export Screening Results (CSV / Excel)", expanded=False):
            st.markdown("Download structured match reports including atomic breakdown metrics.")

            # Prepare Export DataFrame
            with get_session() as session:
                export_stmt = (
                    select(CandidateMatch)
                    .where(CandidateMatch.jd_id == selected_jd_id)
                    .options(
                        joinedload(CandidateMatch.candidate),
                        joinedload(CandidateMatch.job_description),
                    )
                    .order_by(CandidateMatch.match_score.desc())
                )
                export_matches = session.scalars(export_stmt).unique().all()

            if export_matches:
                export_rows = []
                for idx, m in enumerate(export_matches, start=1):
                    cand = m.candidate
                    jd = m.job_description
                    export_rows.append({
                        "Rank": idx,
                        "Candidate Name": cand.name if cand else "Unknown",
                        "Email": cand.email if cand else "",
                        "Phone": cand.phone if cand else "",
                        "Job Title": jd.title if jd else "",
                        "Match Score (%)": m.match_score,
                        "Category": m.match_category,
                        "Mandatory Met": f"{m.mandatory_met}/{m.mandatory_total}",
                        "Missing Mandatory Skills": m.mandatory_missing_json or "[]",
                        "Preferred Met": f"{m.preferred_met}/{m.preferred_total}",
                        "Experience Score (%)": m.experience_score,
                        "Qualification Score (%)": m.qualification_score,
                        "Domain Score (%)": m.domain_score,
                        "Review Status": m.human_review_status,
                        "Reviewer Notes": m.reviewer_notes or "",
                        "Last Screened": m.last_screened_at.strftime("%Y-%m-%d %H:%M") if m.last_screened_at else "",
                    })

                df_export = pd.DataFrame(export_rows)

                csv_data = df_export.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📄 Download CSV Report",
                    data=csv_data,
                    file_name=f"screening_{selected_jd_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

                # Excel Export
                excel_buffer = io.BytesIO()
                try:
                    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                        df_export.to_excel(writer, index=False, sheet_name="Screening Results")
                    excel_data = excel_buffer.getvalue()
                    st.download_button(
                        label="📊 Download Excel Spreadsheet",
                        data=excel_data,
                        file_name=f"screening_{selected_jd_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                except Exception as exc:
                    logger.warning("Excel export via openpyxl unavailable: %s", exc)


def _render_match_detail(match_id: int, matching_service: MatchingService) -> None:
    """Render comprehensive drilldown inspection card with requirement evidence and review tools."""
    detail = matching_service.get_match_detail(match_id)
    cand_name = detail["candidate_name"]

    st.markdown(
        f"""
        <div style="background-color: #f8fafc; border: 2px solid #3b82f6; border-radius: 8px; padding: 1.25rem; margin-top: 0.5rem; margin-bottom: 1rem;">
            <h4 style="color: #1e3a5f; margin: 0 0 0.5rem 0;">🔎 Detailed Assessment: {cand_name} (Score: {detail['match_score']:.1f}%)</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_eval, tab_strengths, tab_action, tab_wa = st.tabs(
        ["📋 Requirement Evidence", "⭐ Strengths & Gaps", "✍️ Recruiter Review", "💬 WhatsApp Outreach"]
    )

    # TAB 1: EVIDENCE
    with tab_eval:
        st.markdown("##### Component Score Breakdown")
        b1, b2, b3, b4, b5 = st.columns(5)
        with b1:
            st.metric("Mandatory Skills", f"{detail['mandatory_met']}/{detail['mandatory_total']}")
        with b2:
            st.metric("Experience", f"{detail['experience_score']:.0f}%")
        with b3:
            st.metric("Preferred Skills", f"{detail['preferred_met']}/{detail['preferred_total']}")
        with b4:
            st.metric("Qualifications", f"{detail['qualification_score']:.0f}%")
        with b5:
            st.metric("Domain", f"{detail['domain_score']:.0f}%")

        st.markdown("##### Atomic Requirement Justifications")
        evidences = detail.get("evidence", [])
        if not evidences:
            st.info("No atomic evidence items recorded.")
        else:
            for ev in evidences:
                st_icon = "✅" if ev["match_status"] == "matched" else ("⚠️" if ev["match_status"] in ("partial", "uncertain") else "❌")
                bg_col = "#f0fdf4" if ev["match_status"] == "matched" else ("#fefce8" if ev["match_status"] in ("partial", "uncertain") else "#fef2f2")
                border_c = "#86efac" if ev["match_status"] == "matched" else ("#fde047" if ev["match_status"] in ("partial", "uncertain") else "#fca5a5")

                st.markdown(
                    f"""
                    <div style="background-color: {bg_col}; border: 1px solid {border_c}; border-radius: 6px; padding: 0.65rem 0.85rem; margin-bottom: 0.5rem; font-size: 0.88rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 700; color: #1e3a5f;">{st_icon} {ev['requirement_name']}</span>
                            <span style="color: #64748b; font-size: 0.78rem; text-transform: uppercase;">Category: {ev['category']} | Confidence: {ev['confidence']*100:.0f}%</span>
                        </div>
                        <div style="margin-top: 0.35rem; color: #334155;">
                            {ev['evidence_text'] or 'No specific textual evidence cited.'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # TAB 2: STRENGTHS & GAPS
    with tab_strengths:
        c_str, c_gap = st.columns(2)
        with c_str:
            st.markdown("##### 🌟 Key Strengths")
            strengths = detail.get("strengths", [])
            if strengths:
                for s in strengths:
                    st.markdown(f"- ✅ **{s}**")
            else:
                st.caption("No specific high strengths identified.")

        with c_gap:
            st.markdown("##### ⚠️ Requirement Gaps")
            gaps = detail.get("gaps", [])
            if gaps:
                for g in gaps:
                    st.markdown(f"- ❌ **{g}**")
            else:
                st.caption("No critical requirement gaps found.")

        st.markdown(f"**Screening Confidence Level:** `{detail['confidence']*100:.0f}%`")

        if detail.get("reviewer_notes") and ("🤖 AI Fit Assessment" in detail["reviewer_notes"] or "💡 Recommended" in detail["reviewer_notes"]):
            st.markdown("---")
            st.markdown("##### 🤖 AI Screening Insights & Interview Prep")
            st.info(detail["reviewer_notes"])

    # TAB 3: RECRUITER ACTIONS
    with tab_action:
        st.markdown("##### Update Recruiter Status & Notes")
        rev_col1, rev_col2 = st.columns(2)
        with rev_col1:
            new_st = st.selectbox(
                "Decision Status:",
                options=["pending", "reviewed", "shortlisted", "on_hold", "not_selected"],
                index=["pending", "reviewed", "shortlisted", "on_hold", "not_selected"].index(
                    detail.get("human_review_status", "pending")
                ),
                key=f"sb_decision_status_{match_id}",
            )
            reason = st.text_input(
                "Decision Reason:",
                value=detail.get("reviewer_decision_reason") or "",
                placeholder="e.g. Excellent Python depth, approved for screening interview",
                key=f"ti_decision_reason_{match_id}",
            )

        with rev_col2:
            notes = st.text_area(
                "Recruiter Commentary / Notes:",
                value=detail.get("reviewer_notes") or "",
                height=100,
                key=f"ta_decision_notes_{match_id}",
            )

        save_c1, save_c2 = st.columns([1, 4])
        with save_c1:
            if st.button("💾 Save Decision", key=f"btn_save_decision_{match_id}", type="primary"):
                matching_service.update_review_status(
                    match_id=match_id,
                    status=new_st,
                    notes=notes,
                    reason=reason,
                    reviewer="Recruiter",
                )
                st.success("Decision recorded successfully!")
                st.rerun()

        with save_c2:
            if st.button("🔄 Re-run Screening for Candidate", key=f"btn_rerun_{match_id}"):
                matching_service.rerun_matching(match_id)
                st.success("Match re-evaluated!")
                st.rerun()

    # TAB 4: WHATSAPP OUTREACH
    with tab_wa:
        wa_srv = WhatsAppService()
        st.markdown("##### 💬 WhatsApp Outreach to Candidate")

        if not wa_srv.is_enabled():
            st.info("ℹ️ WhatsApp outreach is currently disabled in configuration (WHATSAPP_ENABLED=false).")
        else:
            cand_p = detail.get("candidate_phone") or ""
            if not cand_p.strip():
                st.warning("⚠️ Candidate has no phone number on file. Please enter their phone number below to enable WhatsApp outreach.")

            wa_col1, wa_col2 = st.columns([1, 1.4])
            with wa_col1:
                wa_num = st.text_input(
                    "Candidate WhatsApp Number:",
                    value=cand_p,
                    placeholder="+91 9876543210 (with country code)",
                    key=f"mr_wa_phone_{match_id}",
                    help="Candidate's phone number. Standard 10-digit Indian numbers automatically use +91.",
                )
                recruiter_name = st.text_input(
                    "Recruiter Sign-off:",
                    value="Talent Acquisition Team",
                    key=f"mr_wa_recruiter_{match_id}",
                )
                wa_templates = wa_srv.get_templates(
                    candidate_name=cand_name,
                    job_title=detail.get("jd_title") or "Target Position",
                    recruiter_name=recruiter_name.strip() or "Talent Acquisition Team",
                )
                sel_wa_tpl = st.selectbox(
                    "Outreach Template:",
                    options=list(wa_templates.keys()),
                    format_func=lambda k: wa_templates[k]["name"],
                    key=f"mr_wa_tpl_{match_id}",
                )
            with wa_col2:
                default_wa = wa_templates[sel_wa_tpl]["message"]

                # Ensure switching templates immediately updates the text area in Streamlit
                last_tpl_tracker = f"_last_wa_tpl_{match_id}"
                last_recruiter_tracker = f"_last_wa_rec_{match_id}"
                body_key = f"mr_wa_body_{match_id}"
                clean_recruiter = recruiter_name.strip()

                if (
                    st.session_state.get(last_tpl_tracker) != sel_wa_tpl
                    or st.session_state.get(last_recruiter_tracker) != clean_recruiter
                ):
                    st.session_state[body_key] = default_wa
                    st.session_state[last_tpl_tracker] = sel_wa_tpl
                    st.session_state[last_recruiter_tracker] = clean_recruiter

                msg_text = st.text_area(
                    "WhatsApp Message (Editable):",
                    value=default_wa,
                    height=150,
                    key=body_key,
                )

                # Quick reset to default template text if needed
                if st.button("↺ Reset Message to Template Default", key=f"mr_btn_reset_{match_id}", help="Revert edits back to standard template text"):
                    st.session_state[body_key] = default_wa
                    st.rerun()

                redirect_info = wa_srv.generate_whatsapp_redirect(wa_num, msg_text)
                wa_link = redirect_info.get("url")

                # Preview bubble
                st.markdown(
                    f"""
                    <div style="background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px; padding: 0.6rem 0.8rem; margin-bottom: 0.6rem;">
                        <div style="font-size: 0.78rem; color: #166534; font-weight: 700; margin-bottom: 0.2rem;">📱 WhatsApp Preview:</div>
                        <div style="font-size: 0.82rem; color: #1e293b; white-space: pre-wrap; font-family: sans-serif; line-height: 1.4;">{msg_text}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if not redirect_info.get("success"):
                    st.warning(f"⚠️ {redirect_info.get('error') or 'Please enter a valid phone number.'}")

                wb1, wb2 = st.columns(2)
                with wb1:
                    if wa_link:
                        st.link_button(
                            "💬 Contact on WhatsApp",
                            url=wa_link,
                            type="primary",
                            use_container_width=True,
                            help="Opens WhatsApp Web or mobile app. Review the message and press Send manually.",
                        )
                    else:
                        st.button(
                            "💬 Contact on WhatsApp",
                            disabled=True,
                            key=f"mr_wa_dis_{match_id}",
                            use_container_width=True,
                            help="Provide a valid phone number to generate WhatsApp link",
                        )
                with wb2:
                    if st.button("📝 Record Outreach Note", key=f"mr_wa_log_{match_id}", use_container_width=True):
                        if not wa_link:
                            st.error("Cannot record outreach: Invalid phone number.")
                        else:
                            now_str = datetime.now().strftime("%b %d, %H:%M")
                            st.info(f"Outreach attempt noted on {now_str}. Please review and manually press Send in WhatsApp.")
                st.caption("ℹ️ Generates a direct WhatsApp link. HR reviews the prefilled message and sends it manually.")


def _render_candidate_comparison(match_ids: List[int], matching_service: MatchingService) -> None:
    """Render side-by-side comparison matrix for 2 or 3 selected candidate matches."""
    st.markdown("### ⚖️ Side-by-Side Candidate Comparison")

    details = [matching_service.get_match_detail(m_id) for m_id in match_ids]
    cols = st.columns(len(details))

    for idx, (col, d) in enumerate(zip(cols, details)):
        with col:
            st.markdown(
                f"""
                <div style="background-color: #ffffff; border: 2px solid #2563eb; border-radius: 8px; padding: 1rem; text-align: center; margin-bottom: 1rem;">
                    <h3 style="color: #1e3a5f; margin: 0;">{d['candidate_name']}</h3>
                    <div style="margin: 0.5rem 0;">{_render_score_badge(d['match_score'])}</div>
                    <div>{_render_category_badge(d['match_category'])}</div>
                    <div style="margin-top: 0.35rem;">{_render_review_status_badge(d['human_review_status'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(f"**Mandatory Met:** `{d['mandatory_met']}/{d['mandatory_total']}`")
            st.markdown(f"**Preferred Met:** `{d['preferred_met']}/{d['preferred_total']}`")
            st.markdown(f"**Experience Score:** `{d['experience_score']:.0f}%`")
            st.markdown(f"**Qualifications:** `{d['qualification_score']:.0f}%`")
            st.markdown(f"**Confidence:** `{d['confidence']*100:.0f}%`")

            st.markdown("##### 🌟 Strengths")
            for s in d.get("strengths", [])[:3]:
                st.markdown(f"- {s}")

            st.markdown("##### ⚠️ Gaps")
            for g in d.get("gaps", [])[:3]:
                st.markdown(f"- {g}")

    # Requirement-by-requirement comparison table
    st.markdown("##### 📊 Skill-by-Skill Requirements Grid")
    all_req_names = list(
        dict.fromkeys(
            ev["requirement_name"]
            for d in details
            for ev in d.get("evidence", [])
        )
    )

    grid_rows = []
    for req_name in all_req_names:
        row: Dict[str, Any] = {"Requirement": req_name}
        for d in details:
            cand_ev = next((ev for ev in d.get("evidence", []) if ev["requirement_name"] == req_name), None)
            if cand_ev:
                st_code = cand_ev["match_status"]
                icon = "✅ Met" if st_code == "matched" else ("⚠️ Partial" if st_code in ("partial", "uncertain") else "❌ Missing")
            else:
                icon = "—"
            row[d["candidate_name"]] = icon
        grid_rows.append(row)

    df_grid = pd.DataFrame(grid_rows)
    st.dataframe(df_grid, use_container_width=True, hide_index=True)
