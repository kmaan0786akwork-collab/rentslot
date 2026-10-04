"""
Interval algorithms behind the availability engine.

Every booking is a half-open date interval [start, end): the item goes out on
`start` and comes back on `end`, so a new rental can start on the same day the
previous one is returned.

Nothing here touches the database. It's pure Python, so it's easy to unit-test.
"""
from __future__ import annotations

import heapq
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Iterator


@dataclass(frozen=True, order=True)
class Interval:
    start: date
    end: date  # exclusive

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")

    @property
    def days(self) -> int:
        return (self.end - self.start).days


def overlaps(a: Interval, b: Interval) -> bool:
    """Two half-open intervals overlap iff each one starts before the other ends. O(1)."""
    return a.start < b.end and b.start < a.end


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """Classic merge-intervals: sort by start, then fold. O(n log n).

    Touching intervals ([1,3) and [3,5)) are merged because there's no gap between them.
    """
    out: list[Interval] = []
    for iv in sorted(intervals):
        if out and iv.start <= out[-1].end:
            if iv.end > out[-1].end:
                out[-1] = Interval(out[-1].start, iv.end)
        else:
            out.append(iv)
    return out


def is_free(busy: list[Interval], req: Interval) -> bool:
    """Is `req` free on one unit? O(log n) with binary search.

    `busy` must be sorted and non-overlapping (true for a single unit, because
    we never allow a double booking). In that case ends are sorted too, so only
    the last interval that starts before req.end can possibly overlap.
    """
    i = bisect_left(busy, req.end, key=lambda iv: iv.start)
    return i == 0 or busy[i - 1].end <= req.start


def gaps(busy: list[Interval], from_date: date, duration_days: int) -> Iterator[Interval]:
    """Yield the earliest window of `duration_days` inside each free gap, in date order.

    The last yield is always the open-ended gap after the final booking, so the
    generator never comes back empty. O(log n) to skip past bookings, then O(n).
    """
    span = timedelta(days=duration_days)
    cursor = from_date
    # skip bookings that already ended by from_date
    for b in busy[bisect_right(busy, from_date, key=lambda iv: iv.end):]:
        if b.start - cursor >= span:
            yield Interval(cursor, cursor + span)
        cursor = max(cursor, b.end)
    yield Interval(cursor, cursor + span)


def next_free_slots(
    unit_busy: dict[int, list[Interval]],
    from_date: date,
    duration_days: int,
    k: int = 3,
) -> list[tuple[int, Interval]]:
    """Find the k earliest distinct start dates across ALL units.

    This is a k-way merge with a min-heap: every unit contributes a sorted
    stream of free windows (see `gaps`), and the heap always hands back the
    earliest window among all units.

    Time: O(U log U + k log U) heap work, plus the gap scans. U = number of units.
    """
    heap: list[tuple[date, int, Interval]] = []
    streams: dict[int, Iterator[Interval]] = {}
    for unit_id, busy in unit_busy.items():
        stream = gaps(busy, from_date, duration_days)
        first = next(stream)
        heapq.heappush(heap, (first.start, unit_id, first))
        streams[unit_id] = stream

    results: list[tuple[int, Interval]] = []
    seen_starts: set[date] = set()
    while heap and len(results) < k:
        start, unit_id, window = heapq.heappop(heap)
        if start not in seen_starts:  # customers care about dates, not which unit
            seen_starts.add(start)
            results.append((unit_id, window))
        nxt = next(streams[unit_id], None)
        if nxt is not None:
            heapq.heappush(heap, (nxt.start, unit_id, nxt))
    return results


def max_concurrent(intervals: Iterable[Interval]) -> int:
    """Peak number of overlapping bookings ("Meeting Rooms II").

    Sort by start and keep a min-heap of end dates for the rentals still out.
    The biggest the heap ever gets is the peak demand. O(n log n).
    """
    ends: list[date] = []
    peak = 0
    for iv in sorted(intervals):
        while ends and ends[0] <= iv.start:  # returned before (or on) this start date
            heapq.heappop(ends)
        heapq.heappush(ends, iv.end)
        peak = max(peak, len(ends))
    return peak


def fully_booked_ranges(unit_busy: dict[int, list[Interval]], window: Interval) -> list[Interval]:
    """Date ranges inside `window` when EVERY unit is out. Sweep line, O(n log n).

    Each booking becomes +1 at its start and -1 at its end. Sort the events
    (returns before pickups on the same day, because intervals are half-open)
    and walk through them, tracking how many units are out.
    """
    total_units = len(unit_busy)
    if total_units == 0:
        return [window]

    events: list[tuple[date, int]] = []
    for busy in unit_busy.values():
        for b in busy:
            if overlaps(b, window):
                events.append((max(b.start, window.start), +1))
                events.append((min(b.end, window.end), -1))
    events.sort()  # -1 sorts before +1 on the same date

    out: list[Interval] = []
    out_count = 0
    blocked_since: date | None = None
    for day, delta in events:
        out_count += delta
        if out_count == total_units and blocked_since is None:
            blocked_since = day
        elif out_count < total_units and blocked_since is not None:
            if day > blocked_since:
                out.append(Interval(blocked_since, day))
            blocked_since = None
    return merge(out)
