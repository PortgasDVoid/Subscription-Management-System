"""Queue + (optionally) deliver email. Without SMTP_HOST the message stays 'queued' in email_logs (dev mode)."""
import os, smtplib
from email.message import EmailMessage
from sqlalchemy import text


def send_email(conn, to, template, subject, body, user_id=None, related_type=None, related_id=None):
    log_id = conn.execute(text("""INSERT INTO email_logs(user_id,to_email,template,subject,related_type,related_id)
        VALUES (:u,:t,:tpl,:s,:rt,:ri) RETURNING id"""),
        {"u": user_id, "t": to, "tpl": template, "s": subject, "rt": related_type, "ri": related_id}).scalar_one()
    host = os.getenv("SMTP_HOST")
    if not host:
        return {"id": log_id, "status": "queued"}
    try:
        msg = EmailMessage()
        msg["From"] = os.getenv("SMTP_FROM", "billing@brightloop.test"); msg["To"] = to; msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as s:
            if os.getenv("SMTP_USER"):
                s.starttls(); s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            s.send_message(msg)
        conn.execute(text("UPDATE email_logs SET status='sent',sent_at=now() WHERE id=:i"), {"i": log_id})
        return {"id": log_id, "status": "sent"}
    except Exception as exc:
        conn.execute(text("UPDATE email_logs SET status='failed',error=:e WHERE id=:i"), {"i": log_id, "e": str(exc)[:300]})
        return {"id": log_id, "status": "failed", "error": str(exc)[:300]}
