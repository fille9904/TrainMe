from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import sqlite3
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TRAINME_DB_PATH", BASE_DIR / "trainme.db"))
STATIC_DIR = BASE_DIR / "app" / "static"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_REDIRECT_URI = os.environ.get("STRAVA_REDIRECT_URI", "http://127.0.0.1:8000/strava/callback")
SESSION_MAX_AGE = 60 * 60 * 24 * 30


TRACKS: dict[str, dict[str, Any]] = {
    "atlet": {
        "name": "Athlete",
        "tagline": "For users who want to improve performance and make smarter decisions from training data.",
        "focus": [
            "Performance analysis using Strava data",
            "AI tips for load, recovery, and progression",
            "Suggestions for training formats that build capacity",
        ],
        "accent": "performance",
        "subcategories": {
            "strength": "Explosiveness, max strength, and supporting sessions for athletic performance.",
            "mixed": "Periodized weeks with technique, mobility, recovery, and quality sessions.",
            "cardio": "Intervals, distance, zones, and Strava-based fitness tracking.",
        },
    },
    "aktiv": {
        "name": "Active",
        "tagline": "For users who train regularly and want to stay healthy, strong, and energized.",
        "focus": [
            "General training tips for a sustainable routine",
            "Nutrition advice for energy, stamina, and recovery",
            "Balance between strength, cardio, and rest",
        ],
        "accent": "active",
        "subcategories": {
            "strength": "Safe basic exercises, smart progression, and routines that last.",
            "mixed": "Weekly plans with strength, mobility, walks, cycling, or group training.",
            "cardio": "Cardio sessions for heart health, energy, and better everyday recovery.",
        },
    },
    "komma-igang": {
        "name": "Getting started",
        "tagline": "For users who want to start gently, build habits, and get extra nutrition support.",
        "focus": [
            "General movement that is easy to start with",
            "Strong focus on simple nutrition habits",
            "Small steps that build confidence",
        ],
        "accent": "start",
        "subcategories": {
            "strength": "Bodyweight training, simple home sessions, and gentle strength work to get started.",
            "mixed": "Walks, mobility, and short sessions that fit a new routine.",
            "cardio": "Easy cardio sessions with a clear starting level and focus on consistency.",
        },
    },
}


SUBCATEGORY_NAMES = {
    "strength": "Strength",
    "mixed": "Mixed",
    "cardio": "Cardio",
}

SUBCATEGORY_ALIASES = {
    "styrka": "strength",
    "blandat": "mixed",
    "kondition": "cardio",
}


def ensure_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username VARCHAR UNIQUE,
                email VARCHAR UNIQUE,
                password VARCHAR,
                category VARCHAR,
                height FLOAT,
                weight FLOAT,
                goal VARCHAR
            )
            """
        )
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "csrf_token" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN csrf_token VARCHAR")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS strava_connections (
                user_id INTEGER PRIMARY KEY,
                athlete_id INTEGER,
                athlete_name VARCHAR,
                scope VARCHAR,
                access_token VARCHAR,
                refresh_token VARCHAR,
                expires_at INTEGER,
                updated_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS training_plan_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                day_index INTEGER,
                day_name VARCHAR,
                session TEXT,
                is_done INTEGER DEFAULT 0,
                comment TEXT,
                updated_at INTEGER,
                UNIQUE(user_id, day_index),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS subcategory_plan_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                track_id VARCHAR,
                subcategory_id VARCHAR,
                day_index INTEGER,
                day_name VARCHAR,
                session TEXT,
                is_done INTEGER DEFAULT 0,
                comment TEXT,
                updated_at INTEGER,
                UNIQUE(user_id, track_id, subcategory_id, day_index),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS training_archive (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                source VARCHAR,
                track_id VARCHAR,
                subcategory_id VARCHAR,
                day_name VARCHAR,
                session TEXT,
                comment TEXT,
                completed_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_recipes (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                track_id VARCHAR,
                title VARCHAR,
                reason TEXT,
                url TEXT,
                saved_at INTEGER,
                UNIQUE(user_id, url),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS weight_entries (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                weight FLOAT,
                recorded_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token VARCHAR PRIMARY KEY,
                user_id INTEGER,
                csrf_token VARCHAR,
                strava_state VARCHAR,
                created_at INTEGER,
                expires_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        for row in db.execute("SELECT id FROM users WHERE csrf_token IS NULL OR csrf_token = ''").fetchall():
            db.execute("UPDATE users SET csrf_token = ? WHERE id = ?", (secrets.token_urlsafe(32), row[0]))


def query_one(sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def execute(sql: str, params: tuple[Any, ...]) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(sql, params)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        user = db.execute("SELECT csrf_token FROM users WHERE id = ?", (user_id,)).fetchone()
        csrf_token = user[0] if user and user[0] else secrets.token_urlsafe(32)
        if not user or not user[0]:
            db.execute("UPDATE users SET csrf_token = ? WHERE id = ?", (csrf_token, user_id))
        db.execute(
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
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        session = db.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
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


def strava_client_id() -> str:
    return os.environ.get("STRAVA_CLIENT_ID", "").strip()


def strava_client_secret() -> str:
    return os.environ.get("STRAVA_CLIENT_SECRET", "").strip()


def strava_is_configured() -> bool:
    return bool(strava_client_id() and strava_client_secret())


def strava_config_error() -> str | None:
    client_id = strava_client_id()
    if not client_id or not strava_client_secret():
        return "Strava API keys are missing. Add STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET."
    if not client_id.isdigit():
        return "STRAVA_CLIENT_ID must be the numbers from the Strava Client ID field, not the Client Secret or app name."
    return None


def get_strava_connection(user_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM strava_connections WHERE user_id = ?", (user_id,))


def strava_authorize_url(user_id: int, state: str) -> str:
    params = {
        "client_id": strava_client_id(),
        "redirect_uri": STRAVA_REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read",
        "state": state,
    }
    return f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"


def post_form_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = urlencode(payload).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, access_token: str) -> Any:
    request = Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {access_token}")
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def save_strava_tokens(user_id: int, token_data: dict[str, Any], scope: str) -> None:
    athlete = token_data.get("athlete") or {}
    athlete_name = " ".join(
        part for part in [athlete.get("firstname"), athlete.get("lastname")] if part
    ) or athlete.get("username") or "Strava athlete"
    execute(
        """
        INSERT INTO strava_connections (
            user_id, athlete_id, athlete_name, scope, access_token, refresh_token, expires_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            athlete_id = excluded.athlete_id,
            athlete_name = excluded.athlete_name,
            scope = excluded.scope,
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            expires_at = excluded.expires_at,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            athlete.get("id"),
            athlete_name,
            scope,
            token_data.get("access_token"),
            token_data.get("refresh_token"),
            token_data.get("expires_at"),
            int(time.time()),
        ),
    )


