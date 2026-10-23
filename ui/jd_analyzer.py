"""Streamlit UI component for Job Description Requirement Analysis in TalentMatch AI.

Provides rule-based and AI-assisted requirement decomposition, interactive editing of
extracted screening criteria, category assignment, weight normalization, and persistence.
"""

import logging
from typing import Any, Dict, List, Optional

import streamlit as st

from config.settings import get_settings
from services.jd_analyzer import JDAnalyzerService
from services.jd_service import JDService
from ui.styles import get_custom_css

logger = logging.getLogger(__name__)

CATEGORY_OPTIONS = [
    "mandatory_skill",
    "preferred_skill",
    "experience",
    "education",
    "certification",
    "domain",
    "tool",
    "responsibility",
    "other",
]

IMPORTANCE_OPTIONS = [
    "mandatory",
    "preferred",
    "informational",
]


def render_jd_analyzer() -> None:
    """Render the Job Description Requirement Decomposition & Analysis workstation."""
    st.markdown(get_custom_css(), unsafe_allow_html=True)
    settings = get_settings()
    jd_service = JDService()
    analyzer_service = JDAnalyzerService()

    # Session State Setup
    if "analyzer_selected_jd_id" not in st.session_state:
        st.session_state["analyzer_selected_jd_id"] = st.session_state.get(
            "selected_analyzer_jd_id", None
        )
    if "analyzer_rows" not in st.session_state:
        st.session_state["analyzer_rows"] = []
    if "analyzer_last_loaded_jd_id" not in st.session_state:
        st.session_state["analyzer_last_loaded_jd_id"] = None
    if "analyzer_custom_text" not in st.session_state:
        st.session_state["analyzer_custom_text"] = ""

    # Header Banner
    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h1 style="color: #1e3a5f; margin: 0; font-size: 2rem; font-weight: 700;">
                🎯 Requirement Analyzer
            </h1>
            <p style="color: #64748b; margin: 0.2rem 0 0 0; font-size: 0.95rem;">
                Decompose job descriptions into weighted, atomic screening criteria (skills, experience, education, tools).
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 1. Fetch available JDs for selection
    try:
        available_jds, _ = jd_service.get_all_jds(limit=200)
    except Exception as exc:
        logger.error("Failed to fetch JDs for analyzer: %s", exc)
        available_jds = []

    jd_options_map: Dict[str, Optional[int]] = {
        "-- Paste Custom / Unsaved Text --": None
    }
    for j in available_jds:
        dept_str = f" [{j.department}]" if j.department else ""
        label = f"#{j.id} - {j.title}{dept_str} ({j.analysis_status})"
        jd_options_map[label] = j.id

    # Determine default dropdown index
    options_keys = list(jd_options_map.keys())
    default_index = 0
    preselected_id = st.session_state.get("selected_analyzer_jd_id") or st.session_state.get("analyzer_selected_jd_id")

    if preselected_id is not None:
        for idx, (label, j_id) in enumerate(jd_options_map.items()):
            if j_id == preselected_id:
                default_index = idx
                break

    # Selection Controls
    sel_col1, sel_col2 = st.columns([3, 1.2])
    with sel_col1:
        chosen_label = st.selectbox(
            "Select Requisition to Analyze",
            options=options_keys,
            index=default_index,
            key="analyzer_jd_dropdown",
            help="Choose an existing job description to inspect its criteria or extract new ones.",
        )
        selected_jd_id = jd_options_map[chosen_label]
        st.session_state["analyzer_selected_jd_id"] = selected_jd_id

    # Check if selected JD has changed -> load saved requirements
    if selected_jd_id != st.session_state["analyzer_last_loaded_jd_id"]:
        st.session_state["analyzer_last_loaded_jd_id"] = selected_jd_id
        if selected_jd_id is not None:
            saved_reqs = jd_service.get_jd_requirements(selected_jd_id)
            if saved_reqs:
                st.session_state["analyzer_rows"] = [
                    {
                        "requirement_name": r.requirement_name,
                        "category": r.category,
                        "importance": r.importance,
                        "original_evidence": r.original_evidence or "",
                        "normalized_value": r.normalized_value or "",
                        "weight": float(r.weight),
                        "is_enabled": bool(r.is_enabled),
                        "recruiter_notes": r.recruiter_notes or "",
                    }
                    for r in saved_reqs
                ]
            else:
                st.session_state["analyzer_rows"] = []
        else:
            st.session_state["analyzer_rows"] = []

    # Load current JD object if selected
    current_jd = None
    if selected_jd_id is not None:
        try:
            current_jd = jd_service.get_jd(selected_jd_id)
        except Exception as exc:
            st.error(f"Failed to load JD #{selected_jd_id}: {exc}")

    with sel_col2:
        # Engine indicator
        ai_ready = settings.is_ai_available
        if ai_ready:
            method_options = ["AI Engine (Google Gemini)", "Rule-based Engine (Deterministic)"]
        else:
            method_options = ["Rule-based Engine (Deterministic)"]

        chosen_method = st.selectbox(
            "Analysis Engine",
            options=method_options,
            index=0,
            key="analyzer_method_select",
            help="AI Engine uses Gemini LLM for deep semantic decomposition; Rule-based uses regex keyword matching.",
        )

    # Status / Warning Banners
    if current_jd:
        if current_jd.analysis_status == "needs_reanalysis":
            st.markdown(
                """
                <div class="tm-alert tm-alert-warning">
                    <div>
                        <b>⚠️ Re-analysis Recommended</b>
                        <div>The job description content was modified after requirements were saved. Re-run analysis to incorporate the latest changes.</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif current_jd.analysis_status == "analyzed":
            st.markdown(
                f"""
                <div class="tm-alert tm-alert-info">
                    <div>
                        <b>ℹ️ Analysis Status: Analyzed</b>
                        <div>Currently displaying {len(st.session_state['analyzer_rows'])} active requirements for <b>'{current_jd.title}'</b>. You can fine-tune or re-extract below.</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Input Preview or Custom Input Area
    text_to_process = ""
    if current_jd:
        with st.expander(f"📄 Requisition Content Preview: {current_jd.title}", expanded=False):
            st.markdown(f"**Department:** {current_jd.department or 'N/A'} • **Location:** {current_jd.location or 'N/A'}")
            st.markdown(current_jd.description_text)
            if current_jd.qualifications:
                st.markdown("**Qualifications:**")
                st.markdown(current_jd.qualifications)
            if current_jd.responsibilities:
                st.markdown("**Responsibilities:**")
                st.markdown(current_jd.responsibilities)

        # Build composite text
        parts = [current_jd.title, current_jd.description_text]
        if current_jd.qualifications:
            parts.append(f"Qualifications:\n{current_jd.qualifications}")
        if current_jd.responsibilities:
            parts.append(f"Responsibilities:\n{current_jd.responsibilities}")
        if current_jd.certifications:
            parts.append(f"Certifications:\n{current_jd.certifications}")
        text_to_process = "\n\n".join(parts)
    else:
        st.session_state["analyzer_custom_text"] = st.text_area(
            "Paste Job Description Text Here",
            value=st.session_state["analyzer_custom_text"],
            height=200,
            placeholder="Paste job posting title, qualifications, responsibilities, and technical requirements...",
        )
        text_to_process = st.session_state["analyzer_custom_text"]

    # Analysis Action Bar
    act_col1, act_col2, act_col3 = st.columns([1.5, 1.5, 2.5])
    with act_col1:
        if st.button("🚀 Run Extraction", type="primary", use_container_width=True):
            if not text_to_process.strip():
                st.error("Please provide or select job description text to analyze.")
            else:
                with st.spinner("Decomposing requisition into atomic requirements..."):
                    if "AI Engine" in chosen_method and settings.is_ai_available:
                        extracted = analyzer_service.analyze_jd_with_ai(text_to_process)
                    else:
                        extracted = analyzer_service.analyze_jd_rule_based(text_to_process)

                st.session_state["analyzer_rows"] = extracted
                st.success(f"Successfully decomposed {len(extracted)} requirements!")
                st.rerun()

    with act_col2:
        if st.button("➕ Add Requirement", use_container_width=True):
            st.session_state["analyzer_rows"].append({
                "requirement_name": "New Requirement",
                "category": "mandatory_skill",
                "importance": "mandatory",
                "original_evidence": "Manually added by recruiter",
                "normalized_value": "new_requirement",
                "weight": 5.0,
                "is_enabled": True,
                "recruiter_notes": "",
            })
            st.rerun()

    with act_col3:
        if st.button("🤖 AI Quality Review & Audit", use_container_width=True):
            if not text_to_process.strip():
                st.error("Please provide or select job description text to review.")
            else:
                with st.spinner("Running Google Gemini AI Quality Review..."):
                    audit_res = analyzer_service.review_jd_with_ai(text_to_process)
                    st.session_state["jd_ai_review_result"] = audit_res
                st.rerun()

    # Display AI Quality Audit Card if generated
    if "jd_ai_review_result" in st.session_state and st.session_state["jd_ai_review_result"]:
        audit = st.session_state["jd_ai_review_result"]
        with st.expander(
            f"📊 AI Requisition Quality Audit • Score: {audit.get('overall_score', 80)}/100 ({audit.get('grade', 'Good')})",
            expanded=True,
        ):
            score_val = audit.get("overall_score", 80)
            score_color = "#15803d" if score_val >= 80 else ("#b45309" if score_val >= 60 else "#b91c1c")
            st.markdown(
                f"""
                <div style="background-color: #f8fafc; border-left: 4px solid {score_color}; padding: 0.85rem 1rem; border-radius: 6px; margin-bottom: 0.75rem;">
                    <div style="font-size: 1.05rem; font-weight: 700; color: #1e293b;">
                        Requisition Quality Assessment: <span style="color: {score_color};">{score_val}/100 — {audit.get('grade', 'Good')}</span>
                    </div>
                    <div style="color: #475569; margin-top: 0.35rem; font-size: 0.92rem;">
                        {audit.get('summary', '')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            aud_c1, aud_c2 = st.columns(2)
            with aud_c1:
                st.markdown("**Seniority Alignment:**")
                st.caption(audit.get("seniority_alignment", "Standard mid-level expectations."))

                st.markdown("**⚠️ Ambiguities / Vague Requirements:**")
                ambs = audit.get("ambiguities", [])
                if ambs:
                    for a in ambs:
                        st.markdown(f"- 🔸 {a}")
                else:
                    st.caption("No significant ambiguities detected.")

            with aud_c2:
                st.markdown("**🔍 Missing Key Requisition Details:**")
                missing = audit.get("missing_elements", [])
                if missing:
                    for m in missing:
                        st.markdown(f"- 🔹 {m}")
                else:
                    st.caption("No critical missing elements detected.")

                st.markdown("**💡 Actionable Screening Recommendations:**")
                recs = audit.get("screening_recommendations", [])
                if recs:
                    for r in recs:
                        st.markdown(f"- ✅ {r}")
                else:
                    st.caption("No specific recommendations.")

    # 2. Editable Requirements Table
    rows: List[Dict[str, Any]] = st.session_state["analyzer_rows"]

    if not rows:
        st.markdown(
            """
            <div class="tm-empty-state">
                <div class="tm-empty-icon">⚡</div>
                <div class="tm-empty-title">No Requirements Extracted Yet</div>
                <div class="tm-empty-desc">
                    Click <b>Run Extraction</b> to automatically detect required skills, experience thresholds,
                    degrees, and tools, or click <b>Add Requirement</b> to build custom screening criteria.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown("---")

    # Metrics & Weight Distribution Summary
    total_enabled_weight = sum(r["weight"] for r in rows if r.get("is_enabled", True))
    mandatory_count = sum(1 for r in rows if r.get("importance") == "mandatory" and r.get("is_enabled", True))
    preferred_count = sum(1 for r in rows if r.get("importance") == "preferred" and r.get("is_enabled", True))
    info_count = sum(1 for r in rows if r.get("importance") == "informational" and r.get("is_enabled", True))

    stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)
    with stat_col1:
        st.metric("Total Requirements", len(rows))
    with stat_col2:
        st.metric("Mandatory Criteria", mandatory_count)
    with stat_col3:
        st.metric("Preferred Criteria", preferred_count)
    with stat_col4:
        st.metric("Informational", info_count)
    with stat_col5:
        st.metric("Total Weight Sum", f"{total_enabled_weight:.1f}")

    # Weight Normalization Action
    bal_col1, bal_col2, bal_spacer = st.columns([1.5, 1.5, 3])
    with bal_col1:
        if st.button("⚖️ Auto-Balance (Scale to 100%)", help="Proportionally scale all enabled requirement weights so their sum is exactly 100%"):
            if total_enabled_weight > 0:
                scale_factor = 100.0 / total_enabled_weight
                for r in rows:
                    if r.get("is_enabled", True):
                        r["weight"] = round(r["weight"] * scale_factor, 1)
                st.session_state["analyzer_rows"] = rows
                st.success("Weights normalized to sum to 100%!")
                st.rerun()

    with bal_col2:
        if st.button("🔄 Reset Default Weights", help="Restore standard weights (Mandatory=8.0, Preferred=3.0, Informational=1.0)"):
            for r in rows:
                imp = r.get("importance", "mandatory")
                cat = r.get("category", "mandatory_skill")
                if imp == "mandatory":
                    r["weight"] = 8.0 if cat in ("experience", "mandatory_skill") else 5.0
                elif imp == "preferred":
                    r["weight"] = 3.0
                else:
                    r["weight"] = 1.0
            st.session_state["analyzer_rows"] = rows
            st.info("Weights restored to default baseline.")
            st.rerun()

    st.markdown("<div style='height: 0.75rem;'></div>", unsafe_allow_html=True)
    st.markdown("### 📋 Configured Requirements Breakdown")

    # Render interactive requirements editor
    row_to_delete = None
    for idx, req in enumerate(rows):
        card_border = "#2563eb" if req.get("importance") == "mandatory" else "#cbd5e1"
        is_enabled = req.get("is_enabled", True)
        opacity = "1.0" if is_enabled else "0.55"

        with st.container():
            st.markdown(
                f"""
                <div style="border-left: 4px solid {card_border}; opacity: {opacity};
                            background-color: #ffffff; border-radius: 6px; border-top: 1px solid #e2e8f0;
                            border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;
                            padding: 0.75rem; margin-bottom: 0.75rem;">
                </div>
                """,
                unsafe_allow_html=True,
            )

            c_enabled, c_name, c_cat, c_imp, c_weight, c_del = st.columns([0.6, 3, 1.8, 1.5, 1.5, 0.6])

            with c_enabled:
                new_enabled = st.checkbox(
                    "On",
                    value=req.get("is_enabled", True),
                    key=f"req_en_{idx}",
                    help="Enable or disable this requirement in screening evaluation",
                )
                req["is_enabled"] = new_enabled

            with c_name:
                new_name = st.text_input(
                    "Requirement Title",
                    value=req.get("requirement_name", ""),
                    key=f"req_name_{idx}",
                    label_visibility="collapsed",
                    placeholder="Requirement name...",
                )
                req["requirement_name"] = new_name

            with c_cat:
                cat_idx = CATEGORY_OPTIONS.index(req.get("category", "mandatory_skill")) if req.get("category") in CATEGORY_OPTIONS else 0
                new_cat = st.selectbox(
                    "Category",
                    options=CATEGORY_OPTIONS,
                    index=cat_idx,
                    key=f"req_cat_{idx}",
                    label_visibility="collapsed",
                )
                req["category"] = new_cat

            with c_imp:
                imp_idx = IMPORTANCE_OPTIONS.index(req.get("importance", "mandatory")) if req.get("importance") in IMPORTANCE_OPTIONS else 0
                new_imp = st.selectbox(
                    "Importance",
                    options=IMPORTANCE_OPTIONS,
                    index=imp_idx,
                    key=f"req_imp_{idx}",
                    label_visibility="collapsed",
                )
                req["importance"] = new_imp

            with c_weight:
                new_weight = st.number_input(
                    "Weight",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(req.get("weight", 1.0)),
                    step=0.5,
                    key=f"req_wt_{idx}",
                    label_visibility="collapsed",
                )
                req["weight"] = new_weight

            with c_del:
                if st.button("🗑️", key=f"req_del_{idx}", help="Remove this requirement"):
                    row_to_delete = idx

            # Second row: normalized value, notes, evidence
            sub_c1, sub_c2 = st.columns([1.5, 2.5])
            with sub_c1:
                new_norm = st.text_input(
                    "Normalized Key",
                    value=req.get("normalized_value", ""),
                    key=f"req_norm_{idx}",
                    help="Canonical keyword representation used for matching logic",
                )
                req["normalized_value"] = new_norm

            with sub_c2:
                new_notes = st.text_input(
                    "Recruiter Note / Matching Guideline",
                    value=req.get("recruiter_notes", ""),
                    key=f"req_note_{idx}",
                    placeholder="e.g., Must have production-grade experience...",
                )
                req["recruiter_notes"] = new_notes

            if req.get("original_evidence"):
                st.caption(f"**Evidence in JD:** *\"{req['original_evidence']}\"*")

    # Handle deletion
    if row_to_delete is not None:
        rows.pop(row_to_delete)
        st.session_state["analyzer_rows"] = rows
        st.rerun()

    # 3. Persistence Section
    st.markdown("---")
    save_col1, save_col2 = st.columns([2, 3])

    with save_col1:
        if selected_jd_id is not None:
            if st.button("💾 Save & Apply Requirements to Requisition", type="primary", use_container_width=True):
                valid_rows = [r for r in rows if (r.get("requirement_name") or "").strip()]
                if not valid_rows:
                    st.error("Cannot save empty requirements list.")
                else:
                    try:
                        saved = jd_service.save_requirements(selected_jd_id, valid_rows)
                        st.success(
                            f"✅ Successfully saved {len(saved)} requirements for Requisition #{selected_jd_id}!\n"
                            "Analysis status transitioned to 'Analyzed'."
                        )
                        st.rerun()
                    except Exception as exc:
                        logger.error("Failed to persist requirements: %s", exc)
                        st.error(f"Error saving requirements: {exc}")
        else:
            st.info("💡 To save these requirements, select an existing Job Description from the top dropdown.")
