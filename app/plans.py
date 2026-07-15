from __future__ import annotations

import sqlite3
import time
from urllib.parse import urlencode

from app.config import TRACKS
from app.db import execute


def user_profile_summary(user: sqlite3.Row) -> str:
    parts = [f"Track: {TRACKS.get(user['category'], TRACKS['aktiv'])['name']}"]
    if user["height"]:
        parts.append(f"Height: {user['height']} cm")
    if user["weight"]:
        parts.append(f"Weight: {user['weight']} kg")
    if user["goal"]:
        parts.append(f"Goal: {user['goal']}")
    return ". ".join(parts)


def weekly_training_plan(user: sqlite3.Row, track_id: str, strava_summary: str | None) -> list[tuple[str, str]]:
    goal = (user["goal"] or "").lower()
    has_strava = bool(strava_summary)

    if track_id == "komma-igang":
        return [
            ("Monday", "10,000 steps at an easy pace. Split it into 2-3 walks if needed."),
            ("Tuesday", "Beginner full-body strength 25-35 min: sit-to-stand, wall push-ups, rows, and core."),
            ("Wednesday", "10,000 steps at an easy pace. Keep it comfortable and steady."),
            ("Thursday", "Gentle mobility and balance 25 min plus simple stretching."),
            ("Friday", "10,000 steps. Add short hills only if it still feels easy."),
            ("Saturday", "Beginner cardio 25-35 min: bike, easy jog/walk intervals, or swimming."),
            ("Sunday", "10,000 steps and a simple meal-prep check for the next week."),
        ]

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
        quality = "High-quality intervals: 8 x 3 min hard with 2 min easy, plus drills and cooldown."
        long_session = "Long endurance session 90-120 min easy with the final 15 min controlled if recovery is good."
    elif strength_bias:
        quality = "Max-strength session: squat or deadlift 6 x 3, explosive jumps, loaded carries, and trunk work."
        long_session = "Aerobic base 60-75 min easy, then mobility for hips, ankles, and T-spine."
    else:
        quality = "Threshold session: 4 x 8 min at controlled hard effort with 3 min easy between."
        long_session = "Long endurance session 90 min easy plus 6 relaxed strides."

    return [
        ("Monday", f"Heavy lower-body strength 70 min: squat/deadlift focus, unilateral work, and core, {intensity_note}."),
        ("Tuesday", quality),
        ("Wednesday", "Active recovery workout: 35-45 min zone 1-2 plus 25 min mobility and prehab."),
        ("Thursday", "Upper-body power and hypertrophy 65 min: pull, press, loaded carries, rear shoulder, hip stability."),
        ("Friday", "Speed and technique: drills, 8-10 short hill sprints or strides, and easy aerobic volume."),
        ("Saturday", long_session),
        ("Sunday", "Recovery session: 30-40 min easy movement, mobility, meal planning, and weekly review."),
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
    normalized_track = track_name.lower()
    if "getting" in normalized_track:
        if sub_id == "start-with-gym":
            return [
                ("Monday", "Easy gym orientation 30-35 min: treadmill walk, leg press, chest press, seated row, and gentle stretching."),
                ("Tuesday", "Active rest exercise: 10,000 steps at an easy pace, split into shorter walks if needed."),
                ("Wednesday", "Beginner gym strength 30 min: leg curl, lat pulldown, shoulder press, bodyweight box squat, and dead bug."),
                ("Thursday", "Active rest exercise: 10,000 steps and 5-10 min relaxed mobility."),
                ("Friday", "Easy gym circuit 30-35 min: bike warm-up, machines for full body, light core, and long rests."),
                ("Saturday", "Active rest exercise: 10,000 steps at a comfortable conversational pace."),
                ("Sunday", "Active rest exercise: 10,000 steps plus simple meal planning for the next week."),
            ]
        if sub_id == "start-without-gym":
            return [
                ("Monday", "Home starter workout 25-30 min: sit-to-stand, wall push-ups, glute bridges, bird dog, and stretching."),
                ("Tuesday", "Active rest exercise: 10,000 steps at an easy pace, broken into short walks if needed."),
                ("Wednesday", "No-equipment strength 25 min: step-ups, incline push-ups, hip hinge practice, side plank, and mobility."),
                ("Thursday", "Active rest exercise: 10,000 steps and 5 min gentle stretching."),
                ("Friday", "Easy home circuit 25-30 min: chair squats, wall push-ups, calf raises, dead bug, and relaxed breathing."),
                ("Saturday", "Active rest exercise: 10,000 steps at a comfortable pace."),
                ("Sunday", "Active rest exercise: 10,000 steps plus a short reflection on energy, sleep, and food choices."),
            ]
        return [
            ("Monday", "Low-impact weight-loss workout 25-30 min: brisk walk warm-up, chair squats, wall push-ups, step-ups, and core."),
            ("Tuesday", "Active rest exercise: 10,000 steps at a comfortable pace and simple hydration focus."),
            ("Wednesday", "Easy cardio 25-35 min: bike, swim, elliptical, or walk intervals with no hard efforts."),
            ("Thursday", "Active rest exercise: 10,000 steps plus 5-10 min stretching."),
            ("Friday", "Gentle strength and mobility 25 min: glute bridges, band or towel rows, dead bug, balance, and hips."),
            ("Saturday", "Active rest exercise: 10,000 steps. Keep the pace easy enough to recover."),
            ("Sunday", "Active rest exercise: 10,000 steps plus meal prep for protein, vegetables, and regular meals."),
        ]

    if "athlete" in normalized_track:
        if sub_id == "strength":
            return [
                ("Monday", "Heavy lower body 75 min: squat or trap-bar deadlift 6 x 3, split squats, hamstrings, calves, and core."),
                ("Tuesday", "Speed and plyometrics 45 min: sprint drills, jumps, bounds, and mobility."),
                ("Wednesday", "Upper-body power 65 min: weighted pull, press, rows, carries, rear shoulder, and trunk rotation."),
                ("Thursday", "Aerobic recovery 45 min zone 2 plus hips, ankles, and T-spine mobility."),
                ("Friday", "Full-body strength 70 min: deadlift or squat variation, Olympic-lift pattern, push, pull, and loaded carries."),
                ("Saturday", "Conditioning finisher: sled pushes, hill sprints, or assault bike intervals plus prehab."),
                ("Sunday", "Recovery workout 35 min easy movement, mobility, and readiness review."),
            ]
        if sub_id == "mixed":
            return [
                ("Monday", "Strength power session 70 min: heavy lower body, jumps, core, and loaded carries."),
                ("Tuesday", "Quality run or bike intervals: 8 x 3 min hard with controlled recovery."),
                ("Wednesday", "Upper-body strength 60 min plus mobility and prehab."),
                ("Thursday", "Tempo cardio 45-60 min with 20-30 min steady hard effort."),
                ("Friday", "Full-body athletic circuit: strength, agility, short sprints, and trunk stability."),
                ("Saturday", "Long aerobic session 90-120 min easy, adjusted by Strava load."),
                ("Sunday", "Recovery workout: easy movement, mobility, soft-tissue work, and weekly review."),
            ]
        return [
            ("Monday", "Aerobic base 60 min zone 2 plus 6 strides and mobility."),
            ("Tuesday", "VO2 intervals: 6-8 x 3 min hard with 2 min easy recovery."),
            ("Wednesday", "Strength for endurance 45 min: calves, hamstrings, hips, single-leg work, and core."),
            ("Thursday", "Threshold session: 3-4 x 8 min controlled hard effort with easy recovery."),
            ("Friday", "Recovery run or bike 40-50 min very easy plus mobility."),
            ("Saturday", "Long endurance session 90-120 min easy, with fueling practice."),
            ("Sunday", "Technique and recovery: drills, 30 min easy, stretching, and Strava review."),
        ]

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
    if sub_id == "start-with-gym":
        return [
            "Easy machine-based workouts that build confidence in the gym.",
            "Enough rest between exercises so the body can handle the routine.",
            "Walking is the active rest exercise on non-gym days.",
        ]
    if sub_id == "start-without-gym":
        return [
            "Simple home and outdoor workouts that are doable without equipment.",
            "Low pressure progression with rest and short sessions.",
            "Walking is used as active recovery so rest days still support the habit.",
        ]
    if sub_id == "lose-weight":
        return [
            "Low-impact workouts that support consistency and weight loss.",
            "Walking on recovery days to increase daily movement without hard training.",
            "Nutrition habits that are simple enough to repeat.",
        ]
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
