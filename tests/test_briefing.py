from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import patch

import httpx

from seoultech_lms.briefing import build_course_briefing
from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import ACTIVITY_LIST, ENTER_COURSE, MAIN_FORM, NOTICE_LIST, NOTICE_VIEW, REPORT_VIEW
from seoultech_lms.models import Assignment, Course, Notice
from seoultech_lms.parser import enrich_assignment

_NOW = datetime(2026, 11, 12, 12, 30, tzinfo=timezone(timedelta(hours=9)))
_COURSE_ID = "A20260001"


class CourseBriefingTests(unittest.TestCase):
    def test_windows_use_real_submission_timestamp_and_seoul_calendar(self) -> None:
        assignments = [
            Assignment("recent", _COURSE_ID, "최근 제출", due_at=_NOW - timedelta(days=4),
                       submitted=True, submitted_at=(_NOW - timedelta(days=2)).astimezone(timezone.utc)),
            Assignment("old", _COURSE_ID, "예전 제출", due_at=_NOW,
                       submitted=True, submitted_at=_NOW - timedelta(days=2, seconds=1)),
            Assignment("future", _COURSE_ID, "미래 제출", submitted=True, submitted_at=_NOW + timedelta(seconds=1)),
            Assignment("no-date", _COURSE_ID, "제출일 미확인", due_at=_NOW, submitted=True),
            Assignment("unknown", _COURSE_ID, "미확인 과제"),
            Assignment("late", _COURSE_ID, "마감 지난 과제", due_at=datetime(2026, 11, 10, 9), submitted=False),
        ]
        notices = [
            Notice("boundary", _COURSE_ID, "7번째 날", created_at=datetime(2026, 11, 6, 0)),
            Notice("too-old", _COURSE_ID, "8번째 날", created_at=datetime(2026, 11, 5, 23, 59)),
            Notice("today", _COURSE_ID, "오늘", created_at=datetime(2026, 11, 12, 0)),
            Notice("future", _COURSE_ID, "내일", created_at=datetime(2026, 11, 13, 0)),
        ]
        result = build_course_briefing([Course(_COURSE_ID, "예시 수업")], assignments, notices, [], now=_NOW)
        self.assertEqual([item["id"] for item in result["pending_assignments"]], ["late", "unknown"])
        self.assertEqual([item["id"] for item in result["completed_assignments"]], ["recent"])
        self.assertEqual(result["completed_assignments"][0]["submitted_at"], "2026-11-10T12:30:00+09:00")
        self.assertEqual(result["pending_assignments"][0]["due_at"], "2026-11-10T09:00:00+09:00")
        self.assertEqual([item["id"] for item in result["recent_notices"]], ["today", "boundary"])

    def test_submission_metadata_does_not_take_deadline_or_student_body(self) -> None:
        detail = """
        <table><tr><td>마감일</td><td>2026.11.20 (금) 오후 11:59</td></tr></table>
        <div id="submit_form">
          <div class="inner_title_box">
            <div class="submit_info_box"><div class="txt">정상제출</div>
              <div class="date">2026.11.10 (화) 오후 2:00</div>
              <div class="date">2026.11.11 (수) 오후 2:00</div></div>
          </div>
          <div class="editor_content">제출된 내역이 없습니다. 2026.11.12 (목) 오후 2:00</div>
        </div>
        """
        item = enrich_assignment(detail, Assignment("1", _COURSE_ID, "예시 과제", submitted=False))
        self.assertTrue(item.submitted)
        self.assertEqual(item.submitted_at, datetime(2026, 11, 11, 14))
        self.assertEqual(item.due_at, datetime(2026, 11, 20, 23, 59))
        self.assertIsNone(item.description)
        unknown = enrich_assignment(
            '<div id="submit_form"><div class="editor_content">제출된 내역이 없습니다.</div></div>',
            Assignment("2", _COURSE_ID, "제출 여부 확인 필요"),
        )
        self.assertIsNone(unknown.submitted)


class CourseBriefingClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_index_uses_lists_and_only_changed_assignment_needs_a_detail(self) -> None:
        calls = []
        day_label = "D-3"
        deadline = "2026.11.20 (금) 오후 11:59"

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append((request.method, path))
            if path == MAIN_FORM:
                return httpx.Response(200, text=f"""
                <a class="logout" href="/ilos/lo/logout.acl"></a>
                <div class="my_lecture_container"><a id="kj_1" onclick="eclassRoom('{_COURSE_ID}')">예시 수업</a></div>
                """)
            if path == ENTER_COURSE:
                return httpx.Response(200, json={"isError": False})
            if path == ACTIVITY_LIST:
                return httpx.Response(200, text=f"""
                <a class="activity not_submit" id="class_menu_report_10">
                  <span class="activity_title">미제출 과제</span>
                  <span class="activity_info_dday"><b>{day_label}</b> {deadline}</span>
                </a>
                <a class="activity" id="class_menu_report_11">
                  <span class="activity_title">상태 미확인 과제</span>
                </a>
                """)
            if path == NOTICE_LIST:
                return httpx.Response(200, text="")
            if path == REPORT_VIEW:
                self.assertEqual(request.url.params["RT_SEQ"], "10")
                return httpx.Response(200, text=f"""
                <table><tr><td>마감일</td><td>{deadline}</td></tr></table>
                <div id="submit_form">제출된 내역이 없습니다.</div>
                """)
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            first = await client.get_home_course_index(_COURSE_ID)
            day_label = "D-2"
            unchanged = await client.get_home_course_index(_COURSE_ID)
            deadline = "2026.11.21 (토) 오후 11:59"
            changed = await client.get_home_course_index(_COURSE_ID)
            details = await client.get_home_course_details(_COURSE_ID, ["10", "99"], False, False)

        self.assertEqual([item["submitted"] for item in first["assignments"]], [False, None])
        self.assertEqual(first["assignments"], unchanged["assignments"])
        self.assertNotEqual(first["assignments"][0]["signature"], changed["assignments"][0]["signature"])
        self.assertEqual(first["assignments"][1], changed["assignments"][1])
        self.assertEqual(calls, [
            ("POST", ENTER_COURSE), ("POST", ACTIVITY_LIST), ("POST", NOTICE_LIST),
        ] * 3 + [("GET", MAIN_FORM), ("POST", ENTER_COURSE), ("POST", ACTIVITY_LIST), ("GET", REPORT_VIEW)])
        self.assertEqual(details["assignments"], [
            {"id": "10", "due_at": "2026-11-21T23:59:00", "submitted": False, "submitted_at": None,
             "late_due_at": None, "signature": changed["assignments"][0]["signature"]},
        ])

    async def test_opened_course_notice_returns_full_structured_body_for_listed_id(self) -> None:
        long_paragraph = "긴 강의 안내입니다. " * 30
        image_path = "/ilosfiles/editor-file/SYNTHETIC/2026/notice.png"
        calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append(path)
            if path == MAIN_FORM:
                return httpx.Response(200, text=f"""
                <a class="logout" href="/ilos/lo/logout.acl"></a>
                <div class="my_lecture_container"><a id="kj_1" onclick="eclassRoom('{_COURSE_ID}')">예시 수업</a></div>
                """)
            if path == ENTER_COURSE:
                return httpx.Response(200, json={"isError": False})
            if path == NOTICE_LIST:
                return httpx.Response(200, text="""
                <button class="board_list_wrap" data-num="42">
                  <div class="board_title">예시 공지</div><div class="board_text">잘린 미리보기</div>
                </button>
                """)
            if path == NOTICE_VIEW:
                self.assertEqual(request.content.decode().split("&")[0], "ARTL_NUM=42")
                return httpx.Response(200, text=f"""
                <div class="editor_content" style="height:20px">
                  <p>{long_paragraph}<br><strong onclick="alert(1)">마지막 줄</strong></p>
                  <ul><li>목록 항목</li></ul><script>hidden_script()</script>
                  <a href="javascript:alert(1)">위험 주소</a>
                  <a href="https://www.example.com/page">원문 링크</a>
                  <img src="{image_path}" alt="본문 그림" onerror="alert(1)">
                  <img src="https://invalid.example{image_path}" alt="외부 그림">
                </div>
                <div class="comment_zone">제외할 댓글</div>
                """)
            if path == image_path:
                self.assertEqual(request.url.host, "eclass.seoultech.ac.kr")
                return httpx.Response(200, content=b"fixture-image", headers={"content-type": "image/png"})
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            detail = await client.get_course_notice(_COURSE_ID, "42")
            with self.assertRaises(ValueError):
                await client.get_course_notice(_COURSE_ID, "99")
        self.assertEqual(calls.count(NOTICE_VIEW), 1)
        self.assertIn(f"<p>{long_paragraph}<br><strong>마지막 줄</strong></p>", detail["body_html"])
        self.assertIn("<ul><li>목록 항목</li></ul>", detail["body_html"])
        self.assertIn('<a href="https://www.example.com/page">원문 링크</a>', detail["body_html"])
        self.assertIn('src="data:image/png;base64,Zml4dHVyZS1pbWFnZQ==" alt="본문 그림"', detail["body_html"])
        self.assertIn('<button type="button" class="course-notice-image-source">외부 그림 · e-Class에서 확인 ↗</button>', detail["body_html"])
        self.assertEqual(calls.count(image_path), 1)
        for omitted in ("잘린 미리보기", "hidden_script", "onclick", "onerror", "javascript:", "제외할 댓글", "invalid.example"):
            self.assertNotIn(omitted, detail["body_html"])

    async def test_briefing_reuses_read_paths_and_keeps_other_data_when_detail_fails(self) -> None:
        calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append((request.method, path))
            if path == MAIN_FORM:
                return httpx.Response(200, text=f"""
                <a class="logout" href="/ilos/lo/logout.acl"></a>
                <div class="my_lecture_container">
                  <a id="kj_1" onclick="eclassRoom('{_COURSE_ID}')">예시 수업</a>
                </div>
                """)
            if path == ENTER_COURSE:
                return httpx.Response(200, json={"isError": False})
            if path == NOTICE_LIST:
                return httpx.Response(200, text="""
                <button class="board_list_wrap" data-num="42">
                  <div class="board_title">예시 공지</div>
                  <div class="board_text">목록 미리보기</div>
                  <div class="board_list_bottom">11월 11일 오후 2:00</div>
                </button>
                """)
            if path == ACTIVITY_LIST:
                return httpx.Response(200, text="""
                <a id="class_menu_report_10">제출한 과제</a>
                <a id="class_menu_report_11">상세 조회에 실패한 과제</a>
                """)
            if path == REPORT_VIEW and request.url.params["RT_SEQ"] == "10":
                return httpx.Response(200, text="""
                <div id="submit_form"><div class="inner_title_box">
                  <div class="submit_info_box"><div class="txt">정상제출</div>
                    <div class="date">2026.11.11 (수) 오후 2:00</div></div>
                </div></div>
                """)
            if path == REPORT_VIEW:
                return httpx.Response(500)
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            with patch("seoultech_lms.client.build_course_briefing", partial(build_course_briefing, now=_NOW)):
                result = await client.get_course_briefing()

        self.assertEqual(calls, [
            ("GET", MAIN_FORM), ("POST", ENTER_COURSE), ("POST", NOTICE_LIST),
            ("POST", ACTIVITY_LIST), ("GET", REPORT_VIEW), ("GET", REPORT_VIEW),
        ])
        self.assertEqual(result["completed_assignments"][0]["submitted_at"], "2026-11-11T14:00:00+09:00")
        self.assertIsNone(result["pending_assignments"][0]["submitted"])
        self.assertEqual(result["recent_notices"][0]["content"], "목록 미리보기")
        self.assertEqual(len(result["unavailable"]), 1)
