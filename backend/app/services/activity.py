"""Real, derived activity signals for the dashboard -- no fabricated placeholders.

There is no session-duration tracking anywhere in this app (every activity table
has only a point-in-time timestamp, never a start/end pair), so "hours spent" is
not a number that can be told honestly today. What IS real: which calendar days
had at least one timestamped activity row. This builds that calendar instead of
a fabricated hours figure.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import CommunicationSession, InterviewSession, SpeechSession, TopicProgress, VaultEntry

_SOURCES = [
    (TopicProgress, "completed_at"),
    (CommunicationSession, "created_at"),
    (InterviewSession, "created_at"),
    (SpeechSession, "created_at"),
    (VaultEntry, "created_at"),
]


def _activity_dates(db: Session, model, ts_field: str, user_id: int, since: datetime) -> list[date]:
    col = getattr(model, ts_field)
    rows = db.query(col).filter(model.user_id == user_id, col.isnot(None), col >= since).all()
    return [dt.date() if hasattr(dt, "date") else dt for (dt,) in rows if dt is not None]


def _level(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 2:
        return 2
    if count <= 4:
        return 3
    return 4


def activity_calendar(db: Session, user_id: int, window_days: int = 31) -> dict:
    today = date.today()
    start = today - timedelta(days=window_days - 1)
    since = datetime.combine(start, datetime.min.time())

    counts: dict[date, int] = defaultdict(int)
    for model, field in _SOURCES:
        for d in _activity_dates(db, model, field, user_id, since):
            if start <= d <= today:
                counts[d] += 1

    cells = []
    d = start
    while d <= today:
        cells.append({"date": d.isoformat(), "level": _level(counts.get(d, 0))})
        d += timedelta(days=1)

    this_week_start = today - timedelta(days=6)
    last_week_start = today - timedelta(days=13)
    active_days = sum(1 for c in cells if c["level"] > 0)
    active_this_week = sum(
        1 for c in cells if c["level"] > 0 and date.fromisoformat(c["date"]) >= this_week_start
    )
    active_last_week = sum(
        1
        for c in cells
        if c["level"] > 0 and last_week_start <= date.fromisoformat(c["date"]) < this_week_start
    )

    return {
        "cells": cells,
        "range_start": start.isoformat(),
        "range_end": today.isoformat(),
        "active_days": active_days,
        "active_this_week": active_this_week,
        "active_last_week": active_last_week,
    }
