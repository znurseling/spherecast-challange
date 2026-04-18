import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
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

def fetch_emails(limit=5):
    """
    Fetches the latest emails from the INBOX.
    Returns a list of email summaries.
    """
    if not config.SMTP_PASS:
        return []

    emails = []
    try:
        # Connect to IMAP
        mail = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        mail.login(config.SMTP_USER, config.SMTP_PASS)
        mail.select("inbox")

        # Search for all emails
        status, messages = mail.search(None, "ALL")
        if status != "OK":
            return []

        # Get the IDs of the last N emails
        mail_ids = messages[0].split()
        latest_ids = mail_ids[-limit:][::-1] # Reverse to get newest first

        for m_id in latest_ids:
            status, data = mail.fetch(m_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Decode subject
            subject, encoding = decode_header(msg["Subject"])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8")

            # Decode from
            from_ = msg.get("From")

            emails.append({
                "id": m_id.decode(),
                "from": from_,
                "subject": subject,
                "date": msg.get("Date"),
                "body": _get_email_body(msg)
            })

        mail.logout()
        return emails
    except Exception as e:
        logger.error(f"Failed to fetch emails: {str(e)}")
        return []

def _get_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="ignore")
    else:
        return msg.get_payload(decode=True).decode(errors="ignore")
    return ""
