from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import STRAVA_API_BASE, STRAVA_AUTHORIZE_URL, STRAVA_REDIRECT_URI, STRAVA_TOKEN_URL
from app.db import execute, query_one
from app.utils import esc


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


def format_pace(distance_m: float, moving_seconds: float) -> str:
    if distance_m <= 0 or moving_seconds <= 0:
        return "tempo unavailable"
    seconds_per_km = moving_seconds / (distance_m / 1000)
    minutes = int(seconds_per_km // 60)
    seconds = int(round(seconds_per_km % 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d} min/km"


def format_speed(distance_m: float, moving_seconds: float) -> str:
    if distance_m <= 0 or moving_seconds <= 0:
        return "speed unavailable"
    return f"{distance_m / 1000 / (moving_seconds / 3600):.1f} km/h"


def activity_metric_line(activity: dict[str, Any]) -> str:
    sport = activity.get("sport_type") or activity.get("type") or "Activity"
    name = activity.get("name") or sport
    distance_m = float(activity.get("distance") or 0)
    moving_seconds = float(activity.get("moving_time") or 0)
    calories = int(float(activity.get("calories") or 0))
    distance_km = distance_m / 1000
    minutes = int(moving_seconds / 60)
    pace = format_pace(distance_m, moving_seconds)
    speed = format_speed(distance_m, moving_seconds)
    kcal_per_hour = int(round(calories / (moving_seconds / 3600))) if calories and moving_seconds else 0
    kcal_text = f", {calories} kcal burned" if calories else ", kcal burned unavailable"
    kcal_rate = f", {kcal_per_hour} kcal/hour" if kcal_per_hour else ""
    return f"{name} ({sport}): {distance_km:.1f} km, {minutes} min, tempo {pace}, average speed {speed}{kcal_text}{kcal_rate}"


def fetch_recent_activities(connection: sqlite3.Row, per_page: int = 10) -> list[dict[str, Any]]:
    activities = get_json(f"{STRAVA_API_BASE}/athlete/activities?per_page={per_page}", connection["access_token"])
    if not activities:
        return []

    detailed_activities: list[dict[str, Any]] = []
    for activity in activities[:per_page]:
        activity_id = activity.get("id")
        if not activity_id:
            detailed_activities.append(activity)
            continue
        try:
            detailed = get_json(
                f"{STRAVA_API_BASE}/activities/{activity_id}?include_all_efforts=false",
                connection["access_token"],
            )
        except (HTTPError, URLError, TimeoutError, RuntimeError):
            detailed_activities.append(activity)
            continue
        merged = {**activity, **(detailed or {})}
        detailed_activities.append(merged)
    return detailed_activities


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
    if int(connection["expires_at"] or 0) > int(time.time()) + 60:
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
        raise RuntimeError("Strava connection could not be refreshed.")
    return refreshed


def fetch_strava_summary(user_id: int) -> tuple[str | None, str | None]:
    connection = get_strava_connection(user_id)
    if not connection:
        return None, None

    try:
        connection = refresh_strava_connection(connection)
        activities = fetch_recent_activities(connection)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return None, f"Could not fetch Strava data right now: {exc}"

    if not activities:
        return "Strava is connected, but no activities were found yet.", None

    total_distance_m = sum(float(activity.get("distance") or 0) for activity in activities)
    total_seconds = sum(float(activity.get("moving_time") or 0) for activity in activities)
    total_calories = sum(float(activity.get("calories") or 0) for activity in activities)
    sport_counts: dict[str, int] = {}
    for activity in activities:
        sport = activity.get("sport_type") or activity.get("type") or "Activity"
        sport_counts[sport] = sport_counts.get(sport, 0) + 1

    sports = ", ".join(f"{count} {sport}" for sport, count in sorted(sport_counts.items()))
    distance_km = total_distance_m / 1000
    hours = total_seconds / 3600
    average_pace = format_pace(total_distance_m, total_seconds)
    average_speed = format_speed(total_distance_m, total_seconds)
    activity_lines = " | ".join(activity_metric_line(activity) for activity in activities[:10])
    return (
        f"Latest 10 Strava sessions: {sports}. Total: {distance_km:.1f} km, {hours:.1f} hours"
        f"{f', and {total_calories:.0f} kcal burned' if total_calories else ''}. "
        f"Average tempo/pace: {average_pace}; average speed: {average_speed}. "
        f"Workout data points for AI analysis: {activity_lines}.",
        None,
    )


def fetch_strava_summary_html(user_id: int) -> tuple[str | None, str | None, str | None]:
    connection = get_strava_connection(user_id)
    if not connection:
        return None, None, None

    try:
        connection = refresh_strava_connection(connection)
        activities = fetch_recent_activities(connection)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return None, None, f"Could not fetch Strava data right now: {exc}"

    if not activities:
        return "Strava is connected, but no activities were found yet.", "<p>No Strava activities were found yet.</p>", None

    total_distance_m = sum(float(activity.get("distance") or 0) for activity in activities)
    total_seconds = sum(float(activity.get("moving_time") or 0) for activity in activities)
    total_calories = sum(float(activity.get("calories") or 0) for activity in activities)
    rows = []
    summary_lines = []
    for activity in activities[:10]:
        sport = activity.get("sport_type") or activity.get("type") or "Activity"
        name = activity.get("name") or sport
        distance_km = float(activity.get("distance") or 0) / 1000
        moving_seconds = float(activity.get("moving_time") or 0)
        minutes = int(moving_seconds / 60)
        raw_calories = activity.get("calories")
        calories = int(float(raw_calories or 0))
        start = (activity.get("start_date_local") or activity.get("start_date") or "")[:10]
        pace = format_pace(float(activity.get("distance") or 0), moving_seconds)
        speed = format_speed(float(activity.get("distance") or 0), moving_seconds)
        calories_text = f" - {calories} kcal burned" if raw_calories is not None else " - kcal burned unavailable"
        summary_lines.append(activity_metric_line(activity))
        rows.append(
            f"""
            <li>
                <strong>{esc(name)}</strong>
                <span>{esc(start)} - {esc(sport)} - {distance_km:.1f} km - {minutes} min - tempo {esc(pace)} - avg speed {esc(speed)}{esc(calories_text)}</span>
            </li>
            """
        )

    summary = (
        f"Latest 10 Strava sessions. Total: {total_distance_m / 1000:.1f} km, {total_seconds / 3600:.1f} hours"
        f"{f', and {total_calories:.0f} kcal burned' if total_calories else ''}. "
        f"Average tempo/pace: {format_pace(total_distance_m, total_seconds)}; average speed: {format_speed(total_distance_m, total_seconds)}. "
        f"Workout data points for AI analysis: {' | '.join(summary_lines)}."
    )
    html_block = f"""
    <div class="strava-summary">
        <div class="strava-total-grid">
            <div><span>{len(activities[:10])}</span><p>latest sessions</p></div>
            <div><span>{total_distance_m / 1000:.1f}</span><p>total km</p></div>
            <div><span>{total_seconds / 3600:.1f}</span><p>total hours</p></div>
            <div><span>{total_calories:.0f}</span><p>calories burned</p></div>
        </div>
        <ul class="strava-activity-list">{''.join(rows)}</ul>
    </div>
    """
    return summary, html_block, None


def activity_started_between(activity: dict[str, Any], start_ts: int, end_ts: int) -> bool:
    started = activity.get("start_date_local") or activity.get("start_date")
    if not started:
        return True
    try:
        activity_time = int(time.mktime(time.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return True
    return start_ts <= activity_time < end_ts


def fetch_strava_calories_burned(user_id: int, start_ts: int | None = None, end_ts: int | None = None) -> tuple[int | None, str | None]:
    connection = get_strava_connection(user_id)
    if not connection:
        return None, None

    try:
        connection = refresh_strava_connection(connection)
        query = {"per_page": 10}
        if start_ts is not None:
            query["after"] = start_ts
        if end_ts is not None:
            query["before"] = end_ts
        activities = get_json(f"{STRAVA_API_BASE}/athlete/activities?{urlencode(query)}", connection["access_token"])
        detailed_activities = []
        for activity in activities or []:
            activity_id = activity.get("id")
            if not activity_id:
                detailed_activities.append(activity)
                continue
            try:
                detailed = get_json(
                    f"{STRAVA_API_BASE}/activities/{activity_id}?include_all_efforts=false",
                    connection["access_token"],
                )
            except (HTTPError, URLError, TimeoutError, RuntimeError):
                detailed = {}
            detailed_activities.append({**activity, **(detailed or {})})
        activities = detailed_activities
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return None, f"Could not fetch Strava calories right now: {exc}"

    if start_ts is not None and end_ts is not None:
        activities = [activity for activity in activities or [] if activity_started_between(activity, start_ts, end_ts)]
    total_calories = sum(float(activity.get("calories") or 0) for activity in activities or [])
    return int(total_calories), None
