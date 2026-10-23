"""Logging configuration for TalentMatch AI.

Provides structured logging with console and file output, log rotation,
and sensitive data scrubbing (API keys, emails, phone numbers).
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys
from typing import Optional

from config.settings import get_settings


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive information like API keys, emails, and phone numbers."""

    # Patterns for scrubbing
    EMAIL_PATTERN = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )
    PHONE_PATTERN = re.compile(
        r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b"
    )
    GEMINI_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z-_]{35}")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._scrub(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._scrub(a) if isinstance(a, str) else a for a in record.args
                )

        return True

    def _scrub(self, text: str) -> str:
        """Replace sensitive patterns with redaction placeholders."""
        settings = get_settings()
        if settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY) > 6:
            text = text.replace(settings.GEMINI_API_KEY, "[REDACTED_API_KEY]")

        text = self.GEMINI_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
        text = self.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
        # Avoid masking simple short numeric sequences like years or counts
        def mask_phone(match: re.Match) -> str:
            val = match.group(0)
            digits = [c for c in val if c.isdigit()]
            if len(digits) >= 10:
                return "[REDACTED_PHONE]"
            return val

        text = self.PHONE_PATTERN.sub(mask_phone, text)
        return text


def setup_logging(
    name: str = "talentmatch",
    log_file: Optional[Path] = None,
    debug: Optional[bool] = None,
) -> logging.Logger:
    """Configure structured logging with file and console handlers.

    Args:
        name: Name of the logger to configure.
        log_file: Optional path to the log file. Defaults to logs/talentmatch.log.
        debug: Explicit debug flag. Defaults to settings.DEBUG_MODE.

    Returns:
        logging.Logger: Configured logger instance.
    """
    settings = get_settings()
    is_debug = debug if debug is not None else settings.DEBUG_MODE
    level = logging.DEBUG if is_debug else logging.INFO

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if already configured
    if logger.handlers:
        return logger

    # Ensure log directory exists
    log_path = log_file or (settings.LOGS_DIR / "talentmatch.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scrubber = SensitiveDataFilter()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(scrubber)
    logger.addHandler(console_handler)

    # Rotating File Handler (10MB max per file, up to 5 backups)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(scrubber)
    logger.addHandler(file_handler)

    # Prevent propagation to the root logger if not desired
    logger.propagate = False

    logger.debug(
        "Structured logging initialized for %s (Debug: %s, File: %s)",
        name,
        is_debug,
        log_path,
    )
    return logger
