"""WhatsApp direct redirect service for recruiter-candidate outreach in TalentMatch AI.

Implements direct 1-click WhatsApp web & mobile redirection (https://wa.me/)
with prefilled editable recruitment templates, E.164 phone normalization,
country code handling, and zero runtime dependencies on external messaging APIs.
"""

import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

from config.settings import get_settings

logger = logging.getLogger(__name__)


def _mask_phone_for_log(phone: Optional[str]) -> str:
    """Mask phone number preserving only the last 4 digits for privacy."""
    if not phone:
        return "None"
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) <= 4:
        return "****"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def _get_setting_value(key: str, default: str = "") -> str:
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


class WhatsAppService:
    """Service providing recruiter-candidate outreach via direct WhatsApp URL redirection."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_enabled(self) -> bool:
        """Check whether WhatsApp outreach is enabled in application settings."""
        self._reload_env_settings()
        return bool(self.settings.WHATSAPP_ENABLED)

    def _reload_env_settings(self) -> None:
        """Dynamically refresh configuration from Streamlit secrets, os.environ, or .env."""
        dotenv_path = self.settings.BASE_DIR / ".env"
        if dotenv_path.exists():
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=dotenv_path, override=False)

        from config.settings import _str_to_bool

        self.settings.WHATSAPP_ENABLED = _str_to_bool(
            _get_setting_value("WHATSAPP_ENABLED", str(self.settings.WHATSAPP_ENABLED)),
            default=True,
        )
        self.settings.WHATSAPP_PROVIDER = _get_setting_value(
            "WHATSAPP_PROVIDER", self.settings.WHATSAPP_PROVIDER
        ).strip().lower()
        self.settings.DEFAULT_COUNTRY_CODE = _get_setting_value(
            "DEFAULT_COUNTRY_CODE", self.settings.DEFAULT_COUNTRY_CODE
        ).strip()
        # Optional legacy credentials (only accessed if provider is explicitly twilio or meta)
        self.settings.TWILIO_ACCOUNT_SID = _get_setting_value(
            "TWILIO_ACCOUNT_SID", self.settings.TWILIO_ACCOUNT_SID
        ).strip()
        self.settings.TWILIO_AUTH_TOKEN = _get_setting_value(
            "TWILIO_AUTH_TOKEN", self.settings.TWILIO_AUTH_TOKEN
        ).strip()
        self.settings.TWILIO_WHATSAPP_NUMBER = _get_setting_value(
            "TWILIO_WHATSAPP_NUMBER", self.settings.TWILIO_WHATSAPP_NUMBER
        ).strip()
        self.settings.META_WHATSAPP_TOKEN = _get_setting_value(
            "META_WHATSAPP_TOKEN", self.settings.META_WHATSAPP_TOKEN
        ).strip()
        self.settings.META_PHONE_NUMBER_ID = _get_setting_value(
            "META_PHONE_NUMBER_ID", self.settings.META_PHONE_NUMBER_ID
        ).strip()

    def normalize_phone_number(
        self,
        raw_phone: Optional[str],
        default_country_code: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Normalize phone number to international digits-only format for WhatsApp wa.me links.

        Rules:
        - Strips all non-digit characters (+, spaces, hyphens, brackets, dots).
        - Strips leading zeros from local formats (e.g. '09876543210' -> '9876543210').
        - If input begins with '+', preserves the international country code.
        - If input is a 10-digit number without country code, adds DEFAULT_COUNTRY_CODE.
        - Prevents duplicate country codes (e.g. '919876543210' does not get '91' added again).
        - Validates that the normalized string contains between 10 and 15 digits (ITU-T E.164).

        Args:
            raw_phone: Raw phone string from resume or user input.
            default_country_code: Optional country code prefix (e.g. '+91', '91').

        Returns:
            Tuple[Optional[str], Optional[str]]: (digits_only, error_message).
            If valid, returns (digits_only, None). If invalid, returns (None, error_message).
        """
        if not raw_phone or not str(raw_phone).strip():
            return None, "Candidate phone number is missing."

        phone_str = str(raw_phone).strip()
        cc_prefix = (default_country_code or self.settings.DEFAULT_COUNTRY_CODE or "+91").strip()
        cc_digits = re.sub(r"\D", "", cc_prefix)

        has_plus = phone_str.startswith("+")

        # Extract only numeric digits
        digits = re.sub(r"\D", "", phone_str)
        if not digits:
            return None, "Phone number contains no numeric digits."

        # Strip leading trunk zero (common in domestic formats like 09876543210)
        if digits.startswith("0") and len(digits) > 10:
            digits = digits.lstrip("0")
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]

        # Case 1: Explicit '+' prefix indicates country code already supplied by user
        if has_plus:
            if 10 <= len(digits) <= 15:
                return digits, None
            return None, f"Invalid international phone number length ({len(digits)} digits). Expected 10-15 digits."

        # Case 2: Standard 10-digit local number -> prepend default country code
        if len(digits) == 10:
            if cc_digits:
                return f"{cc_digits}{digits}", None
            return digits, None

        # Case 3: Already contains default country code (e.g. 12 digits starting with '91')
        if cc_digits and digits.startswith(cc_digits) and len(digits) == (len(cc_digits) + 10):
            return digits, None

        # Case 4: General valid international number without '+' (11-15 digits)
        if 10 <= len(digits) <= 15:
            return digits, None

        return None, f"Invalid phone number: '{phone_str}'. Expected 10 to 15 digits with valid country code."

    def sanitize_phone_number(
        self,
        raw_phone: Optional[str],
        default_country_code: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Backward-compatible helper returning (e164_with_plus, digits_only)."""
        digits, err = self.normalize_phone_number(raw_phone, default_country_code)
        if not digits:
            return None, None
        return f"+{digits}", digits

    def generate_whatsapp_redirect(
        self,
        phone: Optional[str],
        message: str,
        default_country_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a direct WhatsApp https://wa.me/ redirect link with a prefilled message.

        This method generates a direct WhatsApp link that opens WhatsApp Web or the WhatsApp
        application with the message prefilled for HR review. It does not send messages
        automatically; HR must manually review and press Send.

        Args:
            phone: Candidate phone number (raw string with or without country code).
            message: Outreach message text.
            default_country_code: Optional fallback country code (defaults to settings.DEFAULT_COUNTRY_CODE).

        Returns:
            dict: {
                "success": bool,
                "url": Optional[str],
                "phone_digits": Optional[str],
                "masked_phone": Optional[str],
                "error": Optional[str],
            }
        """
        self._reload_env_settings()

        if not self.is_enabled():
            return {
                "success": False,
                "url": None,
                "phone_digits": None,
                "masked_phone": None,
                "error": "WhatsApp outreach is currently disabled in application settings (WHATSAPP_ENABLED=false).",
            }

        digits, error = self.normalize_phone_number(phone, default_country_code)
        if not digits:
            return {
                "success": False,
                "url": None,
                "phone_digits": None,
                "masked_phone": None,
                "error": error or "Invalid or missing phone number.",
            }

        clean_message = (message or "").strip()
        encoded_message = urllib.parse.quote(clean_message)
        wa_url = f"https://wa.me/{digits}?text={encoded_message}"

        logger.info(
            "Generated WhatsApp redirect link for recipient %s (message length: %d)",
            _mask_phone_for_log(digits),
            len(clean_message),
        )

        return {
            "success": True,
            "url": wa_url,
            "phone_digits": digits,
            "masked_phone": _mask_phone_for_log(digits),
            "error": None,
        }

    def generate_whatsapp_web_link(
        self,
        raw_phone: Optional[str],
        message: str,
        default_country_code: Optional[str] = None,
    ) -> Optional[str]:
        """Convenience method returning the https://wa.me/ URL or None if phone is invalid."""
        res = self.generate_whatsapp_redirect(raw_phone, message, default_country_code)
        return res.get("url")

    def get_templates(
        self,
        candidate_name: Optional[str] = None,
        job_title: Optional[str] = None,
        recruiter_name: Optional[str] = None,
        company_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, str]]:
        """Generate formatted recruitment outreach templates tailored for WhatsApp.

        Gracefully handles missing candidate names, missing job titles, and missing recruiter info.
        Automatically cleans parsed resume headers (e.g. '- Resume Page 1 of 2').
        Uses standard WhatsApp bold (*text*) styling.

        Args:
            candidate_name: Optional full name of candidate.
            job_title: Optional target Job Title.
            recruiter_name: Optional recruiter or sender sign-off name.
            company_name: Optional company or agency name.

        Returns:
            Dict[str, Dict[str, str]]: Template dictionary with name, description, and message.
        """
        raw_cand = (candidate_name or "").strip()
        # Clean common parsing artifacts like ' - Resume Page 1 of 2', ' - CV', 'Page 1', etc.
        clean_cand = re.sub(
            r"(?i)\s*[-–—|/]?\s*(?:resume|curriculum\s+vitae|cv)\b.*$",
            "",
            raw_cand,
        ).strip()
        clean_cand = re.sub(
            r"(?i)\s*[-–—|/]?\s*(?:page\s*\d+.*|\(.*?\bpage\b.*?\)).*$",
            "",
            clean_cand,
        ).strip()
        display_name = clean_cand if clean_cand else "Candidate"
        salutation_name = clean_cand.split()[0].title() if clean_cand else "Candidate"
        role_label = (job_title or "").strip() or "our open position"
        recruiter_label = (recruiter_name or "").strip() or "Talent Acquisition Team"
        company_label = (company_name or "").strip() or "our team"

        return {
            "interview_invitation": {
                "name": "🎯 Interview Invitation",
                "description": "Invite candidate for interview with proposed time slots.",
                "message": (
                    f"Dear *{salutation_name}*,\n\n"
                    f"Great news! Your profile has been shortlisted for the *{role_label}* position at *{company_label}*. "
                    f"Our technical hiring panel would love to invite you for an interview. 🚀\n\n"
                    f"Could you please share *2 or 3 convenient time slots* over the next 2-3 business days that work best for your schedule?\n\n"
                    f"Once confirmed, we will send over the calendar invite and meeting details.\n\n"
                    f"Best regards,\n*{recruiter_label}* | {company_label}"
                ),
            },
            "request_information": {
                "name": "📋 Request Candidate Details (CTC, Notice & Experience)",
                "description": "Comprehensive 11-point screening questionnaire for candidate evaluation.",
                "message": (
                    f"Dear *{salutation_name}*,\n\n"
                    f"Thank you for your interest in the *{role_label}* role at *{company_label}*! We reviewed your profile and were impressed with your background and experience. 🚀\n\n"
                    f"As we move forward with the next stage of our evaluation process, could you please provide us with the following details by replying directly here:\n\n"
                    f"1️⃣ *Name:* {display_name}\n"
                    f"2️⃣ *Current Company:*\n"
                    f"3️⃣ *Total Experience:*\n"
                    f"4️⃣ *Relevant Experience:*\n"
                    f"5️⃣ *Current Salary Package (CTC):*\n"
                    f"6️⃣ *Expected Salary Package (CTC):*\n"
                    f"7️⃣ *Notice Period / Earliest Joining Date:*\n"
                    f"8️⃣ *Current Location:*\n"
                    f"9️⃣ *Reason for Job Change:*\n"
                    f"🔟 *Any Offers in Hand?:*\n"
                    f"1️⃣1️⃣ *Highest Education & Year:*\n\n"
                    f"Please reply directly here on WhatsApp at your earliest convenience with the above information.\n\n"
                    f"We look forward to hearing from you!\n\n"
                    f"Best regards,\n*{recruiter_label}* | {company_label}"
                ),
            },
            "quick_inquiry": {
                "name": "⚡ Quick CTC & Notice Inquiry",
                "description": "Short 4-point inquiry about CTC, notice period, and experience.",
                "message": (
                    f"Hi *{salutation_name}*, hope you're having a great day! 👋\n\n"
                    f"This is *{recruiter_label}* reaching out from *{company_label}* regarding your application for the *{role_label}* role.\n\n"
                    f"To help us proceed with the evaluation process, could you please share a few quick details:\n\n"
                    f"1️⃣ *Total & Relevant Experience:*\n"
                    f"2️⃣ *Current CTC & Expected CTC:*\n"
                    f"3️⃣ *Notice Period / Earliest Joining Date:*\n"
                    f"4️⃣ *Current Location & Relocation Openness:*\n\n"
                    f"Looking forward to hearing from you! Please feel free to reply directly here.\n\n"
                    f"Best regards,\n*{recruiter_label}*"
                ),
            },
            "shortlist_notification": {
                "name": "⭐ Shortlisted Candidate Notification",
                "description": "Notify candidate that their resume screening was successful.",
                "message": (
                    f"Hi *{salutation_name}*,\n\n"
                    f"Congratulations! 🎉 We have reviewed your profile and you have been shortlisted for the *{role_label}* position.\n\n"
                    f"Our team is currently finalizing interview schedules and will be in touch with you shortly regarding the next steps.\n\n"
                    f"Feel free to reply if you have any questions in the meantime.\n\n"
                    f"Best regards,\n*{recruiter_label}* | {company_label}"
                ),
            },
            "application_status": {
                "name": "📑 Application Status Update",
                "description": "Update candidate on recent review stage completion and next discussion.",
                "message": (
                    f"Hi *{salutation_name}*,\n\n"
                    f"Hope you are doing well! Following up on your application for the *{role_label}* position.\n\n"
                    f"Our hiring team has completed the latest review stage and we would like to connect with you for a brief update.\n\n"
                    f"Please let us know your availability for a quick 5-minute call today or tomorrow.\n\n"
                    f"Best regards,\n*{recruiter_label}*"
                ),
            },
            "custom": {
                "name": "✍️ Custom Recruiter Message",
                "description": "Compose a custom outreach message.",
                "message": (
                    f"Hi *{salutation_name}*,\n\n"
                    f"Reaching out regarding your application for the *{role_label}* position at {company_label}...\n\n"
                    f"Best regards,\n*{recruiter_label}*"
                ),
            },
        }

    def send_message(
        self,
        to_phone: str,
        message: str,
        candidate_name: Optional[str] = None,
        job_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute outreach or generate redirect link based on configured provider.

        When provider is 'web_direct' (the default):
        Generates the direct https://wa.me/ redirect link without calling any external APIs.
        HR reviews the prefilled message and manually sends in WhatsApp.

        Args:
            to_phone: Candidate destination phone number.
            message: Message text content.
            candidate_name: Optional candidate name for logging.
            job_title: Optional job title for context.

        Returns:
            dict with 'success', 'mode', 'url', 'link', 'phone', 'message', and 'details'.
        """
        self._reload_env_settings()

        redirect = self.generate_whatsapp_redirect(to_phone, message)
        if not redirect["success"]:
            return {
                "success": False,
                "mode": self.settings.WHATSAPP_PROVIDER,
                "url": None,
                "link": None,
                "phone": to_phone,
                "error": redirect["error"],
                "message": redirect["error"],
            }

        provider = (self.settings.WHATSAPP_PROVIDER or "web_direct").lower()

        # Mode 1: Direct WhatsApp URL Redirect (Default & Recommended - Zero Dependencies)
        if provider == "web_direct":
            return {
                "success": True,
                "mode": "web_direct",
                "url": redirect["url"],
                "link": redirect["url"],
                "phone_digits": redirect["phone_digits"],
                "masked_phone": redirect["masked_phone"],
                "message": (
                    f"WhatsApp redirect link ready for candidate ({redirect['masked_phone']}). "
                    "Click 'Contact on WhatsApp' to open WhatsApp Web or mobile app and send manually."
                ),
            }

        # Mode 2: Simulation Mode
        elif provider == "simulation":
            logger.info("Simulated WhatsApp redirect for %s", redirect["masked_phone"])
            return {
                "success": True,
                "mode": "simulation",
                "url": redirect["url"],
                "link": redirect["url"],
                "phone_digits": redirect["phone_digits"],
                "masked_phone": redirect["masked_phone"],
                "message": f"[Simulation] WhatsApp outreach generated for {redirect['masked_phone']}.",
            }

        # Mode 3: Legacy Twilio WhatsApp API (Only if explicitly enabled)
        elif provider == "twilio":
            sid = self.settings.TWILIO_ACCOUNT_SID
            token = self.settings.TWILIO_AUTH_TOKEN
            from_num = self.settings.TWILIO_WHATSAPP_NUMBER or "whatsapp:+14155238886"

            if not sid or not token:
                logger.warning("Twilio credentials not set. Falling back to web_direct redirect.")
                return {
                    "success": True,
                    "mode": "web_direct",
                    "url": redirect["url"],
                    "link": redirect["url"],
                    "phone_digits": redirect["phone_digits"],
                    "masked_phone": redirect["masked_phone"],
                    "message": "Twilio credentials not set in environment. Generated 1-Click WhatsApp Direct link.",
                }

            try:
                e164_str = f"+{redirect['phone_digits']}"
                to_formatted = f"whatsapp:{e164_str}" if not e164_str.startswith("whatsapp:") else e164_str
                from_formatted = f"whatsapp:{from_num}" if not from_num.startswith("whatsapp:") else from_num

                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
                data = urllib.parse.urlencode({
                    "From": from_formatted,
                    "To": to_formatted,
                    "Body": message,
                }).encode("utf-8")

                req = urllib.request.Request(url, data=data, method="POST")
                auth_str = base64.b64encode(f"{sid}:{token}".encode("ascii")).decode("ascii")
                req.add_header("Authorization", f"Basic {auth_str}")

                with urllib.request.urlopen(req, timeout=12) as response:
                    resp_json = json.loads(response.read().decode("utf-8"))
                    logger.info("Twilio WhatsApp message sent. SID: %s", resp_json.get("sid"))
                    return {
                        "success": True,
                        "mode": "twilio",
                        "url": redirect["url"],
                        "link": redirect["url"],
                        "phone_digits": redirect["phone_digits"],
                        "masked_phone": redirect["masked_phone"],
                        "message": "WhatsApp message dispatched via Twilio API.",
                        "details": resp_json,
                    }
            except Exception as tw_err:
                logger.error("Twilio dispatch failed: %s", tw_err, exc_info=True)
                return {
                    "success": False,
                    "mode": "twilio",
                    "url": redirect["url"],
                    "link": redirect["url"],
                    "phone_digits": redirect["phone_digits"],
                    "masked_phone": redirect["masked_phone"],
                    "message": f"Twilio API Error: {tw_err}. Use direct WhatsApp link instead.",
                }

        # Mode 4: Legacy Meta Cloud API (Only if explicitly enabled)
        elif provider == "meta":
            meta_token = self.settings.META_WHATSAPP_TOKEN
            phone_id = self.settings.META_PHONE_NUMBER_ID

            if not meta_token or not phone_id:
                logger.warning("Meta Cloud API credentials not set. Falling back to web_direct redirect.")
                return {
                    "success": True,
                    "mode": "web_direct",
                    "url": redirect["url"],
                    "link": redirect["url"],
                    "phone_digits": redirect["phone_digits"],
                    "masked_phone": redirect["masked_phone"],
                    "message": "Meta credentials not set. Generated 1-Click WhatsApp Direct link.",
                }

            try:
                url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
                payload = json.dumps({
                    "messaging_product": "whatsapp",
                    "to": redirect["phone_digits"],
                    "type": "text",
                    "text": {"body": message},
                }).encode("utf-8")

                req = urllib.request.Request(url, data=payload, method="POST")
                req.add_header("Authorization", f"Bearer {meta_token}")
                req.add_header("Content-Type", "application/json")

                with urllib.request.urlopen(req, timeout=12) as response:
                    resp_json = json.loads(response.read().decode("utf-8"))
                    logger.info("Meta WhatsApp message sent.")
                    return {
                        "success": True,
                        "mode": "meta",
                        "url": redirect["url"],
                        "link": redirect["url"],
                        "phone_digits": redirect["phone_digits"],
                        "masked_phone": redirect["masked_phone"],
                        "message": "WhatsApp message dispatched via Meta API.",
                        "details": resp_json,
                    }
            except Exception as meta_err:
                logger.error("Meta WhatsApp dispatch failed: %s", meta_err, exc_info=True)
                return {
                    "success": False,
                    "mode": "meta",
                    "url": redirect["url"],
                    "link": redirect["url"],
                    "phone_digits": redirect["phone_digits"],
                    "masked_phone": redirect["masked_phone"],
                    "message": f"Meta WhatsApp API Error: {meta_err}. Use direct WhatsApp link instead.",
                }

        # Fallback default
        return {
            "success": True,
            "mode": "web_direct",
            "url": redirect["url"],
            "link": redirect["url"],
            "phone_digits": redirect["phone_digits"],
            "masked_phone": redirect["masked_phone"],
            "message": f"WhatsApp direct redirect ready for {redirect['masked_phone']}.",
        }
