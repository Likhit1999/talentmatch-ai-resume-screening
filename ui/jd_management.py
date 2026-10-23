"""Streamlit UI component for Job Description management in TalentMatch AI.

Provides requisition listing, search/filters, summary analytics, creation/editing,
file upload ingestion (PDF/DOCX/TXT), status toggling, version inspection, and safe deletion.
"""

from datetime import datetime
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from services.jd_service import JDService
from ui.styles import get_custom_css

logger = logging.getLogger(__name__)


def _render_jd_status_badge(status: str) -> str:
    """Render color-coded workflow status badge for job requisitions with Bootstrap Icons."""
    clean = (status or "Open").strip()
    c_lower = clean.lower()
    if c_lower in ("open", "active"):
        bg, fg, border, icon = "#F0FDF4", "#15803D", "#BBF7D0", "bi bi-check-circle-fill"
        label = "Open"
    elif c_lower in ("in progress", "in_progress"):
        bg, fg, border, icon = "#EFF6FF", "#1E40AF", "#BFDBFE", "bi bi-arrow-repeat"
        label = "In Progress"
    elif c_lower in ("on hold", "on_hold"):
        bg, fg, border, icon = "#FFFBEB", "#B45309", "#FDE68A", "bi bi-pause-circle-fill"
        label = "On Hold"
    elif c_lower in ("draft",):
        bg, fg, border, icon = "#FAF5FF", "#7E22CE", "#E9D5FF", "bi bi-pencil-square"
        label = "Draft"
    else:  # Closed, Inactive
        bg, fg, border, icon = "#F8FAFC", "#475569", "#E2E8F0", "bi bi-archive-fill"
        label = "Closed"
    return f"<span style='background-color: {bg}; color: {fg}; border: 1px solid {border}; padding: 3px 9px; border-radius: 9999px; font-weight: 600; font-size: 0.8rem;'><i class='{icon}' style='margin-right: 4px;'></i>{label}</span>"


def _extract_text_from_upload(uploaded_file) -> str:
    """Extract text from uploaded PDF, DOCX, or plain text document."""
    file_name = uploaded_file.name.lower()
    content = uploaded_file.read()

    try:
        if file_name.endswith(".pdf"):
            import pypdf
            pdf_reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = [page.extract_text() or "" for page in pdf_reader.pages]
            return "\n\n".join(pages_text).strip()

        elif file_name.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text]
            return "\n\n".join(paragraphs).strip()

        else:  # .txt or generic text
            return content.decode("utf-8", errors="replace").strip()
    except Exception as exc:
        logger.error("Failed to parse uploaded document %s: %s", uploaded_file.name, exc)
        st.error(f"Error reading file '{uploaded_file.name}': {exc}")
        return ""


