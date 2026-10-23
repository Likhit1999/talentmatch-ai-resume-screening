"""Streamlit UI module for the Candidate Database & Talent Directory in TalentMatch AI.

Provides talent pool browsing, multi-criteria filtering (skills, text search, parse status),
summary telemetry metrics, detailed profile inspector, manual data correction,
associated match reviews, and candidate removal with privacy safeguarding.
"""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional

import streamlit as st

from services.candidate_service import CandidateService


def _mask_email(email: Optional[str]) -> str:
    """Mask email for privacy in overview directory tables."""
    if not email or "@" not in email:
        return "—"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked = user[0] + "*"
    else:
        masked = user[0] + "***" + user[-1]
    return f"{masked}@{domain}"


def _mask_phone(phone: Optional[str]) -> str:
    """Mask phone number for privacy in overview directory tables."""
    if not phone:
        return "—"
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 4:
        return f"***-***-{digits[-4:]}"
    return "***"


def _render_status_badge(status: str) -> str:
    """Generate styled HTML badge for parsing and screening status."""
    st_clean = (status or "unknown").lower()
    if st_clean in ("parsed", "new", "success"):
        return "<span style='background-color: #DCFCE7; color: #15803D; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>Parsed</span>"
    elif st_clean == "duplicate":
        return "<span style='background-color: #FEF3C7; color: #B45309; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>Duplicate</span>"
    elif st_clean == "warning":
        return "<span style='background-color: #FFEDD5; color: #C2410C; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>Warning</span>"
    elif st_clean == "failed":
        return "<span style='background-color: #FEE2E2; color: #B91C1C; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>Failed</span>"
    else:
        return f"<span style='background-color: #F1F5F9; color: #475569; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>{status}</span>"


def _render_score_badge(score: float) -> str:
    """Format and color-code screening match scores."""
    if score >= 80.0:
        bg, fg = "#DCFCE7", "#15803D"
    elif score >= 60.0:
        bg, fg = "#DBEAFE", "#1E40AF"
    elif score >= 40.0:
        bg, fg = "#FEF3C7", "#B45309"
    else:
        bg, fg = "#FEE2E2", "#B91C1C"
    return f"<span style='background-color: {bg}; color: {fg}; padding: 3px 8px; border-radius: 6px; font-weight: 700; font-size: 0.85rem;'>{score:.1f}%</span>"


