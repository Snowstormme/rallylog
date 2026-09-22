"""Account tokens, email delivery and database-backed request limits."""

import hashlib
import hmac
import secrets
import time

import requests
from flask import abort, current_app, request
from sqlalchemy import delete, func, select

from . import db
from .models import AuthToken, RateLimitEvent


def limit_action(action, subject, maximum, seconds):
    """Count attempts in the shared database so restarts do not reset limits."""
    key = hmac.new(
        current_app.secret_key.encode(), f"{action}:{subject}".encode(), hashlib.sha256
    ).hexdigest()
    now = int(time.time())
    recent = db.session.scalar(
        select(func.count(RateLimitEvent.id)).where(
            RateLimitEvent.key_hash == key,
            RateLimitEvent.created_at > now - seconds,
        )
    )
    if recent >= maximum:
        abort(429)
    db.session.add(RateLimitEvent(key_hash=key, created_at=now))
    if secrets.randbelow(100) == 0:
        db.session.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < now - 86400))
    db.session.commit()


def client_ip():
    return request.remote_addr or "unknown"


def issue_token(user, purpose, lifetime_seconds):
    raw = secrets.token_urlsafe(32)
    db.session.execute(
        delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose)
    )
    db.session.add(AuthToken(
        digest=hashlib.sha256(raw.encode()).hexdigest(),
        user_id=user.id,
        purpose=purpose,
        expires_at=int(time.time()) + lifetime_seconds,
    ))
    db.session.commit()
    return raw


def valid_token(raw, purpose):
    if not raw or len(raw) > 128:
        return None
    token = db.session.get(AuthToken, hashlib.sha256(raw.encode()).hexdigest())
    if token and token.purpose == purpose and token.expires_at > int(time.time()):
        return token
    return None


def send_account_email(user, purpose):
    raw = issue_token(user, purpose, 86400 if purpose == "verify" else 1800)
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    if purpose == "verify":
        subject = "Verify your Rallylog email"
        body = f"Verify your Rallylog email address:\n\n{base}/verify-email/{raw}\n\nThis link expires in 24 hours."
    else:
        subject = "Reset your Rallylog password"
        body = f"Reset your Rallylog password:\n\n{base}/reset-password/{raw}\n\nThis link expires in 30 minutes. If you did not request it, ignore this email."

    delivery = current_app.config.get("MAIL_DELIVERY")
    if delivery:
        delivery(user.email, subject, body)
        return
    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {current_app.config['RESEND_API_KEY']}"},
        json={
            "from": current_app.config["MAIL_FROM"],
            "to": [user.email],
            "subject": subject,
            "text": body,
        },
        timeout=10,
    )
    response.raise_for_status()