def exchange_strava_code(user_id: int, code: str, scope: str) -> None:
    token_data = post_form_json(
        STRAVA_TOKEN_URL,
        {
            "client_id": strava_client_id(),
            "client_secret": strava_client_secret(),
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    save_strava_tokens(user_id, token_data, scope)


def refresh_strava_connection(connection: sqlite3.Row) -> sqlite3.Row:
    if int(connection["expires_at"] or 0) > int(time.time()) + 300:
        return connection

    token_data = post_form_json(
        STRAVA_TOKEN_URL,
        {
            "client_id": strava_client_id(),
            "client_secret": strava_client_secret(),
            "grant_type": "refresh_token",
            "refresh_token": connection["refresh_token"],
        },
    )
    execute(
        """
        UPDATE strava_connections
        SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (
            token_data.get("access_token"),
            token_data.get("refresh_token"),
            token_data.get("expires_at"),
            int(time.time()),
            connection["user_id"],
        ),
    )
    refreshed = get_strava_connection(connection["user_id"])
    if not refreshed:
        raise RuntimeError("The Strava connection could not be refreshed.")
    return refreshed


def fetch_strava_summary(user_id: int) -> tuple[str | None, str | None]:
    connection = get_strava_connection(user_id)
    if not connection:
        return None, None

    try:
        connection = refresh_strava_connection(connection)
        activities = get_json(f"{STRAVA_API_BASE}/athlete/activities?per_page=10", connection["access_token"])
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return None, f"Could not fetch Strava data right now: {exc}"

    if not activities:
        return "Strava is connected, but no activities were found yet.", None

    total_distance_km = sum(float(activity.get("distance") or 0) for activity in activities) / 1000
    total_seconds = sum(float(activity.get("moving_time") or 0) for activity in activities)
    sport_counts: dict[str, int] = {}
    latest_lines = []

    for activity in activities[:5]:
        sport = activity.get("sport_type") or activity.get("type") or "Activeitet"
        sport_counts[sport] = sport_counts.get(sport, 0) + 1
        distance_km = float(activity.get("distance") or 0) / 1000
        minutes = int(float(activity.get("moving_time") or 0) / 60)
        latest_lines.append(f"{sport}: {distance_km:.1f} km, {minutes} min")

    sports = ", ".join(f"{name} x{count}" for name, count in sorted(sport_counts.items()))
    hours = total_seconds / 3600
    summary = (
        f"Strava is connected to {connection['athlete_name']}. "
        f"Latest {len(activities)} sessions: {total_distance_km:.1f} km and {hours:.1f} total hours. "
        f"Training types: {sports}. Latest sessions: {' | '.join(latest_lines)}."
    )
    return summary, None


def fetch_strava_summary_html(user_id: int) -> tuple[str | None, str | None, str | None]:
    connection = get_strava_connection(user_id)
    if not connection:
        return None, None, None

    try:
        connection = refresh_strava_connection(connection)
        activities = get_json(f"{STRAVA_API_BASE}/athlete/activities?per_page=10", connection["access_token"])
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return None, None, f"Could not fetch Strava data right now: {exc}"

    if not activities:
        empty = "Strava is connected, but no activities were found yet."
        return empty, f"<p>{esc(empty)}</p>", None

    total_distance_km = sum(float(activity.get("distance") or 0) for activity in activities) / 1000
    total_seconds = sum(float(activity.get("moving_time") or 0) for activity in activities)
    total_hours = total_seconds / 3600
    rows = []
    summary_lines = []

    for index, activity in enumerate(activities[:10], start=1):
        name = activity.get("name") or "Session"
        sport = activity.get("sport_type") or activity.get("type") or "Activeitet"
        distance_km = float(activity.get("distance") or 0) / 1000
        minutes = int(float(activity.get("moving_time") or 0) / 60)
        date = str(activity.get("start_date_local") or activity.get("start_date") or "")[:10]
        elevation = float(activity.get("total_elevation_gain") or 0)
        average_speed = float(activity.get("average_speed") or 0) * 3.6
        rows.append(
            f"""
            <li>
                <strong>{esc(index)}. {esc(name)}</strong>
                <span>{esc(date)} Â· {esc(sport)} Â· {distance_km:.1f} km Â· {minutes} min Â· {elevation:.0f} m stigning Â· {average_speed:.1f} km/h snitt</span>
            </li>
            """
        )
        summary_lines.append(f"{sport}: {distance_km:.1f} km, {minutes} min")

    summary = (
        f"Strava is connected to {connection['athlete_name']}. "
        f"Latest {len(activities[:10])} sessions: {total_distance_km:.1f} km and {total_hours:.1f} total hours. "
        f"Session: {' | '.join(summary_lines)}."
    )
    html_block = f"""
    <div class="strava-summary">
        <div class="strava-total-grid">
            <div><span>{len(activities[:10])}</span><p>latest sessions</p></div>
            <div><span>{total_distance_km:.1f}</span><p>totalt km</p></div>
            <div><span>{total_hours:.1f}</span><p>totalt timmar</p></div>
        </div>
        <ul class="strava-activity-list">{''.join(rows)}</ul>
    </div>
    """
    return summary, html_block, None


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


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def check_items(items: list[str]) -> str:
    return "".join(f"<li>{esc(item)}</li>" for item in items)


def header(user: sqlite3.Row | None) -> str:
    auth = (
        """
        <a class="ghost-button" href="/ai-coach">AI coach</a>
        <a class="ghost-button" href="/strava">Strava</a>
        <a class="ghost-button" href="/profile">Profile</a>
        <form method="post" action="/logga-ut">{csrf_input(user)}<button class="icon-button" type="submit" aria-label="Log out" title="Log out">â†—</button></form>
        """
        if user
        else """
        <a class="ghost-button" href="/logga-in">Log in</a>
        <a class="primary-button compact" href="/registrera">Create account</a>
        """
    )
    return f"""
    <header class="site-header">
        <a class="brand" href="/"><span class="brand-mark">T</span><span>TrainMe</span></a>
        <nav class="nav-links" aria-label="Main menu">
            <a href="/spar/atlet">Athlete</a>
            <a href="/spar/aktiv">Active</a>
            <a href="/spar/komma-igang">Getting started</a>
        </nav>
        <div class="account-actions">{auth}</div>
    </header>
    """


def page(title: str, body: str, user: sqlite3.Row | None = None) -> bytes:
    document = f"""
    <!DOCTYPE html>
    <html lang="sv">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{esc(title)}</title>
        <link rel="stylesheet" href="/static/css/style.css">
    </head>
    <body>
        {header(user)}
        <main>{body}</main>
    </body>
    </html>
    """
    return document.encode("utf-8")


def track_cards() -> str:
    cards = []
    for track_id, track in TRACKS.items():
        chips = "".join(f"<span>{esc(SUBCATEGORY_NAMES[sub_id])}</span>" for sub_id in track["subcategories"])
        cards.append(
            f"""
            <article class="track-card {track["accent"]}">
                <div class="track-card-header">
                    <p class="eyebrow">{esc(track["name"])}</p>
                    <h2>{esc(track["name"])}</h2>
                </div>
                <p>{esc(track["tagline"])}</p>
                <ul class="check-list">{check_items(track["focus"])}</ul>
                <div class="chip-row">{chips}</div>
                <a class="text-link" href="/spar/{track_id}">Open {esc(track["name"])}</a>
            </article>
            """
        )
    return "".join(cards)


def home_page(user: sqlite3.Row | None) -> bytes:
    body = f"""
    <section class="hero">
        <div class="hero-copy">
            <p class="eyebrow">Training help for different levels</p>
            <h1>TrainMe</h1>
            <p class="lead">Choose whether you are an Athlete, Active, or Getting started. You can explore for free,
            and with an account you get AI help and Strava-based insights.</p>
            <div class="hero-actions">
                <a class="primary-button" href="/registrera">Create account</a>
                <a class="ghost-button" href="#spar">Explore without an account</a>
            </div>
        </div>
        <div class="hero-panel" aria-label="TrainMe sammanfattning">
            <div><span class="metric">3</span><span class="metric-label">training tracks</span></div>
            <div><span class="metric">9</span><span class="metric-label">subcategories</span></div>
            <div><span class="metric">AI</span><span class="metric-label">with account</span></div>
        </div>
    </section>
    <section class="track-grid" id="spar" aria-label="TrainMe track">{track_cards()}</section>
    <section class="access-band">
        <div><p class="eyebrow">Free or account</p><h2>Start right away. Create an account when you want more help.</h2></div>
        <div class="access-grid">
            <div><h3>Without account</h3><p>Read about tracks, subcategories, training formats, and basic tips.</p></div>
            <div><h3>With account</h3><p>Get AI coaching, save goals, and connect Strava for better recommendations.</p></div>
        </div>
    </section>
    """
    return page("TrainMe", body, user)


def track_page(track_id: str, user: sqlite3.Row | None) -> bytes:
    track = TRACKS[track_id]
    account_actions = (
        '<a class="primary-button" href="/ai-coach">Open AI coach</a><a class="ghost-button" href="/strava">Connect Strava</a>'
        if user
        else '<a class="primary-button" href="/registrera">Create account for AI</a><a class="ghost-button" href="#subcategories">Continue for free</a>'
    )
    connection = get_strava_connection(user["id"]) if user else None
    if user:
        account_actions = (
            '<a class="ghost-button" href="/strava">Strava is connected</a>'
            if connection
            else '<a class="primary-button" href="/strava">Connect Strava</a>'
        )
    strava_onboarding = (
        """
        <section class="strava-onboarding">
            <div>
                <p class="eyebrow">Easy Strava connection</p>
                <h2>Connect Strava with one click</h2>
                <p>TrainMe sends you to Strava, you approve access, and then the AI coach can use your latest sessions as input.</p>
            </div>
            <a class="primary-button compact" href="/strava">Connect Strava</a>
        </section>
        """
        if user and not connection
        else ""
    )
    subcards = []
    for sub_id, copy in track["subcategories"].items():
        subcards.append(
            f"""
            <article class="subcategory-card">
                <span class="sub-icon">{len(subcards) + 1}</span>
                <h2>{esc(SUBCATEGORY_NAMES[sub_id])}</h2>
                <p>{esc(copy)}</p>
                <a class="text-link" href="/spar/{track_id}/{sub_id}">View plan</a>
            </article>
            """
        )
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">TrainMe track</p>
        <h1>{esc(track["name"])}</h1>
        <p class="lead">{esc(track["tagline"])}</p>
        <div class="hero-actions">{account_actions}</div>
    </section>
    <section class="subcategory-grid track-subcategories" id="subcategories">{"".join(subcards)}</section>
    <section class="content-grid">
        <div class="focus-panel"><h2>Focus</h2><ul class="check-list">{check_items(track["focus"])}</ul></div>
        <div class="locked-panel"><h2>AI + Strava</h2><p>{'Your AI coach can use your chosen track, goals, and Strava data for more personal tips.' if user else 'Create an account so TrainMe can save your profile, goal, and Strava data for AI help.'}</p></div>
    </section>
    {strava_onboarding}
    """
    return page(f"{track['name']} | TrainMe", body, user)


def subcategory_page(track_id: str, sub_id: str, user: sqlite3.Row | None) -> bytes:
    track = TRACKS[track_id]
    personal = (
        '<p>You are logged in. The AI coach can use your track and goals to give more relevant suggestions.</p><a class="primary-button compact" href="/ai-coach">Open AI coach</a>'
        if user
        else '<p>This works without an account. Create an account for AI help, saved goals, and Strava connection.</p><a class="primary-button compact" href="/registrera">Create account</a>'
    )
    third_step = {
        "komma-igang": "Build nutrition around simple routines: protein, vegetables, and regular meals.",
        "aktiv": "Adjust nutrition and rest so the body stays healthy over time.",
    }.get(track_id, "Use training data to guide load and quality.")
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">{esc(track["name"])}</p>
        <h1>{esc(SUBCATEGORY_NAMES[sub_id])}</h1>
        <p class="lead">{esc(track["subcategories"][sub_id])}</p>
    </section>
    <section class="program-layout">
        <div>
            <h2>Starting suggestion</h2>
            <div class="step-list">
                <div><span>01</span><p>Choose 2-4 sessions per week based on your current level.</p></div>
                <div><span>02</span><p>Track energy, recovery, and progression after each week.</p></div>
                <div><span>03</span><p>{esc(third_step)}</p></div>
            </div>
        </div>
        <aside class="locked-panel"><h2>Personal help</h2>{personal}</aside>
    </section>
    """
    return page(f"{SUBCATEGORY_NAMES[sub_id]} | TrainMe", body, user)


def register_page(user: sqlite3.Row | None, error: bool = False) -> bytes:
    options = "".join(f'<option value="{track_id}">{esc(track["name"])}</option>' for track_id, track in TRACKS.items())
    message = '<p class="form-error">Email or username already exists.</p>' if error else ""
    body = f"""
    <section class="form-shell">
        <div><p class="eyebrow">TrainMe account</p><h1>Create account</h1><p class="lead">The account unlocks AI help, saved goals, and the ability to connect Strava.</p></div>
        <form class="form-card" method="post" action="/registrera">
            {message}
            <label>Username<input name="username" type="text" autocomplete="username" required></label>
            <label>Email<input name="email" type="email" autocomplete="email" required></label>
            <label> Password<input name="password" type="password" autocomplete="new-password" minlength="6" required></label>
            <label>Track<select name="category" required>{options}</select></label>
            <div class="two-fields">
                <label>Height cm<input name="height" type="number" min="80" max="240" step="0.5"></label>
                <label>Weight kg<input name="weight" type="number" min="20" max="300" step="0.1"></label>
            </div>
            <label>Goal<textarea name="goal" rows="4" placeholder="Example: run 10 km, get stronger, improve nutrition habits"></textarea></label>
            <button class="primary-button" type="submit">Create account</button>
            <a class="text-link" href="/logga-in">I already have an account</a>
        </form>
    </section>
    """
    return page("Create account | TrainMe", body, user)


def login_page(user: sqlite3.Row | None, error: bool = False) -> bytes:
    message = '<p class="form-error">Wrong email or password.</p>' if error else ""
    body = f"""
    <section class="form-shell narrow">
        <div><p class="eyebrow">Welcome back</p><h1>Log in</h1><p class="lead">Continue with AI coaching and Strava data.</p></div>
        <form class="form-card" method="post" action="/logga-in">
            {message}
            <label>Email<input name="email" type="email" autocomplete="email" required></label>
            <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
            <button class="primary-button" type="submit">Log in</button>
            <a class="text-link" href="/registrera">Create account</a>
        </form>
    </section>
    """
    return page("Log in | TrainMe", body, user)


def user_profile_summary(user: sqlite3.Row) -> str:
    parts = [f"Name: {user['username']}", f"Track: {user['category'] or 'aktiv'}"]
    if user["height"]:
        parts.append(f"Langd: {user['height']} cm")
    if user["weight"]:
        parts.append(f"Weight: {user['weight']} kg")
    if user["goal"]:
        parts.append(f"Goal: {user['goal']}")
    return ". ".join(parts)


def weekly_training_plan(user: sqlite3.Row, track_id: str, strava_summary: str | None) -> list[tuple[str, str]]:
    goal = (user["goal"] or "").lower()
    has_strava = bool(strava_summary)

    if track_id != "atlet":
        return [
            ("Monday", "Full-body strength 45 min with controlled progression."),
            ("Tuesday", "Easy cardio 30-45 min at conversational pace."),
            ("Wednesday", "Mobility and recovery 20 min."),
            ("Thursday", "Mixed session with strength, balance, and a short pulse finisher."),
            ("Friday", "Rest or walk."),
            ("Saturday", "Longer optional activity 45-75 min."),
            ("Sunday", "Plan the week and keep nutrition simple."),
        ]

    intensity_note = "based on Strava history" if has_strava else "at a starting level until Strava is connected"
    endurance_bias = any(word in goal for word in ["run", "race", "cardio", "bike", "10 km", "marathon"])
    strength_bias = any(word in goal for word in ["strong", "strength", "muscle", "explosive"])

    if endurance_bias:
        quality = "Intervals 6 x 3 min with 2 min easy between, guided by daily readiness."
        long_session = "Langpass 70-100 min lugnt. Avsluta strongt om kroppen svarar bra."
    elif strength_bias:
        quality = "Explosive strength: squats/deadlifts 5 x 3, jumps or sprint technique, long rest."
        long_session = "Cardio 45-60 min easy for aerobic base and recovery."
    else:
        quality = "Quality session: threshold or tempo 3 x 8 min with controlled effort."
        long_session = "Longer endurance session 60-90 min in an easy zone."

    return [
        ("Monday", f"Lower-body strength and core 50 min, {intensity_note}."),
        ("Tuesday", quality),
        ("Wednesday", "Active recovery: 30 min very easy plus mobility."),
        ("Thursday", "Upper-body strength and injury prevention: pull, press, rear shoulder, hip stability."),
        ("Friday", "Short technique session or fartlek 35-45 min. Stop if the legs feel heavy."),
        ("Saturday", long_session),
        ("Sunday", "Rest, meal planning, and weekly review in the AI chat."),
    ]


def render_weekly_plan(plan: list[tuple[str, str]]) -> str:
    return "".join(
        f"""
        <div class="week-day">
            <span>{esc(day)}</span>
            <div class="session-card-content">
                <p>{esc(session)}</p>
                <a class="tutorial-link" href="{esc(tutorial_url(session))}" target="_blank" rel="noopener">Tutorial</a>
            </div>
        </div>
        """
        for day, session in plan
    )


def tutorial_query(session: str) -> str:
    text = session.lower()
    matches = [
        (("squat",), "how to squat proper form tutorial"),
        (("leg press",), "how to leg press proper form tutorial"),
        (("deadlift", "hip-dominant", "posterior chain"), "how to deadlift proper form tutorial"),
        (("press", "pull", "upper-body", "upper body"), "upper body press and pull workout tutorial"),
        (("lower-body", "lower body"), "lower body strength workout tutorial"),
        (("full-body", "full body"), "full body strength workout tutorial"),
        (("core", "stability"), "core stability exercises tutorial"),
        (("calves", "hamstrings", "hips"), "runner strength exercises tutorial"),
        (("mobility", "recovery"), "mobility routine tutorial"),
        (("interval", "fartlek"), "running intervals workout tutorial"),
        (("tempo", "threshold"), "tempo run workout tutorial"),
        (("long run", "distance run", "easy run", "cardio"), "running form tutorial"),
        (("walk",), "proper walking exercise tutorial"),
        (("cycling",), "cycling workout tutorial"),
        (("circuit",), "circuit training workout tutorial"),
        (("sprint", "jumps"), "sprint technique and jump training tutorial"),
    ]
    for keywords, query in matches:
        if any(keyword in text for keyword in keywords):
            return query
    return f"{session} exercise tutorial"


def tutorial_url(session: str) -> str:
    return "https://www.google.com/search?" + urlencode(
        {"btnI": "1", "q": f"site:youtube.com/watch {tutorial_query(session)}"}
    )


def subcategory_training_plan(sub_id: str, track_name: str) -> list[tuple[str, str]]:
    if sub_id == "strength":
        return [
            ("Monday", "Heavy lower body: squat or leg press, hip-dominant movement, and core."),
            ("Tuesday", "Mobility, easy walk, and recovery."),
            ("Wednesday", "Upper body: press, pull, shoulder stability, and controlled volume."),
            ("Thursday", "Rest or low-load technique training."),
            ("Friday", "Full-body strength: 4-6 basic exercises with clear progression."),
            ("Saturday", "Accessory strength: posterior chain, calves, grip, and injury prevention."),
            ("Sunday", "Evaluate weights, reps, energy, and plan next week."),
        ]
    if sub_id == "mixed":
        return [
            ("Monday", "Full-body strength 45-60 min focused on basic lifts."),
            ("Tuesday", "Easy run 30-45 min at conversational pace."),
            ("Wednesday", "Mobility, core, and active recovery."),
            ("Thursday", "Lower-body strength plus a short conditioning finisher."),
            ("Friday", "Intervals or fartlek 25-40 min depending on daily readiness."),
            ("Saturday", "Optional mixed session: circuit strength, cycling, jogging, or group training."),
            ("Sunday", "Rest and comment on what worked best."),
        ]
    return [
        ("Monday", "Easy distance run 35-50 min with controlled heart rate."),
        ("Tuesday", "Strength for runners: calves, hamstrings, hips, and core 30 min."),
        ("Wednesday", "Intervals: 6 x 2-3 min with easy jog recovery."),
        ("Thursday", "Rest or walk and mobility."),
        ("Friday", "Tempo session 20-30 min at steady effort."),
        ("Saturday", "Easy long run, build volume without chasing pace."),
        ("Sunday", "Recovery and analysis of distance, time, and feel."),
    ]


def subcategory_focus_points(sub_id: str) -> list[str]:
    if sub_id == "strength":
        return [
            "Progressive load in foundational strength exercises.",
            "Technique, stability, and enough rest between heavy sessions.",
            "Comments on every session to track weights, reps, and readiness.",
        ]
    if sub_id == "mixed":
        return [
            "Balance between strength training and running.",
            "Enough variation without making the week scattered.",
            "Comments that capture energy, load, and what should be prioritized.",
        ]
    return [
        "Running with clear structure: easy, quality, and long runs.",
        "Strava data as input for distance, time, and load.",
        "Comments after sessions to guide next week's volume.",
    ]


def nutrition_tips_for_track(track_id: str, variant: int = 0) -> list[tuple[str, str, str]]:
    recipe_sets = {
        "atlet": [
            [
                (
                    "Chicken with rice or quinoa",
                    "Protein and carbohydrates for muscle growth, hard sessions, and recovery.",
                    "https://www.ica.se/recept/?q=chicken%20quinoa",
                ),
                (
                    "Salmon with potatoes and vegetables",
                    "Healthy fats, protein, and energy for performance-focused training.",
                    "https://www.ica.se/recept/?q=salmon%20potatoes%20vegetables",
                ),
                (
                    "Greek yogurt or overnight oats with berries",
                    "Convenient breakfast or evening meal with protein and slow carbohydrates.",
                    "https://www.ica.se/recept/?q=overnight%20oats%20berries",
                ),
                (
                    "Turkey pasta with spinach",
                    "A high-energy meal that supports heavy strength blocks and recovery.",
                    "https://www.ica.se/recept/?q=turkey%20pasta%20spinach",
                ),
                (
                    "Tuna rice bowl with avocado",
                    "Fast protein, carbohydrates, and fats for users training often.",
                    "https://www.ica.se/recept/?q=tuna%20rice%20bowl",
                ),
            ],
            [
                (
                    "Beef stir-fry with noodles",
                    "Iron, protein, and carbohydrates for performance and adaptation.",
                    "https://www.ica.se/recept/?q=beef%20stir%20fry%20noodles",
                ),
                (
                    "Protein pancakes with cottage cheese",
                    "Easy extra calories and protein when the goal is to build more.",
                    "https://www.ica.se/recept/?q=protein%20pancakes%20cottage%20cheese",
                ),
                (
                    "Chicken burrito bowl",
                    "A simple way to combine protein, rice, beans, and vegetables.",
                    "https://www.ica.se/recept/?q=chicken%20burrito%20bowl",
                ),
                (
                    "Prawn omelet with sourdough toast",
                    "Protein-rich meal with enough energy for a demanding week.",
                    "https://www.ica.se/recept/?q=prawn%20omelet",
                ),
                (
                    "Cottage cheese smoothie bowl",
                    "Useful snack after training when appetite is low.",
                    "https://www.ica.se/recept/?q=cottage%20cheese%20smoothie%20bowl",
                ),
            ],
        ],
        "komma-igang": [
            [
                (
                    "Lentil soup with vegetables",
                    "A filling meal with fiber and low energy density.",
                    "https://www.ica.se/recept/?q=lentil%20soup%20vegetables",
                ),
                (
                    "Chicken salad with hearty vegetables",
                    "Easy to portion and good for users who want to lose weight.",
                    "https://www.ica.se/recept/?q=chicken%20salad",
                ),
                (
                    "Cod with vegetables and potatoes",
                    "Lean protein with a simple everyday base.",
                    "https://www.ica.se/recept/?q=cod%20vegetables%20potatoes",
                ),
                (
                    "Vegetable omelet with cottage cheese",
                    "Quick, filling, and protein-rich without being complicated.",
                    "https://www.ica.se/recept/?q=vegetable%20omelet%20cottage%20cheese",
                ),
                (
                    "Turkey lettuce wraps",
                    "Light meal with plenty of protein and crunchy vegetables.",
                    "https://www.ica.se/recept/?q=turkey%20lettuce%20wraps",
                ),
            ],
            [
                (
                    "Bean chili with salad",
                    "Fiber and protein that make it easier to stay full.",
                    "https://www.ica.se/recept/?q=bean%20chili%20salad",
                ),
                (
                    "Shrimp bowl with cauliflower rice",
                    "Light but satisfying meal with lean protein.",
                    "https://www.ica.se/recept/?q=shrimp%20cauliflower%20rice",
                ),
                (
                    "Chicken vegetable tray bake",
                    "Simple portions and easy leftovers for the next day.",
                    "https://www.ica.se/recept/?q=chicken%20vegetable%20tray%20bake",
                ),
                (
                    "Greek salad with grilled chicken",
                    "Fresh, protein-forward meal for a calorie-aware routine.",
                    "https://www.ica.se/recept/?q=greek%20salad%20chicken",
                ),
                (
                    "Skyr with berries and nuts",
                    "Simple breakfast or snack with protein and controlled portions.",
                    "https://www.ica.se/recept/?q=skyr%20berries%20nuts",
                ),
            ],
        ],
        "aktiv": [
            [
                (
                    "Omelet with vegetables",
                    "Quick protein-rich meal for everyday recovery.",
                    "https://www.ica.se/recept/?q=omelet%20vegetables",
                ),
                (
                    "Salmon or chicken with roasted root vegetables",
                    "Balanced plate for energy, health, and regular training.",
                    "https://www.ica.se/recept/?q=salmon%20root%20vegetables",
                ),
                (
                    "Vegetarian bean stew",
                    "Fiber, protein, and solid everyday food for an active lifestyle.",
                    "https://www.ica.se/recept/?q=vegetarian%20bean%20stew",
                ),
                (
                    "Chicken pita with yogurt sauce",
                    "Balanced everyday meal with protein, vegetables, and carbohydrates.",
                    "https://www.ica.se/recept/?q=chicken%20pita%20yogurt%20sauce",
                ),
                (
                    "Tofu noodle bowl",
                    "Plant-based meal with energy for mixed training.",
                    "https://www.ica.se/recept/?q=tofu%20noodle%20bowl",
                ),
            ],
            [
                (
                    "Turkey meatballs with tomato sauce",
                    "A practical protein-rich dinner for regular training weeks.",
                    "https://www.ica.se/recept/?q=turkey%20meatballs%20tomato",
                ),
                (
                    "Halloumi salad with quinoa",
                    "Good mix of protein, texture, and slow carbohydrates.",
                    "https://www.ica.se/recept/?q=halloumi%20salad%20quinoa",
                ),
                (
                    "Chicken noodle soup",
                    "Light, warm meal that supports recovery and routine.",
                    "https://www.ica.se/recept/?q=chicken%20noodle%20soup",
                ),
                (
                    "Egg and avocado toast",
                    "Fast meal with protein and healthy fats.",
                    "https://www.ica.se/recept/?q=egg%20avocado%20toast",
                ),
                (
                    "Chickpea curry with rice",
                    "Fiber, steady energy, and easy leftovers.",
                    "https://www.ica.se/recept/?q=chickpea%20curry%20rice",
                ),
            ],
        ],
    }
    variants = recipe_sets.get(track_id, recipe_sets["aktiv"])
    return variants[variant % len(variants)]


def recipe_search_url(title: str) -> str:
    return "https://www.google.com/search?" + urlencode({"btnI": "1", "q": f"{title} recipe"})


def recipe_site_result_url(title: str, site: str) -> str:
    return "https://www.google.com/search?" + urlencode({"btnI": "1", "q": f"site:{site} {title} recipe"})


def recipe_source_links(title: str, primary_url: str) -> list[tuple[str, str]]:
    return [
        ("Best match", recipe_search_url(title)),
        ("Primary source", primary_url),
        ("ICA", recipe_site_result_url(title, "ica.se/recept")),
        ("Koket", recipe_site_result_url(title, "koket.se")),
        ("Allrecipes", recipe_site_result_url(title, "allrecipes.com")),
        ("BBC Good Food", recipe_site_result_url(title, "bbcgoodfood.com")),
    ]


def render_nutrition_tips(
    track_id: str,
    recipe_variant: int = 0,
    can_save: bool = False,
    return_to: str = "",
    csrf_html: str = "",
) -> str:
    tips = nutrition_tips_for_track(track_id, recipe_variant)
    rows = []
    more_rows = []
    for index, (title, reason, url) in enumerate(tips):
        target_rows = rows if index < 3 else more_rows
        recipe_url = recipe_search_url(title)
        source_links = "".join(
            f'<a href="{esc(source_url)}" target="_blank" rel="noopener">{esc(label)}</a>'
            for label, source_url in recipe_source_links(title, url)
        )
        save_form = ""
        if can_save:
            save_form = f"""
                <form class="recipe-save-form" method="post" action="/recipes/save">
                    {csrf_html}
                    <input type="hidden" name="track_id" value="{esc(track_id)}">
                    <input type="hidden" name="title" value="{esc(title)}">
                    <input type="hidden" name="reason" value="{esc(reason)}">
                    <input type="hidden" name="url" value="{esc(recipe_url)}">
                    <input type="hidden" name="return_to" value="{esc(return_to)}">
                    <button class="ghost-button compact" type="submit">Save recipe</button>
                </form>
            """
        target_rows.append(
            f"""
            <li>
                <strong>{esc(title)}</strong>
                <span>{esc(reason)}</span>
                <div class="recipe-actions">
                    <a class="text-link" href="{esc(recipe_url)}" target="_blank" rel="noopener">Recipe</a>
                    {save_form}
                </div>
                <details class="recipe-source-fallbacks">
                    <summary>More recipe sources</summary>
                    <div>{source_links}</div>
                </details>
            </li>
            """
        )
    more_block = ""
    if more_rows:
        more_block = f"""
        <details class="more-recipes">
            <summary>More recipes</summary>
            <ul>{''.join(more_rows)}</ul>
        </details>
        """
    next_variant = recipe_variant + 1
    return f"""
    <div class="meal-tips">
        <div class="meal-tips-heading">
            <h3>Meals that fit</h3>
            <a class="ghost-button compact" href="?recipes={next_variant}">New recipes</a>
        </div>
        <ul>{''.join(rows)}</ul>
        {more_block}
    </div>
    """


def current_week_label() -> str:
    year, week, _ = time.localtime().tm_year, time.strftime("%V"), time.strftime("%u")
    return f"Week {week}, {year}"


def current_weekday_label() -> str:
    return time.strftime("%A")


def rotate_plan(plan: list[tuple[str, str]], seed: int) -> list[tuple[str, str]]:
    variants = [
        "AI-adjusted focus: keep quality high but stop if you feel unusually heavy.",
        "New variation: put extra emphasis on technique and even load.",
        "AI-generated variation: prioritize recovery between hard elements.",
        "Updated type: note heart rate, energy, and a comment after the session.",
    ]
    return [
        (day, f"{session} {variants[(index + seed) % len(variants)]}")
        for index, (day, session) in enumerate(plan)
    ]


def regenerate_ai_training_plan(user: sqlite3.Row, strava_summary: str | None) -> None:
    track_id = user["category"] or "aktiv"
    plan = rotate_plan(weekly_training_plan(user, track_id, strava_summary), int(time.time()) % 4)
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        for index, (day, session) in enumerate(plan):
            db.execute(
                """
                INSERT INTO training_plan_items (user_id, day_index, day_name, session, is_done, comment, updated_at)
                VALUES (?, ?, ?, ?, 0, '', ?)
                ON CONFLICT(user_id, day_index) DO UPDATE SET
                    day_name = excluded.day_name,
                    session = excluded.session,
                    is_done = 0,
                    comment = '',
                    updated_at = excluded.updated_at
                """,
                (user["id"], index, day, session, now),
            )


def regenerate_subcategory_training_plan(user: sqlite3.Row, track_id: str, sub_id: str) -> None:
    plan = rotate_plan(subcategory_training_plan(sub_id, TRACKS[track_id]["name"]), int(time.time()) % 4)
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        for index, (day, session) in enumerate(plan):
            db.execute(
                """
                INSERT INTO subcategory_plan_items (
                    user_id, track_id, subcategory_id, day_index, day_name, session, is_done, comment, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, '', ?)
                ON CONFLICT(user_id, track_id, subcategory_id, day_index) DO UPDATE SET
                    day_name = excluded.day_name,
                    session = excluded.session,
                    is_done = 0,
                    comment = '',
                    updated_at = excluded.updated_at
                """,
                (user["id"], track_id, sub_id, index, day, session, now),
            )


def ensure_user_training_plan(user: sqlite3.Row, track_id: str, strava_summary: str | None) -> None:
    existing = query_one(
        "SELECT id FROM training_plan_items WHERE user_id = ? LIMIT 1",
        (user["id"],),
    )
    if existing:
        return

    now = int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        for index, (day, session) in enumerate(weekly_training_plan(user, track_id, strava_summary)):
            db.execute(
                """
                INSERT INTO training_plan_items (user_id, day_index, day_name, session, is_done, comment, updated_at)
                VALUES (?, ?, ?, ?, 0, '', ?)
                """,
                (user["id"], index, day, session, now),
            )


def get_user_training_plan(user: sqlite3.Row, track_id: str, strava_summary: str | None) -> list[sqlite3.Row]:
    ensure_user_training_plan(user, track_id, strava_summary)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            """
            SELECT * FROM training_plan_items
            WHERE user_id = ?
            ORDER BY day_index
            """,
            (user["id"],),
        ).fetchall()


def render_editable_weekly_plan(items: list[sqlite3.Row], csrf_html: str = "") -> str:
    cards = []
    for item in items:
        checked = "checked" if item["is_done"] else ""
        cards.append(
            f"""
            <details class="week-day editable-week-day">
                <summary>
                    <span>{esc(item["day_name"])}</span>
                    <div class="session-card-content">
                        <p>{esc(item["session"])}</p>
                    </div>
                </summary>
                <a class="tutorial-link" href="{esc(tutorial_url(item["session"]))}" target="_blank" rel="noopener">Tutorial</a>
                <form class="plan-edit-stack" method="post" action="/plan/update">
                    {csrf_html}
                    <input type="hidden" name="item_id" value="{esc(item["id"])}">
                    <label class="done-toggle">
                        <input type="checkbox" name="is_done" value="1" {checked}>
                        Done
                    </label>
                    <label class="plan-field">Change session
                        <textarea name="session" rows="3" required>{esc(item["session"])}</textarea>
                    </label>
                    <label class="plan-field">Comment
                        <textarea name="comment" rows="3" placeholder="How did the session feel? What do you want to adjust?">{esc(item["comment"] or "")}</textarea>
                    </label>
                    <button class="ghost-button compact" type="submit">Save session</button>
                </form>
            </details>
            """
        )
    return "".join(cards)


def archive_completed_training(
    user_id: int,
    source: str,
    track_id: str,
    subcategory_id: str | None,
    day_name: str,
    session: str,
    comment: str,
) -> None:
    execute(
        """
        INSERT INTO training_archive (
            user_id, source, track_id, subcategory_id, day_name, session, comment, completed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, source, track_id, subcategory_id, day_name, session, comment, int(time.time())),
    )


def render_weight_progress(weight_entries: list[sqlite3.Row]) -> str:
    if not weight_entries:
        return """
        <div class="weight-empty">
            <h3>No weight entries yet</h3>
            <p>Add your first weight to start tracking progress.</p>
        </div>
        """

    chart_entries = list(reversed(weight_entries[:12]))
    weights = [float(entry["weight"]) for entry in chart_entries]
    min_weight = min(weights)
    max_weight = max(weights)
    weight_range = max(max_weight - min_weight, 1.0)
    width = 620
    height = 220
    padding_x = 36
    padding_y = 28
    usable_width = width - padding_x * 2
    usable_height = height - padding_y * 2

    if len(chart_entries) == 1:
        points = [(width / 2, padding_y + usable_height / 2)]
    else:
        points = []
        for index, weight in enumerate(weights):
            x = padding_x + (usable_width * index / (len(weights) - 1))
            y = padding_y + usable_height - ((weight - min_weight) / weight_range * usable_height)
            points.append((x, y))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"><title>{esc(chart_entries[index]["weight"])} kg</title></circle>'
        for index, (x, y) in enumerate(points)
    )
    latest = chart_entries[-1]
    oldest = chart_entries[0]
    delta = float(latest["weight"]) - float(oldest["weight"])
    delta_label = f"{delta:+.1f} kg" if len(chart_entries) > 1 else "First entry"
    latest_date = time.strftime("%Y-%m-%d", time.localtime(latest["recorded_at"] or 0))
    rows = []
    for entry in weight_entries[:6]:
        recorded = time.strftime("%Y-%m-%d", time.localtime(entry["recorded_at"] or 0))
        rows.append(
            f"""
            <li>
                <strong>{esc(entry["weight"])} kg</strong>
                <span>{esc(recorded)}</span>
            </li>
            """
        )

    return f"""
    <div class="weight-progress">
        <div class="weight-summary">
            <div><span>Latest</span><strong>{esc(latest["weight"])} kg</strong><small>{esc(latest_date)}</small></div>
            <div><span>Change</span><strong>{esc(delta_label)}</strong><small>shown entries</small></div>
        </div>
        <svg class="weight-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Weight progress graph">
            <line x1="{padding_x}" y1="{height - padding_y}" x2="{width - padding_x}" y2="{height - padding_y}"></line>
            <line x1="{padding_x}" y1="{padding_y}" x2="{padding_x}" y2="{height - padding_y}"></line>
            <polyline points="{polyline}"></polyline>
            {circles}
        </svg>
        <ul class="weight-history">{''.join(rows)}</ul>
    </div>
    """


def ensure_subcategory_plan(user: sqlite3.Row, track_id: str, sub_id: str) -> None:
    existing = query_one(
        """
        SELECT id FROM subcategory_plan_items
        WHERE user_id = ? AND track_id = ? AND subcategory_id = ?
        LIMIT 1
        """,
        (user["id"], track_id, sub_id),
    )
    if existing:
        return

    now = int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        for index, (day, session) in enumerate(subcategory_training_plan(sub_id, TRACKS[track_id]["name"])):
            db.execute(
                """
                INSERT INTO subcategory_plan_items (
                    user_id, track_id, subcategory_id, day_index, day_name, session, is_done, comment, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, '', ?)
                """,
                (user["id"], track_id, sub_id, index, day, session, now),
            )


def get_subcategory_plan(user: sqlite3.Row, track_id: str, sub_id: str) -> list[sqlite3.Row]:
    ensure_subcategory_plan(user, track_id, sub_id)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            """
            SELECT * FROM subcategory_plan_items
            WHERE user_id = ? AND track_id = ? AND subcategory_id = ?
            ORDER BY day_index
            """,
            (user["id"], track_id, sub_id),
        ).fetchall()


