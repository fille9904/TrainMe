from __future__ import annotations

import os
import secrets
import sqlite3
import sys
import time
from http import cookies
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Core configuration, persistence, security, and API helpers live in separate modules.

# Core concerns are implemented in separate modules. These assignments keep the
# existing page-rendering code stable while moving app behavior out of main.py.
from app.config import (  # noqa: E402
    BASE_DIR,
    DB_PATH,
    SESSION_MAX_AGE,
    STATIC_DIR,
    SUBCATEGORY_ALIASES,
    SUBCATEGORY_NAMES,
    TRACKS,
)
from app.calories import add_calorie_entry, render_calorie_counter, today_bounds
from app.ai_calories import estimate_calories_from_image, estimate_calories_from_text
from app.db import ensure_db, execute, query_one  # noqa: E402
from app.plans import (  # noqa: E402
    archive_completed_training,
    rotate_plan,
    subcategory_focus_points,
    subcategory_training_plan,
    tutorial_url,
    user_profile_summary,
    weekly_training_plan,
)
from app.recipes import nutrition_tips_for_track, recipe_search_url, recipe_source_links  # noqa: E402
from app.security import (  # noqa: E402
    create_session,
    csrf_input,
    delete_session,
    get_session,
    hash_password,
    valid_csrf,
    verify_password,
)
from app.strava_api import (  # noqa: E402
    exchange_strava_code,
    fetch_strava_calories_burned,
    fetch_strava_summary,
    fetch_strava_summary_html,
    get_strava_connection,
    strava_authorize_url,
    strava_config_error,
    strava_is_configured,
)
from app.utils import check_items, esc  # noqa: E402


MAX_FORM_BYTES = 6 * 1024 * 1024
ALLOWED_FOOD_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
DEFAULT_START_SUBCATEGORY = "start-without-gym"




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


def subcategory_focus_sentence(track_id: str, sub_id: str) -> str:
    if track_id == "komma-igang":
        labels = {
            "start-with-gym": "easy gym workouts, enough rest, and walking as active recovery",
            "start-without-gym": "simple no-equipment workouts, enough rest, and walking as active recovery",
            "lose-weight": "low-impact workouts, weight-loss habits, and walking as active recovery",
        }
        return labels.get(sub_id, "easy workouts and walking as active recovery")
    return (
        "strength training"
        if sub_id == "strength"
        else "both strength training and running"
        if sub_id == "mixed"
        else "running and cardio"
    )



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