def render_jd_management() -> None:
    """Render the Job Description Management dashboard and CRUD workflows."""
    st.markdown(get_custom_css(), unsafe_allow_html=True)
    service = JDService()

    # Session State Initialization
    if "jd_form_mode" not in st.session_state:
        st.session_state["jd_form_mode"] = None  # None, "create", or "edit"
    if "jd_edit_id" not in st.session_state:
        st.session_state["jd_edit_id"] = None
    if "jd_view_id" not in st.session_state:
        st.session_state["jd_view_id"] = None
    if "jd_page" not in st.session_state:
        st.session_state["jd_page"] = 1
    if "jd_search_query" not in st.session_state:
        st.session_state["jd_search_query"] = ""
    if "jd_status_filter" not in st.session_state:
        st.session_state["jd_status_filter"] = "All"
    if "jd_dept_filter" not in st.session_state:
        st.session_state["jd_dept_filter"] = "All"
    if "jd_confirm_delete_id" not in st.session_state:
        st.session_state["jd_confirm_delete_id"] = None
    if "jd_force_delete_ready" not in st.session_state:
        st.session_state["jd_force_delete_ready"] = False

    # Top Header Banner
    header_col1, header_col2 = st.columns([3, 1])
    with header_col1:
        st.markdown(
            """
            <div style="margin-bottom: 0.5rem;">
                <h1 style="color: #1e3a5f; margin: 0; font-size: 2rem; font-weight: 700;">Job Descriptions</h1>
                <p style="color: #64748b; margin: 0.2rem 0 0 0; font-size: 0.95rem;">
                    Manage enterprise job requisitions, define requirements, and trigger intelligent parsing.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with header_col2:
        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
        if st.session_state["jd_form_mode"] is None:
            if st.button("➕ Add New JD", type="primary", use_container_width=True):
                st.session_state["jd_form_mode"] = "create"
                st.session_state["jd_edit_id"] = None
                st.session_state["jd_view_id"] = None
                st.rerun()
        else:
            if st.button("✖️ Close Form", use_container_width=True):
                st.session_state["jd_form_mode"] = None
                st.session_state["jd_edit_id"] = None
                st.rerun()

    # 1. Summary Metrics
    try:
        all_jds_unfiltered, total_all = service.get_all_jds(limit=1000)
        open_count = sum(1 for j in all_jds_unfiltered if j.status in ("Open", "Active"))
        in_prog_count = sum(1 for j in all_jds_unfiltered if j.status == "In Progress")
        closed_count = sum(1 for j in all_jds_unfiltered if j.status in ("Closed", "Inactive", "On Hold", "Draft"))
        analyzed_count = sum(1 for j in all_jds_unfiltered if j.analysis_status == "analyzed")
        distinct_depts = sorted(list({j.department for j in all_jds_unfiltered if j.department}))
    except Exception as exc:
        logger.error("Failed to fetch metric aggregates: %s", exc)
        total_all, open_count, in_prog_count, closed_count, analyzed_count = 0, 0, 0, 0, 0
        distinct_depts = []

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f"""
            <div class="tm-metric-card">
                <div class="tm-metric-value">{total_all}</div>
                <div class="tm-metric-label">Total JDs</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f"""
            <div class="tm-metric-card">
                <div class="tm-metric-value" style="color: #15803d;">{open_count}</div>
                <div class="tm-metric-label">Open Requisitions</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f"""
            <div class="tm-metric-card">
                <div class="tm-metric-value" style="color: #1e40af;">{in_prog_count}</div>
                <div class="tm-metric-label">In Progress</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m4:
        st.markdown(
            f"""
            <div class="tm-metric-card">
                <div class="tm-metric-value" style="color: #64748b;">{closed_count}</div>
                <div class="tm-metric-label">Closed / On Hold / Draft</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

    # 2. Add / Edit Form (when triggered)
    if st.session_state["jd_form_mode"] in ("create", "edit"):
        _render_jd_form(service)
        st.markdown("---")

    # 3. View Detail Panel (when triggered)
    if st.session_state["jd_view_id"]:
        _render_jd_detail_view(service, st.session_state["jd_view_id"])
        st.markdown("---")

    # 4. Delete Confirmation Dialog
    if st.session_state["jd_confirm_delete_id"]:
        _render_delete_confirmation(service, st.session_state["jd_confirm_delete_id"])
        st.markdown("---")

    # 5. Search Bar & Filter Controls
    search_col, filter_status_col, filter_dept_col = st.columns([2.5, 1, 1.2])

    with search_col:
        search_input = st.text_input(
            "Search Job Descriptions",
            value=st.session_state["jd_search_query"],
            placeholder="Search by title, department, skills, qualifications...",
            key="input_search_query",
        )
        if search_input != st.session_state["jd_search_query"]:
            st.session_state["jd_search_query"] = search_input
            st.session_state["jd_page"] = 1
            st.rerun()

    with filter_status_col:
        status_opts = ["All", "Open", "In Progress", "On Hold", "Closed", "Draft"]
        status_idx = status_opts.index(st.session_state["jd_status_filter"]) if st.session_state["jd_status_filter"] in status_opts else 0
        status_sel = st.selectbox(
            "Filter Status",
            options=status_opts,
            index=status_idx,
            key="select_status_filter",
        )
        if status_sel != st.session_state["jd_status_filter"]:
            st.session_state["jd_status_filter"] = status_sel
            st.session_state["jd_page"] = 1
            st.rerun()

    with filter_dept_col:
        dept_opts = ["All"] + distinct_depts
        dept_idx = dept_opts.index(st.session_state["jd_dept_filter"]) if st.session_state["jd_dept_filter"] in dept_opts else 0
        dept_sel = st.selectbox(
            "Filter Department",
            options=dept_opts,
            index=dept_idx,
            key="select_dept_filter",
        )
        if dept_sel != st.session_state["jd_dept_filter"]:
            st.session_state["jd_dept_filter"] = dept_sel
            st.session_state["jd_page"] = 1
            st.rerun()

    # 6. Fetch Filtered Records
    limit_per_page = 10
    current_page = st.session_state["jd_page"]
    offset = (current_page - 1) * limit_per_page

    query_filters: Dict[str, Any] = {}
    if st.session_state["jd_status_filter"] != "All":
        query_filters["status"] = st.session_state["jd_status_filter"]
    if st.session_state["jd_dept_filter"] != "All":
        query_filters["department"] = st.session_state["jd_dept_filter"]

    search_term = st.session_state["jd_search_query"].strip() or None

    try:
        jds, total_matching = service.get_all_jds(
            filters=query_filters,
            search=search_term,
            offset=offset,
            limit=limit_per_page,
        )
    except Exception as exc:
        logger.error("Error fetching job descriptions: %s", exc)
        st.error(f"Error fetching job descriptions: {exc}")
        jds, total_matching = [], 0

    # 7. Render Table or Empty State
    if not jds:
        _render_empty_state()
        return

    st.markdown(
        f"<div style='font-size: 0.9rem; color: #64748b; margin-bottom: 0.5rem;'>Showing <b>{len(jds)}</b> of <b>{total_matching}</b> job requisitions</div>",
        unsafe_allow_html=True,
    )

    # Render Table Header
    cols = st.columns([2.6, 1.4, 1.1, 1.3, 1.2, 3.6])
    cols[0].markdown("**Title & ID**")
    cols[1].markdown("**Department**")
    cols[2].markdown("**Status**")
    cols[3].markdown("**Analysis**")
    cols[4].markdown("**Created**")
    cols[5].markdown("**Actions**")
    st.markdown("<hr style='margin: 0.25rem 0 0.5rem 0; border-color: #e2e8f0;'>", unsafe_allow_html=True)

    # Render Table Rows
    for jd in jds:
        r_cols = st.columns([2.6, 1.4, 1.1, 1.3, 1.2, 3.6])

        # Title & ID
        with r_cols[0]:
            st.markdown(
                f"<div style='font-weight: 600; color: #1e3a5f;'>{jd.title}</div>"
                f"<div style='font-size: 0.78rem; color: #94a3b8;'>ID: #{jd.id} • {jd.location or 'Location unspecified'}</div>",
                unsafe_allow_html=True,
            )

        # Department
        with r_cols[1]:
            st.markdown(
                f"<span style='font-size: 0.88rem; color: #475569;'>{jd.department or '—'}</span>",
                unsafe_allow_html=True,
            )

        # Status Badge
        with r_cols[2]:
            st.markdown(_render_jd_status_badge(jd.status), unsafe_allow_html=True)

        # Analysis Status Badge
        with r_cols[3]:
            req_count = len(jd.requirements) if hasattr(jd, "requirements") and jd.requirements else 0
            if jd.analysis_status == "analyzed":
                a_html = f"<span class='tm-badge badge-analyzed' title='{req_count} requirements'>Analyzed ({req_count})</span>"
            elif jd.analysis_status == "needs_reanalysis":
                a_html = "<span class='tm-badge badge-needs-reanalysis' title='Content changed since analysis'>Needs Re-sync</span>"
            else:
                a_html = "<span class='tm-badge badge-not-analyzed'>Not Analyzed</span>"
            st.markdown(a_html, unsafe_allow_html=True)

        # Created Date
        with r_cols[4]:
            created_str = jd.created_at.strftime("%b %d, %Y") if jd.created_at else "—"
            st.markdown(f"<span style='font-size: 0.82rem; color: #64748b;'>{created_str}</span>", unsafe_allow_html=True)

        # Actions Group
        with r_cols[5]:
            act_col1, act_col2, act_col3, act_col4, act_col5, act_col6 = st.columns(6)

            with act_col1:
                if st.button("👁️", key=f"view_btn_{jd.id}", help="View Details & Requirements"):
                    st.session_state["jd_view_id"] = jd.id
                    st.rerun()

            with act_col2:
                if st.button("✏️", key=f"edit_btn_{jd.id}", help="Edit Requisition"):
                    st.session_state["jd_form_mode"] = "edit"
                    st.session_state["jd_edit_id"] = jd.id
                    st.session_state["jd_view_id"] = None
                    st.rerun()

            with act_col3:
                if st.button("📋", key=f"dup_btn_{jd.id}", help="Duplicate Requisition"):
                    try:
                        duplicated = service.duplicate_jd(jd.id)
                        st.success(f"Duplicated as '{duplicated.title}'!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error duplicating: {e}")

            with act_col4:
                if st.button("⚡", key=f"analyze_btn_{jd.id}", help="Open in Requirement Analyzer"):
                    st.session_state["selected_analyzer_jd_id"] = jd.id
                    # Set active navigation/tab to Analyzer if parent handles it
                    st.session_state["jd_active_subtab"] = "analyzer"
                    st.success(f"Selected #{jd.id} for analysis. Switch to Requirement Analyzer tab.")
                    st.rerun()

            with act_col5:
                status_icon = "⏸️" if jd.status == "Active" else "▶️"
                status_help = "Deactivate" if jd.status == "Active" else "Activate"
                if st.button(status_icon, key=f"toggle_btn_{jd.id}", help=status_help):
                    try:
                        updated_jd = service.toggle_status(jd.id)
                        st.info(f"Status changed to {updated_jd.status}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error toggling status: {e}")

            with act_col6:
                if st.button("🗑️", key=f"del_btn_{jd.id}", help="Delete Requisition"):
                    st.session_state["jd_confirm_delete_id"] = jd.id
                    st.session_state["jd_force_delete_ready"] = False
                    st.rerun()

        st.markdown("<hr style='margin: 0.2rem 0; border-color: #f1f5f9;'>", unsafe_allow_html=True)

    # 8. Pagination Controls
    total_pages = max(1, (total_matching + limit_per_page - 1) // limit_per_page)
    if total_pages > 1:
        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
        p_prev, p_info, p_next = st.columns([1, 4, 1])

        with p_prev:
            if st.button("⬅️ Previous", disabled=(current_page <= 1), use_container_width=True):
                st.session_state["jd_page"] = max(1, current_page - 1)
                st.rerun()

        with p_info:
            st.markdown(
                f"<div style='text-align: center; color: #64748b; font-size: 0.88rem; margin-top: 0.4rem;'>"
                f"Page <b>{current_page}</b> of <b>{total_pages}</b> ({total_matching} total jobs)"
                f"</div>",
                unsafe_allow_html=True,
            )

        with p_next:
            if st.button("Next ➡️", disabled=(current_page >= total_pages), use_container_width=True):
                st.session_state["jd_page"] = min(total_pages, current_page + 1)
                st.rerun()


def _render_jd_form(service: JDService) -> None:
    """Render Add or Edit Job Description form."""
    is_edit = st.session_state["jd_form_mode"] == "edit"
    jd_id = st.session_state["jd_edit_id"]

    existing_jd: Optional[Any] = None
    if is_edit and jd_id:
        try:
            existing_jd = service.get_jd(jd_id)
        except Exception as exc:
            st.error(f"Could not load Job Description #{jd_id}: {exc}")
            st.session_state["jd_form_mode"] = None
            return

    form_title = f"✏️ Edit Job Description #{jd_id}" if is_edit else "➕ Create New Job Description"

    with st.expander(form_title, expanded=True):
        st.markdown(
            "<p style='color: #64748b; font-size: 0.88rem; margin-top: -0.5rem;'>"
            "Fill in requisition details or upload a job document (PDF/DOCX/TXT) to auto-fill the description."
            "</p>",
            unsafe_allow_html=True,
        )

        # File Upload Ingestion
        uploaded_doc = st.file_uploader(
            "Upload Job Description Document (PDF, DOCX, TXT) - Optional",
            type=["pdf", "docx", "txt"],
            key="jd_file_uploader",
            help="Uploading a document will automatically parse its text and auto-extract all criteria.",
        )

        extracted_text_from_file = ""
        suggested_title = ""
        if uploaded_doc is not None:
            extracted_text_from_file = _extract_text_from_upload(uploaded_doc)
            if extracted_text_from_file:
                suggested_title = Path(uploaded_doc.name).stem.replace("_", " ").replace("-", " ").title()
                st.info(f"✅ Extracted {len(extracted_text_from_file)} characters from '{uploaded_doc.name}'.")

        # Streamlined Form: Ask only Job Title, rest auto-extracted
        with st.form("jd_management_form"):
            title_default = existing_jd.title if existing_jd else (suggested_title or "")
            title = st.text_input(
                "Job Title *",
                value=title_default,
                placeholder="e.g., Senior Full Stack Engineer, QA Automation Lead",
                help="Enter the official role title. All skills, experience, and criteria will be automatically extracted from the JD text.",
            )

            # Main Description
            default_desc = extracted_text_from_file if extracted_text_from_file else (existing_jd.description_text if existing_jd else "")
            description_text = st.text_area(
                "Job Description Text *",
                value=default_desc,
                height=200,
                placeholder="Paste the job description overview, role summary, requirements, or let the uploaded file populate it...",
                help="This text is used by the AI engine to automatically extract atomic screening criteria (skills, experience, qualifications).",
            )

            st.markdown(
                """
                <div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 6px; padding: 0.6rem 0.85rem; margin-bottom: 0.8rem; font-size: 0.85rem; color: #15803D;">
                    ✨ <strong>Smart Extraction Active:</strong> Required experience range (e.g. 4–5 yrs), mandatory & preferred skills, education, tools, and certifications will be automatically extracted upon saving.
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Optional Advanced Overrides (Collapsed)
            with st.expander("⚙️ Optional Advanced Requisition Details (Department, Location, Custom Overrides)", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    dept_val = existing_jd.department if existing_jd and existing_jd.department else ""
                    department = st.text_input("Department", value=dept_val, placeholder="e.g., Engineering, Data Science")

                    location_val = existing_jd.location if existing_jd and existing_jd.location else ""
                    location = st.text_input("Location", value=location_val, placeholder="e.g., Remote / San Francisco, CA")

                with col2:
                    emp_types = ["Full-time", "Part-time", "Contract", "Internship", "Remote"]
                    emp_val = existing_jd.employment_type if existing_jd and existing_jd.employment_type in emp_types else "Full-time"
                    employment_type = st.selectbox(
                        "Employment Type",
                        options=emp_types,
                        index=emp_types.index(emp_val) if emp_val in emp_types else 0,
                    )

                    status_opts = ["Open", "In Progress", "On Hold", "Closed", "Draft"]
                    current_st = existing_jd.status if existing_jd else "Open"
                    if current_st == "Active":
                        current_st = "Open"
                    elif current_st == "Inactive":
                        current_st = "Closed"
                    status_idx = status_opts.index(current_st) if current_st in status_opts else 0
                    status = st.selectbox("Status", options=status_opts, index=status_idx)

                exp_c1, exp_c2 = st.columns(2)
                with exp_c1:
                    exp_min_val = float(existing_jd.experience_min) if existing_jd and existing_jd.experience_min is not None else 0.0
                    experience_min = st.number_input(
                        "Min Experience Override (Years, 0 = Auto-detect)", min_value=0.0, max_value=30.0, value=exp_min_val, step=0.5
                    )
                with exp_c2:
                    exp_max_val = float(existing_jd.experience_max) if existing_jd and existing_jd.experience_max is not None else 0.0
                    experience_max = st.number_input(
                        "Max Experience Override (Years, 0 = Auto-detect)", min_value=0.0, max_value=30.0, value=exp_max_val, step=0.5
                    )

                q_val = existing_jd.qualifications if existing_jd and existing_jd.qualifications else ""
                qualifications = st.text_area("Custom Qualifications (Optional)", value=q_val, height=70)

                r_val = existing_jd.responsibilities if existing_jd and existing_jd.responsibilities else ""
                responsibilities = st.text_area("Custom Responsibilities (Optional)", value=r_val, height=70)

                cert_val = existing_jd.certifications if existing_jd and existing_jd.certifications else ""
                certifications = st.text_input("Custom Certifications (Optional)", value=cert_val)

                notes_val = existing_jd.recruiter_notes if existing_jd and existing_jd.recruiter_notes else ""
                recruiter_notes = st.text_area("Internal Recruiter Notes", value=notes_val, height=60)

            btn_col1, btn_col2 = st.columns([2, 3])
            with btn_col1:
                submitted = st.form_submit_button("💾 Save & Auto-Extract Requisition Criteria", type="primary", use_container_width=True)

            if submitted:
                if not title.strip():
                    st.error("Please provide a Job Title.")
                    return
                if not description_text.strip():
                    st.error("Please provide Job Description text or upload a document.")
                    return

                payload = {
                    "title": title.strip(),
                    "department": department.strip() or None,
                    "location": location.strip() or None,
                    "employment_type": employment_type,
                    "experience_min": experience_min if experience_min > 0 else None,
                    "experience_max": experience_max if experience_max > 0 else None,
                    "description_text": description_text.strip(),
                    "qualifications": qualifications.strip() or None,
                    "responsibilities": responsibilities.strip() or None,
                    "certifications": certifications.strip() or None,
                    "recruiter_notes": recruiter_notes.strip() or None,
                    "status": status,
                }

                try:
                    if is_edit:
                        updated = service.update_jd(jd_id, payload)
                        st.success(f"Requisition #{updated.id} '{updated.title}' updated successfully!")
                    else:
                        created = service.create_jd(payload)

                        # Auto-extract atomic screening requirements immediately
                        with st.spinner("🤖 Automatically extracting criteria, experience range, and skills from JD..."):
                            try:
                                from services.jd_analyzer import JDAnalyzer
                                from services.scoring_service import parse_experience_range_from_text

                                analyzer = JDAnalyzer()
                                extracted_reqs = analyzer.analyze_jd(created.description_text)
                                if extracted_reqs:
                                    service.save_extracted_requirements(created.id, extracted_reqs)

                                    # Auto-update experience min/max if found in extracted requirements
                                    for r in extracted_reqs:
                                        if r.get("category") == "experience":
                                            emin, emax = parse_experience_range_from_text(r.get("requirement_name", ""))
                                            if emin is not None and (created.experience_min is None or created.experience_min <= 0):
                                                service.update_jd(created.id, {"experience_min": emin, "experience_max": emax})
                                                break

                                    st.success(f"✓ Requisition #{created.id} '{created.title}' created and {len(extracted_reqs)} screening criteria auto-extracted!")
                                else:
                                    st.success(f"Requisition #{created.id} '{created.title}' created successfully!")
                            except Exception as ai_exc:
                                logger.warning("Auto extraction failed on JD create: %s", ai_exc)
                                st.success(f"Requisition #{created.id} '{created.title}' created successfully!")

                    st.session_state["jd_form_mode"] = None
                    st.session_state["jd_edit_id"] = None
                    st.rerun()
                except Exception as exc:
                    logger.error("Failed to save JD: %s", exc)
                    st.error(f"Failed to save Job Description: {exc}")
                    st.session_state["jd_edit_id"] = None
                    st.rerun()
                except Exception as exc:
                    logger.error("Failed to save JD: %s", exc)
                    st.error(f"Failed to save Job Description: {exc}")


def _render_jd_detail_view(service: JDService, jd_id: int) -> None:
    """Render expanded read-only drawer for Job Description details and requirements."""
    try:
        jd = service.get_jd(jd_id)
        versions = service.get_jd_versions(jd_id)
        requirements = service.get_jd_requirements(jd_id)
        screening_summary = service.get_jd_screening_summary(jd_id)
    except Exception as exc:
        st.error(f"Failed to load details for JD #{jd_id}: {exc}")
        return

    with st.expander(f"👁️ Inspection View: {jd.title} (#{jd.id})", expanded=True):
        close_col, action_col = st.columns([5, 1])
        with action_col:
            if st.button("✖️ Close View", key="close_detail_btn", use_container_width=True):
                st.session_state["jd_view_id"] = None
                st.rerun()

        # Metadata Row
        st.markdown(
            f"""
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
                <div style="display: flex; gap: 2rem; flex-wrap: wrap; align-items: center;">
                    <div><b>Department:</b> {jd.department or 'N/A'}</div>
                    <div><b>Location:</b> {jd.location or 'N/A'}</div>
                    <div><b>Employment:</b> {jd.employment_type or 'N/A'}</div>
                    <div><b>Experience:</b> {jd.experience_min or 0} - {jd.experience_max or 'Any'} years</div>
                    <div><b>Status:</b> {_render_jd_status_badge(jd.status)}</div>
                    <div><b>Analysis:</b> {jd.analysis_status}</div>
                    <div><b>Created:</b> {jd.created_at.strftime('%Y-%m-%d %H:%M') if jd.created_at else '—'}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Job Description Content",
            f"Extracted Requirements ({len(requirements)})",
            f"Version History ({len(versions)})",
            "🤖 AI Quality Review",
            f"🎯 Screened Candidates ({screening_summary['total_screened']})",
        ])

        with tab1:
            st.markdown("#### Description")
            st.markdown(jd.description_text)

            if jd.qualifications:
                st.markdown("#### Qualifications")
                st.markdown(jd.qualifications)

            if jd.responsibilities:
                st.markdown("#### Responsibilities")
                st.markdown(jd.responsibilities)

            if jd.certifications:
                st.markdown("#### Certifications")
                st.markdown(jd.certifications)

            if jd.recruiter_notes:
                st.markdown("#### Internal Recruiter Notes")
                st.info(jd.recruiter_notes)

        with tab2:
            if not requirements:
                st.info("No requirements analyzed yet. Click the ⚡ Analyze button to decompose this requisition.")
            else:
                st.markdown(
                    "<p style='font-size: 0.88rem; color: #64748b;'>These atomic criteria are evaluated against candidate resumes during batch screening.</p>",
                    unsafe_allow_html=True,
                )
                req_data = [
                    {
                        "Name": r.requirement_name,
                        "Category": r.category.replace("_", " ").title(),
                        "Importance": r.importance.title(),
                        "Weight": r.weight,
                        "Enabled": "Yes" if r.is_enabled else "No",
                        "Evidence": r.original_evidence or "—",
                    }
                    for r in requirements
                ]
                st.dataframe(req_data, use_container_width=True, hide_index=True)

        with tab3:
            if not versions:
                st.info("No historical snapshots found.")
            else:
                for v in versions:
                    snapshot = v.get_snapshot()
                    reqs_in_v = len(snapshot.get("requirements", []))
                    created_time = v.created_at.strftime("%b %d, %Y %H:%M:%S") if v.created_at else "—"
                    st.markdown(
                        f"""
                        <div style="border-left: 3px solid #3b82f6; padding-left: 0.75rem; margin-bottom: 0.75rem;">
                            <b>Version {v.version_number}</b> • <span style="color: #64748b;">Captured on {created_time}</span>
                            <div style="font-size: 0.85rem; color: #475569;">
                                Title: <i>{snapshot.get('title')}</i> • Requirements in snapshot: <b>{reqs_in_v}</b>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        with tab4:
            st.markdown("#### 🤖 AI Requisition Quality Audit")
            st.markdown(
                "<span style='color: #64748b; font-size: 0.88rem;'>"
                "Evaluate requisition clarity, identify ambiguous phrasing, verify seniority realism, "
                "and receive actionable recommendations to optimize candidate screening."
                "</span>",
                unsafe_allow_html=True,
            )
            audit_key = f"audit_jd_res_{jd.id}"
            if st.button("⚡ Run AI Quality Review", key=f"btn_run_audit_{jd.id}", type="primary"):
                from services.jd_analyzer import JDAnalyzerService
                analyzer = JDAnalyzerService()
                full_jd_text = f"{jd.title}\n\n{jd.description_text}"
                if jd.qualifications:
                    full_jd_text += f"\n\nQualifications:\n{jd.qualifications}"
                if jd.responsibilities:
                    full_jd_text += f"\n\nResponsibilities:\n{jd.responsibilities}"
                with st.spinner("Analyzing requisition with Google Gemini..."):
                    st.session_state[audit_key] = analyzer.review_jd_with_ai(full_jd_text)

            if audit_key in st.session_state:
                audit = st.session_state[audit_key]
                score_val = audit.get("overall_score", 80)
                score_color = "#15803d" if score_val >= 80 else ("#b45309" if score_val >= 60 else "#b91c1c")
                st.markdown(
                    f"""
                    <div style="background-color: #f8fafc; border-left: 4px solid {score_color}; padding: 0.85rem 1rem; border-radius: 6px; margin: 1rem 0;">
                        <div style="font-size: 1.05rem; font-weight: 700; color: #1e293b;">
                            Quality Score: <span style="color: {score_color};">{score_val}/100 — {audit.get('grade', 'Good')}</span>
                        </div>
                        <div style="color: #475569; margin-top: 0.35rem; font-size: 0.92rem;">
                            {audit.get('summary', '')}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                c_a1, c_a2 = st.columns(2)
                with c_a1:
                    st.markdown("**Seniority Alignment:**")
                    st.caption(audit.get("seniority_alignment", "—"))
                    st.markdown("**⚠️ Ambiguities / Vague Requirements:**")
                    ambs = audit.get("ambiguities", [])
                    if ambs:
                        for a in ambs:
                            st.markdown(f"- 🔸 {a}")
                    else:
                        st.caption("No significant ambiguities detected.")
                with c_a2:
                    st.markdown("**🔍 Missing Key Requisition Details:**")
                    missing = audit.get("missing_elements", [])
                    if missing:
                        for m in missing:
                            st.markdown(f"- 🔹 {m}")
                    else:
                        st.caption("No critical missing elements detected.")
                    st.markdown("**💡 Screening Recommendations:**")
                    recs = audit.get("screening_recommendations", [])
                    if recs:
                        for r in recs:
                            st.markdown(f"- ✅ {r}")
                    else:
                        st.caption("No specific recommendations.")

        with tab5:
            st.markdown(f"#### 🎯 Screened Candidate Profiles for '{jd.title}'")
            total_cand = screening_summary["total_screened"]
            if total_cand == 0:
                st.info(
                    "No candidates have been evaluated against this job requisition yet. "
                    "Navigate to Match & Rank to screen candidate resumes."
                )
                if st.button("⚡ Go to Match & Rank for this Requisition", key=f"btn_nav_mr_{jd.id}", type="primary"):
                    st.session_state["mr_selected_jd_id"] = jd.id
                    st.session_state.nav_index = 5  # Match & Rank
                    st.rerun()
            else:
                sm1, sm2, sm3, sm4 = st.columns(4)
                with sm1:
                    st.metric("Total Screened", total_cand)
                with sm2:
                    st.metric("Average Score", f"{screening_summary['average_score']}%")
                with sm3:
                    st.metric("Strong Matches", screening_summary["by_category"].get("strong_match", 0))
                with sm4:
                    st.metric("Pending Review", screening_summary["by_review_status"].get("pending", 0))

                cand_table = []
                for c in screening_summary["candidates"]:
                    cand_table.append({
                        "ID": c["candidate_id"],
                        "Candidate Name": c["candidate_name"],
                        "Email": c["email"] or "—",
                        "Phone": c["phone"] or "—",
                        "Match Score": f"{c['match_score']:.1f}%",
                        "Category": c["match_category"].replace("_", " ").title(),
                        "Mandatory Met": c["mandatory_met"],
                        "Review Status": c["human_review_status"].replace("_", " ").title(),
                        "Notes": c["reviewer_notes"] or "—",
                        "Screened Date": c["last_screened_at"] or "—",
                    })

                st.dataframe(
                    cand_table,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "ID": st.column_config.NumberColumn(width="small"),
                        "Candidate Name": st.column_config.TextColumn(width="medium"),
                        "Email": st.column_config.TextColumn(width="medium"),
                        "Phone": st.column_config.TextColumn(width="small"),
                        "Match Score": st.column_config.TextColumn(width="small"),
                        "Category": st.column_config.TextColumn(width="small"),
                        "Mandatory Met": st.column_config.TextColumn(width="small"),
                        "Review Status": st.column_config.TextColumn(width="medium"),
                        "Notes": st.column_config.TextColumn(width="medium"),
                        "Screened Date": st.column_config.TextColumn(width="small"),
                    },
                )

                if st.button("⚡ Open Full Match & Rank Workspace for this JD", key=f"btn_nav_mr_full_{jd.id}"):
                    st.session_state["mr_selected_jd_id"] = jd.id
                    st.session_state.nav_index = 5  # Match & Rank
                    st.rerun()


def _render_delete_confirmation(service: JDService, jd_id: int) -> None:
    """Render safety confirmation prompt when deletion is requested."""
    try:
        jd = service.get_jd(jd_id)
    except Exception:
        st.session_state["jd_confirm_delete_id"] = None
        return

    with st.container():
        st.markdown(
            f"""
            <div class="tm-alert tm-alert-warning">
                <div>
                    <b>⚠️ Confirm Deletion of Job Requisition #{jd.id}</b>
                    <div>Are you sure you want to permanently delete <b>'{jd.title}'</b>? This action cannot be undone.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("Cancel", key="cancel_delete_btn", use_container_width=True):
                st.session_state["jd_confirm_delete_id"] = None
                st.session_state["jd_force_delete_ready"] = False
                st.rerun()

        with c2:
            force_mode = st.session_state["jd_force_delete_ready"]
            del_label = "🔥 Force Delete" if force_mode else "🗑️ Delete"
            if st.button(del_label, type="primary", key="execute_delete_btn", use_container_width=True):
                try:
                    success = service.delete_jd(jd_id, force=force_mode)
                    if success:
                        st.success(f"Job Description #{jd_id} deleted.")
                        st.session_state["jd_confirm_delete_id"] = None
                        st.session_state["jd_force_delete_ready"] = False
                        st.rerun()
                except ValueError as ve:
                    st.error(str(ve))
                    st.warning("To delete anyway including all associated match scores and shortlists, click 'Force Delete' below.")
                    st.session_state["jd_force_delete_ready"] = True
                    st.rerun()


def _render_empty_state() -> None:
    """Render empty state card when no requisitions match search/filter."""
    st.markdown(
        """
        <div class="tm-empty-state">
            <div class="tm-empty-icon">📋</div>
            <div class="tm-empty-title">No Job Descriptions Found</div>
            <div class="tm-empty-desc">
                No job postings match your active search filter, or the requisition repository is empty.
                Create a new job description or upload an existing job posting document to get started.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1.5, 1, 1.5])
    with col2:
        if st.button("➕ Create First JD", type="primary", use_container_width=True):
            st.session_state["jd_form_mode"] = "create"
            st.session_state["jd_search_query"] = ""
            st.session_state["jd_status_filter"] = "All"
            st.session_state["jd_dept_filter"] = "All"
            st.rerun()
