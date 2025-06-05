# push_helper.py
# Push notification + email helper functions

import smtplib
import os
import json
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

# ─── Placeholder Stub ─────────────────────────────────────────────────────────
def get_user_device_token(user_id: str) -> Optional[str]:
    """
    Placeholder: Return a user's device token for push notifications.
    You should replace this with actual DB lookup logic.
    """
    # TODO: implement retrieving device token (FCM token) for this user from your DB
    return None

def send_push_placeholder(user_id: str, title: str, message: str, data: dict = None) -> bool:
    """
    Placeholder method for sending push notifications to a user.
    Example: FCM for mobile / Web Push / etc.
    Right now it just prints to console.
    """
    try:
        print(f"📲 [Placeholder] Would send push to {user_id}: {title} – {message} | data: {data}")
        return True
    except Exception as e:
        print(f"❌ send_push_placeholder error: {e}")
        return False

# ── Firebase Admin (FCM) Implementation ─────────────────────────────
import firebase_admin
from firebase_admin import credentials, messaging

firebase_admin_json = os.getenv("FIREBASE_ADMIN_JSON")  # ← this should already be in your Render vars

if not firebase_admin_json:
    raise RuntimeError("❌ FIREBASE_ADMIN_JSON environment variable not set")

try:
    cred_dict = json.loads(firebase_admin_json)
    cred = credentials.Certificate(cred_dict)

    # Only initialize if not already done (prevent duplicate init error)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
except Exception as e:
    raise RuntimeError(f"🔥 Failed to initialize Firebase Admin SDK: {e}")

# ─── Email‐sending Helper ──────────────────────────────────────────────────────
def send_email_alert(to_email: str, subject: str, body: str, location: Optional[str] = None) -> bool:
    """
    Simple SMTP email alert. Replace with your own SMTP credentials or service.
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    from_email = os.getenv("FROM_EMAIL", smtp_user)

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, from_email]):
        print("⚠️ SMTP is not fully configured; skipping email.")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        content = body
        if location:
            content = f"Location: {location}\n\n{body}"
        msg.attach(MIMEText(content, "plain"))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        return True

    except Exception as e:
        print(f"❌ Failed to send email to {to_email}: {e}")
        return False
