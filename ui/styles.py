"""Custom styling and CSS theme for TalentMatch AI.

Provides a professional Navy/Blue (#1e3a5f) enterprise theme, badge components,
card styles, table interactions, responsive layouts, and typography.
"""


def get_custom_css() -> str:
    """Return comprehensive custom CSS stylesheet for TalentMatch AI Streamlit application.

    Returns:
        str: HTML style block containing CSS rules and Bootstrap Icons CDN.
    """
    return """
<!-- Bootstrap Icons CDN -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">

<style>
    /* =========================================================================
       1. Global Theme Variables & Base Styles
       ========================================================================= */
    :root {
        --tm-navy-primary: #1e3a5f;
        --tm-navy-dark: #0f172a;
        --tm-navy-light: #2c4c7c;
        --tm-blue-accent: #2563eb;
        --tm-blue-secondary: #3b82f6;
        --tm-blue-soft: #eff6ff;
        
        --tm-bg-app: #f8fafc;
        --tm-card-bg: #ffffff;
        --tm-border-light: #e2e8f0;
        --tm-border-focus: #3b82f6;
        
        --tm-text-primary: #0f172a;
        --tm-text-secondary: #475569;
        --tm-text-muted: #64748b;
        --tm-text-light: #94a3b8;
        
        --tm-success-bg: #dcfce7;
        --tm-success-text: #15803d;
        --tm-success-border: #86efac;
        
        --tm-warning-bg: #fef3c7;
        --tm-warning-text: #92400e;
        --tm-warning-border: #fcd34d;
        
        --tm-danger-bg: #fee2e2;
        --tm-danger-text: #991b1b;
        --tm-danger-border: #fca5a5;
        
        --tm-info-bg: #dbeafe;
        --tm-info-text: #1e40af;
        --tm-info-border: #93c5fd;
        
        --tm-gray-bg: #f1f5f9;
        --tm-gray-text: #475569;
        --tm-gray-border: #cbd5e1;
        
        --tm-radius-sm: 4px;
        --tm-radius-md: 8px;
        --tm-radius-lg: 12px;
        --tm-radius-pill: 9999px;
        
        --tm-shadow-subtle: 0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04);
        --tm-shadow-card: 0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.05);
        --tm-shadow-hover: 0 10px 15px -3px rgba(15, 23, 42, 0.08), 0 4px 6px -4px rgba(15, 23, 42, 0.03);
    }
        --tm-info-border: #93c5fd;
        
        --tm-gray-bg: #f1f5f9;
        --tm-gray-text: #475569;
        --tm-gray-border: #cbd5e1;
        
        --tm-radius-sm: 4px;
        --tm-radius-md: 8px;
        --tm-radius-lg: 12px;
        --tm-radius-pill: 9999px;
        
        --tm-shadow-subtle: 0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04);
        --tm-shadow-card: 0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.05);
        --tm-shadow-hover: 0 10px 15px -3px rgba(15, 23, 42, 0.08), 0 4px 6px -4px rgba(15, 23, 42, 0.03);
    }

    /* Overall font and background polish */
    .stApp {
        background-color: var(--tm-bg-app);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: var(--tm-text-primary);
    }

    /* =========================================================================
       2. Sidebar Styling
       ========================================================================= */
    section[data-testid="stSidebar"] {
        background-color: #ffffff !important;
        border-right: 1px solid var(--tm-border-light);
    }

    /* Navigation buttons in sidebar — look like menu items */
    section[data-testid="stSidebar"] div.stButton > button {
        background-color: transparent !important;
        border: none !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        color: #475569 !important;
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 0.55rem 0.75rem !important;
        margin: 1px 0 !important;
        min-height: unset !important;
        transition: all 0.12s ease !important;
    }

    section[data-testid="stSidebar"] div.stButton > button:hover {
        background-color: #F0F4FF !important;
        color: #1E3A8A !important;
        border: none !important;
        transform: none !important;
    }

    /* Active nav button (type=primary) */
    section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
        background-color: #EFF6FF !important;
        color: #1E40AF !important;
        font-weight: 600 !important;
        border: none !important;
        border-left: 3px solid #1E40AF !important;
        border-radius: 0 8px 8px 0 !important;
    }

    section[data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {
        background-color: #DBEAFE !important;
    }

    section[data-testid="stSidebar"] div.stButton > button p,
    section[data-testid="stSidebar"] div.stButton > button span {
        font-size: 0.88rem !important;
        font-weight: inherit !important;
    }

    /* =========================================================================
       3. Section Headers & Title Components
       ========================================================================= */
    .tm-header-container {
        padding: 0.75rem 0 1.25rem 0;
        border-bottom: 2px solid var(--tm-border-light);
        margin-bottom: 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
    }

    .tm-header-title {
        color: var(--tm-navy-primary);
        font-size: 2.1rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin: 0;
        line-height: 1.2;
    }

    .tm-header-subtitle {
        color: var(--tm-text-muted);
        font-size: 1rem;
        margin-top: 0.35rem;
        margin-bottom: 0;
    }

    .tm-section-header {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--tm-navy-primary);
        margin-top: 1.5rem;
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    /* =========================================================================
       4. Card Components & Metrics
       ========================================================================= */
    .tm-card {
        background-color: var(--tm-card-bg);
        border: 1px solid var(--tm-border-light);
        border-radius: var(--tm-radius-md);
        padding: 1.25rem;
        box-shadow: var(--tm-shadow-card);
        margin-bottom: 1.25rem;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }

    .tm-card:hover {
        box-shadow: var(--tm-shadow-hover);
    }

    .tm-card-highlight {
        border-left: 5px solid var(--tm-navy-primary);
    }

    .tm-metric-card {
        background-color: var(--tm-card-bg);
        border: 1px solid var(--tm-border-light);
        border-radius: var(--tm-radius-md);
        padding: 1rem;
        text-align: center;
        box-shadow: var(--tm-shadow-subtle);
        transition: all 0.2s ease;
    }

    .tm-metric-card:hover {
        border-color: var(--tm-blue-accent);
        transform: translateY(-2px);
    }

    .tm-metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--tm-navy-primary);
        line-height: 1.1;
    }

    .tm-metric-label {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--tm-text-muted);
        margin-top: 0.35rem;
    }

    /* =========================================================================
       5. Badges (Status, Analysis, Scores, Categories)
       ========================================================================= */
    .tm-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.25rem 0.65rem;
        border-radius: var(--tm-radius-pill);
        font-size: 0.78rem;
        font-weight: 600;
        line-height: 1;
        border: 1px solid transparent;
        white-space: nowrap;
    }

    /* Status Badges */
    .badge-active {
        background-color: var(--tm-success-bg);
        color: var(--tm-success-text);
        border-color: var(--tm-success-border);
    }

    .badge-inactive {
        background-color: var(--tm-gray-bg);
        color: var(--tm-gray-text);
        border-color: var(--tm-gray-border);
    }

    /* Analysis Status Badges */
    .badge-analyzed {
        background-color: var(--tm-info-bg);
        color: var(--tm-info-text);
        border-color: var(--tm-info-border);
    }

    .badge-needs-reanalysis {
        background-color: var(--tm-warning-bg);
        color: var(--tm-warning-text);
        border-color: var(--tm-warning-border);
    }

    .badge-not-analyzed {
        background-color: var(--tm-danger-bg);
        color: var(--tm-danger-text);
        border-color: var(--tm-danger-border);
    }

    /* Score Badges */
    .score-badge {
        display: inline-block;
        padding: 0.35rem 0.75rem;
        border-radius: var(--tm-radius-pill);
        font-size: 0.9rem;
        font-weight: 700;
        text-align: center;
    }

    .score-high {
        background-color: var(--tm-success-bg);
        color: var(--tm-success-text);
        border: 1px solid var(--tm-success-border);
    }

    .score-medium {
        background-color: var(--tm-warning-bg);
        color: var(--tm-warning-text);
        border: 1px solid var(--tm-warning-border);
    }

    .score-low {
        background-color: var(--tm-danger-bg);
        color: var(--tm-danger-text);
        border: 1px solid var(--tm-danger-border);
    }

    /* Category Badges */
    .cat-badge {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: var(--tm-radius-sm);
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: capitalize;
    }

    .cat-mandatory-skill {
        background-color: #dbeafe;
        color: #1e40af;
        border: 1px solid #bfdbfe;
    }

    .cat-preferred-skill {
        background-color: #e0e7ff;
        color: #3730a3;
        border: 1px solid #c7d2fe;
    }

    .cat-experience {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px solid #fde68a;
    }

    .cat-education {
        background-color: #f3e8ff;
        color: #6b21a8;
        border: 1px solid #e9d5ff;
    }

    .cat-certification {
        background-color: #dcfce7;
        color: #15803d;
        border: 1px solid #bbf7d0;
    }

    .cat-tool {
        background-color: #ccfbf1;
        color: #115e59;
        border: 1px solid #99f6e4;
    }

    .cat-responsibility {
        background-color: #f1f5f9;
        color: #334155;
        border: 1px solid #e2e8f0;
    }

    /* =========================================================================
       6. Table & Grid Styling
       ========================================================================= */
    .tm-table-container {
        border: 1px solid var(--tm-border-light);
        border-radius: var(--tm-radius-md);
        background-color: var(--tm-card-bg);
        box-shadow: var(--tm-shadow-card);
        overflow: hidden;
        margin-top: 1rem;
        margin-bottom: 1.5rem;
    }

    .tm-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.88rem;
        text-align: left;
    }

    .tm-table th {
        background-color: #f8fafc;
        color: var(--tm-text-secondary);
        font-weight: 600;
        padding: 0.75rem 1rem;
        border-bottom: 2px solid var(--tm-border-light);
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
    }

    .tm-table td {
        padding: 0.85rem 1rem;
        border-bottom: 1px solid var(--tm-border-light);
        color: var(--tm-text-primary);
        vertical-align: middle;
    }

    .tm-table tr:last-child td {
        border-bottom: none;
    }

    .tm-table tr:hover {
        background-color: #f0f7ff;
    }

    /* =========================================================================
       7. Button Enhancements
       ========================================================================= */
    /* Primary Action Buttons */
    div.stButton > button[kind="primary"] {
        background-color: var(--tm-navy-primary) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: var(--tm-radius-md) !important;
        font-weight: 600 !important;
        padding: 0.45rem 1.15rem !important;
        box-shadow: var(--tm-shadow-subtle) !important;
        transition: all 0.15s ease !important;
    }

    div.stButton > button[kind="primary"]:hover {
        background-color: var(--tm-navy-light) !important;
        transform: translateY(-1px) !important;
        box-shadow: var(--tm-shadow-card) !important;
    }

    /* Secondary / Default Outline Buttons */
    div.stButton > button[kind="secondary"],
    div.stButton > button:not([kind="primary"]) {
        border: 1px solid var(--tm-border-light) !important;
        background-color: #ffffff !important;
        color: var(--tm-text-primary) !important;
        border-radius: var(--tm-radius-md) !important;
        font-weight: 500 !important;
        transition: all 0.15s ease !important;
        font-family: "Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }

    div.stButton > button[kind="secondary"]:hover,
    div.stButton > button:not([kind="primary"]):hover {
        border-color: var(--tm-blue-accent) !important;
        color: var(--tm-blue-accent) !important;
        background-color: var(--tm-blue-soft) !important;
    }

    /* Action button container & compact icon buttons styling */
    div.stButton > button {
        padding: 0.2rem 0.4rem !important;
        min-height: 2.2rem !important;
        line-height: 1 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        overflow: visible !important;
        text-align: center !important;
    }

    div.stButton > button p,
    div.stButton > button span {
        font-size: 1.15rem !important;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1 !important;
        display: inline-block !important;
        visibility: visible !important;
        opacity: 1 !important;
        font-family: "Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }

    /* Danger action button helper */
    .btn-danger button {
        background-color: #fee2e2 !important;
        color: #b91c1c !important;
        border-color: #fca5a5 !important;
    }

    .btn-danger button:hover {
        background-color: #dc2626 !important;
        color: #ffffff !important;
        border-color: #dc2626 !important;
    }

    /* =========================================================================
       8. Forms & Inputs
       ========================================================================= */
    .stTextInput input,
    .stTextArea textarea,
    .stSelectbox div[data-baseweb="select"] {
        border-radius: var(--tm-radius-md) !important;
        border: 1px solid var(--tm-border-light) !important;
        font-size: 0.9rem !important;
    }

    .stTextInput input:focus,
    .stTextArea textarea:focus {
        border-color: var(--tm-blue-accent) !important;
        box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15) !important;
    }

    /* Expanders styling */
    div[data-testid="stExpander"] {
        border: 1px solid var(--tm-border-light) !important;
        border-radius: var(--tm-radius-md) !important;
        background-color: var(--tm-card-bg) !important;
        box-shadow: var(--tm-shadow-subtle) !important;
        margin-bottom: 1rem !important;
    }

    div[data-testid="stExpander"] details summary {
        font-weight: 600 !important;
        color: var(--tm-navy-primary) !important;
    }

    /* =========================================================================
       9. Alerts & Notification Banners
       ========================================================================= */
    .tm-alert {
        padding: 0.85rem 1.15rem;
        border-radius: var(--tm-radius-md);
        margin-bottom: 1rem;
        font-size: 0.9rem;
        display: flex;
        align-items: center;
        gap: 0.65rem;
    }

    .tm-alert-info {
        background-color: var(--tm-info-bg);
        color: var(--tm-info-text);
        border: 1px solid var(--tm-info-border);
    }

    .tm-alert-warning {
        background-color: var(--tm-warning-bg);
        color: var(--tm-warning-text);
        border: 1px solid var(--tm-warning-border);
    }

    .tm-alert-success {
        background-color: var(--tm-success-bg);
        color: var(--tm-success-text);
        border: 1px solid var(--tm-success-border);
    }

    .tm-alert-danger {
        background-color: var(--tm-danger-bg);
        color: var(--tm-danger-text);
        border: 1px solid var(--tm-danger-border);
    }

    /* =========================================================================
       10. Empty State Display
       ========================================================================= */
    .tm-empty-state {
        text-align: center;
        padding: 3rem 1.5rem;
        background-color: var(--tm-card-bg);
        border: 2px dashed var(--tm-border-light);
        border-radius: var(--tm-radius-lg);
        margin: 1.5rem 0;
    }

    .tm-empty-icon {
        font-size: 3rem;
        margin-bottom: 0.75rem;
        opacity: 0.7;
    }

    .tm-empty-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--tm-navy-primary);
        margin-bottom: 0.35rem;
    }

    .tm-empty-desc {
        font-size: 0.92rem;
        color: var(--tm-text-muted);
        max-width: 460px;
        margin: 0 auto 1.25rem auto;
    }

    /* =========================================================================
       11. Weight Meter & Progress
       ========================================================================= */
    .tm-weight-meter-container {
        background-color: #f1f5f9;
        border-radius: var(--tm-radius-pill);
        height: 10px;
        overflow: hidden;
        margin-top: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .tm-weight-meter-bar {
        background-color: var(--tm-navy-primary);
        height: 100%;
        border-radius: var(--tm-radius-pill);
        transition: width 0.3s ease;
    }

    /* =========================================================================
       12. Pagination Controls
       ========================================================================= */
    .tm-pagination {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 1.25rem;
        padding: 0.75rem 0;
        border-top: 1px solid var(--tm-border-light);
        font-size: 0.88rem;
        color: var(--tm-text-secondary);
    }

    /* =========================================================================
       13. Bootstrap 5 Modern Card & Metric Enhancements
       ========================================================================= */
    .tm-bs-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .tm-bs-card:hover {
        border-color: #CBD5E1;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
        transform: translateY(-2px);
    }

    /* Modern KPI Stat Card with Icon Box */
    .tm-stat-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.15rem 1.25rem;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        display: flex;
        align-items: center;
        gap: 1.1rem;
        transition: all 0.2s ease;
        margin-bottom: 0.75rem;
    }
    .tm-stat-card:hover {
        border-color: #94A3B8;
        box-shadow: 0 6px 16px rgba(15, 23, 42, 0.07);
        transform: translateY(-2px);
    }

    .tm-icon-box {
        width: 48px;
        height: 48px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.4rem;
        flex-shrink: 0;
    }
    .tm-icon-box-blue {
        background-color: #EFF6FF;
        color: #2563EB;
        border: 1px solid #DBEAFE;
    }
    .tm-icon-box-green {
        background-color: #F0FDF4;
        color: #16A34A;
        border: 1px solid #DCFCE7;
    }
    .tm-icon-box-amber {
        background-color: #FFFBEB;
        color: #D97706;
        border: 1px solid #FEF3C7;
    }
    .tm-icon-box-purple {
        background-color: #FAF5FF;
        color: #9333EA;
        border: 1px solid #F3E8FF;
    }
    .tm-icon-box-indigo {
        background-color: #EEF2FF;
        color: #4F46E5;
        border: 1px solid #E0E7FF;
    }

    .tm-stat-content {
        flex: 1;
        min-width: 0;
    }
    .tm-stat-title {
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748B;
        margin-bottom: 0.2rem;
    }
    .tm-stat-num {
        font-size: 1.75rem;
        font-weight: 700;
        color: #0F172A;
        line-height: 1.15;
    }
    .tm-stat-sub {
        font-size: 0.8rem;
        color: #64748B;
        margin-top: 0.25rem;
    }

    /* Contextual Badges with Subtle Backgrounds */
    .badge-subtle-primary {
        background-color: #EFF6FF;
        color: #1E40AF;
        border: 1px solid #BFDBFE;
    }
    .badge-subtle-success {
        background-color: #F0FDF4;
        color: #15803D;
        border: 1px solid #BBF7D0;
    }
    .badge-subtle-warning {
        background-color: #FFFBEB;
        color: #B45309;
        border: 1px solid #FDE68A;
    }
    .badge-subtle-danger {
        background-color: #FEF2F2;
        color: #B91C1C;
        border: 1px solid #FECACA;
    }
    .badge-subtle-secondary {
        background-color: #F8FAFC;
        color: #475569;
        border: 1px solid #E2E8F0;
    }

    /* Candidate Initials Avatar */
    .tm-avatar {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: linear-gradient(135deg, #1E40AF 0%, #3B82F6 100%);
        color: #FFFFFF;
        font-weight: 700;
        font-size: 0.85rem;
        letter-spacing: 0.02em;
        box-shadow: 0 1px 3px rgba(30, 64, 175, 0.2);
    }

    /* Evidence Callout Box */
    .tm-callout {
        border-left: 4px solid #2563EB;
        background-color: #F8FAFC;
        padding: 0.85rem 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.65rem 0;
        font-size: 0.9rem;
    }

    /* =========================================================================
       14. Responsive Utilities
       ========================================================================= */
    @media (max-width: 768px) {
        .tm-header-container {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.75rem;
        }
        .tm-header-title {
            font-size: 1.6rem;
        }
        .tm-metric-value {
            font-size: 1.5rem;
        }
    }
</style>
"""


