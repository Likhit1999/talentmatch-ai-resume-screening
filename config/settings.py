"""Application configuration and settings management for TalentMatch AI.

Loads environment variables using python-dotenv and provides typed settings
with sensible defaults.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env file only if it exists (never load placeholder .env.example into environment)
if (BASE_DIR / ".env").exists():
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

KNOWN_PLACEHOLDERS = {
    "your_api_key_here",
    "your_google_api_key_here",
    "your_gemini_api_key_here",
    "placeholder",
    "none",
    "null",
    "undefined",
    "",
}


def clean_api_key(val: Optional[str]) -> str:
    """Clean, unquote, and validate an API key string.

    Strips whitespace, newlines, and surrounding quotes (' or ").
    Returns an empty string if the key matches known dummy placeholders.
    """
    if val is None:
        return ""
    cleaned = str(val).strip().strip("'\"").strip()
    if cleaned.lower() in KNOWN_PLACEHOLDERS:
        return ""
    return cleaned


def _get_env_or_secret(key: str, default: str = "") -> str:
    """Read configuration with priority: Streamlit secrets -> os.environ -> default.

    Supports:
    - Direct key lookups in st.secrets (e.g. GEMINI_API_KEY, gemini_api_key)
    - Common sections in st.secrets (e.g. st.secrets["gemini"]["api_key"])
    - Direct lookups in os.environ
    """
    # 1. Check Streamlit Cloud Secrets first
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets is not None:
            # Check candidate key name variations
            for k in (key, key.upper(), key.lower()):
                if k in st.secrets:
                    val = st.secrets[k]
                    if val is not None:
                        s_val = clean_api_key(val) if "api_key" in key.lower() else str(val).strip().strip("'\"").strip()
                        if s_val and s_val.lower() not in KNOWN_PLACEHOLDERS:
                            return s_val

            # Check nested sections: [general], [gemini], [google], [ai]
            for sec in ("general", "gemini", "google", "ai"):
                if sec in st.secrets:
                    sec_data = st.secrets[sec]
                    if isinstance(sec_data, dict):
                        for k in (key, key.upper(), key.lower(), "api_key", "key"):
                            if k in sec_data:
                                val = sec_data[k]
                                if val is not None:
                                    s_val = clean_api_key(val) if "api_key" in key.lower() else str(val).strip().strip("'\"").strip()
                                    if s_val and s_val.lower() not in KNOWN_PLACEHOLDERS:
                                        return s_val
    except Exception:
        pass

    # 2. Check Environment Variables
    for k in (key, key.upper(), key.lower()):
        val = os.getenv(k)
        if val is not None:
            s_val = clean_api_key(val) if "api_key" in key.lower() else str(val).strip().strip("'\"").strip()
            if s_val and s_val.lower() not in KNOWN_PLACEHOLDERS:
                return s_val

    return default


def _str_to_bool(value: Optional[str], default: bool = False) -> bool:
    """Helper to convert string representations of booleans to bool."""
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1", "yes", "on", "t")


class Settings:
    """Application settings class containing configuration parameters."""

    def __init__(self) -> None:
        # Base paths
        self.BASE_DIR: Path = BASE_DIR
        self.LOGS_DIR: Path = BASE_DIR / "logs"
        self.UPLOADS_DIR: Path = BASE_DIR / "uploads"
        self.EXPORTS_DIR: Path = BASE_DIR / "exports"

        # AI Configuration
        self.GEMINI_API_KEY: str = _get_env_or_secret("GEMINI_API_KEY") or _get_env_or_secret("GOOGLE_API_KEY")
        self.AI_ENABLED: bool = _str_to_bool(_get_env_or_secret("AI_ENABLED", "true"), default=True)
        self._ai_model: str = _get_env_or_secret("AI_MODEL", "gemini-3.1-flash-lite").strip()

        # Database Configuration
        self.DATABASE_URL: str = os.getenv(
            "DATABASE_URL", f"sqlite:///{BASE_DIR / 'talentmatch.db'}"
        ).strip()

        # File Upload Settings
        self.MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
        self.MAX_BATCH_SIZE: int = int(os.getenv("MAX_BATCH_SIZE", "500"))

        # Retention & Operational Settings
        self.RESUME_RETENTION_DAYS: int = int(os.getenv("RESUME_RETENTION_DAYS", "365"))
        self.DEBUG_MODE: bool = _str_to_bool(os.getenv("DEBUG_MODE"), default=False)

        # Server Settings
        self.APP_HOST: str = os.getenv("APP_HOST", "localhost").strip()
        self.APP_PORT: int = int(os.getenv("APP_PORT", "8501"))

        # SMTP Email Settings
        self.SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
        self.SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USER: str = os.getenv("SMTP_USER", "").strip()
        self.SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "").strip()
        self.SMTP_USE_TLS: bool = _str_to_bool(os.getenv("SMTP_USE_TLS"), default=True)

        # Configurable sender email addresses (comma-separated list in env: e.g. careers@company.com,hr@company.com)
        raw_senders = os.getenv("SENDER_EMAILS", "").strip()
        senders_list = [s.strip() for s in raw_senders.split(",") if s.strip()]
        if not senders_list and self.SMTP_USER:
            senders_list = [self.SMTP_USER]
        if not senders_list:
            senders_list = ["hr@talentmatch.ai", "careers@talentmatch.ai", "recruiting@talentmatch.ai"]
        self.SENDER_EMAILS: list[str] = senders_list

        # WhatsApp Outreach Settings
        self.WHATSAPP_ENABLED: bool = _str_to_bool(_get_env_or_secret("WHATSAPP_ENABLED", "true"), default=True)
        self.WHATSAPP_PROVIDER: str = _get_env_or_secret("WHATSAPP_PROVIDER", "web_direct").strip().lower()
        self.DEFAULT_COUNTRY_CODE: str = _get_env_or_secret("DEFAULT_COUNTRY_CODE", "+91").strip()
        self.TWILIO_ACCOUNT_SID: str = _get_env_or_secret("TWILIO_ACCOUNT_SID", "").strip()
        self.TWILIO_AUTH_TOKEN: str = _get_env_or_secret("TWILIO_AUTH_TOKEN", "").strip()
        self.TWILIO_WHATSAPP_NUMBER: str = _get_env_or_secret("TWILIO_WHATSAPP_NUMBER", "").strip()
        self.META_WHATSAPP_TOKEN: str = _get_env_or_secret("META_WHATSAPP_TOKEN", "").strip()
        self.META_PHONE_NUMBER_ID: str = _get_env_or_secret("META_PHONE_NUMBER_ID", "").strip()

        # Ensure essential directories exist
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def get_api_key(self) -> str:
        """Get the current Gemini API key from Streamlit secrets, environment, or database."""
        # 1. Check Streamlit Secrets & Environment dynamically
        key = _get_env_or_secret("GEMINI_API_KEY")
        if not key:
            key = _get_env_or_secret("GOOGLE_API_KEY")
        if key:
            return key

        # 2. Check cached instance setting if valid
        if hasattr(self, "GEMINI_API_KEY") and self.GEMINI_API_KEY:
            cleaned = clean_api_key(self.GEMINI_API_KEY)
            if cleaned:
                return cleaned

        # 3. Check database setting (ApplicationSetting table)
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select

            with get_session() as session:
                val = session.scalar(
                    select(ApplicationSetting.value).where(ApplicationSetting.key == "gemini_api_key")
                )
                if val:
                    cleaned = clean_api_key(val)
                    if cleaned:
                        return cleaned
        except Exception:
            pass

        # 4. If running locally with .env file, reload .env
        dotenv_file = self.BASE_DIR / ".env"
        if dotenv_file.exists():
            load_dotenv(dotenv_path=dotenv_file, override=True)
            env_key = clean_api_key(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
            if env_key:
                return env_key

        return ""

    @property
    def AI_MODEL(self) -> str:
        """Dynamically resolve active AI model from environment (.env) or database."""
        return self.get_model()

    @AI_MODEL.setter
    def AI_MODEL(self, value: str) -> None:
        self._ai_model = (value or "").strip()

    def get_model(self) -> str:
        """Get the current AI model from Streamlit secrets, environment, or database setting."""
        # 1. Check Streamlit Secrets & Environment
        model = _get_env_or_secret("AI_MODEL")
        if model:
            return model

        # 2. Check database setting
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select

            with get_session() as session:
                val = session.scalar(
                    select(ApplicationSetting.value).where(ApplicationSetting.key == "ai_model")
                )
                if val and val.strip():
                    return val.strip()
        except Exception:
            pass

        # 3. Reload local .env if present
        dotenv_file = self.BASE_DIR / ".env"
        if dotenv_file.exists():
            load_dotenv(dotenv_path=dotenv_file, override=True)
            env_model = os.getenv("AI_MODEL", "").strip().strip("'\"")
            if env_model:
                return env_model

        return getattr(self, "_ai_model", "") or "gemini-3.1-flash-lite"

    @property
    def is_ai_available(self) -> bool:
        """Check whether AI functionality is enabled and valid credentials exist.

        Returns:
            bool: True if AI is enabled and a valid Gemini API key is found.
        """
        api_key = self.get_api_key()
        if not api_key:
            return False
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select
            with get_session() as session:
                val = session.scalar(select(ApplicationSetting.value).where(ApplicationSetting.key == "ai_enabled"))
                if val is not None and str(val).lower() in ("false", "0", "no", "off"):
                    return False
        except Exception:
            if not self.AI_ENABLED:
                return False
        return True

    def __repr__(self) -> str:
        return (
            f"<Settings AI_ENABLED={self.AI_ENABLED} AI_MODEL={self.AI_MODEL!r} "
            f"DATABASE_URL={self.DATABASE_URL!r} DEBUG_MODE={self.DEBUG_MODE}>"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton getter for application settings.

    Returns:
        Settings: The cached Settings instance.
    """
    return Settings()
