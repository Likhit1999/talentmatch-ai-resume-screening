"""Streamlit UI module for Shortlists & Pipeline Management in TalentMatch AI.

Provides candidate shortlisting, pipeline stage tracking, recruiter note curation,
and multi-format export capabilities (Excel and CSV).
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from services.candidate_service import CandidateService
from services.email_service import EmailService
from services.jd_service import JDService
from services.shortlist_service import ShortlistService
from services.whatsapp_service import WhatsAppService

STATUS_COLORS = {
    "shortlisted": ("#DCFCE7", "#15803D"),
    "interview_scheduled": ("#DBEAFE", "#1E40AF"),
    "on_hold": ("#FEF3C7", "#B45309"),
    "not_selected": ("#FEE2E2", "#B91C1C"),
}

def _render_stage_badge(status: str) -> str:
    """Render formatted stage badge with color styling."""
    clean_st = (status or "shortlisted").lower()
    bg, fg = STATUS_COLORS.get(clean_st, ("#F1F5F9", "#475569"))
    label = clean_st.replace("_", " ").title()
    return f"<span style='background-color: {bg}; color: {fg}; padding: 3px 10px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>{label}</span>"


def _render_score_badge(score: Optional[float]) -> str:
    """Format and color-code screening match scores."""
    if score is None:
        return "<span style='color: #94A3B8; font-size: 0.85rem;'>Not Screened</span>"
    if score >= 80.0:
        bg, fg = "#DCFCE7", "#15803D"
    elif score >= 60.0:
        bg, fg = "#DBEAFE", "#1E40AF"
    elif score >= 40.0:
        bg, fg = "#FEF3C7", "#B45309"
    else:
        bg, fg = "#FEE2E2", "#B91C1C"
    return f"<span style='background-color: {bg}; color: {fg}; padding: 3px 8px; border-radius: 6px; font-weight: 700; font-size: 0.85rem;'>{score:.1f}%</span>"


def render_shortlist() -> None:
    """Render the Candidate Shortlist and Export Management page."""
    shortlist_service = ShortlistService()
    jd_service = JDService()
    candidate_service = CandidateService()
    email_service = EmailService()
    whatsapp_service = WhatsAppService()

    # Automatically sync any matches that were marked as shortlisted in review
    shortlist_service.sync_unassigned_shortlisted_matches()

    # Load JDs for selection and filtering
    all_jds, _ = jd_service.get_all_jds(limit=200)
    jd_options = {jd.title: jd.id for jd in all_jds}

    # =========================================================================
    # 1. HEADER & ACTION CONTROLS
    # =========================================================================
    h_col1, h_col2 = st.columns([3, 1.2])

    with h_col1:
        st.markdown(
            """
            <div style="margin-bottom: 0.75rem;">
                <h2 style="color: #1E3A8A; margin: 0 0 0.25rem 0; font-weight: 700;">Candidate Shortlists & Pipeline Hub</h2>
                <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                    Curate job-specific talent pipelines, track candidates through recruitment stages,
                    reach out to candidates for salary/notice period details, and export structured talent dossiers.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with h_col2:
        st.markdown("<div style='margin-top: 0.5rem;'></div>", unsafe_allow_html=True)
        show_create = st.toggle("➕ New Shortlist", value=False, key="toggle_create_shortlist")

    # =========================================================================
    # 2. CREATE NEW SHORTLIST FORM (Collapsible)
    # =========================================================================
    if show_create:
        with st.container():
            st.markdown(
                """
                <div style="background-color: #F8FAFC; border: 1px solid #CBD5E1; border-left: 4px solid #1E40AF; border-radius: 8px; padding: 1.25rem; margin-bottom: 1.5rem;">
                    <h4 style="color: #1E3A8A; margin: 0 0 0.5rem 0;">Create New Candidate Pipeline</h4>
                    <span style="color: #64748B; font-size: 0.85rem;">Organize candidates evaluated for a specific requisition into a managed recruitment batch.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not jd_options:
                st.warning("No Job Descriptions found. Please create a Job Description first.")
            else:
                with st.form("create_shortlist_form"):
                    f_col1, f_col2 = st.columns(2)
                    with f_col1:
                        new_name = st.text_input("Shortlist Name *", placeholder="e.g. Senior Backend - Tier 1 Fast Track")
                    with f_col2:
                        selected_jd_title = st.selectbox("Target Job Requisition *", options=list(jd_options.keys()))

                    new_desc = st.text_area(
                        "Shortlist Purpose / Notes",
                        placeholder="e.g. Top candidates meeting mandatory requirements with >80% match for immediate panel interviews.",
                        height=80,
                    )

                    submit_btn = st.form_submit_button("Create Shortlist", type="primary")

                    if submit_btn:
                        if not new_name.strip():
                            st.error("Shortlist name is required.")
                        else:
                            try:
                                created = shortlist_service.create_shortlist(
                                    name=new_name.strip(),
                                    jd_id=jd_options[selected_jd_title],
                                    description=new_desc.strip() if new_desc else None,
                                    created_by="Recruiter",
                                )
                                st.success(f"Shortlist '{created['name']}' created successfully!")
                                st.session_state["selected_shortlist_id"] = created["id"]
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Failed to create shortlist: {exc}")

    # =========================================================================
    # 3. FILTERS BAR
    # =========================================================================
    filter_col1, filter_col2, filter_col3 = st.columns([3, 2, 1.5])

    with filter_col1:
        jd_filter_choices = ["All Requisitions"] + list(jd_options.keys())
        selected_jd_filter = st.selectbox("Filter by Requisition", options=jd_filter_choices, index=0)

    with filter_col2:
        status_filter = st.selectbox("Filter by Shortlist Status", options=["All", "Active", "Archived"], index=1)

    filter_jd_id = jd_options[selected_jd_filter] if selected_jd_filter != "All Requisitions" else None
    filter_status = None if status_filter == "All" else status_filter.lower()

    shortlists = shortlist_service.get_shortlists(jd_id=filter_jd_id, status=filter_status)

    with filter_col3:
        st.markdown("<div style='margin-top: 1.8rem; color: #64748B; font-weight: 600; font-size: 0.9rem;'>", unsafe_allow_html=True)
        st.markdown(f"Total: <strong>{len(shortlists)}</strong> pipeline(s)", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Empty State Check
    if not shortlists:
        st.markdown(
            """
            <div style="text-align: center; padding: 3rem 1rem; background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 10px; margin: 1.5rem 0;">
                <h3 style="color: #475569; margin-bottom: 0.5rem;">No Shortlists Available</h3>
                <p style="color: #64748B; max-width: 500px; margin: 0 auto 1.5rem auto;">
                    No shortlists match the selected filters. Use the "➕ New Shortlist" toggle above to create your first talent pipeline, or shortlist candidates from <strong>Match & Rank</strong>.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown("---")

    # =========================================================================
    # 4. SHORTLIST SELECTOR & PIPELINE DETAIL VIEW
    # =========================================================================
    shortlist_map = {
        f"#{s['id']} — {s['name']} ({s['jd_title']}) [{s['candidate_count']} candidates]": s["id"]
        for s in shortlists
    }

    # Maintain selection state
    default_idx = 0
    saved_id = st.session_state.get("selected_shortlist_id")
    if saved_id:
        for idx, (label, s_id) in enumerate(shortlist_map.items()):
            if s_id == saved_id:
                default_idx = idx
                break

    selected_label = st.selectbox(
        "Select Shortlist to Inspect & Manage:",
        options=list(shortlist_map.keys()),
        index=default_idx,
    )
    current_shortlist_id = shortlist_map[selected_label]
    st.session_state["selected_shortlist_id"] = current_shortlist_id

    # Load complete shortlist data
    shortlist_data = shortlist_service.get_shortlist(current_shortlist_id)
    stats = shortlist_service.get_shortlist_stats(current_shortlist_id)

    # Shortlist Header Card
    sh_col1, sh_col2 = st.columns([3, 1.5])
    with sh_col1:
        status_bg = "#F0FDF4" if shortlist_data["status"] == "active" else "#F8FAFC"
        status_fg = "#15803D" if shortlist_data["status"] == "active" else "#64748B"
        status_border = "#BBF7D0" if shortlist_data["status"] == "active" else "#E2E8F0"
        status_icon = "bi bi-check-circle-fill" if shortlist_data["status"] == "active" else "bi bi-archive-fill"
        st.markdown(
            f"""
            <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-left: 5px solid #1E40AF; border-radius: 10px; padding: 1.25rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(15,23,42,0.04);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="color: #0F172A; margin: 0; font-size: 1.25rem; font-weight: 700;">{shortlist_data['name']}</h3>
                    <span style="background-color: {status_bg}; color: {status_fg}; border: 1px solid {status_border}; padding: 3px 10px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;">
                        <i class="{status_icon}" style="margin-right: 4px;"></i>{shortlist_data['status'].upper()}
                    </span>
                </div>
                <div style="color: #475569; font-size: 0.9rem; margin-top: 0.4rem;">
                    <i class="bi bi-briefcase" style="color: #2563EB;"></i> <strong>Requisition:</strong> {shortlist_data['jd_title']} &nbsp;•&nbsp; 
                    <i class="bi bi-calendar" style="color: #64748B;"></i> <strong>Created:</strong> {shortlist_data['created_at']}
                </div>
                <div style="color: #64748B; font-size: 0.88rem; margin-top: 0.5rem; line-height: 1.4;">
                    {shortlist_data['description'] or 'No description entered.'}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with sh_col2:
        st.markdown(
            f"""
            <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 1rem 1.15rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(15,23,42,0.04);">
                <div style="font-weight: 700; color: #0F172A; font-size: 0.95rem; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
                    <i class="bi bi-bar-chart-fill" style="color: #2563EB;"></i> Pipeline Telemetry
                </div>
                <div style="font-size: 0.85rem; color: #334155; line-height: 1.75;">
                    <i class="bi bi-people" style="color: #2563EB;"></i> <strong>Candidates:</strong> {stats['total_candidates']}&nbsp;•&nbsp;
                    <i class="bi bi-graph-up" style="color: #16A34A;"></i> <strong>Mean Score:</strong> {stats['avg_match_score']}%<br/>
                    <span style="color: #15803D;"><i class="bi bi-check-circle-fill"></i> Shortlisted: {stats['by_status'].get('shortlisted', 0)}</span> &nbsp;•&nbsp; 
                    <span style="color: #1E40AF;"><i class="bi bi-calendar-check-fill"></i> Interview: {stats['by_status'].get('interview_scheduled', 0)}</span><br/>
                    <span style="color: #B45309;"><i class="bi bi-pause-circle-fill"></i> On Hold: {stats['by_status'].get('on_hold', 0)}</span> &nbsp;•&nbsp; 
                    <span style="color: #B91C1C;"><i class="bi bi-x-circle-fill"></i> Rejected: {stats['by_status'].get('not_selected', 0)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Action Toolbar: Export & Archive
    tool_col1, tool_col2, tool_col3, tool_col4 = st.columns([1.5, 1.5, 1.5, 2.5])

    with tool_col1:
        # Generate Excel Export
        try:
            excel_path = shortlist_service.export_shortlist(current_shortlist_id, format="excel")
            excel_bytes = Path(excel_path).read_bytes()
            st.download_button(
                label="📥 Export Excel",
                data=excel_bytes,
                file_name=Path(excel_path).name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl_excel_{current_shortlist_id}",
            )
        except Exception as ex:
            st.caption(f"Excel export error: {ex}")

    with tool_col2:
        # Generate CSV Export
        try:
            csv_path = shortlist_service.export_shortlist(current_shortlist_id, format="csv")
            csv_bytes = Path(csv_path).read_bytes()
            st.download_button(
                label="📄 Export CSV",
                data=csv_bytes,
                file_name=Path(csv_path).name,
                mime="text/csv",
                use_container_width=True,
                key=f"dl_csv_{current_shortlist_id}",
            )
        except Exception as ex:
            st.caption(f"CSV export error: {ex}")

    with tool_col3:
        if shortlist_data["status"] == "active":
            if st.button("📦 Archive Shortlist", use_container_width=True, key=f"arch_{current_shortlist_id}"):
                shortlist_service.archive_shortlist(current_shortlist_id)
                st.success("Shortlist archived.")
                st.rerun()

    st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # 5. CANDIDATE PIPELINE TABLE & STAGE MANAGEMENT
    # =========================================================================
    candidates = shortlist_data.get("candidates", [])
    available_senders = email_service.get_sender_addresses()

    st.markdown(f"#### 👥 Pipeline Candidates ({len(candidates)})")

    if not candidates:
        st.info("No candidates added to this shortlist yet. Use the section below to add candidates.")
    else:
        # Search & Filter Toolbar for Shortlist
        sf_col1, sf_col2, sf_col3 = st.columns([3, 2, 1.5])
        with sf_col1:
            shortlist_search = st.text_input(
                "Filter Candidates in Shortlist",
                placeholder="Search by name, email, or keywords...",
                key="sl_cand_search",
            )
        with sf_col2:
            stage_filter_opts = ["All Stages", "Shortlisted", "Interview Scheduled", "On Hold", "Not Selected"]
            selected_stage_filter = st.selectbox(
                "Filter by Stage",
                options=stage_filter_opts,
                index=0,
                key="sl_stage_filter",
            )

        # Apply in-memory filtering
        filtered_candidates = []
        for c in candidates:
            # Search filter
            if shortlist_search.strip():
                term = shortlist_search.strip().lower()
                c_name = (c.get("candidate_name") or "").lower()
                c_email = (c.get("email") or "").lower()
                c_notes = (c.get("recruiter_notes") or "").lower()
                if term not in c_name and term not in c_email and term not in c_notes:
                    continue

            # Stage filter
            if selected_stage_filter != "All Stages":
                expected_st = selected_stage_filter.lower().replace(" ", "_")
                if c.get("status") != expected_st:
                    continue

            filtered_candidates.append(c)

        st.caption(f"Showing **{len(filtered_candidates)}** of **{len(candidates)}** candidate(s):")

        # Table View
        table_rows = []
        for cand in filtered_candidates:
            score_val = cand.get("match_score")
            score_str = f"{score_val:.1f}%" if score_val is not None else "Not Screened"
            table_rows.append({
                "ID": cand["candidate_id"],
                "Candidate Name": cand["candidate_name"],
                "Email": cand["email"] or "—",
                "Phone": cand["phone"] or "—",
                "Match Score": score_str,
                "Category": (cand.get("match_category") or "—").replace("_", " ").title(),
                "Stage": (cand.get("status") or "shortlisted").replace("_", " ").title(),
                "Recruiter Notes": cand.get("recruiter_notes") or "—",
                "Added Date": cand.get("added_at") or "—",
            })

        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "Candidate Name": st.column_config.TextColumn(width="medium"),
                "Email": st.column_config.TextColumn(width="medium"),
                "Phone": st.column_config.TextColumn(width="small"),
                "Match Score": st.column_config.TextColumn(width="small"),
                "Category": st.column_config.TextColumn(width="small"),
                "Stage": st.column_config.TextColumn(width="medium"),
                "Recruiter Notes": st.column_config.TextColumn(width="large"),
                "Added Date": st.column_config.TextColumn(width="small"),
            },
        )

        st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

        # Interactive Candidate Action & Outreach Workspace
        with st.expander("⚡ Candidate Action & Email Outreach Workspace", expanded=True):
            cand_select_options = {
                f"#{c['candidate_id']} {c['candidate_name']} — {c['status'].replace('_', ' ').title()} ({c.get('match_score') or 0:.0f}%)": c
                for c in candidates
            }
            chosen_label = st.selectbox(
                "Select Candidate to Manage / Email:",
                options=list(cand_select_options.keys()),
                key=f"sl_sel_cand_action_{current_shortlist_id}",
            )
            cand = cand_select_options[chosen_label]

            act_col1, act_col2 = st.columns([2.5, 3])

            with act_col1:
                st.markdown(f"##### 📋 Update Stage & Notes: **{cand['candidate_name']}**")
                stage_options = ["shortlisted", "interview_scheduled", "on_hold", "not_selected"]
                cur_idx = stage_options.index(cand["status"]) if cand["status"] in stage_options else 0
                new_stage = st.selectbox(
                    "Pipeline Stage",
                    options=stage_options,
                    index=cur_idx,
                    format_func=lambda x: x.replace("_", " ").title(),
                    key=f"stage_sel_tbl_{cand['candidate_id']}",
                )

                new_notes = st.text_area(
                    "Recruiter Evaluation Notes",
                    value=cand["recruiter_notes"] or "",
                    placeholder="e.g. Completed initial technical screen. Highly recommended for hiring manager round.",
                    height=90,
                    key=f"notes_in_tbl_{cand['candidate_id']}",
                )

                b_c1, b_c2 = st.columns(2)
                with b_c1:
                    if st.button("💾 Save Stage & Notes", key=f"save_cand_tbl_{cand['candidate_id']}", type="primary", use_container_width=True):
                        shortlist_service.update_candidate_status(
                            shortlist_id=current_shortlist_id,
                            candidate_id=cand["candidate_id"],
                            status=new_stage,
                            notes=new_notes,
                        )
                        st.success(f"Updated {cand['candidate_name']}!")
                        st.rerun()

                with b_c2:
                    if st.button("🗑️ Remove Candidate", key=f"rem_tbl_{current_shortlist_id}_{cand['candidate_id']}", use_container_width=True):
                        removed = shortlist_service.remove_candidate(current_shortlist_id, cand["candidate_id"])
                        if removed:
                            st.success(f"Removed {cand['candidate_name']} from shortlist.")
                            st.rerun()

            with act_col2:
                st.markdown(f"##### 📢 Candidate Outreach Hub: **{cand['candidate_name']}**")
                tab_wa, tab_email = st.tabs(["💬 WhatsApp Outreach", "✉️ Email Outreach"])

                # ---------------------------------------------------------
                # TAB 1: WHATSAPP OUTREACH
                # ---------------------------------------------------------
                with tab_wa:
                    if not whatsapp_service.is_enabled():
                        st.info("ℹ️ WhatsApp outreach is currently disabled in configuration (WHATSAPP_ENABLED=false).")
                    else:
                        raw_cand_phone = cand.get("phone") or ""
                        if not raw_cand_phone.strip():
                            st.warning("⚠️ Candidate has no phone number on file. Please enter their phone number below to enable WhatsApp outreach.")

                        wa_phone_input = st.text_input(
                            "Candidate WhatsApp Number:",
                            value=raw_cand_phone,
                            placeholder="+91 9876543210 (include country code)",
                            key=f"wa_phone_tbl_{cand['candidate_id']}",
                            help="Candidate's phone number. Standard 10-digit Indian numbers automatically use +91.",
                        )

                        wa_recruiter_name = st.text_input(
                            "Your Name / Sign-off:",
                            value="Talent Acquisition Team",
                            key=f"wa_recruiter_tbl_{cand['candidate_id']}",
                        )

                        wa_templates = whatsapp_service.get_templates(
                            candidate_name=cand["candidate_name"],
                            job_title=shortlist_data.get("jd_title", "Target Role"),
                            recruiter_name=wa_recruiter_name.strip() or "Talent Acquisition Team",
                        )

                        wa_tpl_key = st.selectbox(
                            "Select Message Template:",
                            options=list(wa_templates.keys()),
                            format_func=lambda k: wa_templates[k]["name"],
                            key=f"wa_tpl_sel_{cand['candidate_id']}",
                        )

                        default_wa_body = wa_templates[wa_tpl_key]["message"]

                        # Ensure switching templates immediately updates the text area in Streamlit
                        last_tpl_tracker = f"_last_wa_tpl_{cand['candidate_id']}"
                        last_recruiter_tracker = f"_last_wa_rec_{cand['candidate_id']}"
                        body_key = f"wa_body_tbl_{cand['candidate_id']}"
                        clean_recruiter = wa_recruiter_name.strip()

                        if (
                            st.session_state.get(last_tpl_tracker) != wa_tpl_key
                            or st.session_state.get(last_recruiter_tracker) != clean_recruiter
                        ):
                            st.session_state[body_key] = default_wa_body
                            st.session_state[last_tpl_tracker] = wa_tpl_key
                            st.session_state[last_recruiter_tracker] = clean_recruiter

                        wa_body = st.text_area(
                            "WhatsApp Message Body (supports *bold*, _italic_):",
                            value=default_wa_body,
                            height=180,
                            key=body_key,
                        )

                        # Quick reset to default template text if needed
                        if st.button("↺ Reset Message to Template Default", key=f"btn_reset_wa_{cand['candidate_id']}", help="Revert edits back to standard template text"):
                            st.session_state[body_key] = default_wa_body
                            st.rerun()

                        redirect_info = whatsapp_service.generate_whatsapp_redirect(wa_phone_input, wa_body)
                        wa_link = redirect_info.get("url")

                        # Preview bubble
                        st.markdown(
                            f"""
                            <div style="background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px; padding: 0.65rem 0.85rem; margin-bottom: 0.75rem;">
                                <div style="font-size: 0.78rem; color: #166534; font-weight: 700; margin-bottom: 0.2rem;">📱 WhatsApp Message Preview:</div>
                                <div style="font-size: 0.82rem; color: #1e293b; white-space: pre-wrap; font-family: sans-serif; line-height: 1.4;">{wa_body}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if not redirect_info.get("success"):
                            st.warning(f"⚠️ {redirect_info.get('error') or 'Please provide a valid phone number.'}")

                        wa_c1, wa_c2 = st.columns([1.3, 1])
                        with wa_c1:
                            if wa_link:
                                st.link_button(
                                    "💬 Contact on WhatsApp",
                                    url=wa_link,
                                    type="primary",
                                    use_container_width=True,
                                    help="Opens WhatsApp Web or mobile app. Review the prefilled message and press Send manually.",
                                )
                            else:
                                st.button(
                                    "💬 Contact on WhatsApp",
                                    disabled=True,
                                    key=f"wa_dis_btn_{cand['candidate_id']}",
                                    use_container_width=True,
                                    help="Provide valid phone number with country code",
                                )

                        with wa_c2:
                            if st.button("📝 Record Outreach Note", key=f"wa_send_btn_{cand['candidate_id']}", type="secondary", use_container_width=True):
                                if not wa_link:
                                    st.error("Cannot record outreach: Invalid phone number.")
                                else:
                                    now_str = datetime.now().strftime("%b %d, %H:%M")
                                    existing_notes = cand.get("recruiter_notes") or ""
                                    update_note = f"[WhatsApp Outreach on {now_str}]: Opened WhatsApp to contact candidate regarding {shortlist_data.get('jd_title', 'position')} (Manual send pending in WhatsApp)"
                                    combined_notes = f"{existing_notes}\n{update_note}".strip() if existing_notes else update_note
                                    shortlist_service.update_candidate_status(
                                        shortlist_id=current_shortlist_id,
                                        candidate_id=cand["candidate_id"],
                                        notes=combined_notes,
                                    )
                                    st.info(f"Outreach attempt noted in candidate pipeline records. Please review and send in WhatsApp.")

                        st.caption("ℹ️ Generates a direct WhatsApp link. HR reviews the prefilled message and sends it manually.")

                # ---------------------------------------------------------
                # TAB 2: EMAIL OUTREACH
                # ---------------------------------------------------------
                with tab_email:
                    tpl = email_service.generate_candidate_inquiry_template(
                        candidate_name=cand["candidate_name"],
                        job_title=shortlist_data["jd_title"],
                    )

                    from_email_choice = st.selectbox(
                        "From Mailbox:",
                        options=available_senders,
                        key=f"em_sender_tbl_{cand['candidate_id']}",
                        help="Select sender address configured in SENDER_EMAILS in .env",
                    )
                    to_email_input = st.text_input(
                        "To Candidate:",
                        value=cand["email"] or "",
                        placeholder="candidate@example.com",
                        key=f"em_to_tbl_{cand['candidate_id']}",
                    )
                    em_subject = st.text_input(
                        "Subject:",
                        value=tpl["subject"],
                        key=f"em_sub_tbl_{cand['candidate_id']}",
                    )
                    em_body = st.text_area(
                        "Message Body:",
                        value=tpl["body"],
                        height=200,
                        key=f"em_body_tbl_{cand['candidate_id']}",
                    )

                    if st.button("🚀 Send Outreach Email", key=f"em_send_btn_tbl_{cand['candidate_id']}", type="primary"):
                        if not to_email_input.strip():
                            st.error("Please provide a valid recipient email address.")
                        else:
                            with st.spinner("Dispatching outreach email..."):
                                send_res = email_service.send_email(
                                    to_email=to_email_input.strip(),
                                    subject=em_subject.strip(),
                                    body=em_body,
                                    from_email=from_email_choice,
                                )
                            if send_res.get("success"):
                                st.success(send_res.get("message"))
                            else:
                                st.error(send_res.get("message"))

    # =========================================================================

    # =========================================================================
    # 6. ADD CANDIDATE TO SHORTLIST CONTROLS
    # =========================================================================
    st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
    with st.expander("➕ Add Candidate to this Shortlist", expanded=False):
        # Fetch candidate pool not currently in this shortlist
        existing_cand_ids = {c["candidate_id"] for c in candidates}
        all_candidates, _ = candidate_service.get_candidates(limit=300)
        available_cands = [c for c in all_candidates if c["id"] not in existing_cand_ids]

        if not available_cands:
            st.info("All candidates in the directory are already present in this shortlist.")
        else:
            add_col1, add_col2, add_col3 = st.columns([3, 3, 1.5])

            with add_col1:
                cand_select_map = {
                    f"#{c['id']} — {c['name']} ({c['email'] or 'No Email'})": c["id"]
                    for c in available_cands
                }
                selected_cand_label = st.selectbox("Select Candidate", options=list(cand_select_map.keys()))
                selected_cand_id = cand_select_map[selected_cand_label]

            with add_col2:
                add_notes = st.text_input("Initial Recruiter Notes (Optional)", placeholder="e.g. Strong match on React & Python")

            with add_col3:
                st.write("")
                st.write("")
                if st.button("Add to Pipeline", type="primary", use_container_width=True):
                    try:
                        shortlist_service.add_candidate(
                            shortlist_id=current_shortlist_id,
                            candidate_id=selected_cand_id,
                            notes=add_notes,
                        )
                        st.success("Candidate added to shortlist!")
                        st.rerun()
                    except Exception as add_err:
                        st.error(f"Failed to add candidate: {add_err}")
