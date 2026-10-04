import os
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")

SEED = [
    # name, category, daily_rate, number of units
    ("Oxygen Concentrator 5L", "Respiratory", 450, 3),
    ("Oxygen Concentrator 10L", "Respiratory", 700, 1),
    ("CPAP Machine", "Respiratory", 400, 2),
    ("BiPAP Machine", "Respiratory", 650, 1),
    ("Patient Monitor (5-para)", "Monitoring", 550, 2),
    ("Hospital Bed (Semi-Fowler)", "Furniture", 300, 2),
]


def db_path() -> str:
    return os.environ.get("DB_PATH", "rentslot.db")


def connect() -> sqlite3.Connection:
    # isolation_level=None -> we control transactions ourselves (BEGIN IMMEDIATE)
    conn = sqlite3.connect(db_path(), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA.read_text())
        if conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 0:
            seed(conn)
    finally:
        conn.close()


def seed(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    for name, category, rate, n_units in SEED:
        eq_id = conn.execute(
            "INSERT INTO equipment (name, category, daily_rate) VALUES (?, ?, ?)",
            (name, category, rate),
        ).lastrowid
        prefix = "".join(w[0] for w in name.split() if w[0].isalnum()).upper()
        for i in range(1, n_units + 1):
            conn.execute(
                "INSERT INTO units (equipment_id, serial_no) VALUES (?, ?)",
                (eq_id, f"{prefix}-{eq_id:02d}{i:02d}"),
            )
    conn.execute("COMMIT")


def get_conn():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