def render_candidate_database() -> None:
    """Render the Candidate Talent Pool & Database view."""
    candidate_service = CandidateService()

    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h2 style="color: #1E3A8A; margin: 0 0 0.35rem 0;">Candidate Talent Directory</h2>
            <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                Browse, search, and inspect candidates ingested into the talent pool.
                Filter by technical skills and ingestion status, verify extracted profiles, or perform manual corrections.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ==========================================
    # 1. SUMMARY TELEMETRY CARDS
    # ==========================================
    _, total_count = candidate_service.get_candidates(limit=1)
    _, parsed_count = candidate_service.get_candidates(status="parsed", limit=1)
    _, warn_count = candidate_service.get_candidates(status="warning", limit=1)
    _, fail_count = candidate_service.get_candidates(status="failed", limit=1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Candidates", total_count)
    with c2:
        st.metric("Fully Parsed", parsed_count)
    with c3:
        st.metric("With Warnings", warn_count)
    with c4:
        st.metric("Extraction Failures", fail_count)

    st.markdown("---")

    # Empty State Check
    if total_count == 0:
        st.markdown(
            """
            <div style="text-align: center; padding: 3rem 1rem; background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 10px; margin: 1.5rem 0;">
                <h3 style="color: #475569; margin-bottom: 0.5rem;">No Candidates Found</h3>
                <p style="color: #64748B; max-width: 500px; margin: 0 auto 1.5rem auto;">
                    Your candidate directory is currently empty. Ingest resumes via drag-and-drop or raw text paste to populate the talent pool.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # ==========================================
    # 2. SEARCH & FILTER CONTROLS
    # ==========================================
    with st.expander("🔍 Search & Filter Options", expanded=True):
        f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns([2.5, 2.5, 2, 2, 1.2])

        with f_col1:
            search_query = st.text_input(
                "Search by Name, Email, or Keyword",
                value=st.session_state.get("cand_search_query", ""),
                placeholder="e.g. John Doe or Python",
            )
            st.session_state["cand_search_query"] = search_query

        with f_col2:
            skill_input = st.text_input(
                "Filter by Skill(s) (comma-separated)",
                value=st.session_state.get("cand_skill_filter", ""),
                placeholder="e.g. Python, Docker, React",
            )
            st.session_state["cand_skill_filter"] = skill_input
            active_skills = [s.strip() for s in skill_input.split(",") if s.strip()]

        with f_col3:
            role_filter = st.text_input(
                "Filter by Role/Category",
                value=st.session_state.get("cand_role_filter", ""),
                placeholder="e.g. QA or Backend",
            )
            st.session_state["cand_role_filter"] = role_filter

        with f_col4:
            status_opts = ["All", "Parsed", "Warning", "Failed", "Pending"]
            current_status = st.session_state.get("cand_status_filter", "All")
            status_index = status_opts.index(current_status) if current_status in status_opts else 0
            selected_status = st.selectbox(
                "Ingestion Status",
                options=status_opts,
                index=status_index,
            )
            st.session_state["cand_status_filter"] = selected_status

        with f_col5:
            st.write("")
            st.write("")
            if st.button("Reset Filters", use_container_width=True):
                st.session_state["cand_search_query"] = ""
                st.session_state["cand_skill_filter"] = ""
                st.session_state["cand_role_filter"] = ""
                st.session_state["cand_status_filter"] = "All"
                st.session_state["candidate_page"] = 1
                st.rerun()

    # ==========================================
    # 3. PAGINATION SETUP & QUERY
    # ==========================================
    page_size = 15
    current_page = st.session_state.get("candidate_page", 1)
    offset = (current_page - 1) * page_size

    filter_status_val = None if selected_status == "All" else selected_status.lower()

    candidates, matching_count = candidate_service.get_candidates(
        search=search_query if search_query.strip() else None,
        skills=active_skills if active_skills else None,
        status=filter_status_val,
        job_category=role_filter if role_filter.strip() else None,
        offset=offset,
        limit=page_size,
    )

    total_pages = max(1, (matching_count + page_size - 1) // page_size)
    if current_page > total_pages:
        current_page = total_pages
        st.session_state["candidate_page"] = current_page

    st.markdown(
        f"<p style='color: #64748B; font-size: 0.9rem; margin: 0.5rem 0;'>"
        f"Displaying <strong>{len(candidates)}</strong> of <strong>{matching_count}</strong> matching candidate(s) (Page {current_page} of {total_pages})"
        f"</p>",
        unsafe_allow_html=True,
    )

    # ==========================================
    # 4. CANDIDATE DIRECTORY TABLE
    # ==========================================
    # Requirement: Never expose full email/phone in summary tables!
    table_data = []
    for cand in candidates:
        skills_str = ", ".join(cand["skills"][:4])
        if len(cand["skills"]) > 4:
            skills_str += f" (+{len(cand['skills']) - 4})"

        exp_entries = len(cand.get("experience", []))
        exp_summary = f"{exp_entries} role(s)" if exp_entries > 0 else "—"

        table_data.append({
            "ID": cand["id"],
            "Name": cand["name"],
            "Role / Category": cand.get("job_category") or "General",
            "Email": cand.get("email") or "—",
            "Phone": cand.get("phone") or "—",
            "Skills": skills_str or "—",
            "Experience": exp_summary,
            "Status": cand["parsing_status"].capitalize(),
            "Upload Date": cand["created_at"][:10] if cand["created_at"] else "—",
        })

    st.dataframe(
        table_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn(width="small"),
            "Name": st.column_config.TextColumn(width="medium"),
            "Role / Category": st.column_config.TextColumn(width="medium"),
            "Email": st.column_config.TextColumn(width="medium"),
            "Phone": st.column_config.TextColumn(width="small"),
            "Skills": st.column_config.TextColumn(width="large"),
            "Experience": st.column_config.TextColumn(width="small"),
            "Status": st.column_config.TextColumn(width="small"),
            "Upload Date": st.column_config.TextColumn(width="small"),
        },
    )

    # Pagination navigation controls
    p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns([1.5, 1.5, 3, 1.5, 1.5])
    with p_col2:
        if st.button("⬅️ Previous", disabled=(current_page <= 1), use_container_width=True):
            st.session_state["candidate_page"] = max(1, current_page - 1)
            st.rerun()
    with p_col3:
        st.markdown(
            f"<div style='text-align: center; padding-top: 0.4rem; color: #475569; font-weight: 600;'>"
            f"Page {current_page} of {total_pages}</div>",
            unsafe_allow_html=True,
        )
    with p_col4:
        if st.button("Next ➡️", disabled=(current_page >= total_pages), use_container_width=True):
            st.session_state["candidate_page"] = min(total_pages, current_page + 1)
            st.rerun()

    st.markdown("---")

    # ==========================================
    # 5. CANDIDATE DETAIL VIEW & CORRECTION
    # ==========================================
    st.markdown("### 📋 Candidate Profile Deep-Dive & Correction")

    # Candidate selector
    candidate_options = {
        f"#{c['id']} - {c['name']} ({_mask_email(c['email'])})": c["id"] for c in candidates
    }

    if not candidate_options:
        st.caption("No candidates available for inspection in current filter view.")
        return

    selected_label = st.selectbox(
        "Select a candidate to view, edit, or remove:",
        options=list(candidate_options.keys()),
        index=0,
    )
    selected_id = candidate_options[selected_label]

    # Load complete candidate entity including resumes & matches
    cand_details = candidate_service.get_candidate(selected_id)
    if not cand_details:
        st.warning("Candidate record not found or could not be loaded.")
        return

    # Profile Header
    p_header1, p_header2 = st.columns([3, 1])
    with p_header1:
        st.markdown(
            f"""
            <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-left: 5px solid #1E40AF; border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem;">
                <h3 style="color: #1E3A8A; margin: 0 0 0.5rem 0;">{cand_details['name']}</h3>
                <div style="color: #475569; font-size: 0.95rem; line-height: 1.6;">
                    📧 <strong>Email:</strong> {cand_details['email'] or 'Not Provided'} &nbsp;|&nbsp; 
                    📞 <strong>Phone:</strong> {cand_details['phone'] or 'Not Provided'} &nbsp;|&nbsp; 
                    🆔 <strong>Candidate ID:</strong> {cand_details['id']}
                </div>
                <div style="color: #64748B; font-size: 0.85rem; margin-top: 0.4rem;">
                    📅 <strong>Ingested:</strong> {cand_details['created_at']} &nbsp;|&nbsp; 
                    📦 <strong>Batch:</strong> <code>{cand_details['upload_batch_id'] or 'direct'}</code> &nbsp;|&nbsp;
                    Status: {_render_status_badge(cand_details['parsing_status'])}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with p_header2:
        st.markdown("<div style='padding-top: 0.5rem;'>", unsafe_allow_html=True)
        show_edit = st.toggle("✏️ Edit Profile", value=False, key=f"toggle_edit_{selected_id}")
        st.markdown("</div>", unsafe_allow_html=True)

    # Ingestion Warnings alert if present
    if cand_details.get("parsing_warnings"):
        with st.container():
            st.warning(
                f"**Ingestion Warnings Detected:**\n- " + "\n- ".join(cand_details["parsing_warnings"]),
                icon="⚠️",
            )
            if cand_details["parsing_status"] in ("failed", "warning"):
                if st.button("🔄 Re-process / Retry Extraction", key=f"retry_detail_{selected_id}"):
                    retry_outcome = candidate_service.retry_failed(selected_id)
                    if retry_outcome["success"]:
                        st.success(retry_outcome["message"])
                        st.rerun()
                    else:
                        st.error(retry_outcome["message"])

    # EDIT FORM (if toggled)
    if show_edit:
        st.markdown("#### 🛠️ Manual Candidate Correction")
        with st.form(key=f"edit_candidate_form_{selected_id}"):
            ed_col1, ed_col2 = st.columns(2)
            with ed_col1:
                edit_name = st.text_input("Full Name", value=cand_details["name"])
                edit_email = st.text_input("Email Address", value=cand_details["email"] or "")
            with ed_col2:
                edit_phone = st.text_input("Phone Number", value=cand_details["phone"] or "")
                status_choices = ["parsed", "warning", "failed", "pending"]
                cur_status_idx = (
                    status_choices.index(cand_details["parsing_status"])
                    if cand_details["parsing_status"] in status_choices
                    else 0
                )
                edit_status = st.selectbox("Parsing Status", options=status_choices, index=cur_status_idx)

            edit_summary = st.text_area(
                "Executive Summary",
                value=cand_details["resume_summary"] or "",
                height=100,
            )

            edit_skills_str = st.text_area(
                "Extracted Skills (comma-separated)",
                value=", ".join(cand_details["skills"]),
                height=80,
                help="Edit technical skills recognized for candidate matching.",
            )

            save_submitted = st.form_submit_button("💾 Save Profile Changes", type="primary")
            if save_submitted:
                updated_skills = [s.strip() for s in edit_skills_str.split(",") if s.strip()]
                payload = {
                    "name": edit_name,
                    "email": edit_email if edit_email.strip() else None,
                    "phone": edit_phone if edit_phone.strip() else None,
                    "resume_summary": edit_summary,
                    "parsing_status": edit_status,
                    "skills": updated_skills,
                }
                updated_res = candidate_service.update_candidate(selected_id, payload)
                if updated_res:
                    st.success("Candidate profile updated successfully!")
                    st.rerun()
                else:
                    st.error("Failed to update candidate.")

    # TABS FOR PROFILE DETAILS
    det_tab1, det_tab2, det_tab3, det_tab4, det_tab5, det_tab6 = st.tabs([
        "🏷️ Skills",
        "💼 Experience",
        "🎓 Education & Certs",
        "📄 Original Text",
        "🎯 Matching Results",
        "🗑️ Delete",
    ])

    # Tab 1: Skills
    with det_tab1:
        st.markdown("#### Extracted Technical & Professional Competencies")
        if cand_details["skills"]:
            skills_html = "".join([
                f"<span style='display:inline-block; background-color:#EFF6FF; color:#1D4ED8; "
                f"border:1px solid #BFDBFE; border-radius:6px; padding:4px 10px; margin:3px 5px 3px 0; "
                f"font-size:0.85rem; font-weight:500;'>{s}</span>"
                for s in cand_details["skills"]
            ])
            st.markdown(skills_html, unsafe_allow_html=True)
            st.caption(f"Total skills recognized: {len(cand_details['skills'])}")
        else:
            st.info("No technical skills were automatically identified.")

        if cand_details.get("resume_summary"):
            st.markdown("---")
            st.markdown("#### Professional Profile Summary")
            st.markdown(
                f"<div style='background-color:#F8FAFC; padding:1rem; border-radius:6px; border:1px solid #E2E8F0; color:#334155; font-size:0.92rem; line-height:1.5;'>"
                f"{cand_details['resume_summary']}"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Tab 2: Experience
    with det_tab2:
        st.markdown("#### Work & Employment History")
        exp_entries = cand_details.get("experience", [])
        if not exp_entries:
            st.info("No structured work experience entries could be extracted.")
        else:
            for idx, exp in enumerate(exp_entries, start=1):
                st.markdown(
                    f"""
                    <div style="border: 1px solid #E2E8F0; border-left: 4px solid #3B82F6; border-radius: 6px; padding: 1rem; margin-bottom: 0.75rem; background-color: #FFFFFF;">
                        <div style="font-weight: 700; color: #1E3A8A; font-size: 1rem;">{exp.get('title', 'Role')}</div>
                        <div style="color: #475569; font-weight: 500; font-size: 0.9rem;">
                            🏢 {exp.get('company', 'Organization')} &nbsp;|&nbsp; 
                            ⏱️ <span style="color: #64748B;">{exp.get('duration', 'Duration not specified')}</span>
                        </div>
                        <div style="color: #334155; font-size: 0.88rem; margin-top: 0.5rem; line-height: 1.5;">
                            {exp.get('description', '')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Tab 3: Education & Certs
    with det_tab3:
        st.markdown("#### Academic Qualifications")
        edu_entries = cand_details.get("education", [])
        if not edu_entries:
            st.info("No educational qualifications extracted.")
        else:
            for edu in edu_entries:
                st.markdown(
                    f"""
                    <div style="border: 1px solid #E2E8F0; border-left: 4px solid #10B981; border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 0.5rem; background-color: #FFFFFF;">
                        <span style="font-weight: 700; color: #0F172A;">{edu.get('degree', 'Degree')}</span> &nbsp;—&nbsp; 
                        <span style="color: #334155;">{edu.get('institution', 'Institution')}</span> 
                        <span style="float: right; color: #64748B; font-size: 0.85rem;">🎓 Year: {edu.get('year', 'N/A')}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("---")
        st.markdown("#### Certifications & Credentials")
        cert_entries = cand_details.get("certifications", [])
        if not cert_entries:
            st.info("No certifications recognized.")
        else:
            for cert in cert_entries:
                st.markdown(f"- 📜 **{cert}**")

    # Tab 4: Original Text
    with det_tab4:
        st.markdown("#### Uploaded Resume Documents")
        resumes = cand_details.get("resumes", [])
        if not resumes:
            st.info("No attached resume document records.")
        else:
            for r in resumes:
                st.markdown(f"**Document:** `{r['original_filename']}` ({r['file_type'].upper()})")
                st.caption(f"SHA-256 Hash: `{r['file_hash']}` | Uploaded: {r['upload_timestamp']}")
                with st.expander("📄 View Extracted Text", expanded=False):
                    st.text_area(
                        "Raw Parsed Text",
                        value=r["resume_text"] or "Empty document text",
                        height=350,
                        disabled=True,
                        key=f"raw_text_{r['id']}",
                    )

    # Tab 5: Matching Results
    with det_tab5:
        st.markdown("#### Requisition Screening Results")
        matches = cand_details.get("matches", [])
        if not matches:
            st.info("This candidate has not yet been evaluated in any batch screening runs.")
        else:
            for m in matches:
                m_score = m.get("match_score", 0.0)
                st.markdown(
                    f"""
                    <div style="border: 1px solid #E2E8F0; border-radius: 6px; padding: 0.85rem 1rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{m.get('jd_title', 'Job Description')}</strong><br/>
                            <span style="color: #64748B; font-size: 0.85rem;">Category: <code>{m.get('match_category')}</code> | Review: {m.get('human_review_status')}</span>
                        </div>
                        <div style="text-align: right;">
                            {_render_score_badge(m_score)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Tab 6: Delete
    with det_tab6:
        st.markdown("#### Danger Zone: Permanent Candidate Removal")
        st.warning(
            "Deleting this candidate will permanently remove the profile, all attached resume files, "
            "and all screening match evaluations from the database.",
            icon="⚠️",
        )

        confirm_delete = st.checkbox(
            f"I confirm that I want to permanently delete candidate #{selected_id} ({cand_details['name']})",
            key=f"confirm_del_{selected_id}",
        )

        if st.button("🗑️ Delete Candidate Permanently", type="primary", disabled=not confirm_delete):
            deleted = candidate_service.delete_candidate(selected_id)
            if deleted:
                st.success(f"Candidate #{selected_id} deleted successfully.")
                st.rerun()
            else:
                st.error("Failed to delete candidate.")
