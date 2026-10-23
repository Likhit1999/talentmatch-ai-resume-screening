"""TalentMatch AI - Main Streamlit Application Entrypoint.

AI-Powered Resume Screening & Job Matching Platform.
"""

import sys

# Suppress harmless Windows-specific asyncio proactor pipe shutdown errors (WinError 10054)
if sys.platform == "win32":
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost

        def _silenced_call_connection_lost(self, exc):
            try:
                _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        _ProactorBasePipeTransport._call_connection_lost = _silenced_call_connection_lost
    except Exception:
        pass

import streamlit as st

from config.settings import get_settings
from database.connection import init_db
from ui.candidate_database import render_candidate_database
from ui.dashboard import render_dashboard
from ui.history import render_screening_history
from ui.jd_analyzer import render_jd_analyzer
from ui.jd_management import render_jd_management
from ui.match_rank import render_match_rank
from ui.resume_upload import render_resume_upload
from ui.settings import render_settings
from ui.shortlist import render_shortlist
from ui.styles import get_custom_css
from utils.logging_config import setup_logging

# Page configuration
st.set_page_config(
    page_title="TalentMatch AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize logging and configuration
settings = get_settings()
logger = setup_logging()

# Navigation definitions — icons, labels, and Bootstrap icon classes
NAV_ITEMS = [
    ("📊", "Dashboard", "bi bi-speedometer2"),
    ("📋", "Job Descriptions", "bi bi-briefcase"),
    ("🔍", "JD Analyzer", "bi bi-cpu"),
    ("👥", "Candidate Directory", "bi bi-people"),
    ("📄", "Resume Upload", "bi bi-cloud-arrow-up"),
    ("⚡", "Match & Rank", "bi bi-lightning-charge"),
    ("✅", "Shortlists & Export", "bi bi-bookmark-check"),
    ("📈", "Screening History", "bi bi-clock-history"),
    ("⚙️", "Settings & AI Config", "bi bi-gear"),
]

# Custom CSS for Navy/Blue professional theme + sidebar menu styling
NAVY_BLUE_THEME_CSS = """
<style>
    :root {
        --primary-navy: #0F172A;
        --accent-blue: #1E40AF;
        --secondary-blue: #3B82F6;
        --light-blue-bg: #F0F4F8;
        --card-border: #E2E8F0;
    }

    /* ── Top Navigation Bar (Header) ───────────────────────────── */
    header[data-testid="stHeader"] {
        background-color: #FFFFFF !important;
        border-bottom: 1px solid var(--card-border) !important;
        height: 3.25rem !important;
        display: flex !important;
        align-items: center !important;
        z-index: 99 !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
    }

    /* Hide extraneous Streamlit deploy button */
    [data-testid="stDeployButton"] {
        display: none !important;
        visibility: hidden !important;
    }

    /* Prevent >> (expand menu) button from showing when sidebar is already open */
    section[data-testid="stSidebar"][aria-expanded="true"] ~ * [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"][aria-expanded="true"] ~ div [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebar"][aria-expanded="true"] ~ * [data-testid="stSidebarCollapsedControl"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }

    /* Position >> button cleanly in top navbar when sidebar is collapsed */
    [data-testid="stSidebarCollapsedControl"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        top: 0.35rem !important;
        left: 0.75rem !important;
    }

    /* Eliminate huge blank space / top gap under the top navbar */
    .stMainBlockContainer,
    .block-container,
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stAppViewBlockContainer"],
    section.main > div {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        margin-top: 0 !important;
    }

    section[data-testid="stSidebar"] > div:first-child,
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {
        padding-top: 0.5rem !important;
    }

    /* ── App title bar ─────────────────────────────────────────── */
    .app-title-container {
        padding: 0.25rem 0 0.5rem 0 !important;
        border-bottom: 2px solid var(--card-border);
        margin-bottom: 1rem !important;
    }
    .app-title {
        color: #1E3A8A;
        font-size: 1.75rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .app-subtitle {
        color: #64748B;
        font-size: 0.92rem;
        margin-top: 0.2rem;
    }

    /* ── Feature cards ─────────────────────────────────────────── */
    .feature-card {
        background-color: #FFFFFF;
        border: 1px solid var(--card-border);
        border-left: 5px solid #1E3A8A;
        border-radius: 8px;
        padding: 1.25rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
    }
    .feature-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1E3A8A;
        margin-bottom: 0.5rem;
    }

    /* ── Sidebar branding ──────────────────────────────────────── */
    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.25rem 0 0.5rem 0;
    }
    .sidebar-brand-icon {
        font-size: 1.5rem;
        line-height: 1;
    }
    .sidebar-brand-text {
        font-size: 1.2rem;
        font-weight: 700;
        color: #1E3A8A;
        letter-spacing: -0.02em;
    }
    .sidebar-version {
        display: inline-block;
        padding: 0.15rem 0.5rem;
        border-radius: 9999px;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.025em;
        background-color: #DBEAFE;
        color: #1E40AF;
        margin-bottom: 0.5rem;
    }

    /* ── Sidebar nav section label ─────────────────────────────── */
    .nav-section-label {
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #94A3B8;
        padding: 0.6rem 0.75rem 0.35rem 0.75rem;
    }

    /* ── Sidebar nav buttons ───────────────────────────────────── */
    .nav-btn {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        width: 100%;
        padding: 0.55rem 0.75rem;
        margin: 1px 0;
        border: none;
        border-radius: 8px;
        background: transparent;
        color: #475569;
        font-size: 0.88rem;
        font-weight: 500;
        cursor: pointer;
        text-decoration: none;
        transition: all 0.12s ease;
        text-align: left;
        line-height: 1.3;
    }
    .nav-btn:hover {
        background-color: #F0F4FF;
        color: #1E3A8A;
    }
    .nav-btn-active {
        background-color: #EFF6FF;
        color: #1E40AF;
        font-weight: 600;
        border-left: 3px solid #1E40AF;
        padding-left: calc(0.75rem - 3px);
    }
    .nav-btn-icon {
        font-size: 1.05rem;
        width: 1.25rem;
        text-align: center;
        flex-shrink: 0;
    }

    /* ── Sidebar compact status strip ──────────────────────────── */
    .status-strip {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.55rem 0.75rem;
        border-radius: 8px;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        font-size: 0.75rem;
        color: #475569;
        margin-top: 0.25rem;
    }
    .status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .status-dot-green { background-color: #22C55E; }
    .status-dot-red   { background-color: #EF4444; }
    .status-dot-amber { background-color: #F59E0B; }
    .status-label {
        font-weight: 600;
        color: #334155;
    }
    .status-sep {
        color: #CBD5E1;
    }

    /* ── Hide default Streamlit sidebar elements we don't need ── */
    section[data-testid="stSidebar"] .stRadio { display: none !important; }
</style>
"""

st.markdown(NAVY_BLUE_THEME_CSS, unsafe_allow_html=True)
st.markdown(get_custom_css(), unsafe_allow_html=True)


@st.cache_resource(show_spinner="Initializing Database...")
def bootstrap_application() -> bool:
    """Initialize database tables and default configuration once per session."""
    try:
        init_db()
        logger.info("Application bootstrap complete: database ready.")
        return True
    except Exception as exc:
        logger.error("Database initialization failed: %s", exc, exc_info=True)
        st.error(f"Failed to initialize database: {exc}")
        return False


# Run bootstrap
db_initialized = bootstrap_application()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar Navigation
# ─────────────────────────────────────────────────────────────────────────────
if "nav_index" not in st.session_state:
    st.session_state.nav_index = 0

with st.sidebar:
    # Brand header with modern Bootstrap SVG icon
    st.markdown(
        """
        <div class="sidebar-brand">
            <i class="bi bi-bullseye" style="font-size: 1.6rem; color: #2563EB;"></i>
            <span class="sidebar-brand-text">TalentMatch AI</span>
        </div>
        <span class="sidebar-version">v1.0.0 Enterprise</span>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # Navigation section label
    st.markdown('<div class="nav-section-label">Main Menu</div>', unsafe_allow_html=True)

    # Render clickable navigation buttons
    for idx, (icon, label, *rest) in enumerate(NAV_ITEMS):
        is_active = idx == st.session_state.nav_index
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{idx}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state.nav_index = idx
            st.rerun()

    st.markdown("---")

    # Compact system status strip (replaces verbose telemetry)
    db_ok = db_initialized
    ai_ok = settings.is_ai_available
    db_dot = "status-dot-green" if db_ok else "status-dot-red"
    ai_dot = "status-dot-green" if ai_ok else "status-dot-amber"
    db_text = "DB Ready" if db_ok else "DB Error"
    ai_text = settings.get_model() if ai_ok else "AI Offline"

    st.markdown(
        f"""
        <div class="status-strip">
            <span class="status-dot {db_dot}"></span>
            <span class="status-label">{db_text}</span>
            <span class="status-sep">│</span>
            <span class="status-dot {ai_dot}"></span>
            <span class="status-label">{ai_text}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main Content Area
# ─────────────────────────────────────────────────────────────────────────────
_icon, page_name, bs_icon = NAV_ITEMS[st.session_state.nav_index]

# Header
st.markdown(
    f"""
    <div class="app-title-container">
        <h1 class="app-title"><i class="{bs_icon}" style="color: #2563EB; margin-right: 0.45rem;"></i>{page_name}</h1>
        <div class="app-subtitle">TalentMatch AI • Enterprise Intelligent Screening & Assessment</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Page Router
nav = st.session_state.nav_index

if nav == 0:
    render_dashboard()

elif nav == 1:
    render_jd_management()

elif nav == 2:
    render_jd_analyzer()

elif nav == 3:
    render_candidate_database()

elif nav == 4:
    render_resume_upload()

elif nav == 5:
    render_match_rank()

elif nav == 6:
    render_shortlist()

elif nav == 7:
    render_screening_history()

elif nav == 8:
    render_settings()
