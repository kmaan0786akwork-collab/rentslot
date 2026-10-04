from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app.main import app

    with TestClient(app) as c:
        yield c


def equipment_id(client, name: str) -> int:
    return next(e["id"] for e in client.get("/api/equipment").json() if e["name"] == name)


def book(client, eq, start, end, name="Test User"):
    return client.post(
        "/api/bookings",
        json={"equipment_id": eq, "customer_name": name, "customer_phone": "9876543210", "start": start, "end": end},
    )


def test_seeded_inventory(client):
    items = client.get("/api/equipment").json()
    assert len(items) == 6
    assert all(i["total_units"] >= 1 for i in items)


def test_book_until_sold_out_then_get_suggestions(client):
    eq = equipment_id(client, "CPAP Machine")  # 2 units

    r1 = book(client, eq, day(1), day(5))
    r2 = book(client, eq, day(2), day(4))
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["serial_no"] != r2.json()["serial_no"]

    r3 = book(client, eq, day(3), day(6))
    assert r3.status_code == 409
    # earliest unit back on day 4 (the 2nd booking returns then)
    assert r3.json()["suggestions"][0] == {"start": day(4), "end": day(7)}


def test_back_to_back_booking_allowed(client):
    eq = equipment_id(client, "BiPAP Machine")  # 1 unit
    assert book(client, eq, day(1), day(3)).status_code == 201
    assert book(client, eq, day(3), day(5)).status_code == 201  # pickup on return day
    assert book(client, eq, day(4), day(6)).status_code == 409


def test_availability_endpoint(client):
    eq = equipment_id(client, "BiPAP Machine")
    book(client, eq, day(1), day(10))

    busy = client.get("/api/availability", params={"equipment_id": eq, "start": day(2), "end": day(4)}).json()
    assert busy["available"] is False
    assert busy["suggestions"][0]["start"] == day(10)

    free = client.get("/api/availability", params={"equipment_id": eq, "start": day(10), "end": day(12)}).json()
    assert free["available"] is True and free["suggestions"] == []
    assert free["estimated_cost"] == 650 * 2


def test_cancel_frees_the_slot(client):
    eq = equipment_id(client, "BiPAP Machine")
    b = book(client, eq, day(1), day(5)).json()
    assert book(client, eq, day(2), day(3)).status_code == 409
    assert client.delete(f"/api/bookings/{b['id']}").json()["status"] == "cancelled"
    assert book(client, eq, day(2), day(3)).status_code == 201


def test_calendar_reports_fully_booked_ranges(client):
    eq = equipment_id(client, "CPAP Machine")  # 2 units
    book(client, eq, day(1), day(5))
    book(client, eq, day(3), day(8))
    cal = client.get(f"/api/equipment/{eq}/calendar", params={"days": 30}).json()
    assert cal["fully_booked"] == [{"start": day(3), "end": day(5)}]
    assert cal["peak_concurrent_bookings"] == 2


@pytest.mark.parametrize(
    "start,end",
    [(day(5), day(5)), (day(5), day(2)), (day(-3), day(2)), (day(1), day(400))],
)
def test_invalid_dates_rejected(client, start, end):
    eq = equipment_id(client, "CPAP Machine")
    assert book(client, eq, start, end).status_code == 422


def test_unknown_equipment_404(client):
    assert book(client, 9999, day(1), day(2)).status_code == 404


def test_database_trigger_blocks_double_booking(client):
    """Even if the app logic were bypassed, SQLite rejects the overlap."""
    import sqlite3
    from app.db import connect

    eq = equipment_id(client, "BiPAP Machine")
    first = book(client, eq, day(1), day(5)).json()
    conn = connect()
    unit_id = conn.execute("SELECT unit_id FROM bookings WHERE id = ?", (first["id"],)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="double booking"):
        conn.execute(
            "INSERT INTO bookings (unit_id, customer_name, customer_phone, start_date, end_date) VALUES (?,?,?,?,?)",
            (unit_id, "Sneaky", "9999999999", day(2), day(3)),
        )
    conn.close()