def render_editable_subcategory_plan(items: list[sqlite3.Row], csrf_html: str = "") -> str:
    cards = []
    for item in items:
        checked = "checked" if item["is_done"] else ""
        cards.append(
            f"""
            <details class="week-day editable-week-day">
                <summary>
                    <span>{esc(item["day_name"])}</span>
                    <div class="session-card-content">
                        <p>{esc(item["session"])}</p>
                    </div>
                </summary>
                <a class="tutorial-link" href="{esc(tutorial_url(item["session"]))}" target="_blank" rel="noopener">Tutorial</a>
                <form class="plan-edit-stack" method="post" action="/subcategory-plan/update">
                    {csrf_html}
                    <input type="hidden" name="item_id" value="{esc(item["id"])}">
                    <label class="done-toggle">
                        <input type="checkbox" name="is_done" value="1" {checked}>
                        Done
                    </label>
                    <label class="plan-field">Change session
                        <textarea name="session" rows="3" required>{esc(item["session"])}</textarea>
                    </label>
                    <label class="plan-field">Comment
                        <textarea name="comment" rows="3" placeholder="How did the session feel? What do you want to adjust?">{esc(item["comment"] or "")}</textarea>
                    </label>
                    <button class="ghost-button compact" type="submit">Save session</button>
                </form>
            </details>
            """
        )
    return "".join(cards)


