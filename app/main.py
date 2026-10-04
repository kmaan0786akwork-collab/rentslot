from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service
from .db import get_conn, init_db
from .intervals import Interval

MAX_RENTAL_DAYS = 365
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="RentSlot – Equipment Rental Availability API",
    description="Booking backend that prevents double-booking and suggests the next free slot.",
    version="1.0.0",
    lifespan=lifespan,
)


def to_interval(start: date, end: date) -> Interval:
    if end <= start:
        raise HTTPException(422, "end must be after start (end is the return date)")
    if start < date.today():
        raise HTTPException(422, "start date can't be in the past")
    if (end - start).days > MAX_RENTAL_DAYS:
        raise HTTPException(422, f"rentals are limited to {MAX_RENTAL_DAYS} days")
    return Interval(start, end)


class BookingIn(BaseModel):
    equipment_id: int
    customer_name: str = Field(min_length=2, max_length=80)
    customer_phone: str = Field(pattern=r"^\+?[0-9]{10,13}$")
    start: date
    end: date


@app.exception_handler(service.NotFound)
async def not_found(_, exc: service.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(service.NotAvailable)
async def not_available(_, exc: service.NotAvailable):
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "suggestions": exc.suggestions},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/equipment")
def equipment(conn: sqlite3.Connection = Depends(get_conn)):
    return service.list_equipment(conn)


@app.get("/api/availability")
def availability(
    equipment_id: int,
    start: date,
    end: date,
    suggestions: int = Query(3, ge=1, le=10),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return service.check_availability(conn, equipment_id, to_interval(start, end), suggestions)


@app.post("/api/bookings", status_code=201)
def book(body: BookingIn, conn: sqlite3.Connection = Depends(get_conn)):
    req = to_interval(body.start, body.end)
    return service.create_booking(conn, body.equipment_id, body.customer_name.strip(), body.customer_phone, req)


@app.get("/api/bookings")
def bookings(
    equipment_id: int | None = None,
    include_cancelled: bool = False,
    conn: sqlite3.Connection = Depends(get_conn),
):
    return service.list_bookings(conn, equipment_id, include_cancelled)


@app.get("/api/bookings/{booking_id}")
def booking(booking_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.get_booking(conn, booking_id)


@app.delete("/api/bookings/{booking_id}")
def cancel(booking_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.cancel_booking(conn, booking_id)


@app.get("/api/equipment/{equipment_id}/calendar")
def equipment_calendar(
    equipment_id: int,
    start: date | None = None,
    days: int = Query(60, ge=1, le=366),
    conn: sqlite3.Connection = Depends(get_conn),
):
    s = start or date.today()
    return service.calendar(conn, equipment_id, Interval(s, s + timedelta(days=days)))


# --- frontend ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
