from __future__ import annotations

import unittest
from datetime import date

from seoultech_lms.models import Course, CourseMeeting, Syllabus
from seoultech_lms.timetable import parse_course_timetable, syllabus_rooms_by_weekday


COURSE_ID = "A2024212345601001"
COURSES = {COURSE_ID: Course(COURSE_ID, "예시 강좌", professor="예시 교수")}
WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")


def time_item(course_id: str, start: str, end: str, room: str) -> str:
    return f"""
        <div class="time_item" kjkey="{course_id}">
          <div class="time_info">
            <span class="mobile lect_time_wrap"><span>{start}~</span> <span>{end}</span></span>
            <span class="mobile">{room}</span>
          </div>
          <div class="time_hover">
            <div class="time_info">
              <span class="lect_time_wrap">20:00~21:00</span>
              <span class="mobile">툴팁 강의실</span>
            </div>
          </div>
        </div>
    """


def timetable_grid(slots_by_day: dict[str, str]) -> str:
    days = [
        f"""
        <div class="day_wrap">
          <div class="day_item">{weekday}</div>
          <div class="time_wrap">{slots_by_day.get(weekday, "")}</div>
        </div>
        """
        for weekday in WEEKDAYS
    ]
    return '<div class="class_container">' + "".join(days) + "</div>"


class CourseTimetableTests(unittest.TestCase):
    def test_week_maps_sunday_through_saturday_across_year_boundary(self) -> None:
        html = timetable_grid({
            "일": time_item(COURSE_ID, "09:00", "13:00", "예시관 101"),
            "월": time_item(f"{COURSE_ID}0", "10:00", "11:00", "다른 강의실"),
            "토": time_item(COURSE_ID, "15:00", "16:00", "-"),
        })
        result = parse_course_timetable(html, date(2025, 1, 1), COURSES)
        self.assertEqual(result["week_start"], "2024-12-29")
        self.assertEqual(result["week_end"], "2025-01-04")
        self.assertEqual(result["on_date"], "2025-01-01")
        self.assertEqual(result["timezone"], "Asia/Seoul")
        self.assertEqual(result["entries"], [
            {
                "course_id": COURSE_ID, "course_name": "예시 강좌", "professor": "예시 교수",
                "date": "2024-12-29", "weekday": "일",
                "start_time": "09:00", "end_time": "13:00", "room": "예시관 101",
            },
            {
                "course_id": COURSE_ID, "course_name": "예시 강좌", "professor": "예시 교수",
                "date": "2025-01-04", "weekday": "토",
                "start_time": "15:00", "end_time": "16:00", "room": None,
            },
        ])

    def test_recognized_empty_week_has_no_entries(self) -> None:
        for html in (
            timetable_grid({}),
            '<div class="class_container empty"><div>표시할 시간표가 없습니다.</div></div>',
        ):
            with self.subTest(html=html[:45]):
                result = parse_course_timetable(html, date(2025, 1, 4), COURSES)
                self.assertEqual(result["week_start"], "2024-12-29")
                self.assertEqual(result["week_end"], "2025-01-04")
                self.assertEqual(result["entries"], [])

    def test_non_timetable_response_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_course_timetable("<html><main>로그인 화면</main></html>", date(2025, 1, 1), COURSES)

    def test_syllabus_only_fills_rooms_for_matching_unambiguous_days(self) -> None:
        course = Course(COURSE_ID, "예시 강좌", meetings=(
            CourseMeeting("월", "1 ~ 2"), CourseMeeting("화", "3"), CourseMeeting("화", "5"),
            CourseMeeting("목", "7"),
        ))
        syllabus = Syllabus(COURSE_ID, course.name, "", [[[
            "강의시간/강의실",
            "월(1~2) / 예시관-101, 화(3) / 예시관-102, 화(5) / 예시관-103, 목(8) / 예시관-104",
        ]]])
        self.assertEqual(syllabus_rooms_by_weekday(syllabus, course), {"월": "예시관-101"})
