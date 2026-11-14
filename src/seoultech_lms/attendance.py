from __future__ import annotations

from bs4 import BeautifulSoup

from .models import CourseAttendance

_STATUS = {
    "출석": "present", "지각": "late", "결석": "absent", "조퇴": "early_leave",
    "공결": "excused", "출석인정": "excused", "인정출석": "excused",
}


def parse_attendance(html: str) -> CourseAttendance | None:
    """Summarize the student attendance badges in the course's lesson list."""
    soup = BeautifulSoup(html, "html.parser")
    lessons = soup.select(".attendance_list .attendance_week_time_list > li > .attend_menu")
    if not lessons:
        return None

    counts = dict.fromkeys(_STATUS.values(), 0)
    unconfirmed = 0
    for lesson in lessons:
        if "ready" in lesson.get("class", []):
            continue
        badges = lesson.select(".attendance_week_time.stu .attend_stats_list > .attend_stats")
        statuses = set()
        for badge in badges:
            label = badge.select_one(".attend_dv_icon_title")
            status = label.get_text("", strip=True) if label else str(badge.get("title", ""))
            statuses.add(_STATUS.get("".join(status.split())))
        if len(statuses) == 1 and None not in statuses:
            counts[statuses.pop()] += 1
        else:
            unconfirmed += 1
    return CourseAttendance(**counts, unconfirmed=unconfirmed)
