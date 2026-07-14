from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time

from app.config import SESSION_MAX_AGE
from app.db import execute, query_one
from app.utils import esc


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_password: str | None) -> bool:
    if not stored_password:
        return False
    if "$" not in stored_password:
        return secrets.compare_digest(password, stored_password)
    salt, digest = stored_password.split("$", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return secrets.compare_digest(candidate.hex(), digest)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    user = query_one("SELECT csrf_token FROM users WHERE id = ?", (user_id,))
    csrf_token = user["csrf_token"] if user and user["csrf_token"] else secrets.token_urlsafe(32)
    if not user or not user["csrf_token"]:
        execute("UPDATE users SET csrf_token = ? WHERE id = ?", (csrf_token, user_id))
    execute(
        """
        INSERT INTO sessions (token, user_id, csrf_token, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (token, user_id, csrf_token, now, now + SESSION_MAX_AGE),
    )
    return token


def get_session(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    session = query_one("SELECT * FROM sessions WHERE token = ?", (token,))
    if not session or int(session["expires_at"] or 0) < int(time.time()):
        if session:
            delete_session(token)
        return None
    return session


def delete_session(token: str | None) -> None:
    if token:
        execute("DELETE FROM sessions WHERE token = ?", (token,))


def csrf_input(user: sqlite3.Row | None) -> str:
    if not user:
        return ""
    return f'<input type="hidden" name="csrf_token" value="{esc(user["csrf_token"] or "")}">'


def valid_csrf(user: sqlite3.Row | None, form: dict[str, str]) -> bool:
    if not user:
        return False
    return secrets.compare_digest(form.get("csrf_token", ""), user["csrf_token"] or "")
