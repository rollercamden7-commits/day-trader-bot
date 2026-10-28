"""
Sends email through Gmail - same setup as bot #1 (same Gmail app password and
same EMAIL_TO address), with "[Day Trader]" in the subject so you can tell
the bots apart.

    python -m day_trader.emailer     send yourself a test email
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage

from . import config  # noqa: F401  (loads day_trader/.env)


def send_email(subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if it was sent."""
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    to = os.environ.get("EMAIL_TO") or sender
    if not sender or not password:
        print("Email not configured here (GMAIL_ADDRESS / GMAIL_APP_PASSWORD missing). "
              "Would have sent:\n" + subject + "\n" + body)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[Day Trader] {subject}"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"Email sent to {to}: {subject}")
    return True


if __name__ == "__main__":
    ok = send_email("Test email", "If you can read this, bot #2's email works.")
    sys.exit(0 if ok else 1)
