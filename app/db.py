from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from app.config import DATABASE_URL, DB_PATH

try:
    import psycopg
except ImportError:  # Local SQLite development does not need psycopg installed.
    psycopg = None


USE_POSTGRES = bool(DATABASE_URL)
IntegrityError = sqlite3.IntegrityError
if psycopg is not None:
    IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError)


class Row(dict):
    def __init__(self, columns: Iterable[str], values: Iterable[Any]):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def postgres_url() -> str:
    if DATABASE_URL.startswith("postgres://"):
        return "postgresql://" + DATABASE_URL.removeprefix("postgres://")
    return DATABASE_URL


def sql_for_backend(sql: str) -> str:
    if not USE_POSTGRES:
        return sql
    return sql.replace("?", "%s")


@contextmanager
def connect():
    if USE_POSTGRES:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg is not installed.")
        with psycopg.connect(postgres_url()) as db:
            yield db
    else:
        with sqlite3.connect(DB_PATH) as db:
            db.row_factory = sqlite3.Row
            yield db


def fetch_all(cursor: Any) -> list[Row]:
    rows = cursor.fetchall()
    if not USE_POSTGRES:
        return rows
    columns = [column.name for column in cursor.description]
    return [Row(columns, row) for row in rows]


def fetch_one(cursor: Any) -> Row | sqlite3.Row | None:
    row = cursor.fetchone()
    if row is None or not USE_POSTGRES:
        return row
    columns = [column.name for column in cursor.description]
    return Row(columns, row)


def ensure_db() -> None:
    if USE_POSTGRES:
        ensure_postgres_db()
    else:
        ensure_sqlite_db()


def ensure_sqlite_db() -> None:
    with connect() as db:
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


def ensure_postgres_db() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR UNIQUE,
            email VARCHAR UNIQUE,
            password VARCHAR,
            category VARCHAR,
            height DOUBLE PRECISION,
            weight DOUBLE PRECISION,
            goal VARCHAR,
            csrf_token VARCHAR
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS strava_connections (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            athlete_id BIGINT,
            athlete_name VARCHAR,
            scope VARCHAR,
            access_token VARCHAR,
            refresh_token VARCHAR,
            expires_at INTEGER,
            updated_at INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS training_plan_items (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            day_index INTEGER,
            day_name VARCHAR,
            session TEXT,
            is_done INTEGER DEFAULT 0,
            comment TEXT,
            updated_at INTEGER,
            UNIQUE(user_id, day_index)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subcategory_plan_items (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            track_id VARCHAR,
            subcategory_id VARCHAR,
            day_index INTEGER,
            day_name VARCHAR,
            session TEXT,
            is_done INTEGER DEFAULT 0,
            comment TEXT,
            updated_at INTEGER,
            UNIQUE(user_id, track_id, subcategory_id, day_index)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS training_archive (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            source VARCHAR,
            track_id VARCHAR,
            subcategory_id VARCHAR,
            day_name VARCHAR,
            session TEXT,
            comment TEXT,
            completed_at INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS saved_recipes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            track_id VARCHAR,
            title VARCHAR,
            reason TEXT,
            url TEXT,
            saved_at INTEGER,
            UNIQUE(user_id, url)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weight_entries (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            weight DOUBLE PRECISION,
            recorded_at INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS calorie_entries (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            label TEXT,
            calories INTEGER,
            logged_at INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token VARCHAR PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            csrf_token VARCHAR,
            strava_state VARCHAR,
            created_at INTEGER,
            expires_at INTEGER
        )
        """,
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS csrf_token VARCHAR",
    ]
    with connect() as db:
        for statement in statements:
            db.execute(statement)
        cursor = db.execute("SELECT id FROM users WHERE csrf_token IS NULL OR csrf_token = ''")
        columns = [column.name for column in cursor.description]
        rows = [Row(columns, row) for row in cursor.fetchall()]
        for row in rows:
            db.execute(
                sql_for_backend("UPDATE users SET csrf_token = ? WHERE id = ?"),
                (secrets.token_urlsafe(32), row["id"]),
            )


def query_one(sql: str, params: tuple = ()) -> Row | sqlite3.Row | None:
    with connect() as db:
        cursor = db.execute(sql_for_backend(sql), params)
        return fetch_one(cursor)


def query_all(sql: str, params: tuple = ()) -> list[Row | sqlite3.Row]:
    with connect() as db:
        cursor = db.execute(sql_for_backend(sql), params)
        return fetch_all(cursor)


def execute(sql: str, params: tuple = ()) -> None:
    with connect() as db:
        db.execute(sql_for_backend(sql), params)


def insert_and_get_id(sql: str, params: tuple = ()) -> int:
    with connect() as db:
        if USE_POSTGRES:
            cursor = db.execute(sql_for_backend(sql.rstrip()) + " RETURNING id", params)
            row = cursor.fetchone()
            return int(row[0])
        cursor = db.execute(sql, params)
        return int(cursor.lastrowid)
