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

# Load .env file from base directory if present; fall back to .env.example
if (BASE_DIR / ".env").exists():
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
elif (BASE_DIR / ".env.example").exists():
    load_dotenv(dotenv_path=BASE_DIR / ".env.example", override=False)


def _get_env_or_secret(key: str, default: str = "") -> str:
    """Read configuration from Streamlit Cloud secrets or environment variables."""
    try:
        import streamlit as st

        if hasattr(st, "secrets") and key in st.secrets:
            val = st.secrets[key]
            if val is not None:
                return str(val).strip()
    except Exception:
        pass
    val = os.getenv(key)
    if val is not None:
        return str(val).strip()
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
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.AI_ENABLED: bool = _str_to_bool(os.getenv("AI_ENABLED"), default=True)
        self._ai_model: str = os.getenv("AI_MODEL", "gemini-3.1-flash-lite").strip()

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
        """Get the current Gemini API key from environment (.env/.env.example) or database setting."""
        # Check environment dynamically
        env_key = os.getenv("GEMINI_API_KEY", "").strip() or self.GEMINI_API_KEY
        if env_key and env_key.lower() not in ("your_api_key_here", "none", "placeholder"):
            return env_key

        # If not in env, reload .env or .env.example
        if (self.BASE_DIR / ".env").exists():
            load_dotenv(dotenv_path=self.BASE_DIR / ".env", override=True)
        elif (self.BASE_DIR / ".env.example").exists():
            load_dotenv(dotenv_path=self.BASE_DIR / ".env.example", override=True)

        env_key = os.getenv("GEMINI_API_KEY", "").strip()
        if env_key and env_key.lower() not in ("your_api_key_here", "none", "placeholder"):
            return env_key

        # Check database setting
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select
            with get_session() as session:
                val = session.scalar(select(ApplicationSetting.value).where(ApplicationSetting.key == "gemini_api_key"))
                if val and val.strip() and val.strip().lower() not in ("your_api_key_here", "none", "placeholder"):
                    return val.strip()
        except Exception:
            pass
        return ""

    @property
    def AI_MODEL(self) -> str:
        """Dynamically resolve active AI model from environment (.env) or database."""
        return self.get_model()

    @AI_MODEL.setter
    def AI_MODEL(self, value: str) -> None:
        self._ai_model = (value or "").strip()

    def get_model(self) -> str:
        """Get the current AI model from environment (.env/.env.example) or database setting.

        Environment variables in .env take priority over database settings so changes
        in .env are immediately respected.
        """
        # Dynamic reload of .env so hot edits take effect immediately
        if (self.BASE_DIR / ".env").exists():
            load_dotenv(dotenv_path=self.BASE_DIR / ".env", override=True)
        elif (self.BASE_DIR / ".env.example").exists():
            load_dotenv(dotenv_path=self.BASE_DIR / ".env.example", override=True)

        env_model = os.getenv("AI_MODEL", "").strip().strip("'\"")
        if env_model:
            return env_model

        # Fallback to database setting if not configured in environment
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select
            with get_session() as session:
                val = session.scalar(select(ApplicationSetting.value).where(ApplicationSetting.key == "ai_model"))
                if val and val.strip():
                    return val.strip()
        except Exception:
            pass
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