def coach_reply(user: sqlite3.Row, question: str, strava_summary: str | None) -> str:
    if not question.strip():
        return "Write a question about the weekly plan, recovery, nutrition, or how to interpret Strava data."

    goal = user["goal"] or "your goal"
    data_hint = (
        "I use the Strava summary as load input and adjust volume gradually."
        if strava_summary
        else "Connect Strava so I can account for your actual training history."
    )
    return (
        f"Based on the profile and goal '{goal}' I would prioritize one truly good quality session, "
        f"enough recovery, and simple follow-up after each session. {data_hint}"
    )


def ai_page(user: sqlite3.Row) -> bytes:
    track_id = user["category"] or "aktiv"
    track = TRACKS.get(track_id, TRACKS["aktiv"])
    strava_summary, strava_error = fetch_strava_summary(user["id"])
    if strava_summary:
        strava_block = f"<p>{esc(strava_summary)}</p>"
    elif strava_error:
        strava_block = f"<p>{esc(strava_error)}</p><a class=\"text-link\" href=\"/strava\">Check the Strava connection</a>"
    else:
        strava_block = '<p>Strava is waiting for connection. Connect Strava so the AI bot gets training data as input.</p><a class="text-link" href="/strava">Connect Strava</a>'
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">Account only</p>
        <h1>AI coach for {esc(track["name"])}</h1>
        <p class="lead">Personal training tips based on your track, goals, and future Strava data are collected here.</p>
    </section>
    <section class="coach-grid">
        <article class="coach-panel"><h2>Today's direction</h2><p>The AI area is ready. When a real AI model is connected, TrainMe will send the profile, goals, and Strava summary below.</p></article>
        <article class="coach-panel"><h2>Data sources</h2><p>Profile: {esc(user["username"])}. Track: {esc(track["name"])}.</p>{strava_block}</article>
    </section>
    """
    return page("AI coach | TrainMe", body, user)


def ai_page(user: sqlite3.Row, chat_question: str | None = None, chat_answer: str | None = None) -> bytes:
    track_id = user["category"] or "aktiv"
    track = TRACKS.get(track_id, TRACKS["aktiv"])
    strava_summary, strava_html, strava_error = fetch_strava_summary_html(user["id"])
    week_label = current_week_label()

    if strava_html:
        strava_block = strava_html
        strava_status = "Strava is connected and used in the recommendation."
    elif strava_error:
        strava_block = f'<p>{esc(strava_error)}</p><a class="text-link" href="/strava">Check the Strava connection</a>'
        strava_status = "Strava is connected but could not be read right now."
    else:
        strava_block = '<p>Strava is not connected yet. Connect Strava so the AI coach can use actual training history.</p><a class="text-link" href="/strava">Connect Strava</a>'
        strava_status = "Strava is not connected yet."

    profile_summary = user_profile_summary(user)
    plan_items = get_user_training_plan(user, track_id, strava_summary)
    chat_history = ""
    if chat_question and chat_answer:
        chat_history = f"""
        <div class="chat-message user-message">{esc(chat_question)}</div>
        <div class="chat-message ai-message">{esc(chat_answer)}</div>
        """

    if track_id == "atlet":
        coach_content = f"""
        <section class="athlete-coach-grid">
            <article class="coach-panel weekly-panel">
                <p class="eyebrow">Performance plan</p>
                <div class="panel-heading-row">
                    <h2>This week's training</h2>
                    <span>{esc(week_label)}</span>
                </div>
                <p>The routine is created from your profile, goal, and Strava data when available.</p>
                <form class="plan-refresh-form" method="post" action="/plan/regenerate">
                    {csrf_input(user)}
                    <button class="ghost-button compact" type="submit">Update with AI-generated sessions</button>
                </form>
                <div class="week-plan">{render_editable_weekly_plan(plan_items, csrf_input(user))}</div>
            </article>
            <article class="coach-panel">
                <p class="eyebrow">Inputs</p>
                <h2>Data sources</h2>
                <ul class="check-list">
                    <li>{esc(profile_summary)}</li>
                    <li>{esc(strava_status)}</li>
                    <li>Track: Athlete, focused on performance, progression, and recovery.</li>
                </ul>
            </article>
            <article class="coach-panel">
                <p class="eyebrow">Imported</p>
                <h2>Data from Strava</h2>
                {strava_block}
            </article>
            <article class="coach-panel chat-panel">
                <p class="eyebrow">AI dialogue</p>
                <h2>Chat with the coach</h2>
                <div class="chat-window">
                    <div class="chat-message ai-message">Ask me about this week's sessions, recovery, nutrition, or how to adjust the plan.</div>
                    {chat_history}
                </div>
                <form class="chat-form" method="post" action="/ai-chat">
                    {csrf_input(user)}
                    <textarea name="message" rows="3" placeholder="Example: How should I adjust if I feel worn down after intervals?" required></textarea>
                    <button class="primary-button compact" type="submit">Send</button>
                </form>
            </article>
        </section>
        """
    else:
        coach_content = f"""
        <section class="coach-grid">
            <article class="coach-panel"><h2>Today's direction</h2><p>AI-funktionen ar redo som yta. When a real AI model is connected, TrainMe will send the profile, goal, and Strava summary below.</p></article>
            <article class="coach-panel"><h2>Data sources</h2><p>{esc(profile_summary)}</p>{strava_block}</article>
        </section>
        """

    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">Account only</p>
        <h1>AI coach for {esc(track["name"])}</h1>
        <p class="lead">Personal training tips based on your track, goals, and future Strava data are collected here.</p>
    </section>
    {coach_content}
    """
    return page("AI coach | TrainMe", body, user)


