from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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
