"""Email communication service for candidate follow-up and recruiter outreach.

Handles candidate inquiries, salary expectations, notice periods, and customizable
recruiter email templates with multiple selectable sender mailboxes.
"""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Any, Dict, List, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service providing SMTP candidate outreach and template generation."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def get_sender_addresses(self) -> List[str]:
        """Return the list of configured sender email addresses."""
        return self.settings.SENDER_EMAILS

    def generate_candidate_inquiry_template(
        self,
        candidate_name: str,
        job_title: str,
        recruiter_name: str = "Talent Acquisition Team",
    ) -> Dict[str, str]:
        """Generate structured email template requesting candidate details and compensation expectations."""
        subject = f"Next Steps - Application for {job_title}"
        body = f"""Dear {candidate_name},

Thank you for your interest in the {job_title} role! We reviewed your profile and were impressed with your background and experience.

As we move forward with the next stage of our evaluation process, could you please provide us with the following details:

1. Name: {candidate_name}
2. Current Company: 
3. Total Experience: 
4. Relevant Experience: 
5. Current salary package: 
6. Expected salary package: 
7. Notice period: 
8. Current Location: 
9. Reason for job change: 
10. Any offers in hand?: 
11. Highest education & year: 

Please reply directly to this email at your earliest convenience with the above information.

We look forward to hearing from you!

Best regards,
{recruiter_name}
"""
        return {"subject": subject, "body": body}

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email using configured SMTP settings.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body: Plaintext body content.
            from_email: Sender address selected from available senders.

        Returns:
            dict: Status result with 'success', 'message', and 'details'.
        """
        sender = from_email or (self.settings.SENDER_EMAILS[0] if self.settings.SENDER_EMAILS else "hr@talentmatch.ai")

        if not to_email or "@" not in to_email:
            return {"success": False, "message": f"Invalid recipient email address: '{to_email}'"}

        # If SMTP credentials are not configured, simulate delivery for dev/testing
        if not self.settings.SMTP_USER or not self.settings.SMTP_PASSWORD:
            logger.info(
                "SMTP credentials not fully set in .env. Simulated sending email from %s to %s with subject: %s",
                sender,
                to_email,
                subject,
            )
            return {
                "success": True,
                "simulated": True,
                "message": (
                    f"Email queued and simulated successfully to {to_email} (From: {sender}). "
                    "To enable live delivery, configure SMTP_USER & SMTP_PASSWORD in your .env file."
                ),
            }

        try:
            msg = MIMEMultipart()
            msg["From"] = sender
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if self.settings.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=15)
            else:
                server = smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=15)
                if self.settings.SMTP_USE_TLS:
                    server.starttls()

            server.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
            server.sendmail(sender, [to_email], msg.as_string())
            server.quit()

            logger.info("Email sent successfully to %s from %s", to_email, sender)
            return {
                "success": True,
                "simulated": False,
                "message": f"Email delivered successfully to {to_email} from {sender}!",
            }
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to_email, exc, exc_info=True)
            return {
                "success": False,
                "simulated": False,
                "message": f"SMTP Error sending email: {exc}",
            }