def subcategory_page(track_id: str, sub_id: str, user: sqlite3.Row | None, recipe_variant: int = 0) -> bytes:
    track = TRACKS[track_id]
    sub_name = SUBCATEGORY_NAMES[sub_id]
    plan = subcategory_training_plan(sub_id, track["name"])
    focus_points = subcategory_focus_points(sub_id)
    week_label = current_week_label()
    weekday_label = current_weekday_label()

    if user:
        plan_html = render_editable_subcategory_plan(get_subcategory_plan(user, track_id, sub_id), csrf_input(user))
        profile_summary = user_profile_summary(user)
        strava_summary, strava_html, strava_error = fetch_strava_summary_html(user["id"])
        if strava_html:
            strava_block = strava_html
            strava_status = "Strava is connected and can be used as input."
        elif strava_error:
            strava_block = f'<p>{esc(strava_error)}</p><a class="text-link" href="/strava">Check the Strava connection</a>'
            strava_status = "Strava could not be read right now."
        else:
            strava_block = '<p>Strava is not connected yet. Connect Strava for more personal suggestions.</p><a class="text-link" href="/strava">Connect Strava</a>'
            strava_status = "Strava is not connected yet."
        chat_block = """
            <div class="chat-window">
                <div class="chat-message ai-message">Ask me how to adjust the week within this subcategory.</div>
            </div>
            <form class="chat-form" method="post" action="/ai-chat">
                {csrf_input(user)}
                <textarea name="message" rows="3" placeholder="Example: How should I adapt the sessions if I miss Tuesday?" required></textarea>
                <button class="primary-button compact" type="submit">Send</button>
            </form>
        """
    else:
        plan_html = render_weekly_plan(plan)
        profile_summary = "Log in to use profile, goal, and Strava data."
        strava_block = '<p>Create an account to connect Strava and get personal suggestions.</p><a class="text-link" href="/registrera">Create account</a>'
        strava_status = "An account is required for Strava and AI."
        chat_block = '<p>The chat becomes available when you create an account.</p><a class="primary-button compact" href="/registrera">Create account</a>'

    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">{esc(track["name"])} coach</p>
        <h1>{esc(sub_name)}</h1>
        <p class="lead">{esc(track["subcategories"][sub_id])}</p>
    </section>
    <section class="athlete-coach-grid">
        <article class="coach-panel weekly-panel">
            <p class="eyebrow">{esc(sub_name)} plan</p>
            <div class="panel-heading-row">
                <h2>This week's training</h2>
                <div class="week-date-stack">
                    <span>{esc(week_label)}</span>
                    <small>{esc(weekday_label)}</small>
                </div>
            </div>
            <p>{esc(sub_name)} focuses on {'strength training' if sub_id == 'strength' else 'both strength training and running' if sub_id == 'mixed' else 'running and cardio'}.</p>
            <form class="plan-refresh-form" method="post" action="/subcategory-plan/regenerate">
                {csrf_input(user)}
                <input type="hidden" name="track_id" value="{esc(track_id)}">
                <input type="hidden" name="subcategory_id" value="{esc(sub_id)}">
                <button class="ghost-button compact" type="submit">Update with AI-generated sessions</button>
            </form>
            <div class="week-plan">{plan_html}</div>
        </article>
        <article class="coach-panel">
            <p class="eyebrow">Focus</p>
            <h2>{esc(sub_name)} priorities</h2>
            <ul class="check-list">{check_items(focus_points)}</ul>
            {render_nutrition_tips(track_id, recipe_variant, bool(user), f"/spar/{track_id}/{sub_id}?recipes={recipe_variant}", csrf_input(user))}
        </article>
        <article class="coach-panel chat-panel">
            <p class="eyebrow">AI dialogue</p>
            <h2>Chat about {esc(sub_name)}</h2>
            {chat_block}
        </article>
        <article class="coach-panel">
            <p class="eyebrow">Inputs</p>
            <h2>Data sources</h2>
            <ul class="check-list">
                <li>{esc(profile_summary)}</li>
                <li>{esc(strava_status)}</li>
                <li>Subcategory: {esc(sub_name)}.</li>
            </ul>
        </article>
        <article class="coach-panel">
            <p class="eyebrow">Imported</p>
            <h2>Data from Strava</h2>
            {strava_block}
        </article>
    </section>
    """
    return page(f"{sub_name} | {track['name']} | TrainMe", body, user)


def profile_page(user: sqlite3.Row) -> bytes:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        items = db.execute(
            """
            SELECT * FROM training_archive
            WHERE user_id = ?
            ORDER BY completed_at DESC, id DESC
            """,
            (user["id"],),
        ).fetchall()
        saved_recipes = db.execute(
            """
            SELECT * FROM saved_recipes
            WHERE user_id = ?
            ORDER BY saved_at DESC, id DESC
            """,
            (user["id"],),
        ).fetchall()
        weight_entries = db.execute(
            """
            SELECT * FROM weight_entries
            WHERE user_id = ?
            ORDER BY recorded_at DESC, id DESC
            """,
            (user["id"],),
        ).fetchall()

    profile_content = f"""
    <article class="profile-card">
        <h2>Registered profile data</h2>
        <dl class="profile-data-list">
            <div><dt>Username</dt><dd>{esc(user["username"])}</dd></div>
            <div><dt>Email</dt><dd>{esc(user["email"])}</dd></div>
            <div><dt>Category</dt><dd>{esc(TRACKS.get(user["category"], TRACKS["aktiv"])["name"])}</dd></div>
            <div><dt>Height</dt><dd>{esc(f'{user["height"]} cm' if user["height"] else "Not added")}</dd></div>
            <div><dt>Weight</dt><dd>{esc(f'{user["weight"]} kg' if user["weight"] else "Not added")}</dd></div>
            <div><dt>Goal</dt><dd>{esc(user["goal"] or "No goal added yet.")}</dd></div>
        </dl>
    </article>
    <article class="profile-card weight-card">
        <div class="section-heading-row">
            <h2>Weight progress</h2>
        </div>
        <form class="weight-entry-form" method="post" action="/profile/weight">
            {csrf_input(user)}
            <label>New weight in kg
                <input name="weight" type="number" min="20" max="300" step="0.1" placeholder="Example: 78.4" required>
            </label>
            <button class="primary-button compact" type="submit">Add weight</button>
        </form>
        {render_weight_progress(weight_entries)}
    </article>
    """

    if items:
        archive_items = []
        for item in items:
            completed = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["completed_at"] or 0))
            category = item["subcategory_id"] or item["track_id"] or item["source"]
            archive_items.append(
                f"""
                <article class="archive-item">
                    <div>
                        <p class="eyebrow">{esc(item["source"])} Â· {esc(category)}</p>
                        <h2>{esc(item["day_name"])}</h2>
                        <p>{esc(item["session"])}</p>
                    </div>
                    <div>
                        <span class="archive-date">{esc(completed)}</span>
                        <p class="archive-comment">{esc(item["comment"] or "No comment saved.")}</p>
                    </div>
                </article>
                """
            )
        archive_content = "".join(archive_items)
    else:
        archive_content = """
        <div class="empty-archive">
            <h2>No archived sessions yet</h2>
            <p>When you mark a session as done, it is saved here together with your comment.</p>
        </div>
        """

    if saved_recipes:
        recipe_items = []
        for recipe in saved_recipes:
            saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(recipe["saved_at"] or 0))
            track_name = TRACKS.get(recipe["track_id"], TRACKS["aktiv"])["name"]
            recipe_items.append(
                f"""
                <article class="archive-item saved-recipe-item">
                    <div>
                        <p class="eyebrow">{esc(track_name)} recipe</p>
                        <h2>{esc(recipe["title"])}</h2>
                        <p>{esc(recipe["reason"])}</p>
                        <a class="text-link" href="{esc(recipe["url"])}" target="_blank" rel="noopener">Open recipe</a>
                    </div>
                    <span class="archive-date">Saved {esc(saved)}</span>
                </article>
                """
            )
        saved_recipe_content = "".join(recipe_items)
    else:
        saved_recipe_content = """
        <div class="empty-archive">
            <h2>No saved recipes yet</h2>
            <p>Save recipes from the Meals that fit section and they will appear here.</p>
        </div>
        """

    body = f"""
    <section class="page-hero active">
        <p class="eyebrow">Account overview</p>
        <h1>Profile</h1>
        <p class="lead">Your registered profile data, archived training sessions, and saved recipes are collected here.</p>
    </section>
    <section class="profile-tabs" aria-label="Profile tabs">
        <a class="ghost-button compact" href="#profile-data">Profile data</a>
        <a class="ghost-button compact" href="#past-training-sessions">Past training sessions</a>
        <a class="ghost-button compact" href="#saved-recipes">Saved recipes</a>
    </section>
    <section class="profile-section" id="profile-data">
        {profile_content}
    </section>
    <section class="profile-section" id="past-training-sessions">
        <div class="section-heading-row">
            <h2>Past training sessions</h2>
        </div>
        <div class="archive-list">{archive_content}</div>
    </section>
    <section class="profile-section" id="saved-recipes">
        <div class="section-heading-row">
            <h2>Saved recipes</h2>
        </div>
        <div class="archive-list">{saved_recipe_content}</div>
    </section>
    """
    return page("Profile | TrainMe", body, user)


def strava_page(user: sqlite3.Row, message: str | None = None, error: str | None = None) -> bytes:
    connection = get_strava_connection(user["id"])
    configured = strava_is_configured()
    status = ""
    if message:
        status = f'<p class="form-success">{esc(message)}</p>'
    if error:
        status = f'<p class="form-error">{esc(error)}</p>'

    if connection:
        action = f"""
        <p>Strava is connected to <strong>{esc(connection["athlete_name"])}</strong>. The AI bot can now fetch a summary of your latest sessions.</p>
        <form method="post" action="/strava/disconnect">
            {csrf_input(user)}
            <button class="ghost-button" type="submit">Disconnect Strava</button>
        </form>
        <a class="text-link" href="/ai-coach">View AI input</a>
        """
    elif configured and not strava_config_error():
        action = """
        <p>You do not need to enter a username. Click the button and approve TrainMe in Strava so data is fetched securely through your account.</p>
        <ol class="mini-steps">
            <li>TrainMe sends you to Strava.</li>
            <li>You log in and approve access to your activities.</li>
            <li>You come back here and the AI coach can use your latest sessions.</li>
        </ol>
        <a class="primary-button" href="/strava/connect">Connect Strava</a>
        """
    else:
        config_error = strava_config_error() or "Strava API keys are missing."
        action = """
        <p>The Strava connection is built, but the settings need to be corrected.</p>
        <p class="form-error">""" + esc(config_error) + """</p>
        <p>Add the correct STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET as environment variables and restart the server.</p>
        <button class="primary-button" type="button" disabled>Connect Strava</button>
        """

    body = f"""
    <section class="page-hero performance">
        <p class="eyebrow">Strava</p>
        <h1>Connect Strava</h1>
        <p class="lead">All three tracks can use Strava to give the AI coach better information about your training.</p>
    </section>
    <section class="content-grid">
        <div class="focus-panel"><h2>What TrainMe can use</h2><ul class="check-list"><li>Session history and frequency</li><li>Distance, time, intensity, and progress</li><li>Input for smarter tips about load and recovery</li></ul></div>
        <div class="locked-panel"><h2>Integration</h2>{status}{action}</div>
    </section>
    """
    return page("Strava | TrainMe", body, user)


class TrainMeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ensure_db()
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)
        user = self.current_user()

        if path.startswith("/static/"):
            self.serve_static(path)
        elif path == "/":
            self.send_html(home_page(user))
        elif path == "/registrera":
            self.send_html(register_page(user, error="fel" in query))
        elif path == "/logga-in":
            self.send_html(login_page(user, error="fel" in query))
        elif path == "/ai-coach":
            self.redirect("/registrera") if not user else self.send_html(ai_page(user))
        elif path == "/strava":
            self.redirect("/registrera") if not user else self.send_html(strava_page(user))
        elif path == "/profile":
            self.redirect("/registrera") if not user else self.send_html(profile_page(user))
        elif path == "/arkiv":
            self.redirect("/profile")
        elif path == "/strava/connect":
            self.redirect("/registrera") if not user else self.strava_connect(user)
        elif path == "/strava/callback":
            self.strava_callback(query)
        elif path.startswith("/spar/"):
            parts = path.strip("/").split("/")
            self.handle_track(parts, user, query)
        else:
            self.redirect("/")

    def do_POST(self) -> None:
        ensure_db()
        parsed = urlparse(self.path)
        if parsed.path == "/registrera":
            self.register()
        elif parsed.path == "/logga-in":
            self.login()
        elif parsed.path == "/logga-ut":
            user = self.current_user()
            self.redirect("/", clear_cookie=True) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/strava/disconnect":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.strava_disconnect(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/ai-chat":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.ai_chat(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/plan/update":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.update_plan_item(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/subcategory-plan/update":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.update_subcategory_plan_item(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/plan/regenerate":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.regenerate_plan(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/subcategory-plan/regenerate":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.regenerate_subcategory_plan(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/recipes/save":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.save_recipe(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/profile/weight":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.save_weight(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        else:
            self.redirect("/")

    def handle_track(self, parts: list[str], user: sqlite3.Row | None, query: dict[str, list[str]] | None = None) -> None:
        if len(parts) < 2 or parts[1] not in TRACKS:
            self.redirect("/")
            return
        track_id = parts[1]
        if len(parts) == 2:
            self.send_html(track_page(track_id, user))
            return
        sub_id = SUBCATEGORY_ALIASES.get(parts[2], parts[2])
        if sub_id not in TRACKS[track_id]["subcategories"]:
            self.redirect(f"/spar/{track_id}")
            return
        recipe_variant = 0
        if query:
            try:
                recipe_variant = int(query.get("recipes", ["0"])[0])
            except ValueError:
                recipe_variant = 0
        self.send_html(subcategory_page(track_id, sub_id, user, recipe_variant))

    def register(self) -> None:
        form = self.form_data()
        category = form.get("category", "aktiv")
        if category not in TRACKS:
            category = "aktiv"

        try:
            height = float(form["height"]) if form.get("height") else None
            weight = float(form["weight"]) if form.get("weight") else None
            with sqlite3.connect(DB_PATH) as db:
                cursor = db.execute(
                    """
                    INSERT INTO users (username, email, password, category, height, weight, goal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        form.get("username", "").strip(),
                        form.get("email", "").strip().lower(),
                        hash_password(form.get("password", "")),
                        category,
                        height,
                        weight,
                        form.get("goal", "").strip(),
                    ),
                )
                user_id = cursor.lastrowid
                if weight is not None:
                    db.execute(
                        """
                        INSERT INTO weight_entries (user_id, weight, recorded_at)
                        VALUES (?, ?, ?)
                        """,
                        (user_id, weight, int(time.time())),
                    )
        except (sqlite3.IntegrityError, ValueError):
            self.redirect("/registrera?fel=finns")
            return

        self.redirect(f"/spar/{category}", user_id=user_id)

    def login(self) -> None:
        form = self.form_data()
        user = query_one("SELECT * FROM users WHERE email = ?", (form.get("email", "").strip().lower(),))
        if not user or not verify_password(form.get("password", ""), user["password"]):
            self.redirect("/logga-in?fel=1")
            return
        self.redirect(f"/spar/{user['category'] or 'aktiv'}", user_id=user["id"])

    def ai_chat(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        question = form.get("message", "").strip()
        strava_summary, _ = fetch_strava_summary(user["id"])
        answer = coach_reply(user, question, strava_summary)
        self.send_html(ai_page(user, chat_question=question, chat_answer=answer))

    def update_plan_item(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        item_id = form.get("item_id", "")
        session = form.get("session", "").strip()
        comment = form.get("comment", "").strip()
        is_done = 1 if form.get("is_done") == "1" else 0

        if item_id and session:
            before = query_one(
                "SELECT * FROM training_plan_items WHERE id = ? AND user_id = ?",
                (item_id, user["id"]),
            )
            execute(
                """
                UPDATE training_plan_items
                SET session = ?, comment = ?, is_done = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (session, comment, is_done, int(time.time()), item_id, user["id"]),
            )
            if is_done and before and not before["is_done"]:
                archive_completed_training(
                    user["id"],
                    "AI Coach",
                    user["category"] or "aktiv",
                    None,
                    before["day_name"],
                    session,
                    comment,
                )

        self.redirect("/ai-coach")

    def update_subcategory_plan_item(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        item_id = form.get("item_id", "")
        session = form.get("session", "").strip()
        comment = form.get("comment", "").strip()
        is_done = 1 if form.get("is_done") == "1" else 0

        item = None
        if item_id:
            item = query_one(
                "SELECT * FROM subcategory_plan_items WHERE id = ? AND user_id = ?",
                (item_id, user["id"]),
            )

        if item and session:
            execute(
                """
                UPDATE subcategory_plan_items
                SET session = ?, comment = ?, is_done = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (session, comment, is_done, int(time.time()), item_id, user["id"]),
            )
            if is_done and not item["is_done"]:
                archive_completed_training(
                    user["id"],
                    "Subcategory",
                    item["track_id"],
                    item["subcategory_id"],
                    item["day_name"],
                    session,
                    comment,
                )
            self.redirect(f"/spar/{item['track_id']}/{item['subcategory_id']}")
            return

        self.redirect("/ai-coach")

    def regenerate_plan(self, user: sqlite3.Row) -> None:
        strava_summary, _, _ = fetch_strava_summary_html(user["id"])
        regenerate_ai_training_plan(user, strava_summary)
        self.redirect("/ai-coach")

    def regenerate_subcategory_plan(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        track_id = form.get("track_id", "")
        sub_id = form.get("subcategory_id", "")
        if track_id in TRACKS and sub_id in TRACKS[track_id]["subcategories"]:
            regenerate_subcategory_training_plan(user, track_id, sub_id)
            self.redirect(f"/spar/{track_id}/{sub_id}")
            return
        self.redirect("/ai-coach")

    def save_recipe(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        track_id = form.get("track_id", user["category"] or "aktiv")
        if track_id not in TRACKS:
            track_id = user["category"] or "aktiv"
        title = form.get("title", "").strip()
        reason = form.get("reason", "").strip()
        url = form.get("url", "").strip()
        if not url.startswith(("https://", "http://")):
            url = recipe_search_url(title)
        return_to = form.get("return_to", "/profile#saved-recipes").strip() or "/profile#saved-recipes"
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/profile#saved-recipes"

        if title and url:
            execute(
                """
                INSERT OR IGNORE INTO saved_recipes (user_id, track_id, title, reason, url, saved_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user["id"], track_id, title, reason, url, int(time.time())),
            )

        self.redirect(return_to)

    def save_weight(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        try:
            weight = float(form.get("weight", ""))
        except ValueError:
            self.redirect("/profile#profile-data")
            return

        if not 20 <= weight <= 300:
            self.redirect("/profile#profile-data")
            return

        now = int(time.time())
        with sqlite3.connect(DB_PATH) as db:
            db.execute(
                """
                INSERT INTO weight_entries (user_id, weight, recorded_at)
                VALUES (?, ?, ?)
                """,
                (user["id"], weight, now),
            )
            db.execute(
                """
                UPDATE users
                SET weight = ?
                WHERE id = ?
                """,
                (weight, user["id"]),
            )

        self.redirect("/profile#profile-data")

    def strava_connect(self, user: sqlite3.Row) -> None:
        config_error = strava_config_error()
        if config_error:
            self.send_html(strava_page(user, error=config_error))
            return
        session = self.current_session()
        if not session:
            self.redirect("/registrera")
            return
        state = f"{user['id']}:{secrets.token_urlsafe(24)}"
        execute("UPDATE sessions SET strava_state = ? WHERE token = ?", (state, session["token"]))
        self.redirect(strava_authorize_url(user["id"], state))

    def strava_callback(self, query: dict[str, list[str]]) -> None:
        user = self.current_user()
        if not user:
            self.redirect("/registrera")
            return

        if query.get("error"):
            self.send_html(strava_page(user, error="The Strava connection was cancelled or denied."))
            return

        code = query.get("code", [""])[0]
        scope = query.get("scope", [""])[0]
        state = query.get("state", [""])[0]
        session = self.current_session()
        state_user_id = state.split(":", 1)[0]
        if not code or state_user_id != str(user["id"]) or not session or state != (session["strava_state"] or ""):
            self.send_html(strava_page(user, error="The Strava response could not be verified. Try connecting again."))
            return
        execute("UPDATE sessions SET strava_state = NULL WHERE token = ?", (session["token"],))

        if "activity:read" not in scope:
            self.send_html(strava_page(user, error="TrainMe needs the activity:read permission to fetch your sessions."))
            return

        try:
            exchange_strava_code(user["id"], code, scope)
        except (HTTPError, URLError, TimeoutError) as exc:
            self.send_html(strava_page(user, error=f"Could not complete the Strava connection: {exc}"))
            return

        self.send_html(strava_page(user, message="Strava is connected. The AI bot can now use your latest sessions as input."))

    def strava_disconnect(self, user: sqlite3.Row) -> None:
        execute("DELETE FROM strava_connections WHERE user_id = ?", (user["id"],))
        self.send_html(strava_page(user, message="Strava is disconnected from TrainMe."))

    def valid_post_user(self, user: sqlite3.Row | None) -> bool:
        return valid_csrf(user, self.form_data())

    def current_session(self) -> sqlite3.Row | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        jar = cookies.SimpleCookie(raw_cookie)
        morsel = jar.get("trainme_user")
        if not morsel:
            return None
        return get_session(morsel.value)

    def current_user(self) -> sqlite3.Row | None:
        session = self.current_session()
        if not session:
            return None
        return query_one("SELECT * FROM users WHERE id = ?", (session["user_id"],))

    def form_data(self) -> dict[str, str]:
        if hasattr(self, "_cached_form_data"):
            return self._cached_form_data
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self._cached_form_data = {key: values[0] for key, values in parse_qs(body).items()}
        return self._cached_form_data

    def serve_static(self, path: str) -> None:
        requested = (STATIC_DIR / path.removeprefix("/static/")).resolve()
        if STATIC_DIR.resolve() not in requested.parents or not requested.exists():
            self.send_error(404)
            return
        content_type = "text/css; charset=utf-8" if requested.suffix == ".css" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(requested.read_bytes())

    def send_html(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location: str, user_id: int | None = None, clear_cookie: bool = False) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if user_id is not None:
            token = create_session(user_id)
            self.send_header("Set-Cookie", f"trainme_user={token}; Max-Age={SESSION_MAX_AGE}; HttpOnly; SameSite=Lax; Path=/")
        if clear_cookie:
            session = self.current_session()
            if session:
                delete_session(session["token"])
            self.send_header("Set-Cookie", "trainme_user=; Max-Age=0; Path=/")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def run() -> None:
    ensure_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), TrainMeHandler)
    print(f"TrainMe running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()

