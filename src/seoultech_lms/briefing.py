from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import Assignment, Course, Notice

_SEOUL = ZoneInfo("Asia/Seoul")


def _in_seoul(value: datetime) -> datetime:
    # The e-Class dates without an offset are displayed in Korean local time.
    return value.replace(tzinfo=_SEOUL) if value.tzinfo is None else value.astimezone(_SEOUL)


def _iso(value: datetime | None) -> str | None:
    return _in_seoul(value).isoformat() if value is not None else None


def build_course_briefing(
    courses: list[Course],
    assignments: list[Assignment],
    notices: list[Notice],
    unavailable: list[str],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    as_of = _in_seoul(now) if now is not None else datetime.now(_SEOUL)
    course_names = {course.id: course.name for course in courses}
    pending = [item for item in assignments if item.submitted is not True]
    pending.sort(key=lambda item: (item.due_at is None, _iso(item.due_at) or "", item.title))
    completed = [
        item for item in assignments
        if item.submitted is True and item.submitted_at is not None
        and as_of - timedelta(days=2) <= _in_seoul(item.submitted_at) <= as_of
    ]
    completed.sort(key=lambda item: _iso(item.submitted_at) or "", reverse=True)
    today = as_of.date()
    recent = [
        item for item in notices
        if item.created_at is not None and 0 <= (today - _in_seoul(item.created_at).date()).days < 7
    ]
    recent.sort(key=lambda item: _iso(item.created_at) or "", reverse=True)

    def assignment_summary(item: Assignment) -> dict[str, Any]:
        return {
            "id": item.id,
            "course_id": item.course_id,
            "course_name": course_names[item.course_id],
            "url": item.url,
            "title": item.title,
            "due_at": _iso(item.due_at),
            "submitted": item.submitted,
        }

    result = {
        "as_of": as_of.isoformat(),
        "pending_assignments": [assignment_summary(item) for item in pending],
        "completed_assignments": [
            {**assignment_summary(item), "submitted_at": _iso(item.submitted_at)}
            for item in completed
        ],
        "recent_notices": [
            {
                "id": item.id,
                "course_id": item.course_id,
                "course_name": course_names[item.course_id],
                "title": item.title,
                "created_at": _iso(item.created_at),
                "content": item.content,
                "url": item.url,
            }
            for item in recent
        ],
    }
    if unavailable:
        result["unavailable"] = unavailable
    return result
