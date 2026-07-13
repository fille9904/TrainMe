from __future__ import annotations

import secrets
import sqlite3

from app.config import DB_PATH


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
            CREATE TABLE IF NOT EXISTS calorie_entries (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                label TEXT,
                calories INTEGER,
                logged_at INTEGER,
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


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(sql, params)
