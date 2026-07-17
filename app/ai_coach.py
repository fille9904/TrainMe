from __future__ import annotations

import json
import os
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import TRACKS


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_COACH_MODEL = os.environ.get("OPENAI_COACH_MODEL", "gpt-5.6-luna")
MAX_QUESTION_LENGTH = 2000


def openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def response_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text.strip()

    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return " ".join(chunks).strip()


def fallback_coach_reply(user: sqlite3.Row, question: str, strava_summary: str | None) -> str:
    goal = user["goal"] or "your goal"
    lower_question = question.lower()
    metric_question = any(
        word in lower_question
        for word in ["tempo", "pace", "speed", "kcal", "calorie", "calories", "burned", "strava"]
    )
    if metric_question and strava_summary:
        return (
            "I can use your Strava tempo and kcal data as training-load signals. "
            f"Here is what I see: {strava_summary} "
            "Keep demanding workouts separated by recovery or easy movement, and reduce the next session if fatigue is unusually high."
        )

    data_hint = (
        "Your Strava tempo, distance, duration, and kcal data are included in this guidance."
        if strava_summary
        else "Connect Strava so I can account for your recent training history."
    )
    return (
        f"Based on your goal, '{goal}', prioritize a manageable quality session, enough recovery, "
        f"and a short check-in after training. {data_hint}"
    )


def generate_coach_reply(user: sqlite3.Row, question: str, strava_summary: str | None) -> str:
    clean_question = question.strip()
    if not clean_question:
        return "Write a question about your weekly plan, recovery, nutrition, or Strava data."
    clean_question = clean_question[:MAX_QUESTION_LENGTH]

    api_key = openai_api_key()
    if not api_key:
        return fallback_coach_reply(user, clean_question, strava_summary)

    track_id = user["category"] or "aktiv"
    track_name = TRACKS.get(track_id, TRACKS["aktiv"])["name"]
    profile = (
        f"Track: {track_name}. Goal: {user['goal'] or 'not provided'}. "
        f"Height: {user['height'] or 'not provided'} cm. Weight: {user['weight'] or 'not provided'} kg."
    )
    activity_context = strava_summary or "Strava is not connected, so no activity data is available."
    instructions = (
        "You are TrainMe's supportive training coach. Give concise, practical guidance tailored to the user's level. "
        "Use the supplied Strava data when relevant, including pace, speed, duration, distance, and kcal burned. "
        "Do not invent activity data. Avoid diagnosis and state when pain, illness, or eating-disorder concerns require a qualified professional."
    )
    body = {
        "model": OPENAI_COACH_MODEL,
        "instructions": instructions,
        "input": f"User profile: {profile}\nRecent activity context: {activity_context}\nQuestion: {clean_question}",
        "max_output_tokens": 500,
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        answer = response_output_text(payload)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return fallback_coach_reply(user, clean_question, strava_summary)

    return answer or fallback_coach_reply(user, clean_question, strava_summary)
