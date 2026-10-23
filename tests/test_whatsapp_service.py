"""Unit and integration test suite for WhatsApp web_direct redirection service.

Verifies:
- Phone normalization for Indian mobile numbers with/without +91, spaces, hyphens, brackets
- International phone numbers (US, UK, Singapore, etc.)
- Duplicate country code prevention (e.g. 919876543210 does not become 91919876543210)
- Missing, empty, or malformed phone numbers with descriptive errors
- URL encoding of spaces, newlines, special characters, and Unicode emojis
- Graceful fallbacks for missing candidate names, job titles, and recruiter info
- Behavior when WHATSAPP_ENABLED=false
- Zero network calls to Twilio or Meta APIs when WHATSAPP_PROVIDER=web_direct
"""

import urllib.parse
import urllib.request
import pytest

from services.whatsapp_service import WhatsAppService


@pytest.fixture
def wa_service() -> WhatsAppService:
    return WhatsAppService()


# -----------------------------------------------------------------------------
# 1. Indian Mobile Numbers
# -----------------------------------------------------------------------------
def test_indian_numbers_with_and_without_prefix(wa_service: WhatsAppService):
    """Verify Indian numbers with +91, without prefix, 12-digit format, and leading 0."""
    # 10-digit domestic without prefix
    digits, err = wa_service.normalize_phone_number("9876543210", default_country_code="+91")
    assert err is None
    assert digits == "919876543210"

    # With explicit +91
    digits_plus, err = wa_service.normalize_phone_number("+919876543210")
    assert err is None
    assert digits_plus == "919876543210"

    # 12 digits starting with 91 without plus
    digits_12, err = wa_service.normalize_phone_number("919876543210", default_country_code="+91")
    assert err is None
    assert digits_12 == "919876543210"

    # Domestic with leading zero (e.g. 09876543210)
    digits_zero, err = wa_service.normalize_phone_number("09876543210", default_country_code="+91")
    assert err is None
    assert digits_zero == "919876543210"


# -----------------------------------------------------------------------------
# 2. Spaces, Hyphens, Brackets, and Dots
# -----------------------------------------------------------------------------
def test_numbers_with_formatting_characters(wa_service: WhatsAppService):
    """Verify normalization strips spaces, dashes, parentheses, and dots."""
    # Indian formatted
    digits1, err1 = wa_service.normalize_phone_number("+91 (987) 654-3210")
    assert err1 is None
    assert digits1 == "919876543210"

    digits2, err2 = wa_service.normalize_phone_number("98765 43210", default_country_code="+91")
    assert err2 is None
    assert digits2 == "919876543210"

    digits3, err3 = wa_service.normalize_phone_number("09876-543-210", default_country_code="+91")
    assert err3 is None
    assert digits3 == "919876543210"

    # US formatted
    digits_us, err_us = wa_service.normalize_phone_number("+1 (415) 555-2671")
    assert err_us is None
    assert digits_us == "14155552671"


# -----------------------------------------------------------------------------
# 3. International Numbers
# -----------------------------------------------------------------------------
def test_international_numbers(wa_service: WhatsAppService):
    """Verify international numbers from diverse regions."""
    # United States (+1)
    d_us, _ = wa_service.normalize_phone_number("+14155552671")
    assert d_us == "14155552671"

    # United Kingdom (+44)
    d_uk, _ = wa_service.normalize_phone_number("+44 20 7946 0919")
    assert d_uk == "442079460919"

    # Singapore (+65)
    d_sg, _ = wa_service.normalize_phone_number("+65 6789 0123")
    assert d_sg == "6567890123"

    # Australia (+61)
    d_au, _ = wa_service.normalize_phone_number("+61 412 345 678")
    assert d_au == "61412345678"


# -----------------------------------------------------------------------------
# 4. Missing or Invalid Phone Numbers
# -----------------------------------------------------------------------------
def test_missing_or_invalid_phone_numbers(wa_service: WhatsAppService):
    """Verify missing, empty, or malformed numbers produce descriptive errors."""
    # None input
    d1, err1 = wa_service.normalize_phone_number(None)
    assert d1 is None
    assert "missing" in err1.lower()

    # Empty string
    d2, err2 = wa_service.normalize_phone_number("")
    assert d2 is None
    assert "missing" in err2.lower()

    # Whitespace only
    d3, err3 = wa_service.normalize_phone_number("   ")
    assert d3 is None
    assert "missing" in err3.lower()

    # Non-digit text
    d4, err4 = wa_service.normalize_phone_number("invalid-phone")
    assert d4 is None
    assert "no numeric digits" in err4.lower()

    # Too short
    d5, err5 = wa_service.normalize_phone_number("12345")
    assert d5 is None
    assert "invalid phone number" in err5.lower()

    # International too short
    d6, err6 = wa_service.normalize_phone_number("+9112345")
    assert d6 is None
    assert "invalid international phone number length" in err6.lower()

    # Too long (> 15 digits)
    d7, err7 = wa_service.normalize_phone_number("+12345678901234567")
    assert d7 is None
    assert "invalid international phone number length" in err7.lower()