def subcategory_page(track_id: str, sub_id: str, user: sqlite3.Row | None, recipe_variant: int = 0, calorie_message: str = "") -> bytes:
    track = TRACKS[track_id]
    sub_name = SUBCATEGORY_NAMES[sub_id]
    plan = subcategory_training_plan(sub_id, track["name"])
    focus_points = subcategory_focus_points(sub_id)
    week_label = current_week_label()
    weekday_label = current_weekday_label()
    calorie_counter = ""

    if user:
        plan_html = render_editable_subcategory_plan(get_subcategory_plan(user, track_id, sub_id), csrf_input(user))
        profile_summary = user_profile_summary(user)
        strava_summary, strava_html, strava_error = fetch_strava_summary_html(user["id"])
        strava_burned, _ = fetch_strava_calories_burned(user["id"], *today_bounds())
        calorie_counter = render_calorie_counter(user["id"], csrf_input(user), strava_burned, f"/spar/{track_id}/{sub_id}", calorie_message)
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
        calorie_counter = """
        <div class="calorie-counter">
            <h3>Daily calorie counter</h3>
            <p>Create an account to log food calories, estimate intake with AI, and combine it with calories burned from Strava.</p>
            <a class="primary-button compact" href="/registrera">Create account</a>
        </div>
        """

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
            <p>{esc(sub_name)} focuses on {esc(subcategory_focus_sentence(track_id, sub_id))}.</p>
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
            {calorie_counter}
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
        elif parsed.path == "/calories/add":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.save_calories(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/calories/estimate-text":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.estimate_text_calories(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
        elif parsed.path == "/calories/estimate-photo":
            user = self.current_user()
            self.redirect("/registrera") if not user else self.estimate_photo_calories(user) if self.valid_post_user(user) else self.send_error(403, "Invalid CSRF token")
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
        calorie_message = query.get("calorie_message", [""])[0] if query else ""
        self.send_html(subcategory_page(track_id, sub_id, user, recipe_variant, calorie_message))

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

    def save_calories(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        return_to = form.get("return_to", f"/spar/komma-igang/{DEFAULT_START_SUBCATEGORY}").strip() or f"/spar/komma-igang/{DEFAULT_START_SUBCATEGORY}"
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = f"/spar/komma-igang/{DEFAULT_START_SUBCATEGORY}"
        label = form.get("label", "").strip() or "Meal"
        try:
            calories = int(float(form.get("calories", "")))
        except ValueError:
            self.redirect(return_to)
            return

        if not 1 <= calories <= 5000:
            self.redirect(return_to)
            return

        add_calorie_entry(user["id"], label, calories)
        self.redirect(return_to)

    def calorie_return_to(self, form: dict[str, str]) -> str:
        return_to = form.get("return_to", "/spar/aktiv/strength").strip() or "/spar/aktiv/strength"
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/spar/aktiv/strength"
        return return_to

    def redirect_with_calorie_message(self, return_to: str, message: str) -> None:
        separator = "&" if "?" in return_to else "?"
        self.redirect(f"{return_to}{separator}calorie_message={quote(message[:220])}")

    def estimate_text_calories(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        return_to = self.calorie_return_to(form)
        description = form.get("description", "").strip()
        calories, note = estimate_calories_from_text(description)
        if calories:
            add_calorie_entry(user["id"], f"AI estimate: {description[:60] or 'meal'}", calories)
            self.redirect_with_calorie_message(return_to, f"Added {calories} kcal. {note}")
            return
        self.redirect_with_calorie_message(return_to, note)

    def estimate_photo_calories(self, user: sqlite3.Row) -> None:
        form = self.form_data()
        return_to = self.calorie_return_to(form)
        upload = self.uploaded_files().get("food_photo")
        if not upload or not upload.get("content"):
            self.redirect_with_calorie_message(return_to, "Upload a food photo first.")
            return
        content_type = upload.get("content_type", "")
        content = upload["content"]
        if content_type not in ALLOWED_FOOD_IMAGE_TYPES:
            self.redirect_with_calorie_message(return_to, "Use a JPEG, PNG, or WebP food photo.")
            return
        if len(content) > MAX_FORM_BYTES:
            self.redirect_with_calorie_message(return_to, "The food photo is too large. Use an image under 6 MB.")
            return

        calories, note = estimate_calories_from_image(content, content_type)
        if calories:
            add_calorie_entry(user["id"], "AI photo estimate", calories)
            self.redirect_with_calorie_message(return_to, f"Added {calories} kcal from the photo. {note}")
            return
        self.redirect_with_calorie_message(return_to, note)

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
        if length > MAX_FORM_BYTES:
            self._cached_form_data = {}
            self._cached_uploaded_files = {}
            return self._cached_form_data
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            self._cached_form_data, self._cached_uploaded_files = self.parse_multipart_form(body, content_type)
            return self._cached_form_data

        self._cached_uploaded_files = {}
        self._cached_form_data = {key: values[0] for key, values in parse_qs(body.decode("utf-8")).items()}
        return self._cached_form_data

    def uploaded_files(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self, "_cached_form_data"):
            self.form_data()
        return getattr(self, "_cached_uploaded_files", {})

    def parse_multipart_form(self, body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        parser_input = b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        message = BytesParser(policy=default).parsebytes(parser_input)
        fields: dict[str, str] = {}
        files: dict[str, dict[str, Any]] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                files[name] = {
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "content": payload,
                }
            else:
                fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return fields, files

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





