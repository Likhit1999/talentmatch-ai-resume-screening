"""Streamlit UI module for Resume Upload and Batch Ingestion in TalentMatch AI.

Provides multi-format file drag-and-drop, raw text paste parsing,
batch deduplication, progress tracking, and recent upload inspection.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import streamlit as st

from config.settings import get_settings
from services.candidate_service import CandidateService
from services.jd_service import JDService


def _mask_email(email: Optional[str]) -> str:
    """Mask email username for data privacy compliance."""
    if not email or "@" not in email:
        return "—"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked = user[0] + "*"
    else:
        masked = user[0] + "***" + user[-1]
    return f"{masked}@{domain}"


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into readable KB/MB string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


def _render_status_badge(status: str) -> str:
    """Generate HTML badge for candidate or file status with Bootstrap Icons."""
    st_clean = (status or "unknown").lower()
    if st_clean in ("new", "parsed", "success"):
        return "<span style='background-color: #F0FDF4; color: #15803D; border: 1px solid #BBF7D0; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'><i class='bi bi-check-circle-fill' style='margin-right: 4px;'></i>Parsed</span>"
    elif st_clean == "duplicate":
        return "<span style='background-color: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'><i class='bi bi-copy' style='margin-right: 4px;'></i>Duplicate</span>"
    elif st_clean == "warning":
        return "<span style='background-color: #FFF7ED; color: #C2410C; border: 1px solid #FED7AA; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'><i class='bi bi-exclamation-triangle-fill' style='margin-right: 4px;'></i>Warning</span>"
    elif st_clean == "failed":
        return "<span style='background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'><i class='bi bi-x-circle-fill' style='margin-right: 4px;'></i>Failed</span>"
    else:
        return f"<span style='background-color: #F8FAFC; color: #475569; border: 1px solid #E2E8F0; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'>{status}</span>"


def render_resume_upload() -> None:
    """Render the Resume Upload and Parsing interface."""
    candidate_service = CandidateService()
    jd_service = JDService()
    settings = get_settings()

    # Load active JD titles for suggested job categories
    all_jds, _ = jd_service.get_all_jds(limit=100)
    jd_titles = [jd.title for jd in all_jds]
    category_suggestions = ["General / Unassigned"] + jd_titles + [
        "QA Engineer / Automation",
        "Frontend Developer",
        "Backend Developer",
        "Full Stack Developer",
        "DevOps / Cloud Engineer",
        "Data Scientist / AI Engineer",
        "Product Manager",
    ]
    # Remove duplicates preserving order
    seen = set()
    category_choices = []
    for c in category_suggestions:
        if c not in seen:
            seen.add(c)
            category_choices.append(c)

    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h2 style="color: #1E3A8A; margin: 0 0 0.35rem 0;">Resume Upload & Document Ingestion</h2>
            <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                Upload candidate resumes individually, in bulk multi-file batches, or as compressed ZIP archives.
                Categorize candidate batches by target role (e.g. QA profiles, Backend) to streamline subsequent screening.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_upload, tab_zip, tab_paste = st.tabs([
        "📁 Multi-File Upload",
        "📦 Bulk ZIP Upload",
        "📝 Paste Resume Text",
    ])

    # ==========================================
    # TAB 1: MULTI-FILE UPLOAD (BATCH)
    # ==========================================
    with tab_upload:
        cat_col1, cat_col2 = st.columns([2.5, 2.5])
        with cat_col1:
            selected_cat = st.selectbox(
                "Target Role / Batch Category (Optional):",
                options=category_choices,
                index=0,
                key="multi_cat_select",
                help="Categorizing resumes by job role allows targeted screening later without testing unrelated profiles.",
            )
        with cat_col2:
            custom_cat = st.text_input(
                "Or enter custom role tag:",
                placeholder="e.g. Senior QA Automation Engineer",
                key="multi_custom_cat",
            )

        active_batch_category = (
            custom_cat.strip()
            if custom_cat.strip()
            else (selected_cat if selected_cat != "General / Unassigned" else None)
        )

        st.markdown("#### Select Resume Documents")
        uploaded_files = st.file_uploader(
            "Choose resume files",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            help=f"Supported file extensions: PDF, DOCX, TXT. Max limit per file: {settings.MAX_FILE_SIZE_MB}MB.",
            label_visibility="collapsed",
            key="multi_file_uploader",
        )

        if uploaded_files:
            total_count = len(uploaded_files)
            total_size_bytes = sum(f.size for f in uploaded_files)

            c1, c2, c3 = st.columns([2, 2, 2])
            with c1:
                st.caption(f"**Files Selected:** {total_count}")
            with c2:
                st.caption(f"**Combined Size:** {_format_bytes(total_size_bytes)}")
            with c3:
                st.caption(f"**Assigned Role:** `{active_batch_category or 'General'}`")

            if st.button("🚀 Process Resumes", type="primary", use_container_width=False, key="btn_proc_multi"):
                progress_bar = st.progress(0, text="Starting resume parsing pipeline...")
                status_box = st.empty()

                processed_results = []
                success_count = 0
                dup_count = 0
                fail_count = 0

                for i, file_obj in enumerate(uploaded_files):
                    status_box.markdown(f"**Processing ({i+1}/{total_count}):** `{file_obj.name}`")
                    file_bytes = file_obj.read()
                    res = candidate_service.process_uploaded_file(
                        file_bytes,
                        file_obj.name,
                        job_category=active_batch_category,
                    )
                    res["filename"] = file_obj.name
                    processed_results.append(res)

                    if res["status"] == "duplicate":
                        dup_count += 1
                    elif res["success"]:
                        success_count += 1
                    else:
                        fail_count += 1

                    progress_bar.progress((i + 1) / total_count, text=f"Processed {i+1} of {total_count} files")

                progress_bar.empty()
                status_box.empty()

                st.session_state["last_upload_results"] = {
                    "total": total_count,
                    "success": success_count,
                    "duplicate": dup_count,
                    "failed": fail_count,
                    "results": processed_results,
                    "category": active_batch_category,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

        # Display upload results if present in session_state
        if "last_upload_results" in st.session_state:
            res_data = st.session_state["last_upload_results"]
            st.markdown("---")
            st.markdown("#### Ingestion Results Summary")

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total Files", res_data["total"])
            with m2:
                st.metric("✅ Successfully Added", res_data["success"])
            with m3:
                st.metric("⚠️ Duplicates Skipped", res_data["duplicate"])
            with m4:
                st.metric("❌ Failures", res_data["failed"])

            if res_data.get("category"):
                st.caption(f"Tagged as Role: **{res_data['category']}** | Processed at {res_data['timestamp']}")
            else:
                st.caption(f"Processed at {res_data['timestamp']}")

            with st.expander("🔍 Detailed Ingestion Breakdown", expanded=True):
                for item in res_data["results"]:
                    col_file, col_status, col_name, col_action = st.columns([3, 1.5, 2.5, 1.5])
                    with col_file:
                        st.markdown(f"**{item['filename']}**")
                        if item.get("message") and item["message"] != f"Successfully parsed '{item['filename']}'":
                            st.caption(item["message"])
                    with col_status:
                        st.markdown(_render_status_badge(item["status"]), unsafe_allow_html=True)
                    with col_name:
                        st.write(item.get("candidate_name") or "—")
                    with col_action:
                        if item.get("status") == "failed" and item.get("candidate_id"):
                            cand_id = item["candidate_id"]
                            if st.button("Retry", key=f"retry_btn_{cand_id}_{item['filename']}"):
                                retry_res = candidate_service.retry_failed(cand_id)
                                if retry_res["success"]:
                                    st.success(f"Retried candidate #{cand_id} successfully!")
                                    st.rerun()
                                else:
                                    st.error(retry_res["message"])
                        elif item.get("warnings"):
                            st.caption(f"{len(item['warnings'])} warning(s)")

                    if item.get("warnings"):
                        with st.container():
                            for w in item["warnings"]:
                                st.warning(f"⚠️ {w}", icon="⚠️")

            if st.button("Clear Results", key="clear_res_multi"):
                del st.session_state["last_upload_results"]
                st.rerun()

    # ==========================================
    # TAB 2: BULK ZIP UPLOAD
    # ==========================================
    with tab_zip:
        st.markdown("#### 📦 Bulk ZIP Archive Ingestion")
        st.info(
            "💡 **ZIP Bulk Ingestion:** Upload a single `.zip` file containing tens or hundreds of resumes (.pdf, .docx, .txt). "
            "TalentMatch AI will unpack the archive and parse each candidate resume individually.",
            icon="📦",
        )

        zip_cat1, zip_cat2 = st.columns([2.5, 2.5])
        with zip_cat1:
            selected_zip_cat = st.selectbox(
                "Target Role / Batch Category for this Archive:",
                options=category_choices,
                index=0,
                key="zip_cat_select",
                help="Tag all resumes inside this ZIP file with a specific role, e.g. 'QA Profiles'.",
            )
        with zip_cat2:
            custom_zip_cat = st.text_input(
                "Or enter custom role for ZIP contents:",
                placeholder="e.g. QA Automation Team",
                key="zip_custom_cat",
            )

        active_zip_category = (
            custom_zip_cat.strip()
            if custom_zip_cat.strip()
            else (selected_zip_cat if selected_zip_cat != "General / Unassigned" else None)
        )

        uploaded_zip = st.file_uploader(
            "Choose a ZIP archive containing resumes",
            type=["zip"],
            accept_multiple_files=False,
            help="Upload a .zip file containing PDF, DOCX, or TXT resumes.",
            key="zip_uploader",
        )

        if uploaded_zip:
            zip_bytes = uploaded_zip.read()
            st.caption(f"**Archive:** `{uploaded_zip.name}` ({_format_bytes(len(zip_bytes))}) | Target Role: `{active_zip_category or 'General'}`")

            if st.button("🚀 Unpack & Ingest ZIP Resumes", type="primary", key="btn_proc_zip"):
                with st.spinner("Unpacking archive and processing individual resumes..."):
                    zip_res = candidate_service.process_zip_upload(
                        zip_bytes=zip_bytes,
                        zip_filename=uploaded_zip.name,
                        job_category=active_zip_category,
                    )

                st.session_state["last_zip_results"] = {
                    "data": zip_res,
                    "filename": uploaded_zip.name,
                    "category": active_zip_category,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

        if "last_zip_results" in st.session_state:
            z_payload = st.session_state["last_zip_results"]
            z_data = z_payload["data"]
            st.markdown("---")
            st.markdown(f"#### Results for `{z_payload['filename']}`")

            zm1, zm2, zm3, zm4 = st.columns(4)
            with zm1:
                st.metric("Resumes in Archive", z_data["total"])
            with zm2:
                st.metric("✅ Successfully Parsed", z_data["success_count"])
            with zm3:
                st.metric("⚠️ Duplicates Skipped", z_data["duplicate_count"])
            with zm4:
                st.metric("❌ Failures", z_data["failed_count"])

            if z_payload.get("category"):
                st.caption(f"Role Tag: **{z_payload['category']}** | Ingested at {z_payload['timestamp']}")

            if z_data.get("archive_warnings"):
                for aw in z_data["archive_warnings"]:
                    st.caption(f"ℹ️ {aw}")

            with st.expander("🔍 View Processed Candidates from Archive", expanded=True):
                for item in z_data["results"]:
                    col_file, col_status, col_name = st.columns([3, 1.5, 2.5])
                    with col_file:
                        st.markdown(f"**{item['filename']}**")
                        if item.get("inner_path") and item["inner_path"] != item["filename"]:
                            st.caption(f"Path in ZIP: {item['inner_path']}")
                    with col_status:
                        st.markdown(_render_status_badge(item["status"]), unsafe_allow_html=True)
                    with col_name:
                        st.write(item.get("candidate_name") or "—")

            if st.button("Clear ZIP Results", key="clear_res_zip"):
                del st.session_state["last_zip_results"]
                st.rerun()

    # ==========================================
    # TAB 3: PASTE RESUME TEXT
    # ==========================================
    with tab_paste:
        st.markdown("#### Paste Resume Text")
        st.info(
            "💡 **Batch Tip:** You can paste one resume or multiple resumes at once. "
            "To submit multiple candidate resumes in a single paste, separate them with a delimiter line like `---` or `====`.",
            icon="ℹ️",
        )

        p_cat1, p_cat2 = st.columns([2.5, 2.5])
        with p_cat1:
            selected_paste_cat = st.selectbox(
                "Role / Category for Pasted Content:",
                options=category_choices,
                index=0,
                key="paste_cat_select",
            )
        with p_cat2:
            custom_paste_cat = st.text_input(
                "Or custom role:",
                placeholder="e.g. QA Automation",
                key="paste_custom_cat",
            )

        active_paste_category = (
            custom_paste_cat.strip()
            if custom_paste_cat.strip()
            else (selected_paste_cat if selected_paste_cat != "General / Unassigned" else None)
        )

        pasted_content = st.text_area(
            "Resume text content",
            height=230,
            placeholder="John Doe\nSoftware Engineer\njohn.doe@example.com | (555) 123-4567\n\nSkills: Python, FastAPI, React, PostgreSQL, Docker\n\nExperience:\nSenior Developer at Acme Corp (2020 - Present)\nBuilt scalable APIs and microservices...\n\n---\n\nJane Smith\nQA Automation Engineer\njane.smith@example.com\n...",
            label_visibility="collapsed",
            key="paste_area_input",
        )

        if st.button("⚡ Process Text", type="primary", key="btn_proc_paste"):
            if not pasted_content or not pasted_content.strip():
                st.warning("Please paste resume text before processing.")
            else:
                with st.spinner("Extracting candidate profiles..."):
                    paste_outcome = candidate_service.process_pasted_text(
                        pasted_content,
                        job_category=active_paste_category,
                    )

                st.success(
                    f"Processed {paste_outcome['total']} resume(s): "
                    f"{paste_outcome['success_count']} parsed, "
                    f"{paste_outcome['duplicate_count']} duplicate(s), "
                    f"{paste_outcome['failed_count']} failed."
                )

                st.session_state["last_paste_results"] = {
                    "outcome": paste_outcome,
                    "category": active_paste_category,
                }

        if "last_paste_results" in st.session_state:
            p_payload = st.session_state["last_paste_results"]
            p_res = p_payload["outcome"]
            st.markdown("---")
            st.markdown("#### Pasted Resumes Ingestion Details")
            for item in p_res["results"]:
                with st.container():
                    c_col1, c_col2, c_col3 = st.columns([3, 2, 2])
                    with c_col1:
                        st.markdown(f"**{item['filename']}**")
                        st.caption(item["message"])
                    with c_col2:
                        st.markdown(_render_status_badge(item["status"]), unsafe_allow_html=True)
                    with c_col3:
                        st.write(f"Candidate: **{item.get('candidate_name') or 'Unknown'}**")

    # ==========================================
    # SECTION 3: RECENT UPLOADS & POOL STATS
    # ==========================================
    st.markdown("---")
    st.markdown("### 🕒 Recent Ingested Candidates")

    recent_candidates, total_candidates = candidate_service.get_candidates(limit=20)

    # Batch Statistics Overview
    _, total_parsed_count = candidate_service.get_candidates(status="parsed", limit=1)
    _, total_warn_count = candidate_service.get_candidates(status="warning", limit=1)
    _, total_fail_count = candidate_service.get_candidates(status="failed", limit=1)

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("Total in System", total_candidates)
    with s2:
        st.metric("Fully Parsed", total_parsed_count)
    with s3:
        st.metric("Parsed with Warnings", total_warn_count)
    with s4:
        st.metric("Failed Ingestions", total_fail_count)

    if not recent_candidates:
        st.info("No candidates ingested yet. Use the upload forms above to add resumes to the talent pool.")
    else:
        st.caption(f"Showing the latest {len(recent_candidates)} ingested candidates (Unmasked contact details for recruiter review):")

        # Summary Table for Recent Candidates (Unmasked Email & Phone per requirement)
        table_rows = []
        for cand in recent_candidates:
            first_resume = cand["resumes"][0] if cand["resumes"] else None
            skills_preview = ", ".join(cand["skills"][:5]) + (f" (+{len(cand['skills']) - 5})" if len(cand["skills"]) > 5 else "")
            table_rows.append({
                "ID": cand["id"],
                "Name": cand["name"],
                "Role / Category": cand.get("job_category") or "General",
                "Email": cand.get("email") or "—",
                "Phone": cand.get("phone") or "—",
                "Filename": first_resume["original_filename"] if first_resume else "Pasted Text",
                "Skills": skills_preview if skills_preview else "None detected",
                "Status": cand["parsing_status"].capitalize(),
                "Uploaded": cand["created_at"] or "—",
            })

        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "Name": st.column_config.TextColumn(width="medium"),
                "Role / Category": st.column_config.TextColumn(width="medium"),
                "Email": st.column_config.TextColumn(width="medium"),
                "Phone": st.column_config.TextColumn(width="small"),
                "Filename": st.column_config.TextColumn(width="medium"),
                "Skills": st.column_config.TextColumn(width="large"),
                "Status": st.column_config.TextColumn(width="small"),
                "Uploaded": st.column_config.TextColumn(width="small"),
            },
        )