# -----------------------------------------------------------------------------
# 5. Country Code Handling and Duplicate Prevention
# -----------------------------------------------------------------------------
def test_country_code_handling_and_duplicate_prevention(wa_service: WhatsAppService):
    """Verify duplicate country codes are prevented and final URLs contain clean digits."""
    # Already has 91 in 12-digit format
    d1, err1 = wa_service.normalize_phone_number("918056204859", default_country_code="+91")
    assert err1 is None
    assert d1 == "918056204859"
    assert not d1.startswith("9191")

    # Already has +91
    d2, err2 = wa_service.normalize_phone_number("+918056204859", default_country_code="+91")
    assert err2 is None
    assert d2 == "918056204859"

    # Domestic 10-digit number that starts with 91 (valid Indian mobile series)
    d3, err3 = wa_service.normalize_phone_number("9123456789", default_country_code="+91")
    assert err3 is None
    # Since 9123456789 is 10 digits, +91 is added properly
    assert d3 == "919123456789"

    # Custom country code without plus
    d4, err4 = wa_service.normalize_phone_number("4155552671", default_country_code="1")
    assert err4 is None
    assert d4 == "14155552671"

    # Redirect URL must not contain +, hyphens, or spaces in phone part
    res = wa_service.generate_whatsapp_redirect("+91 (987) 654-3210", "Hello candidate")
    assert res["success"] is True
    assert res["phone_digits"] == "919876543210"
    url = res["url"]
    phone_part = url.split("?text=")[0].replace("https://wa.me/", "")
    assert phone_part == "919876543210"
    assert not any(ch in phone_part for ch in "+- ()[]")


# -----------------------------------------------------------------------------
# 6. Special Characters, Spaces, and Unicode in Messages
# -----------------------------------------------------------------------------
def test_special_characters_and_unicode_in_message(wa_service: WhatsAppService):
    """Verify that message text with newlines, punctuation, and Unicode is URL-encoded safely."""
    special_msg = (
        "Hello Alice! 🎉\n\n"
        "We are excited to invite you for an interview at Diksha Tech. 🚀\n"
        "Key questions: Are you open to relocation? (Y/N) & what's your notice period?\n"
        "Salary: ₹12-15 LPA. *Lead QA Role*."
    )
    res = wa_service.generate_whatsapp_redirect("+919876543210", special_msg)
    assert res["success"] is True
    url = res["url"]

    # Must start with wa.me/digits
    assert url.startswith("https://wa.me/919876543210?text=")

    # Extract query text and decode
    encoded_text = url.split("?text=")[1]
    decoded_text = urllib.parse.unquote(encoded_text)

    # Decoded text must match original message perfectly
    assert decoded_text == special_msg
    assert "🎉" in decoded_text
    assert "🚀" in decoded_text
    assert "₹" in decoded_text
    assert "*Lead QA Role*" in decoded_text
    assert "\n\n" in decoded_text


# -----------------------------------------------------------------------------
# 7. Message Templates and Missing Detail Fallbacks
# -----------------------------------------------------------------------------
def test_templates_with_full_details(wa_service: WhatsAppService):
    """Verify 4 standard recruitment templates when all details are provided."""
    tpls = wa_service.get_templates(
        candidate_name="Kopila Pariyar",
        job_title="Lead QA Engineer",
        recruiter_name="Rupashree",
        company_name="TalentMatch AI",
    )

    # Standard scenario keys
    assert "interview_invitation" in tpls
    assert "request_information" in tpls
    assert "quick_inquiry" in tpls
    assert "shortlist_notification" in tpls
    assert "application_status" in tpls
    assert "custom" in tpls

    invite_msg = tpls["interview_invitation"]["message"]
    assert "*Kopila*" in invite_msg
    assert "*Lead QA Engineer*" in invite_msg
    assert "TalentMatch AI" in invite_msg
    assert "time slots" in invite_msg

    info_msg = tpls["request_information"]["message"]
    assert "*Total Experience:*" in info_msg
    assert "*Relevant Experience:*" in info_msg
    assert "*Current Salary Package (CTC):*" in info_msg
    assert "*Expected Salary Package (CTC):*" in info_msg
    assert "*Notice Period / Earliest Joining Date:*" in info_msg
    assert "*Reason for Job Change:*" in info_msg
    assert "*Any Offers in Hand?:*" in info_msg
    assert "*Highest Education & Year:*" in info_msg

    quick_msg = tpls["quick_inquiry"]["message"]
    assert "*Total & Relevant Experience:*" in quick_msg
    assert "*Current CTC & Expected CTC:*" in quick_msg

    shortlist_msg = tpls["shortlist_notification"]["message"]
    assert "shortlisted" in shortlist_msg.lower()

    status_msg = tpls["application_status"]["message"]
    assert "review stage" in status_msg.lower()


