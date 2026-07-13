from __future__ import annotations

import sqlite3
import time
from urllib.parse import urlencode

from app.config import TRACKS
from app.db import execute


def user_profile_summary(user: sqlite3.Row) -> str:
    parts = [f"Track: {TRACKS.get(user['category'], TRACKS['aktiv'])['name']}"]
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


def rotate_plan(plan: list[tuple[str, str]], seed: int) -> list[tuple[str, str]]:
    variants = [
        "AI-adjusted focus: keep quality high but stop if you feel unusually heavy.",
        "New variation: put extra emphasis on technique and even load.",
        "AI-generated variation: prioritize recovery between hard elements.",
        "Updated type: note heart rate, energy, and a comment after the session.",
    ]
    return [(day, f"{session} {variants[(index + seed) % len(variants)]}") for index, (day, session) in enumerate(plan)]


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
