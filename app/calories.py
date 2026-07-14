from __future__ import annotations

import sqlite3
import time

from app.config import DB_PATH
from app.utils import esc


DEFAULT_DAILY_CALORIE_TARGET = 2000


def today_bounds() -> tuple[int, int]:
    now = time.localtime()
    start = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
    return start, start + 86400


def add_calorie_entry(user_id: int, label: str, calories: int) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            INSERT INTO calorie_entries (user_id, label, calories, logged_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, label, calories, int(time.time())),
        )


def get_today_calorie_entries(user_id: int) -> list[sqlite3.Row]:
    start, end = today_bounds()
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(
            """
            SELECT * FROM calorie_entries
            WHERE user_id = ? AND logged_at >= ? AND logged_at < ?
            ORDER BY logged_at DESC, id DESC
            """,
            (user_id, start, end),
        ).fetchall()


def render_calorie_counter(
    user_id: int,
    csrf_html: str,
    strava_burned: int | None = None,
    return_to: str = "/spar/komma-igang/start-without-gym",
    message: str = "",
) -> str:
    entries = get_today_calorie_entries(user_id)
    consumed = sum(int(entry["calories"] or 0) for entry in entries)
    has_strava_burn = strava_burned is not None
    burned = int(strava_burned) if has_strava_burn else 0
    remaining = DEFAULT_DAILY_CALORIE_TARGET - consumed + burned
    progress = min(int((consumed / DEFAULT_DAILY_CALORIE_TARGET) * 100), 100)
    entry_rows = []
    for entry in entries[:5]:
        logged = time.strftime("%H:%M", time.localtime(entry["logged_at"] or 0))
        entry_rows.append(
            f"""
            <li>
                <strong>{esc(entry["label"] or "Meal")}</strong>
                <span>{esc(entry["calories"])} kcal - {esc(logged)}</span>
            </li>
            """
        )
    history = "".join(entry_rows) if entry_rows else "<li><span>No food calories logged today.</span></li>"
    burned_label = f"{burned} kcal" if has_strava_burn else "Connect Strava"
    strava_note = (
        "Synced from today's Strava activities."
        if has_strava_burn
        else "Connect Strava to fill this data point automatically."
    )
    status = f'<p class="calorie-estimate-status">{esc(message)}</p>' if message else ""
    return f"""
    <div class="calorie-counter">
        <div class="section-heading-row">
            <h3>Daily calorie counter</h3>
        </div>
        <div class="calorie-progress" aria-label="Daily calorie intake progress">
            <div class="calorie-progress-text">
                <strong>{consumed} / {DEFAULT_DAILY_CALORIE_TARGET} kcal</strong>
                <span>resets every day</span>
            </div>
            <div class="calorie-progress-track">
                <div class="calorie-progress-fill" style="width: {progress}%"></div>
            </div>
        </div>
        <div class="calorie-total-grid">
            <div><span>{consumed}</span><p>eaten today</p></div>
            <div><span>{burned_label}</span><p>burned from Strava today</p></div>
            <div><span>{remaining}</span><p>remaining estimate</p></div>
        </div>
        <div class="calorie-tabs">
            <input id="calorie-tab-intake-{user_id}" name="calorie-tabs-{user_id}" type="radio" checked>
            <label for="calorie-tab-intake-{user_id}">Intake</label>
            <input id="calorie-tab-strava-{user_id}" name="calorie-tabs-{user_id}" type="radio">
            <label for="calorie-tab-strava-{user_id}">Strava burn</label>
            <div class="calorie-tab-panel calorie-tab-intake">
                <strong>{consumed} kcal eaten today</strong>
                <span>Food entries reset at midnight.</span>
            </div>
            <div class="calorie-tab-panel calorie-tab-strava">
                <strong>{burned_label}</strong>
                <span>{esc(strava_note)}</span>
            </div>
        </div>
        {status}
        <form class="calorie-entry-form" method="post" action="/calories/add">
            {csrf_html}
            <input type="hidden" name="return_to" value="{esc(return_to)}">
            <label>Meal or snack
                <input name="label" type="text" placeholder="Example: lunch" maxlength="80">
            </label>
            <label>Calories
                <input name="calories" type="number" min="1" max="5000" step="1" placeholder="350" required>
            </label>
            <button class="primary-button compact" type="submit">Add calories</button>
        </form>
        <div class="calorie-ai-tools">
            <form class="calorie-ai-form" method="post" action="/calories/estimate-text">
                {csrf_html}
                <input type="hidden" name="return_to" value="{esc(return_to)}">
                <label>Describe what you ate
                    <textarea name="description" rows="3" placeholder="Example: chicken bowl with rice, avocado, and sauce" required></textarea>
                </label>
                <button class="ghost-button compact" type="submit">Estimate from text</button>
            </form>
            <form class="calorie-ai-form" method="post" action="/calories/estimate-photo" enctype="multipart/form-data">
                {csrf_html}
                <input type="hidden" name="return_to" value="{esc(return_to)}">
                <label>Upload food photo
                    <input name="food_photo" type="file" accept="image/png,image/jpeg,image/webp" required>
                </label>
                <button class="ghost-button compact" type="submit">Estimate from photo</button>
            </form>
        </div>
        <ul class="calorie-entry-list">{history}</ul>
    </div>
    """
