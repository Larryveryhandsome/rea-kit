"""Ephemeral seven-calendar-day selection; discovery is NOT publication time."""
import datetime


def select_recent(listings, *, today):
    start = today - datetime.timedelta(days=6)
    selected, excluded = [], []
    for raw in listings:
        row = dict(raw)
        try:
            published = datetime.date.fromisoformat(str(row.get("listed_at", ""))[:10])
        except ValueError:
            excluded.append({"id": row.get("id"), "reason": "publication date unknown"})
            continue
        if row.get("online") is False or not start <= published <= today:
            excluded.append({"id": row.get("id"), "reason": "offline or outside seven-day window"})
        else:
            selected.append(row)
    return {"listings": selected, "excluded": excluded}