def test_template_candidate_name_sanitization(wa_service: WhatsAppService):
    """Verify raw parsed candidate strings like 'Suresh Sencha - Resume Page 1 of 2' are sanitized."""
    tpls = wa_service.get_templates(
        candidate_name="Suresh Sencha - Resume Page 1 of 2",
        job_title="Fullstack Developer",
        recruiter_name="Talent Acquisition Team",
        company_name="TalentMatch AI",
    )
    msg = tpls["request_information"]["message"]
    assert "Dear *Suresh*" in msg
    assert "*Name:* Suresh Sencha\n" in msg
    assert "Resume Page" not in msg
    assert "*Fullstack Developer*" in msg


def test_templates_with_missing_details_graceful_fallbacks(wa_service: WhatsAppService):
    """Verify templates gracefully handle None / empty strings for candidate, role, recruiter."""
    tpls = wa_service.get_templates(
        candidate_name=None,
        job_title=None,
        recruiter_name=None,
        company_name=None,
    )

    invite_msg = tpls["interview_invitation"]["message"]
    # Fallback salutation
    assert "*Candidate*" in invite_msg
    # Fallback role label
    assert "*our open position*" in invite_msg
    # Fallback company label
    assert "our team" in invite_msg
    # Fallback recruiter label
    assert "*Talent Acquisition Team*" in invite_msg

    # Ensure literal 'None' string never leaked into template output
    for key, tpl in tpls.items():
        assert "None" not in tpl["message"]
        assert "undefined" not in tpl["message"]


# -----------------------------------------------------------------------------
# 8. WHATSAPP_ENABLED=false Behavior
# -----------------------------------------------------------------------------
def test_whatsapp_enabled_false(monkeypatch, wa_service: WhatsAppService):
    """Verify actions and link generation are disabled when WHATSAPP_ENABLED=false."""
    monkeypatch.setenv("WHATSAPP_ENABLED", "false")
    wa_service.settings.WHATSAPP_ENABLED = False

    assert wa_service.is_enabled() is False

    redirect = wa_service.generate_whatsapp_redirect("+919876543210", "Hello")
    assert redirect["success"] is False
    assert redirect["url"] is None
    assert "disabled" in redirect["error"].lower()

    link = wa_service.generate_whatsapp_web_link("+919876543210", "Hello")
    assert link is None

    send_res = wa_service.send_message("+919876543210", "Hello")
    assert send_res["success"] is False
    assert "disabled" in send_res["error"].lower()


# -----------------------------------------------------------------------------
# 9. Zero Network Calls in web_direct Mode
# -----------------------------------------------------------------------------
def test_no_twilio_or_meta_api_calls_in_web_direct(monkeypatch, wa_service: WhatsAppService):
    """Verify web_direct provider never invokes network HTTP calls (urllib.request.urlopen)."""
    monkeypatch.setenv("WHATSAPP_PROVIDER", "web_direct")
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    wa_service.settings.WHATSAPP_PROVIDER = "web_direct"
    wa_service.settings.WHATSAPP_ENABLED = True

    # Spy / guard on urlopen to ensure it is never reached
    urlopen_called = False

    def mock_urlopen(*args, **kwargs):
        nonlocal urlopen_called
        urlopen_called = True
        raise AssertionError("Network HTTP call made during web_direct WhatsApp redirect!")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = wa_service.send_message(
        to_phone="9876543210",
        message="Interview invitation for engineering position.",
        candidate_name="Jane Doe",
        job_title="Software Engineer",
    )

    assert urlopen_called is False
    assert res["success"] is True
    assert res["mode"] == "web_direct"
    assert "https://wa.me/919876543210?text=" in res["url"]


# -----------------------------------------------------------------------------
# 10. Backward Compatible Helpers
# -----------------------------------------------------------------------------
def test_backward_compatible_sanitize_phone(wa_service: WhatsAppService):
    """Verify legacy sanitize_phone_number returns (e164_with_plus, digits_only)."""
    e164, digits = wa_service.sanitize_phone_number("8056204859", default_country_code="+91")
    assert e164 == "+918056204859"
    assert digits == "918056204859"

    inv1, inv_d1 = wa_service.sanitize_phone_number("12345")
    assert inv1 is None
    assert inv_d1 is None