# =============================================================================
# Python Helper Components for Bootstrap-Enhanced UI Rendering
# =============================================================================

def render_stat_card(
    title: str,
    value: str | int | float,
    icon_class: str,
    subtitle: str = "",
    color_scheme: str = "blue",
) -> str:
    """Render a Bootstrap 5 styled KPI stat card with SVG icon box."""
    sub_html = f'<div class="tm-stat-sub">{subtitle}</div>' if subtitle else ""
    return f"""
    <div class="tm-stat-card">
        <div class="tm-icon-box tm-icon-box-{color_scheme}">
            <i class="{icon_class}"></i>
        </div>
        <div class="tm-stat-content">
            <div class="tm-stat-title">{title}</div>
            <div class="tm-stat-num">{value}</div>
            {sub_html}
        </div>
    </div>
    """


def render_badge(text: str, variant: str = "primary", icon: str = "") -> str:
    """Render a modern Bootstrap-styled subtle badge pill."""
    icon_html = f'<i class="{icon}" style="margin-right: 0.3rem;"></i>' if icon else ""
    return f"""
    <span class="tm-badge badge-subtle-{variant}">
        {icon_html}{text}
    </span>
    """


def render_status_pill(status: str) -> str:
    """Render a colored badge pill for JD or workflow statuses."""
    st_clean = status.strip().lower()
    mapping = {
        "open": ("success", "bi bi-check-circle-fill"),
        "active": ("success", "bi bi-check-circle-fill"),
        "in progress": ("primary", "bi bi-arrow-repeat"),
        "on hold": ("warning", "bi bi-pause-circle-fill"),
        "closed": ("secondary", "bi bi-archive-fill"),
        "draft": ("secondary", "bi bi-pencil-square"),
        "strong_match": ("success", "bi bi-star-fill"),
        "good_match": ("primary", "bi bi-hand-thumbs-up-fill"),
        "needs_review": ("warning", "bi bi-question-circle-fill"),
        "not_a_match": ("danger", "bi bi-x-circle-fill"),
    }
    variant, icon = mapping.get(st_clean, ("secondary", "bi bi-circle"))
    return render_badge(status.replace("_", " ").title(), variant=variant, icon=icon)


def render_candidate_avatar(name: str, size: int = 36) -> str:
    """Render a circular avatar chip with candidate initials."""
    parts = (name or "Candidate").strip().split()
    initials = "".join(p[0].upper() for p in parts[:2]) if parts else "C"
    return f"""
    <div class="tm-avatar" style="width: {size}px; height: {size}px; font-size: {int(size * 0.4)}px;">
        {initials}
    </div>
    """


def render_page_header(title: str, subtitle: str = "", icon_class: str = "") -> str:
    """Render modern page header block with Bootstrap icon."""
    icon_html = f'<i class="{icon_class}" style="color: #2563EB; margin-right: 0.6rem;"></i>' if icon_class else ""
    sub_html = f'<p style="color: #64748B; margin: 0.3rem 0 0 0; font-size: 0.95rem;">{subtitle}</p>' if subtitle else ""
    return f"""
    <div style="margin-bottom: 1.25rem;">
        <h2 style="color: #0F172A; margin: 0; font-weight: 700; display: flex; align-items: center;">
            {icon_html}{title}
        </h2>
        {sub_html}
    </div>
    """
