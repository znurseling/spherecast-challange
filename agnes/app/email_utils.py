import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app import config
import logging

logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, body: str):
    """
    Sends an email using the SMTP settings configured in app/config.
    Returns True on success, False otherwise.
    """
    if not config.SMTP_PASS:
        logger.warning("SMTP_PASS is not set. Cannot send email.")
        return False, "Email password is not configured."

    try:
        # Create message
        msg = MIMEMultipart()
        msg["From"] = config.SMTP_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Connect and send
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()  # Secure connection
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_email}")
        return True, "Email sent successfully."
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False, f"Failed to send email: {str(e)}"
