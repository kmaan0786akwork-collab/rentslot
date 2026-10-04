from datetime import date, timedelta

import pytest

from app.intervals import (
    Interval,
    fully_booked_ranges,
    gaps,
    is_free,
    max_concurrent,
    merge,
    next_free_slots,
    overlaps,
)

D0 = date(2030, 1, 1)


def iv(a: int, b: int) -> Interval:
    """Interval from day offsets, e.g. iv(1, 3) = Jan 2 -> Jan 4."""
    return Interval(D0 + timedelta(days=a), D0 + timedelta(days=b))


def d(n: int) -> date:
    return D0 + timedelta(days=n)


def test_invalid_interval_rejected():
    with pytest.raises(ValueError):
        iv(3, 3)
    with pytest.raises(ValueError):
        iv(5, 2)


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (iv(0, 3), iv(2, 5), True),   # partial overlap
        (iv(0, 3), iv(3, 5), False),  # back-to-back: return day = next pickup day
        (iv(0, 10), iv(2, 4), True),  # containment
        (iv(4, 6), iv(0, 2), False),  # disjoint
    ],
)
def test_overlaps(a, b, expected):
    assert overlaps(a, b) is expected
    assert overlaps(b, a) is expected


def test_merge():
    assert merge([iv(5, 8), iv(0, 2), iv(1, 3), iv(3, 4), iv(10, 11)]) == [iv(0, 4), iv(5, 8), iv(10, 11)]
    assert merge([]) == []


def test_is_free_binary_search():
    busy = [iv(0, 3), iv(5, 7), iv(10, 12)]
    assert is_free(busy, iv(3, 5))      # exactly fits the gap
    assert is_free(busy, iv(12, 20))    # after everything
    assert not is_free(busy, iv(2, 4))
    assert not is_free(busy, iv(6, 11))
    assert not is_free(busy, iv(-5, 20))
    assert is_free([], iv(0, 1))


def test_gaps_yields_each_gap_then_open_end():
    busy = [iv(2, 4), iv(5, 7), iv(9, 10)]
    got = list(gaps(busy, d(0), 2))
    # gap [0,2) fits, [4,5) too small, [7,9) fits, then open end from day 10
    assert got == [iv(0, 2), iv(7, 9), iv(10, 12)]


def test_gaps_skips_past_bookings():
    busy = [iv(0, 2), iv(3, 6)]
    assert list(gaps(busy, d(4), 1)) == [iv(6, 7)]


def test_next_free_slots_across_units():
    unit_busy = {
        1: [iv(0, 10)],
        2: [iv(0, 4), iv(6, 20)],
        3: [iv(0, 8)],
    }
    slots = next_free_slots(unit_busy, d(0), 2, k=3)
    # unit 2 has a 2-day gap at day 4, unit 3 frees at 8, unit 1 at 10
    assert [(u, w) for u, w in slots] == [(2, iv(4, 6)), (3, iv(8, 10)), (1, iv(10, 12))]


def test_next_free_slots_dedupes_same_start_date():
    unit_busy = {1: [iv(0, 5)], 2: [iv(0, 5)]}
    starts = [w.start for _, w in next_free_slots(unit_busy, d(0), 1, k=3)]
    assert starts == [d(5)]  # both units free on the same day -> one suggestion


def test_max_concurrent():
    assert max_concurrent([iv(0, 5), iv(1, 3), iv(2, 6), iv(5, 7)]) == 3
    assert max_concurrent([iv(0, 2), iv(2, 4)]) == 1  # back-to-back isn't overlap
    assert max_concurrent([]) == 0


def test_fully_booked_ranges():
    unit_busy = {1: [iv(0, 5), iv(8, 12)], 2: [iv(3, 10)]}
    # both out on [3,5) and [8,10)
    assert fully_booked_ranges(unit_busy, iv(0, 15)) == [iv(3, 5), iv(8, 10)]


def test_fully_booked_clips_to_window_and_handles_handover():
    unit_busy = {1: [iv(0, 5), iv(5, 9)]}
    assert fully_booked_ranges(unit_busy, iv(2, 7)) == [iv(2, 7)]
