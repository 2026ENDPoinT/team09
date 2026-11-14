from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup

from .models import Course, Syllabus
from .parser import normalize_text

TIMETABLE_TIMEZONE = "Asia/Seoul"
_WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")
_CLOCK = r"(?:[01]?[0-9]|2[0-3]):[0-5][0-9]"
_TIME_RANGE = re.compile(rf"({_CLOCK})\s*~\s*({_CLOCK})")
_SYLLABUS_SLOT = re.compile(r"([월화수목금토일])\s*\(([^()]+)\)")


def syllabus_rooms_by_meeting(syllabus: Syllabus, course: Course) -> dict[tuple[str, str], str]:
    """Use a syllabus room only when its day and periods match the roster."""
    expected = {(slot.weekday, "".join(slot.periods.split())) for slot in course.meetings}
    rooms_by_slot: dict[tuple[str, str], set[str]] = {}
    for table in syllabus.tables:
        for row in table:
            for label, value in zip(row, row[1:]):
                if "".join(label.split()) not in ("강의시간/강의실", "수업시간/강의실"):
                    continue
                slots = list(_SYLLABUS_SLOT.finditer(value))
                waiting = []
                for index, slot in enumerate(slots):
                    waiting.append((slot[1], "".join(slot[2].split())))
                    end = slots[index + 1].start() if index + 1 < len(slots) else len(value)
                    _, separator, location = value[slot.end():end].partition("/")
                    if not separator:
                        continue
                    room = normalize_text(location).strip(" ,;·")
                    if room and room != "-":
                        for meeting in waiting:
                            if meeting in expected:
                                rooms_by_slot.setdefault(meeting, set()).add(room)
                    waiting.clear()
    return {slot: next(iter(rooms)) for slot, rooms in rooms_by_slot.items() if len(rooms) == 1}


def syllabus_rooms_by_weekday(syllabus: Syllabus, course: Course) -> dict[str, str]:
    """Use a syllabus room for a clock-time entry only when the whole day agrees."""
    rooms_by_slot = syllabus_rooms_by_meeting(syllabus, course)
    rooms_by_day: dict[str, set[str]] = {}
    unconfirmed = set()
    for meeting in course.meetings:
        weekday = meeting.weekday
        if room := rooms_by_slot.get((weekday, "".join(meeting.periods.split()))):
            rooms_by_day.setdefault(weekday, set()).add(room)
        else:
            unconfirmed.add(weekday)
    return {
        weekday: next(iter(values))
        for weekday, values in rooms_by_day.items() if len(values) == 1 and weekday not in unconfirmed
    }


def parse_course_timetable(html: str, on_date: date, courses: dict[str, Course]) -> dict[str, Any]:
    """Read the e-Class Sunday-to-Saturday grid using its displayed clock times."""
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.select_one(".class_container")
    if grid is None:
        raise RuntimeError("e-Class의 주간 수업시간표를 확인하지 못했습니다.")
    days = grid.select(":scope > .day_wrap")
    if not days and "empty" not in grid.get("class", []):
        raise RuntimeError("e-Class의 주간 수업시간표 구조를 확인하지 못했습니다.")

    week_start = on_date - timedelta(days=(on_date.weekday() + 1) % 7)
    entries = []
    for day in days:
        label = day.select_one(":scope > .day_item")
        weekday = normalize_text(label.get_text(" ", strip=True)).removesuffix("요일") if label else ""
        if weekday not in _WEEKDAYS:
            raise RuntimeError("e-Class 시간표의 수업 요일을 확인하지 못했습니다.")
        session_date = (week_start + timedelta(days=_WEEKDAYS.index(weekday))).isoformat()
        for item in day.select(":scope > .time_wrap > .time_item[kjkey]"):
            course = courses.get(item["kjkey"])
            if course is None:
                continue
            time_label = item.select_one(":scope > .time_info > .lect_time_wrap")
            time_range = _TIME_RANGE.fullmatch(normalize_text(time_label.get_text(" ", strip=True))) if time_label else None
            if time_range is None:
                raise RuntimeError("e-Class 시간표의 수업 시작·종료 시각을 확인하지 못했습니다.")
            room_label = item.select_one(":scope > .time_info > .mobile:not(.lect_time_wrap)")
            room = normalize_text(room_label.get_text(" ", strip=True)) if room_label else ""
            entries.append({
                "course_id": course.id,
                "course_name": course.name,
                **({"professor": course.professor} if course.professor else {}),
                "date": session_date,
                "weekday": weekday,
                "start_time": time_range[1].zfill(5),
                "end_time": time_range[2].zfill(5),
                "room": room if room and room != "-" else None,
            })
    entries.sort(key=lambda item: (item["date"], item["start_time"], item["course_id"]))
    return {
        "on_date": on_date.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "timezone": TIMETABLE_TIMEZONE,
        "entries": entries,
    }
