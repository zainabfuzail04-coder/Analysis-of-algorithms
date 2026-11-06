"""Confirmation emails. SMTP env vars set karo to real email jati hai,
warna email console (terminal) mein print hoti hai taake development mein kaam chale.

  MAIL_SERVER, MAIL_PORT (587), MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, MAIL_USE_SSL=1 (port 465 ke liye)
"""
import os
import smtplib
import threading
from email.message import EmailMessage


def send_email(to, subject, body):
    """Returns True agar real SMTP se bheji gayi, warna False (console mein print)."""
    if not to:
        return False
    host = os.environ.get("MAIL_SERVER")
    if not host:
        print(f"\n[EMAIL - SMTP not configured, console only]\nTo: {to}\nSubject: {subject}\n\n{body}\n")
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME", "hotel@localhost")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)

    def _send():
        try:
            ssl = os.environ.get("MAIL_USE_SSL") == "1"
            port = int(os.environ.get("MAIL_PORT", 465 if ssl else 587))
            cls = smtplib.SMTP_SSL if ssl else smtplib.SMTP
            with cls(host, port, timeout=15) as s:
                if not ssl:
                    s.starttls()
                if os.environ.get("MAIL_USERNAME"):
                    s.login(os.environ["MAIL_USERNAME"], os.environ.get("MAIL_PASSWORD", ""))
                s.send_message(msg)
        except Exception as e:           # email fail hone se booking/payment kabhi na rukay
            print(f"[EMAIL FAILED] {e}")

    threading.Thread(target=_send, daemon=True).start()
    return True
