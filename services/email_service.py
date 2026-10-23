"""Email communication service for candidate follow-up and recruiter outreach.

Handles candidate inquiries, salary expectations, notice periods, and customizable
recruiter email templates with multiple selectable sender mailboxes.
"""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import smtplib
import socket
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
        # Dynamically reload .env to ensure fresh credentials if modified without restarting server
        dotenv_path = self.settings.BASE_DIR / ".env"
        if dotenv_path.exists():
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=dotenv_path, override=True)
            from config.settings import _str_to_bool
            self.settings.SMTP_USER = os.getenv("SMTP_USER", self.settings.SMTP_USER).strip()
            self.settings.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", self.settings.SMTP_PASSWORD).strip()
            self.settings.SMTP_HOST = os.getenv("SMTP_HOST", self.settings.SMTP_HOST).strip()
            try:
                self.settings.SMTP_PORT = int(os.getenv("SMTP_PORT", str(self.settings.SMTP_PORT)))
            except ValueError:
                pass
            self.settings.SMTP_USE_TLS = _str_to_bool(os.getenv("SMTP_USE_TLS"), default=self.settings.SMTP_USE_TLS)

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
                server.ehlo()
            else:
                server = smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=15)
                server.ehlo()
                if self.settings.SMTP_USE_TLS:
                    server.starttls()
                    server.ehlo()

            server.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
            server.sendmail(sender, [to_email], msg.as_string())
            try:
                server.quit()
            except Exception:
                pass

            logger.info("Email sent successfully to %s from %s", to_email, sender)
            return {
                "success": True,
                "simulated": False,
                "message": f"Email delivered successfully to {to_email} from {sender}!",
            }
        except smtplib.SMTPAuthenticationError as auth_err:
            logger.error("SMTP Authentication failed for %s: %s", self.settings.SMTP_USER, auth_err)
            return {
                "success": False,
                "simulated": False,
                "message": (
                    f"SMTP Authentication Error (535 Bad Credentials): Username and password rejected by {self.settings.SMTP_HOST}. "
                    "For Gmail / Google Workspace, regular account passwords do not work. You must enable 2-Step Verification "
                    "and generate a 16-character App Password at https://myaccount.google.com/apppasswords."
                ),
            }
        except smtplib.SMTPServerDisconnected as disc_err:
            logger.error("SMTP Server disconnected: %s", disc_err)
            return {
                "success": False,
                "simulated": False,
                "message": (
                    f"SMTP Error: Connection unexpectedly closed by {self.settings.SMTP_HOST}. "
                    "When using Gmail / Google Workspace, Google automatically closes the connection upon receiving invalid "
                    "credentials (535 Bad Credentials). Please verify that your SMTP_USER is correct and generate a new "
                    "16-character Google App Password at https://myaccount.google.com/apppasswords."
                ),
            }
        except (smtplib.SMTPConnectError, TimeoutError, socket.timeout, ConnectionRefusedError) as conn_err:
            logger.error("SMTP Connection failed: %s", conn_err)
            return {
                "success": False,
                "simulated": False,
                "message": (
                    f"SMTP Connection Error: Could not connect to {self.settings.SMTP_HOST}:{self.settings.SMTP_PORT}. "
                    "Please verify your network connection, firewall settings, and port configuration."
                ),
            }
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", to_email, exc, exc_info=True)
            return {
                "success": False,
                "simulated": False,
                "message": f"SMTP Error sending email: {exc}",
            }

