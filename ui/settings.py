"""Streamlit UI module for system settings and AI configuration in TalentMatch AI.

Manages Gemini model credentials, algorithmic scoring weights, file processing constraints,
duplicate detection parameters, export formatting, and database-persisted settings.
"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
import streamlit as st

from config.settings import get_settings
from database.connection import DatabaseManager, get_session
from database.models import ApplicationSetting
from services.audit_service import AuditService

logger = logging.getLogger(__name__)

# Default Scoring Weights
DEFAULT_WEIGHTS = {
    "mandatory_skills": 0.40,
    "preferred_skills": 0.20,
    "experience": 0.20,
    "qualifications": 0.10,
    "domain": 0.10,
}


def _mask_api_key(key: Optional[str]) -> str:
    """Mask API key showing only prefix and suffix."""
    if not key or key.strip() in ("", "your_api_key_here", "none", "placeholder"):
        return "Not Configured"
    clean = key.strip()
    if len(clean) >= 12:
        return f"{clean[:4]}...{clean[-4:]}"
    return "●●●●●●●●"


def _get_db_settings() -> Dict[str, str]:
    """Retrieve all current application settings from the database."""
    settings_dict = {}
    with get_session() as session:
        records = session.scalars(select(ApplicationSetting)).all()
        for r in records:
            settings_dict[r.key] = r.value or ""
    return settings_dict


def _save_db_setting(session, key: str, value: str, description: Optional[str] = None) -> None:
    """Upsert a single setting record in the active database session."""
    existing = session.scalar(select(ApplicationSetting).where(ApplicationSetting.key == key))
    if existing:
        existing.value = str(value)
        if description:
            existing.description = description
        existing.updated_at = datetime.utcnow()
    else:
        new_setting = ApplicationSetting(key=key, value=str(value), description=description)
        session.add(new_setting)


def render_settings() -> None:
    """Render the TalentMatch AI Settings & Configuration view."""
    app_settings = get_settings()
    audit_service = AuditService()

    st.markdown(
        """
        <div style="margin-bottom: 1.25rem;">
            <h2 style="color: #1E3A8A; margin: 0 0 0.25rem 0; font-weight: 700;">System Settings & AI Engine Configuration</h2>
            <p style="color: #64748B; margin: 0; font-size: 0.95rem;">
                Configure Gemini AI model parameters, adjust scoring algorithmic weights, configure upload thresholds,
                and persist organizational defaults in the application database.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Load current persisted settings from database
    db_settings = _get_db_settings()

    # Determine baseline values with fallback to env Settings
    cur_ai_enabled = db_settings.get("ai_enabled", str(app_settings.AI_ENABLED)).lower() in ("true", "1", "yes")
    cur_ai_model = app_settings.get_model()
    cur_api_key = app_settings.get_api_key() or db_settings.get("gemini_api_key", app_settings.GEMINI_API_KEY)

    cur_w_mandatory = float(db_settings.get("weight_mandatory_skills", DEFAULT_WEIGHTS["mandatory_skills"]))
    cur_w_preferred = float(db_settings.get("weight_preferred_skills", DEFAULT_WEIGHTS["preferred_skills"]))
    cur_w_exp = float(db_settings.get("weight_experience", DEFAULT_WEIGHTS["experience"]))
    cur_w_qual = float(db_settings.get("weight_qualifications", DEFAULT_WEIGHTS["qualifications"]))
    cur_w_domain = float(db_settings.get("weight_domain", DEFAULT_WEIGHTS["domain"]))

    cur_max_size = int(db_settings.get("max_file_size_mb", app_settings.MAX_FILE_SIZE_MB))
    cur_max_batch = int(db_settings.get("max_batch_size", app_settings.MAX_BATCH_SIZE))
    cur_retention = int(db_settings.get("resume_retention_days", app_settings.RESUME_RETENTION_DAYS))

    cur_dup_enabled = db_settings.get("duplicate_detection_enabled", "true").lower() in ("true", "1", "yes")
    cur_dup_strict = db_settings.get("duplicate_strictness", "Exact SHA-256 Hash")

    cur_export_fmt = db_settings.get("default_export_format", "Excel (.xlsx)")
    cur_export_contact = db_settings.get("export_include_contact_details", "true").lower() in ("true", "1", "yes")

    # =========================================================================
    # 1. AI CONFIGURATION SECTION
    # =========================================================================
    st.markdown("### 🤖 AI Engine & Model Credentials")
    with st.container():
        st.markdown(
            """
            <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-left: 4px solid #1E40AF; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
                <span style="font-weight: 600; color: #1E3A8A;">Gemini Generative AI Integration</span>
                <p style="color: #64748B; font-size: 0.88rem; margin: 0.25rem 0 0 0;">
                    Powers automated resume extraction, atomic requirement decomposition, and semantic fit scoring.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        ai_c1, ai_c2 = st.columns(2)
        with ai_c1:
            ai_enabled_input = st.toggle("Enable AI Capabilities", value=cur_ai_enabled, key="set_ai_enabled")
            model_options = [
                "gemini-3.1-flash-lite",
                "gemini-3.5-flash",
                "gemini-3.8-flash",
                "gemini-flash-latest",
            ]
            if cur_ai_model and cur_ai_model not in model_options and not cur_ai_model.startswith("gemini-2.0") and not cur_ai_model.startswith("gemini-1.5"):
                model_options.append(cur_ai_model)
            if cur_ai_model in model_options:
                m_idx = model_options.index(cur_ai_model)
            else:
                m_idx = 0  # Default to gemini-3.1-flash-lite (fastest)
            selected_model = st.selectbox("Gemini Model Identifier", options=model_options, index=m_idx)

        with ai_c2:
            st.markdown(f"**Current API Key Status:** `{_mask_api_key(cur_api_key)}`")
            new_api_key = st.text_input(
                "Gemini API Key",
                type="password",
                placeholder="Enter new API key to update...",
                help="Never displayed in plain text after saving.",
            )

        test_col1, test_col2 = st.columns([1.5, 3])
        with test_col1:
            test_conn_btn = st.button("⚡ Test AI Connection & Token Meter", use_container_width=True)

        if test_conn_btn:
            key_to_test = new_api_key.strip() if new_api_key.strip() else cur_api_key
            if not key_to_test or key_to_test.lower() in ("your_api_key_here", "none", "placeholder"):
                st.error("No valid Gemini API key configured. Please enter an API key.")
            else:
                with st.spinner("Connecting to Google Gemini API (fast check)..."):
                    try:
                        reply = None
                        t_start = time.perf_counter()
                        from services.ai_client import get_genai_client, record_token_usage
                        from google.genai import types
                        client = get_genai_client(key_to_test)
                        if not client:
                            raise ValueError("Could not create GenAI client with provided key.")
                        config = types.GenerateContentConfig(max_output_tokens=15, temperature=0.1)
                        response = client.models.generate_content(
                            model=selected_model,
                            contents="Respond with 'PONG' to verify connection.",
                            config=config,
                        )
                        t_latency = int((time.perf_counter() - t_start) * 1000)
                        reply = response.text.strip() if hasattr(response, "text") and response.text else "Connected"

                        # Extract live token usage from response
                        p_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                        c_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                        tot_tok = getattr(response.usage_metadata, "total_token_count", 0) or (p_tok + c_tok)
                        record_token_usage(p_tok, c_tok, tot_tok, t_latency, selected_model)

                        st.success(
                            f"✓ AI Connection Successful! Model: `{selected_model}` | Latency: `{t_latency} ms` | "
                            f"Tokens: `{p_tok} prompt + {c_tok} response = {tot_tok} total` | Response: `{reply}`"
                        )
                    except Exception as conn_err:
                        st.error(f"✕ Connection failed: {conn_err}")

        # -----------------------------------------------------------------
        # Real-Time Token & Quota Tracking Section
        # -----------------------------------------------------------------
        from services.ai_client import (
            get_token_usage_stats,
            reset_token_usage_stats,
            set_plan_tier,
        )

        st.markdown("<div style='margin-top: 1.25rem;'></div>", unsafe_allow_html=True)
        st.markdown("#### 📊 Real-Time Token & Quota Tracker")

        stats = get_token_usage_stats()
        current_plan = stats.get("plan_tier", "free")

        # Plan Tier selection and Countdown clock
        plan_c1, plan_c2 = st.columns([2.2, 1.2])
        with plan_c1:
            tier_options = ["Free Tier (1,500 Requests/Day)", "Pay-As-You-Go (Unlimited / Billed per token)"]
            selected_tier_label = st.radio(
                "Google AI Studio Quota Plan Tier",
                options=tier_options,
                index=0 if current_plan == "free" else 1,
                horizontal=True,
                key="plan_tier_radio",
                help="Select your Google AI Studio plan to accurately track daily remaining requests and rate limits.",
            )
            new_plan = "free" if "Free" in selected_tier_label else "paid"
            if new_plan != current_plan:
                set_plan_tier(new_plan)
                st.rerun()

        with plan_c2:
            st.markdown(
                f"""
                <div style="background: #F1F5F9; border: 1px solid #CBD5E1; border-radius: 8px; padding: 0.6rem 0.85rem; text-align: right; margin-top: 0.2rem;">
                    <span style="font-size: 0.78rem; color: #64748B;">⏰ Daily Quota Resets:</span><br/>
                    <strong style="color: #1E3A8A; font-size: 0.95rem;">in {stats.get('reset_countdown', '24h')}</strong> <span style="font-size: 0.75rem; color: #64748B;">(00:00 UTC)</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Main KPI Metrics
        q_m1, q_m2, q_m3, q_m4 = st.columns(4)
        with q_m1:
            req_rem = stats.get("requests_remaining")
            rem_display = f"{req_rem:,}" if isinstance(req_rem, int) else str(req_rem)
            req_delta = f"-{stats.get('requests_used', 0)} used" if stats.get("requests_used", 0) > 0 else "Full Quota Available"
            st.metric(
                label="⚡ Requests Remaining Today",
                value=rem_display,
                delta=req_delta,
                delta_color="normal" if isinstance(req_rem, int) and req_rem > 100 else "inverse",
                help="Estimated requests remaining today under your active Google AI Studio quota plan.",
            )

        with q_m2:
            st.metric(
                label="📈 Requests Used Today",
                value=f"{stats.get('requests_used', 0):,}",
                delta=f"Active: {stats.get('active_model')}",
                delta_color="off",
                help="Total AI requests processed today across JD analysis and candidate screening.",
            )

        with q_m3:
            total_tokens = stats.get("total_tokens_today", 0)
            st.metric(
                label="🔤 Total Tokens Consumed",
                value=f"{total_tokens:,}",
                delta=f"{stats.get('prompt_tokens_today', 0):,} in / {stats.get('candidates_tokens_today', 0):,} out",
                delta_color="off",
                help="Sum of prompt input tokens and generated completion tokens used today.",
            )

        with q_m4:
            st.metric(
                label="⏱️ Rate Limits (RPM / TPM)",
                value=f"{stats.get('rpm_limit')} RPM",
                delta=f"{stats.get('tpm_limit') // 1000:,}k TPM Limit",
                delta_color="off",
                help="Requests Per Minute (RPM) and Tokens Per Minute (TPM) limits for this model.",
            )

        # Progress bar for Free Tier
        if stats.get("plan_tier") == "free":
            used_pct = stats.get("requests_used_pct", 0.0)
            st.progress(
                min(1.0, used_pct / 100.0),
                text=f"Quota Utilization: {stats.get('requests_used', 0):,} / 1,500 daily requests used ({used_pct}%)",
            )
        else:
            st.info("ℹ️ **Pay-As-You-Go Active:** No daily request ceiling. You are billed directly per token by Google Cloud / AI Studio.")

        # Detailed breakdown expander
        with st.expander("🔍 Detailed Token Breakdown & Diagnostics", expanded=False):
            diag_c1, diag_c2, diag_c3 = st.columns(3)
            with diag_c1:
                st.markdown("**Token Consumption Today**")
                st.write(f"- Prompt (Input) Tokens: `{stats.get('prompt_tokens_today', 0):,}`")
                st.write(f"- Completion (Output) Tokens: `{stats.get('candidates_tokens_today', 0):,}`")
                st.write(f"- Combined Tokens: `{stats.get('total_tokens_today', 0):,}`")
            with diag_c2:
                st.markdown("**Model Specifications**")
                st.write(f"- Active Model: `{stats.get('active_model')}`")
                st.write(f"- Context Window: `{stats.get('context_window', 1048576):,} tokens`")
                st.write(f"- Max Output Tokens: `{stats.get('max_output_tokens', 8192):,} tokens`")
            with diag_c3:
                last_call = stats.get("last_call") or {}
                st.markdown("**Last API Call Diagnostics**")
                if last_call:
                    st.write(f"- Latency: `{last_call.get('latency_ms', 0)} ms`")
                    st.write(f"- Tokens: `{last_call.get('prompt_tokens', 0)} in / {last_call.get('candidates_tokens', 0)} out`")
                    st.write(f"- Timestamp: `{last_call.get('timestamp', 'N/A')}`")
                else:
                    st.write("*No API calls recorded in this session yet.*")

            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                if st.button("🔄 Refresh Usage Stats", use_container_width=True, key="refresh_quota_btn"):
                    st.rerun()
            with btn_col2:
                if st.button("🗑️ Reset Daily Counter", use_container_width=True, key="reset_quota_btn"):
                    reset_token_usage_stats()
                    st.success("Daily token and request counters have been reset.")
                    st.rerun()

    st.markdown("---")

    # =========================================================================
    # 2. SCORING DEFAULTS SECTION
    # =========================================================================
    st.markdown("### ⚖️ Algorithmic Scoring Weight Allocation")
    st.markdown(
        "<span style='color: #64748B; font-size: 0.9rem;'>"
        "Define the relative importance of each dimension when computing candidate match scores."
        "</span>",
        unsafe_allow_html=True,
    )

    # Maintain weight session state for interactive normalization
    if "w_mandatory" not in st.session_state:
        st.session_state["w_mandatory"] = cur_w_mandatory
        st.session_state["w_preferred"] = cur_w_preferred
        st.session_state["w_experience"] = cur_w_exp
        st.session_state["w_qualifications"] = cur_w_qual
        st.session_state["w_domain"] = cur_w_domain

    w_col1, w_col2 = st.columns(2)
    with w_col1:
        w_mand = st.slider("Mandatory Skills Weight", 0.0, 1.0, float(st.session_state["w_mandatory"]), 0.05, key="slider_mand")
        st.session_state["w_mandatory"] = w_mand

        w_pref = st.slider("Preferred Skills Weight", 0.0, 1.0, float(st.session_state["w_preferred"]), 0.05, key="slider_pref")
        st.session_state["w_preferred"] = w_pref

        w_exp = st.slider("Experience Alignment Weight", 0.0, 1.0, float(st.session_state["w_experience"]), 0.05, key="slider_exp")
        st.session_state["w_experience"] = w_exp

    with w_col2:
        w_qual = st.slider("Qualifications & Degree Weight", 0.0, 1.0, float(st.session_state["w_qualifications"]), 0.05, key="slider_qual")
        st.session_state["w_qualifications"] = w_qual

        w_dom = st.slider("Domain Expertise Weight", 0.0, 1.0, float(st.session_state["w_domain"]), 0.05, key="slider_dom")
        st.session_state["w_domain"] = w_dom

        weight_sum = round(w_mand + w_pref + w_exp + w_qual + w_dom, 2)
        if abs(weight_sum - 1.0) < 0.001:
            st.success(f"✓ Total Weight: **{weight_sum * 100:.0f}%** (Balanced)")
        else:
            st.warning(f"⚠️ Total Weight: **{weight_sum * 100:.0f}%** (Expected 100%)")

        btn_norm_col, btn_reset_col = st.columns(2)
        with btn_norm_col:
            if st.button("⚖️ Normalize to 100%", use_container_width=True):
                tot = w_mand + w_pref + w_exp + w_qual + w_dom
                if tot > 0:
                    st.session_state["w_mandatory"] = round(w_mand / tot, 2)
                    st.session_state["w_preferred"] = round(w_pref / tot, 2)
                    st.session_state["w_experience"] = round(w_exp / tot, 2)
                    st.session_state["w_qualifications"] = round(w_qual / tot, 2)
                    st.session_state["w_domain"] = round(w_dom / tot, 2)
                    st.rerun()

        with btn_reset_col:
            if st.button("🔄 Reset Defaults", use_container_width=True):
                st.session_state["w_mandatory"] = DEFAULT_WEIGHTS["mandatory_skills"]
                st.session_state["w_preferred"] = DEFAULT_WEIGHTS["preferred_skills"]
                st.session_state["w_experience"] = DEFAULT_WEIGHTS["experience"]
                st.session_state["w_qualifications"] = DEFAULT_WEIGHTS["qualifications"]
                st.session_state["w_domain"] = DEFAULT_WEIGHTS["domain"]
                st.rerun()

    st.markdown("---")

    # =========================================================================
    # 3. FILE PROCESSING & RETENTION
    # =========================================================================
    st.markdown("### 📁 File Processing & Document Retention")
    f_c1, f_c2, f_c3 = st.columns(3)

    with f_c1:
        max_size_input = st.slider(
            "Max File Upload Size (MB)",
            min_value=2,
            max_value=50,
            value=cur_max_size,
            step=1,
            help="Maximum permitted file size for PDF and DOCX uploads.",
        )

    with f_c2:
        max_batch_input = st.number_input(
            "Max Resumes per Batch",
            min_value=10,
            max_value=2000,
            value=cur_max_batch,
            step=50,
            help="Maximum candidate documents processed concurrently in one batch job.",
        )

    with f_c3:
        retention_days_input = st.number_input(
            "Resume Retention Period (Days)",
            min_value=30,
            max_value=1825,
            value=cur_retention,
            step=30,
            help="Days before archived resume documents become eligible for purging.",
        )

    st.markdown("---")

    # =========================================================================
    # 4. DUPLICATE DETECTION & EXPORT PREFERENCES
    # =========================================================================
    d_c1, d_c2 = st.columns(2)

    with d_c1:
        st.markdown("#### 🔍 Deduplication Settings")
        dup_enabled_input = st.toggle("Enable Resume Deduplication", value=cur_dup_enabled)
        dup_modes = ["Exact SHA-256 Hash", "Hash + Candidate Name", "Fuzzy Content Match"]
        dup_idx = dup_modes.index(cur_dup_strict) if cur_dup_strict in dup_modes else 0
        dup_strictness_input = st.selectbox("Deduplication Strictness", options=dup_modes, index=dup_idx)

    with d_c2:
        st.markdown("#### 📤 Export Preferences")
        export_formats = ["Excel (.xlsx)", "CSV (.csv)"]
        ef_idx = export_formats.index(cur_export_fmt) if cur_export_fmt in export_formats else 0
        export_fmt_input = st.selectbox("Default Export Format", options=export_formats, index=ef_idx)
        export_contact_input = st.toggle("Include Contact Details in Exports", value=cur_export_contact)

    st.markdown("---")

    # =========================================================================
    # 5. PERSISTENCE & SAVE CONTROLS
    # =========================================================================
    save_col1, save_col2 = st.columns([1.5, 4])

    with save_col1:
        save_btn = st.button("💾 Save Configuration Changes", type="primary", use_container_width=True)

    if save_btn:
        final_api_key = new_api_key.strip() if new_api_key.strip() else cur_api_key

        settings_to_persist = {
            "ai_enabled": str(ai_enabled_input).lower(),
            "ai_model": selected_model,
            "gemini_api_key": final_api_key,
            "weight_mandatory_skills": str(st.session_state["w_mandatory"]),
            "weight_preferred_skills": str(st.session_state["w_preferred"]),
            "weight_experience": str(st.session_state["w_experience"]),
            "weight_qualifications": str(st.session_state["w_qualifications"]),
            "weight_domain": str(st.session_state["w_domain"]),
            "max_file_size_mb": str(max_size_input),
            "max_batch_size": str(max_batch_input),
            "resume_retention_days": str(retention_days_input),
            "duplicate_detection_enabled": str(dup_enabled_input).lower(),
            "duplicate_strictness": dup_strictness_input,
            "default_export_format": export_fmt_input,
            "export_include_contact_details": str(export_contact_input).lower(),
        }

        try:
            with get_session() as session:
                for k, v in settings_to_persist.items():
                    _save_db_setting(session, k, v)

                audit_service.log_action(
                    entity_type="ApplicationSetting",
                    entity_id=None,
                    action="update_settings",
                    details={
                        "ai_model": selected_model,
                        "ai_enabled": ai_enabled_input,
                        "max_file_size_mb": max_size_input,
                    },
                    performed_by="Recruiter",
                )

            # Synchronize changes back to .env so .env and database remain aligned
            env_file = app_settings.BASE_DIR / ".env"
            if env_file.exists():
                try:
                    from dotenv import set_key
                    set_key(str(env_file), "AI_MODEL", selected_model)
                    if new_api_key.strip():
                        set_key(str(env_file), "GEMINI_API_KEY", new_api_key.strip())
                    set_key(str(env_file), "AI_ENABLED", str(ai_enabled_input).lower())
                except Exception as env_sync_err:
                    logger.warning("Could not sync updated settings to .env: %s", env_sync_err)

            st.success("✓ All configuration parameters persisted successfully to database and .env!")
            st.rerun()
        except Exception as save_err:
            st.error(f"Failed to persist settings: {save_err}")

    # =========================================================================
    # 6. CONFIGURATION SUMMARY CARD
    # =========================================================================
    st.markdown("<div style='margin-top: 1.5rem;'></div>", unsafe_allow_html=True)
    with st.expander("📋 Current Active Configuration Summary", expanded=True):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown("**AI Capabilities**")
            st.write(f"- Enabled: `{ai_enabled_input}`")
            st.write(f"- Model: `{selected_model}`")
            st.write(f"- API Key: `{_mask_api_key(cur_api_key)}`")
        with sc2:
            st.markdown("**Scoring Model**")
            st.write(f"- Mandatory Skills: `{st.session_state['w_mandatory'] * 100:.0f}%`")
            st.write(f"- Preferred Skills: `{st.session_state['w_preferred'] * 100:.0f}%`")
            st.write(f"- Experience: `{st.session_state['w_experience'] * 100:.0f}%`")
            st.write(f"- Qualifications: `{st.session_state['w_qualifications'] * 100:.0f}%`")
            st.write(f"- Domain Fit: `{st.session_state['w_domain'] * 100:.0f}%`")
        with sc3:
            st.markdown("**Platform Operational Rules**")
            st.write(f"- Max File Size: `{max_size_input} MB`")
            st.write(f"- Max Batch: `{max_batch_input}`")
            st.write(f"- Retention: `{retention_days_input} days`")
            st.write(f"- Deduplication: `{dup_strictness_input}`")
            st.write(f"- Export Format: `{export_fmt_input}`")

    # =========================================================================
    # 7. DANGER ZONE: DATABASE MANAGEMENT & DATA PURGE
    # =========================================================================
    st.markdown("<div style='margin-top: 2rem;'></div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div style="background-color: #FEF2F2; border: 1px solid #FECACA; border-left: 5px solid #DC2626; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.5rem;">
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <i class="bi bi-exclamation-triangle-fill" style="color: #DC2626; font-size: 1.3rem;"></i>
                <h4 style="color: #991B1B; margin: 0; font-weight: 700;">Danger Zone: Database Reset & Purge</h4>
            </div>
            <p style="color: #7F1D1D; font-size: 0.9rem; margin: 0;">
                These actions are permanent and cannot be undone. Use them to reset test data or wipe the local database completely.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dz_tab1, dz_tab2 = st.tabs([
        "🧹 Clear Candidates & Screening Data",
        "💥 Complete Factory Reset",
    ])

    with dz_tab1:
        st.markdown(
            """
            <div style="font-size: 0.9rem; color: #475569; margin-bottom: 1rem;">
                <strong>What this does:</strong> Permanently deletes all uploaded candidate profiles, resume documents, 
                match scores, screening batches, and shortlists.<br/>
                <span style="color: #15803D;"><strong>Preserved:</strong> Your Job Descriptions, requisitions, and application settings remain intact.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        confirm_cand_wipe = st.checkbox(
            "I confirm I want to permanently delete all candidates, resumes, and screening results.",
            key="cb_confirm_cand_wipe",
        )

        if st.button(
            "🗑️ Purge All Candidates & Screening History",
            type="primary" if confirm_cand_wipe else "secondary",
            disabled=not confirm_cand_wipe,
            key="btn_purge_candidates",
        ):
            try:
                db_mgr = DatabaseManager()
                outcome = db_mgr.clear_candidate_and_screening_data()
                st.success(
                    f"✓ Candidate data cleared: {outcome['candidates_deleted']} candidate(s), "
                    f"{outcome['resumes_deleted']} resume(s), {outcome['matches_deleted']} match result(s) deleted."
                )
                audit_service.log_action(
                    entity_type="Database",
                    entity_id=None,
                    action="purge_candidates",
                    details=outcome,
                    performed_by="Recruiter",
                )
                st.rerun()
            except Exception as purge_err:
                st.error(f"Failed to clear candidate data: {purge_err}")

    with dz_tab2:
        st.markdown(
            """
            <div style="font-size: 0.9rem; color: #475569; margin-bottom: 1rem;">
                <strong>What this does:</strong> Drops all tables in <code>talentmatch.db</code> and reinitializes a pristine database.<br/>
                <span style="color: #B91C1C;"><strong>Deleted:</strong> Everything will be erased — Job Descriptions, Candidates, Resumes, Match Results, Shortlists, and Audit Logs.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        confirm_text = st.text_input(
            "Type DELETE to confirm complete database wipe:",
            placeholder="DELETE",
            key="input_confirm_factory_reset",
        )

        is_delete_ready = (confirm_text.strip() == "DELETE")

        if st.button(
            "⚠️ Wipe Entire Database & Start Fresh",
            type="primary" if is_delete_ready else "secondary",
            disabled=not is_delete_ready,
            key="btn_factory_reset",
        ):
            try:
                db_mgr = DatabaseManager()
                db_mgr.reset_database()
                # Clear all active session states related to navigation and selections
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.success("✓ Complete factory reset successful! All tables have been reinitialized.")
                st.rerun()
            except Exception as reset_err:
                st.error(f"Failed to reset database: {reset_err}")
