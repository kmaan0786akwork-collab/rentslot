PRAGMA foreign_keys = ON;

-- An equipment type, e.g. "Oxygen Concentrator 5L"
CREATE TABLE IF NOT EXISTS equipment (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL,
    daily_rate  INTEGER NOT NULL CHECK (daily_rate >= 0)   -- rupees per day
);

-- Physical units in inventory. A type can have many units.
CREATE TABLE IF NOT EXISTS units (
    id            INTEGER PRIMARY KEY,
    equipment_id  INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    serial_no     TEXT    NOT NULL UNIQUE,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- Bookings use half-open ranges: [start_date, end_date)
-- Dates are ISO strings (YYYY-MM-DD), so string comparison = date comparison.
CREATE TABLE IF NOT EXISTS bookings (
    id              INTEGER PRIMARY KEY,
    unit_id         INTEGER NOT NULL REFERENCES units(id),
    customer_name   TEXT    NOT NULL,
    customer_phone  TEXT    NOT NULL,
    start_date      TEXT    NOT NULL,
    end_date        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'confirmed'
                            CHECK (status IN ('confirmed', 'cancelled')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (end_date > start_date)
);

CREATE INDEX IF NOT EXISTS idx_units_equipment ON units(equipment_id);
CREATE INDEX IF NOT EXISTS idx_bookings_unit_dates
    ON bookings(unit_id, start_date, end_date) WHERE status = 'confirmed';

-- Last line of defence: the database itself refuses an overlapping booking,
-- even if application code has a bug.
CREATE TRIGGER IF NOT EXISTS prevent_double_booking
BEFORE INSERT ON bookings
WHEN NEW.status = 'confirmed'
BEGIN
    SELECT RAISE(ABORT, 'double booking: unit already booked for these dates')
    WHERE EXISTS (
        SELECT 1 FROM bookings
        WHERE unit_id = NEW.unit_id
          AND status = 'confirmed'
          AND start_date < NEW.end_date
          AND NEW.start_date < end_date
    );
END;
