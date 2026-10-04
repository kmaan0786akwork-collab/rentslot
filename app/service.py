"""Business logic: glue between SQL and the interval algorithms."""
from __future__ import annotations

import sqlite3
from datetime import date

from .intervals import Interval, fully_booked_ranges, is_free, max_concurrent, next_free_slots


class NotFound(Exception):
    pass


class NotAvailable(Exception):
    def __init__(self, suggestions: list[dict]):
        super().__init__("No unit is free for those dates")
        self.suggestions = suggestions


def get_equipment(conn: sqlite3.Connection, equipment_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    if row is None:
        raise NotFound(f"Equipment {equipment_id} not found")
    return row


def list_equipment(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.id, e.name, e.category, e.daily_rate,
               COUNT(u.id) AS total_units
        FROM equipment e
        LEFT JOIN units u ON u.equipment_id = e.id AND u.is_active = 1
        GROUP BY e.id
        ORDER BY e.category, e.name
        """
    ).fetchall()
    return [dict(r) for r in rows]


def load_unit_busy(conn: sqlite3.Connection, equipment_id: int) -> dict[int, list[Interval]]:
    """Each active unit -> its confirmed bookings, sorted by start date.

    ORDER BY in SQL does the sorting, so each list is ready for binary search.
    Units with no bookings are included (with an empty list).
    """
    rows = conn.execute(
        """
        SELECT u.id AS unit_id, b.start_date, b.end_date
        FROM units u
        LEFT JOIN bookings b ON b.unit_id = u.id AND b.status = 'confirmed'
        WHERE u.equipment_id = ? AND u.is_active = 1
        ORDER BY u.id, b.start_date
        """,
        (equipment_id,),
    ).fetchall()
    busy: dict[int, list[Interval]] = {}
    for r in rows:
        lst = busy.setdefault(r["unit_id"], [])
        if r["start_date"] is not None:
            lst.append(Interval(date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])))
    return busy


def _suggest(unit_busy: dict[int, list[Interval]], req: Interval, k: int) -> list[dict]:
    return [
        {"start": w.start.isoformat(), "end": w.end.isoformat()}
        for _, w in next_free_slots(unit_busy, req.start, req.days, k)
    ]


def _best_fit_unit(unit_busy: dict[int, list[Interval]], req: Interval) -> int | None:
    """Pick the free unit whose previous booking ended closest to req.start.

    Packing bookings tightly onto the same units keeps other units' calendars
    wide open for long rentals (less fragmentation).
    """
    best_unit, best_gap = None, None
    for unit_id, busy in unit_busy.items():
        if not is_free(busy, req):
            continue
        prev_ends = [b.end for b in busy if b.end <= req.start]
        gap = (req.start - max(prev_ends)).days if prev_ends else 10**9
        if best_gap is None or gap < best_gap:
            best_unit, best_gap = unit_id, gap
    return best_unit


def check_availability(conn: sqlite3.Connection, equipment_id: int, req: Interval, k: int = 3) -> dict:
    eq = get_equipment(conn, equipment_id)
    unit_busy = load_unit_busy(conn, equipment_id)
    free_units = [u for u, busy in unit_busy.items() if is_free(busy, req)]
    return {
        "equipment_id": eq["id"],
        "equipment": eq["name"],
        "start": req.start.isoformat(),
        "end": req.end.isoformat(),
        "days": req.days,
        "total_units": len(unit_busy),
        "free_units": len(free_units),
        "available": bool(free_units),
        "estimated_cost": eq["daily_rate"] * req.days,
        "suggestions": [] if free_units else _suggest(unit_busy, req, k),
    }


def create_booking(
    conn: sqlite3.Connection, equipment_id: int, name: str, phone: str, req: Interval
) -> dict:
    eq = get_equipment(conn, equipment_id)
    # BEGIN IMMEDIATE takes the write lock *before* we read availability,
    # so two requests can't both see the unit as free and both book it.
    conn.execute("BEGIN IMMEDIATE")
    try:
        unit_busy = load_unit_busy(conn, equipment_id)
        unit_id = _best_fit_unit(unit_busy, req)
        if unit_id is None:
            conn.execute("ROLLBACK")
            raise NotAvailable(_suggest(unit_busy, req, 3))
        booking_id = conn.execute(
            """INSERT INTO bookings (unit_id, customer_name, customer_phone, start_date, end_date)
               VALUES (?, ?, ?, ?, ?)""",
            (unit_id, name, phone, req.start.isoformat(), req.end.isoformat()),
        ).lastrowid
        conn.execute("COMMIT")
    except NotAvailable:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    booking = get_booking(conn, booking_id)
    booking["total_cost"] = eq["daily_rate"] * req.days
    return booking


def get_booking(conn: sqlite3.Connection, booking_id: int) -> dict:
    row = conn.execute(
        """
        SELECT b.id, b.customer_name, b.customer_phone, b.start_date, b.end_date, b.status,
               b.created_at, u.serial_no, e.id AS equipment_id, e.name AS equipment
        FROM bookings b
        JOIN units u ON u.id = b.unit_id
        JOIN equipment e ON e.id = u.equipment_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"Booking {booking_id} not found")
    return dict(row)


def list_bookings(conn: sqlite3.Connection, equipment_id: int | None, include_cancelled: bool) -> list[dict]:
    sql = """
        SELECT b.id, b.customer_name, b.start_date, b.end_date, b.status,
               u.serial_no, e.id AS equipment_id, e.name AS equipment
        FROM bookings b
        JOIN units u ON u.id = b.unit_id
        JOIN equipment e ON e.id = u.equipment_id
        WHERE (? IS NULL OR e.id = ?)
          AND (? OR b.status = 'confirmed')
        ORDER BY b.start_date, b.id
    """
    rows = conn.execute(sql, (equipment_id, equipment_id, include_cancelled)).fetchall()
    return [dict(r) for r in rows]


def cancel_booking(conn: sqlite3.Connection, booking_id: int) -> dict:
    get_booking(conn, booking_id)  # raises NotFound
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    return get_booking(conn, booking_id)


def calendar(conn: sqlite3.Connection, equipment_id: int, window: Interval) -> dict:
    eq = get_equipment(conn, equipment_id)
    unit_busy = load_unit_busy(conn, equipment_id)
    in_window = [b for busy in unit_busy.values() for b in busy if b.start < window.end and window.start < b.end]
    return {
        "equipment_id": eq["id"],
        "equipment": eq["name"],
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "total_units": len(unit_busy),
        "peak_concurrent_bookings": max_concurrent(in_window),
        "fully_booked": [
            {"start": r.start.isoformat(), "end": r.end.isoformat()}
            for r in fully_booked_ranges(unit_busy, window)
        ],
    }
