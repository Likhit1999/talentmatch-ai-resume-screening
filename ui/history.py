"""Screening history and governance audit trail module for TalentMatch AI.

Provides execution history for automated screening batches, per-requisition evaluations,
exportable audit reports, and full security/data governance audit logs.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from services.audit_service import AuditService
from services.export_service import ExportService


def _render_status_badge(status: str) -> str:
    """Format batch execution status badge."""
    clean_st = (status or "pending").lower()
    if clean_st in ("completed", "success"):
        bg, fg = "#DCFCE7", "#15803D"
    elif clean_st in ("processing", "running"):
        bg, fg = "#DBEAFE", "#1E40AF"
    elif clean_st == "failed":
        bg, fg = "#FEE2E2", "#B91C1C"
    else:
        bg, fg = "#FEF3C7", "#B45309"
    return f"<span style='background-color: {bg}; color: {fg}; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>{status.upper()}</span>"


def render_screening_history() -> None:
    """Render the Screening Batches History and Governance Audit Trail page."""
    audit_service = AuditService()
    export_service = ExportService()

    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h2 style="color: #1E3A8A; margin: 0 0 0.25rem 0; font-weight: 700;">Screening History & Governance Audit Trail</h2>
            <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                Inspect historical automated screening batches, review requirement breakdown telemetry,
                download multi-sheet compliance reports, and audit all critical system actions.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_batches, tab_audit, tab_activity = st.tabs([
        "⚡ Screening Batches & Results",
        "🛡️ System Audit Log",
        "⏱️ Live Activity Stream",
    ])

    # =========================================================================
    # TAB 1: SCREENING BATCHES
    # =========================================================================
    with tab_batches:
        batches_page_size = 10
        cur_batch_page = st.session_state.get("history_batch_page", 1)
        b_offset = (cur_batch_page - 1) * batches_page_size

        batches, total_batch_count = audit_service.get_screening_history(
            offset=b_offset, limit=batches_page_size
        )

        total_b_pages = max(1, (total_batch_count + batches_page_size - 1) // batches_page_size)

        # Batch telemetry top metrics
        tot_screened = sum(b.get("candidate_count", 0) for b in batches)
        tot_evals = sum(b.get("match_count", 0) for b in batches)
        completed_cnt = sum(1 for b in batches if b.get("status") == "completed")

        bm1, bm2, bm3, bm4 = st.columns(4)
        with bm1:
            st.metric("Total Batches", total_batch_count)
        with bm2:
            st.metric("Candidates Screened", tot_screened)
        with bm3:
            st.metric("Evaluations Generated", tot_evals)
        with bm4:
            st.metric("Completed Batches", completed_cnt)

        st.markdown("<div style='margin-bottom: 1rem;'></div>", unsafe_allow_html=True)

        if not batches:
            st.markdown(
                """
                <div style="text-align: center; padding: 3rem 1rem; background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 10px; margin: 1rem 0;">
                    <h3 style="color: #475569; margin-bottom: 0.5rem;">No Screening Batches Recorded</h3>
                    <p style="color: #64748B; max-width: 500px; margin: 0 auto;">
                        Screening executions will appear here once candidates have been evaluated against Job Descriptions.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            # Batches Table Overview
            table_rows = []
            for b in batches:
                jds_str = ", ".join(b["jd_titles"]) if b["jd_titles"] else "All Active"
                table_rows.append({
                    "Batch ID": b["id"],
                    "Name": b["name"],
                    "Target Requisitions": jds_str,
                    "Candidates Screened": b["candidate_count"],
                    "Matches": b["match_count"],
                    "Average Score": f"{b['average_score']:.1f}%",
                    "Method": b["matching_method"],
                    "Status": b["status"].capitalize(),
                    "Screening Date": b["created_at"],
                })

            st.dataframe(
                table_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Batch ID": st.column_config.NumberColumn("ID", width="small"),
                    "Name": st.column_config.TextColumn("Batch Name", width="medium"),
                    "Target Requisitions": st.column_config.TextColumn("Requisitions", width="large"),
                    "Candidates Screened": st.column_config.NumberColumn("Candidates", width="small"),
                    "Matches": st.column_config.NumberColumn("Matches", width="small"),
                    "Average Score": st.column_config.TextColumn("Avg Score", width="small"),
                    "Method": st.column_config.TextColumn("Method", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Screening Date": st.column_config.TextColumn("Date", width="medium"),
                },
            )

            # Pagination controls
            p1, p2, p3, p4, p5 = st.columns([2, 1.5, 2, 1.5, 2])
            with p2:
                if st.button("⬅️ Previous", disabled=(cur_batch_page <= 1), key="batch_prev_btn", use_container_width=True):
                    st.session_state["history_batch_page"] = max(1, cur_batch_page - 1)
                    st.rerun()
            with p3:
                st.markdown(
                    f"<div style='text-align: center; padding-top: 0.4rem; color: #475569; font-weight: 600;'>"
                    f"Page {cur_batch_page} of {total_b_pages}</div>",
                    unsafe_allow_html=True,
                )
            with p4:
                if st.button("Next ➡️", disabled=(cur_batch_page >= total_b_pages), key="batch_next_btn", use_container_width=True):
                    st.session_state["history_batch_page"] = min(total_b_pages, cur_batch_page + 1)
                    st.rerun()

            st.markdown("---")

            # Batch Detail & Multi-Sheet Report Generation
            st.markdown("#### 🔍 Batch Results Deep-Dive & Report Generation")

            batch_choices = {f"Batch #{b['id']} — {b['name']} ({b['created_at']})": b["id"] for b in batches}
            selected_b_label = st.selectbox("Select Batch to Inspect:", options=list(batch_choices.keys()), index=0)
            selected_b_id = batch_choices[selected_b_label]

            # Find matching batch dict
            b_detail = next((b for b in batches if b["id"] == selected_b_id), None)
            if b_detail:
                bd_col1, bd_col2 = st.columns([3, 1.5])
                with bd_col1:
                    st.markdown(
                        f"""
                        <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-left: 4px solid #1E40AF; border-radius: 8px; padding: 1.25rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <h4 style="color: #1E3A8A; margin: 0;">{b_detail['name']}</h4>
                                {_render_status_badge(b_detail['status'])}
                            </div>
                            <div style="color: #475569; font-size: 0.9rem; margin-top: 0.5rem; line-height: 1.6;">
                                📋 <strong>Target Job(s):</strong> {', '.join(b_detail['jd_titles']) or 'All'}<br/>
                                ⚙️ <strong>Algorithm:</strong> <code>{b_detail['matching_method']}</code> &nbsp;|&nbsp; 
                                👤 <strong>Initiator:</strong> {b_detail['created_by']}<br/>
                                📅 <strong>Initiated:</strong> {b_detail['created_at']} &nbsp;|&nbsp;
                                ⏱️ <strong>Completed:</strong> {b_detail['completed_at'] or 'In progress'}
                            </div>
                            <div style="color: #64748B; font-size: 0.85rem; margin-top: 0.5rem;">
                                {b_detail['description']}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with bd_col2:
                    st.markdown(
                        f"""
                        <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 1.25rem;">
                            <div style="font-weight: 700; color: #1E3A8A; font-size: 0.95rem; margin-bottom: 0.5rem;">Score Distribution</div>
                            <div style="font-size: 0.88rem; line-height: 1.8;">
                                🟢 <strong>Strong Matches (≥80%):</strong> {b_detail['strong_matches']}<br/>
                                🔵 <strong>Potential Matches (60-79%):</strong> {b_detail['potential_matches']}<br/>
                                🟡 <strong>Needs Review (<60%):</strong> {b_detail['review_matches']}<br/>
                                📈 <strong>Average Score:</strong> {b_detail['average_score']}%
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)

                # Export Comprehensive Report Button
                try:
                    report_path = export_service.generate_screening_report(selected_b_id)
                    report_bytes = Path(report_path).read_bytes()
                    st.download_button(
                        label="📥 Download Multi-Sheet Screening Report (Excel)",
                        data=report_bytes,
                        file_name=Path(report_path).name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                        key=f"dl_batch_rep_{selected_b_id}",
                    )
                    st.caption("Includes Executive Summary, Detailed Candidate Results, Score Distribution, and Requirement Analysis.")
                except Exception as rep_err:
                    st.warning(f"Report could not be generated: {rep_err}")

    # =========================================================================
    # TAB 2: SYSTEM AUDIT LOG
    # =========================================================================
    with tab_audit:
        st.markdown("#### 🛡️ Compliance & Operations Audit Trail")
        st.markdown(
            "<span style='color: #64748B; font-size: 0.9rem;'>"
            "Immutable log of user operations, CRUD modifications, pipeline transitions, and export generations."
            "</span>",
            unsafe_allow_html=True,
        )

        # Audit Filters
        af_col1, af_col2, af_col3, af_col4 = st.columns([2.5, 2.5, 2, 1.2])

        with af_col1:
            entity_opts = ["All", "JobDescription", "Candidate", "Shortlist", "ScreeningBatch", "ApplicationSetting"]
            sel_entity = st.selectbox("Entity Type", options=entity_opts, index=0)

        with af_col2:
            action_opts = ["All", "create", "update", "delete", "add_candidate", "remove_candidate", "update_candidate_status", "archive", "export"]
            sel_action = st.selectbox("Action", options=action_opts, index=0)

        with af_col3:
            filter_id_str = st.text_input("Entity ID (Optional)", placeholder="e.g. 1")
            filter_entity_id = int(filter_id_str.strip()) if filter_id_str.strip().isdigit() else None

        with af_col4:
            st.write("")
            st.write("")
            if st.button("Reset", key="reset_audit_filters", use_container_width=True):
                st.session_state["audit_page"] = 1
                st.rerun()

        # Audit query
        audit_page_size = 20
        cur_audit_page = st.session_state.get("audit_page", 1)
        a_offset = (cur_audit_page - 1) * audit_page_size

        logs, total_log_count = audit_service.get_audit_log(
            entity_type=None if sel_entity == "All" else sel_entity,
            action=None if sel_action == "All" else sel_action,
            entity_id=filter_entity_id,
            offset=a_offset,
            limit=audit_page_size,
        )

        total_a_pages = max(1, (total_log_count + audit_page_size - 1) // audit_page_size)

        st.caption(f"Showing {len(logs)} of {total_log_count} log entries (Page {cur_audit_page} of {total_a_pages})")

        if not logs:
            st.info("No audit log records match the selected filters.")
        else:
            log_table = []
            for item in logs:
                details_preview = str(item["details"])[:60] + "..." if len(str(item["details"])) > 60 else str(item["details"])
                entity_id_display = str(item["entity_id"]) if item.get("entity_id") is not None else "—"
                log_table.append({
                    "ID": item["id"],
                    "Timestamp": item["performed_at"],
                    "User": item.get("performed_by") or "System",
                    "Entity": item["entity_type"],
                    "Entity ID": entity_id_display,
                    "Action": item["action"].upper(),
                    "Details Preview": details_preview,
                })

            st.dataframe(
                log_table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ID": st.column_config.NumberColumn(width="small"),
                    "Timestamp": st.column_config.TextColumn(width="medium"),
                    "User": st.column_config.TextColumn(width="small"),
                    "Entity": st.column_config.TextColumn(width="small"),
                    "Entity ID": st.column_config.TextColumn(width="small"),
                    "Action": st.column_config.TextColumn(width="small"),
                    "Details Preview": st.column_config.TextColumn(width="large"),
                },
            )

            # Audit Pagination
            ap1, ap2, ap3, ap4, ap5 = st.columns([2, 1.5, 2, 1.5, 2])
            with ap2:
                if st.button("⬅️ Previous", disabled=(cur_audit_page <= 1), key="aud_prev_btn", use_container_width=True):
                    st.session_state["audit_page"] = max(1, cur_audit_page - 1)
                    st.rerun()
            with ap3:
                st.markdown(
                    f"<div style='text-align: center; padding-top: 0.4rem; color: #475569; font-weight: 600;'>"
                    f"Page {cur_audit_page} of {total_a_pages}</div>",
                    unsafe_allow_html=True,
                )
            with ap4:
                if st.button("Next ➡️", disabled=(cur_audit_page >= total_a_pages), key="aud_next_btn", use_container_width=True):
                    st.session_state["audit_page"] = min(total_a_pages, cur_audit_page + 1)
                    st.rerun()

            # Expandable Raw Event Inspector
            with st.expander("🔍 Inspect Full Event Payload by Log ID"):
                inspect_id_str = st.text_input("Enter Log ID to inspect JSON details:", placeholder="e.g. 5")
                if inspect_id_str.strip().isdigit():
                    insp_id = int(inspect_id_str.strip())
                    selected_log = next((l for l in logs if l["id"] == insp_id), None)
                    if selected_log:
                        st.json(selected_log["details"])
                    else:
                        st.caption("Event not in current page results.")

    # =========================================================================
    # TAB 3: LIVE ACTIVITY STREAM
    # =========================================================================
    with tab_activity:
        st.markdown("#### ⏱️ Real-Time Activity Feed")
        st.markdown("<span style='color: #64748B; font-size: 0.9rem;'>Chronological timeline of recent platform events.</span>", unsafe_allow_html=True)

        recent_activity = audit_service.get_recent_activity(limit=25)

        if not recent_activity:
            st.info("No system activity recorded yet.")
        else:
            for act in recent_activity:
                st.markdown(
                    f"""
                    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-left: 4px solid #1E40AF; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 0.6rem; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-size: 1.15rem; margin-right: 0.5rem;">{act['icon']}</span>
                            <span style="color: #0F172A; font-weight: 600; font-size: 0.92rem;">{act['summary']}</span>
                            <div style="color: #64748B; font-size: 0.8rem; margin-top: 0.2rem; margin-left: 1.8rem;">
                                Performed by <strong>{act['user']}</strong> &nbsp;•&nbsp; Timestamp: {act['timestamp']}
                            </div>
                        </div>
                        <div style="color: #64748B; font-size: 0.82rem; font-weight: 600; white-space: nowrap; margin-left: 1rem;">
                            {act['time_ago']}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
