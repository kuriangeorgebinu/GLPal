"""SQLite storage. One local file (glpal.db); nothing leaves the machine except AI calls."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT DEFAULT '',
    medication TEXT DEFAULT 'wegovy',
    current_dose_mg REAL DEFAULT 0.25,
    dose_weekday INTEGER DEFAULT 0,          -- 0 = Monday
    start_weight_kg REAL,
    goal_weight_kg REAL,
    protein_target_g REAL DEFAULT 100,
    water_target_ml REAL DEFAULT 2000
);
CREATE TABLE IF NOT EXISTS doses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL, medication TEXT NOT NULL, dose_mg REAL NOT NULL,
    site TEXT DEFAULT '', notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS symptoms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL, symptom TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 5), notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eaten_at TEXT NOT NULL, description TEXT NOT NULL,
    protein_g REAL DEFAULT 0, calories REAL DEFAULT 0,
    high_fat INTEGER DEFAULT 0, source TEXT DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT, measured_at TEXT NOT NULL, weight_kg REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS water (
    id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, ml REAL NOT NULL
);
INSERT OR IGNORE INTO profile (id) VALUES (1);
"""

TABLES = {
    "doses": ("taken_at", ["taken_at", "medication", "dose_mg", "site", "notes"]),
    "symptoms": ("logged_at", ["logged_at", "symptom", "severity", "notes"]),
    "meals": ("eaten_at", ["eaten_at", "description", "protein_g", "calories", "high_fat", "source"]),
    "weights": ("measured_at", ["measured_at", "weight_kg"]),
    "water": ("logged_at", ["logged_at", "ml"]),
}
PROFILE_FIELDS = ["name", "medication", "current_dose_mg", "dose_weekday", "start_weight_kg",
                  "goal_weight_kg", "protein_target_g", "water_target_ml"]


@contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def get_profile() -> dict:
    with connect() as con:
        return dict(con.execute("SELECT * FROM profile WHERE id = 1").fetchone())


def update_profile(changes: dict) -> dict:
    changes = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}
    if changes:
        cols = ", ".join(f"{k} = ?" for k in changes)
        with connect() as con:
            con.execute(f"UPDATE profile SET {cols} WHERE id = 1", list(changes.values()))
    return get_profile()


def add(table: str, row: dict) -> dict:
    time_col, cols = TABLES[table]
    row = {k: row.get(k) for k in cols if row.get(k) is not None}
    row.setdefault(time_col, now_iso())
    with connect() as con:
        cur = con.execute(
            f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            list(row.values()))
        return dict(con.execute(f"SELECT * FROM {table} WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_rows(table: str, since: str | None = None, limit: int = 500) -> list[dict]:
    time_col, _ = TABLES[table]
    sql, args = f"SELECT * FROM {table}", []
    if since:
        sql, args = sql + f" WHERE {time_col} >= ?", [since]
    sql += f" ORDER BY {time_col} DESC LIMIT ?"
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args + [limit]).fetchall()]


def delete(table: str, row_id: int) -> bool:
    if table not in TABLES:
        return False
    with connect() as con:
        return con.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,)).rowcount > 0
