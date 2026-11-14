from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch
from urllib.parse import parse_qs

import httpx
from playwright.async_api import Error as PlaywrightError

from seoultech_lms.auth import AuthenticationRequired, account_session_path, save_account_session, write_auth_state_secure
from seoultech_lms.attendance import parse_attendance
from seoultech_lms.browser import DesktopLogin, _LoginCapture, _allowed_login_request, _submitted_login_id
from seoultech_lms.client import ReadOnlyViolation, SeoultechLMSClient
from seoultech_lms.content import parse_course_activities, parse_post_list
from seoultech_lms.endpoints import (
    ACTIVITY_LIST, ATTENDANCE_LIST, BASE_URL, BOARD_LIST, COURSE_FILES, COURSE_HOME, ENTER_COURSE,
    MAIN_FORM, MY_INFO, NOTICE_LIST, QNA_LIST, REPORT_VIEW,
)
from seoultech_lms.mcp_server import confirm_desktop_login, get_desktop_login_status
from seoultech_lms import mcp_server
from seoultech_lms.models import CourseAttendance, CourseRoster, LearningActivity, StudentProfile
from seoultech_lms.parser import parse_authenticated_roster


ROSTER = """
<a class="logout" href="/ilos/lo/logout.acl">로그아웃</a>
<div id="my_page_menu_pop"><div class="user_info"><div class="user_name">테스트학생</div></div></div>
<section class="my_lecture_container">
  <div class="term_wrap">
    <p class="container_subtitle">2학기</p>
    <a id="kj_1" title="정규 수업 강의실 들어가기" onclick="eclassRoom('A20260001')">정규 수업</a>
  </div>
  <div class="term_wrap">
    <p class="container_subtitle">비정규과목</p>
    <a id="kj_2" title="특강 강의실 들어가기" onclick="eclassRoom('비20260001')">특강</a>
  </div>
</section>
<a id="kj_3" onclick="eclassRoom('A20260003')">신청하지 않은 수업</a>
"""
ACTIVITIES = """
<div class="activity_week">1주</div>
<a class="activity not_submit" id="class_menu_report_1">미제출 과제</a>
<a class="activity" id="class_menu_report_2">제출 과제<div class="submit_check_outer"><div class="submit_check"></div></div></a>
<a class="activity" id="class_menu_report_2">중복 노출</a>
<a class="activity" id="class_menu_lecture_material_3">자료<div class="submit_check_outer"><div class="submit_check"></div></div></a>
<a class="activity" id="class_menu_lecture_weeks_4">강의</a>
<a class="activity" id="class_menu_test_5">시험</a>
<a class="activity" id="class_menu_discuss_6">토론</a>
<a class="activity" id="class_menu_survey_7">설문</a>
<a class="activity" id="class_menu_other_8">새 활동 유형</a>
"""
EMPTY = '<div class="list_error_msg">조회할 자료가 없습니다.</div>'
STATE = {"cookies": [{"name": "session", "value": "test-cookie", "domain": "eclass.seoultech.ac.kr"}], "origins": []}
ATTENDANCE = """<div class="attendance_list"><ul class="attendance_week_time_list">
  <li><div class="attend_menu"><div class="attendance_week_time stu"><div class="attend_stats_list">
    <div class="attend_stats" title="출석"><div class="attend_dv_icon_title attend">출석</div></div>
    <div class="attend_stats" title="출석">출석</div>
  </div></div></div></li>
  <li><div class="attend_menu"><div class="attendance_week_time stu"><div class="attend_stats_list">
    <div class="attend_stats" title="결석"></div>
  </div></div></div></li>
  <li><div class="attend_menu"><div class="attendance_week_time stu"><div class="attend_stats_list">
    <div class="attend_stats" title="출석 인정"></div>
  </div></div></div></li>
  <li><div class="attend_menu"><div class="attendance_week_time stu"><div class="attend_stats_list">
    <div class="attend_stats" title="확인 중"></div>
  </div></div></div></li>
  <li><div class="attend_menu ready"></div></li>
  <li class="attendance_line"></li>
</ul></div>"""


class MvpTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_both_course_types_and_paginates_without_reading_details(self):
        active = None
        notice_calls = []
        attendance_calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal active
            path = request.url.path
            data = parse_qs(request.content.decode())
            if path == MAIN_FORM:
                return httpx.Response(200, text=ROSTER)
            if path == ENTER_COURSE:
                active = data["KJKEY"][0]
                return httpx.Response(200, json={"isError": False})
            self.assertIn(active, ("A20260001", "비20260001"))
            if path == ACTIVITY_LIST:
                return httpx.Response(200, text=ACTIVITIES)
            if path == ATTENDANCE_LIST:
                self.assertEqual(request.method, "POST")
                self.assertEqual(parse_qs(request.content.decode(), keep_blank_values=True), {"SCH_WEEK_NO": [""], "encoding": ["utf-8"]})
                attendance_calls.append(active)
                return httpx.Response(200, text=ATTENDANCE)
            if path == COURSE_HOME:
                return httpx.Response(200, text='<a href="/ilos/cls/st/board/open_material_list_form.acl?ARTL_GRP_ID=1">게시판</a>')
            if path in (BOARD_LIST, QNA_LIST):
                return httpx.Response(200, text=EMPTY)
            if path == COURSE_FILES:
                return httpx.Response(200, text='<ul class="attach_list"><li><a href="/ilos/co/efile_download.acl?FILE_SEQ=1&amp;CONTENT_SEQ=2">자료.pdf</a></li></ul>')
            if path == NOTICE_LIST:
                offset = int(data["start"][0])
                notice_calls.append((active, offset))
                page = 1 if offset == 1 else 2
                rows = ['<button class="board_list_wrap" data-num="123">공지</button>']
                if page == 2:
                    rows.append('<button class="board_list_wrap" data-num="124">추가 공지</button>')
                buttons = "".join(
                    f'<button class="paging_num_btn{" on" if i == page else ""}">{i}</button>'
                    for i in (1, 2)
                )
                return httpx.Response(200, text="".join(rows) + f'<div class="file_paging">{buttons}</div>')
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url=BASE_URL) as http:
            client._http = http
            result = await client.get_course_overview(include_attendance=True)

        self.assertEqual((result.regular, result.non_regular), (1, 1))
        self.assertEqual(attendance_calls, ["A20260001"])
        self.assertEqual(result.courses[0].attendance, CourseAttendance(1, 0, 1, 0, 1, 1))
        self.assertIsNone(result.courses[1].attendance)
        self.assertEqual(notice_calls, [
            ("A20260001", 1), ("A20260001", 21), ("비20260001", 1), ("비20260001", 21),
        ])
        for item in result.courses:
            self.assertEqual(item.counts, {
                "assignment": 2, "material": 1, "lecture": 1, "quiz": 1, "discussion": 1, "survey": 1,
                "other_activity": 1, "course_notice": 2, "qna": 0, "open_board": 0, "files": 1,
            })
            self.assertEqual(item.total_posts, 10)
            self.assertEqual(item.learning_activity, LearningActivity(1, 2))

    def test_learning_activity_distinguishes_zero_assignments_from_unknown_status(self):
        self.assertEqual(parse_course_activities(EMPTY)[1], LearningActivity(0, 0))
        unknown = '<a class="activity" id="class_menu_report_1">과제</a>'
        self.assertIsNone(parse_course_activities(unknown)[1])
        conflicting = '<a class="activity not_submit" id="class_menu_report_2">같은 과제</a>'
        self.assertEqual(parse_course_activities(ACTIVITIES + conflicting)[1], LearningActivity(0, 1))

    def test_assignment_post_list_uses_only_explicit_submission_markers(self):
        html = """
        <a id="class_menu_report_1" class="activity not_submit">미제출 과제</a>
        <a id="class_menu_report_2" class="activity">제출 과제
          <div class="submit_check_outer"><div class="submit_check"></div></div></a>
        <a id="class_menu_report_3" class="activity">미확인 과제</a>
        """
        self.assertEqual([post.submitted for post in parse_post_list(html, "assignment", "A20260001")],
                         [False, True, None])

    def test_attendance_requires_student_lesson_markup(self):
        self.assertIsNone(parse_attendance("<main>로그인</main>"))
        self.assertIsNone(parse_attendance('<div class="attend_stats" title="결석"></div>'))

    def test_authenticated_roster_can_be_empty(self):
        html = '<a class="logout" href="/ilos/lo/logout.acl"></a><div class="my_lecture_container"></div>'
        roster = parse_authenticated_roster(html)
        self.assertIsNotNone(roster)
        self.assertEqual(roster.courses, [])
        self.assertIsNone(roster.display_name)
        self.assertFalse(roster.non_regular_available)
        self.assertIsNone(parse_authenticated_roster("<form>로그인</form>"))
        self.assertEqual(parse_authenticated_roster(ROSTER).display_name, "테스트학생")

    async def test_my_profile_reads_contact_fields_from_eclass(self):
        def respond(request):
            self.assertEqual((request.method, request.url.path), ("POST", MY_INFO))
            self.assertEqual(request.headers["Referer"], BASE_URL + MAIN_FORM)
            return httpx.Response(200, text="""
                <div class="user_info"><span class="user_name">테스트학생</span>
                <span class="dept_grade">예시학과 <b>2학년</b></span></div>
                <div class="contact"><span>전화번호</span><span>010-0000-0000</span></div>
                <div class="contact"><span>이메일</span><span>fixture@example.test</span></div>
            """)

        client = SeoultechLMSClient()

        @asynccontextmanager
        async def query_client():
            yield client

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            self.assertEqual(await client.get_student_profile("테스트학생"), StudentProfile("테스트학생", "예시학과", 2))
            with patch("seoultech_lms.mcp_server._query_client", query_client):
                self.assertEqual(await mcp_server.get_student_profile(), {
                    "display_name": "테스트학생", "department": "예시학과", "year": 2,
                    "phone": "010-0000-0000", "email": "fixture@example.test",
                })

    async def test_stages_browser_state_and_only_saves_after_confirmation(self):
        login = DesktopLogin()
        finish = asyncio.Event()

        async def capture(opened):
            opened.set_result(True)
            await finish.wait()
            return _LoginCapture(STATE, "")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(login, "_capture", side_effect=capture),
            patch("seoultech_lms.mcp_server._desktop_login", login),
            patch("seoultech_lms.mcp_server.auth_state_path", return_value=Path(directory) / "auth_state.json"),
            patch.object(SeoultechLMSClient, "get_login_roster", new_callable=AsyncMock) as read_roster,
            patch.object(SeoultechLMSClient, "get_student_profile", new_callable=AsyncMock,
                         return_value=StudentProfile("테스트학생", "예시학과", 2)) as read_profile,
        ):
            path = Path(directory) / "auth_state.json"
            self.assertEqual((await login.open())["status"], "opened")
            self.assertEqual((await login.open())["status"], "already_open")
            self.assertEqual((await get_desktop_login_status())["status"], "pending")
            self.assertEqual((await confirm_desktop_login())["status"], "login_required")
            read_roster.assert_not_awaited()
            self.assertFalse(path.exists())

            finish.set()
            await login._attempt  # The login browser has already finished and closed.
            self.assertEqual((await get_desktop_login_status())["status"], "captured")
            self.assertNotIn("cookies", await get_desktop_login_status())
            self.assertFalse(path.exists())
            read_roster.side_effect = AuthenticationRequired()
            self.assertEqual((await confirm_desktop_login())["status"], "login_required")
            self.assertFalse(path.exists())

            read_roster.side_effect = None
            read_roster.return_value = parse_authenticated_roster(ROSTER)
            confirmed = await confirm_desktop_login()
            self.assertEqual(confirmed["status"], "authenticated")
            self.assertEqual(confirmed["display_name"], "테스트학생")
            self.assertEqual(confirmed["student_profile"], {"department": "예시학과", "year": 2})
            read_profile.assert_awaited_once_with("테스트학생")
            self.assertEqual(confirmed["course_roster"]["regular"], 1)
            self.assertEqual(confirmed["course_roster"]["non_regular"], 1)
            self.assertEqual(confirmed["course_roster"]["courses"][0]["name"], "정규 수업")
            self.assertEqual(json.loads(path.read_text()), STATE)
            self.assertIsNone(login.candidate())

    async def test_manual_status_can_capture_authenticated_url_and_close_browser(self):
        login = DesktopLogin()
        browser = MagicMock()
        browser.is_connected.return_value = True
        browser.close = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)
        runtime = MagicMock()
        runtime.__aenter__ = AsyncMock(return_value=playwright)
        runtime.__aexit__ = AsyncMock()
        page = MagicMock()
        page.url = f"{BASE_URL}/ilos/main/member/login_form.acl"
        page.context.cookies = AsyncMock(return_value=STATE["cookies"])
        navigation_started = asyncio.Event()

        async def wait_for_url(*args, **kwargs):
            navigation_started.set()
            await asyncio.Event().wait()

        page.wait_for_url = AsyncMock(side_effect=wait_for_url)
        with (
            patch("seoultech_lms.browser.async_playwright", return_value=runtime),
            patch("seoultech_lms.browser._open_login_page", new=AsyncMock(return_value=page)),
        ):
            self.assertEqual((await login.open())["status"], "opened")
            await navigation_started.wait()
            self.assertEqual((await login.status(recheck=True))["status"], "pending")
            page.url = f"{BASE_URL}{MAIN_FORM}"
            self.assertEqual((await login.status(recheck=True))["status"], "captured")
            browser.close.assert_awaited_once()

    async def test_desktop_login_falls_back_to_installed_chrome(self):
        login = DesktopLogin()
        browser = MagicMock()
        browser.close = AsyncMock()
        playwright = MagicMock()
        launch = AsyncMock(side_effect=[PlaywrightError("Chromium unavailable"), browser])
        playwright.chromium.launch = launch
        runtime = MagicMock()
        runtime.__aenter__ = AsyncMock(return_value=playwright)
        runtime.__aexit__ = AsyncMock()
        page = MagicMock(url=f"{BASE_URL}{MAIN_FORM}")
        page.context.cookies = AsyncMock(return_value=STATE["cookies"])
        page.wait_for_url = AsyncMock()

        with (
            patch("seoultech_lms.browser.async_playwright", return_value=runtime),
            patch("seoultech_lms.browser._open_login_page", new=AsyncMock(return_value=page)) as open_page,
        ):
            self.assertEqual((await login.open())["status"], "opened")
            await login._attempt
            self.assertEqual((await login.status())["status"], "captured")
            self.assertEqual(login.candidate(), STATE)
            self.assertIs(open_page.await_args.args[0], browser)
            browser.close.assert_awaited_once()
            self.assertEqual(launch.await_args_list, [
                call(channel=None, headless=False, timeout=10_000),
                call(channel="chrome", headless=False, timeout=10_000),
            ])

    def test_login_capture_accepts_only_one_valid_account_field(self):
        self.assertEqual(_submitted_login_id("usr_id=20260001&usr_pwd=fixture"), "20260001")
        self.assertIsNone(_submitted_login_id("usr_pwd=fixture"))
        self.assertIsNone(_submitted_login_id("usr_id=20260001&usr_id=20260002"))
        self.assertIsNone(_submitted_login_id("usr_id=..%2Foutside"))

    async def test_desktop_login_requires_verified_account_before_saving(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(mcp_server, "account_storage_root", return_value=Path(directory)),
            patch.object(mcp_server, "_active_account", None),
            patch.object(mcp_server, "_desktop_login", new=MagicMock()) as login,
            patch.object(SeoultechLMSClient, "get_login_roster", new_callable=AsyncMock, return_value=CourseRoster([], False, "테스트학생")),
            patch.object(SeoultechLMSClient, "_request", new_callable=AsyncMock, side_effect=httpx.ConnectError("fixture outage")),
        ):
            login.candidate.return_value = STATE
            login.login_id.return_value = None
            self.assertEqual((await confirm_desktop_login(use_saved=False))["status"], "login_required")
            self.assertEqual(list(Path(directory).iterdir()), [])
            login.login_id.return_value = "20260001"
            result = await confirm_desktop_login(use_saved=False)
            self.assertEqual(result["status"], "authenticated")
            self.assertNotIn("student_profile", result)
            self.assertEqual(mcp_server._account_session_path(), Path(directory) / result["account_key"] / "lms" / "auth_state.json")
            self.assertEqual(json.loads(mcp_server._account_session_path().read_text()), STATE)
            self.assertNotIn("20260001", json.dumps(result))

    async def test_restart_verifies_saved_account_and_fresh_mode_removes_only_sessions(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(mcp_server, "_active_account", None),
            patch.object(mcp_server, "_desktop_login", DesktopLogin()),
            patch.object(SeoultechLMSClient, "get_login_roster", new_callable=AsyncMock,
                         return_value=CourseRoster([], False, "테스트학생")) as read_roster,
            patch.object(SeoultechLMSClient, "get_student_profile", new_callable=AsyncMock, return_value=None),
        ):
            root = Path(directory) / "accounts"
            old = save_account_session(root, "fixture-one", STATE)
            latest = save_account_session(root, "fixture-two", STATE)
            preferences = root / latest / "student-preferences.json"
            preferences.write_text("{}", encoding="utf-8")
            legacy_state = Path(directory) / "lms" / "auth_state.json"
            write_auth_state_secure(legacy_state, STATE)
            with (
                patch.object(mcp_server, "account_storage_root", return_value=root),
                patch.object(mcp_server, "auth_state_path", return_value=legacy_state),
            ):
                self.assertEqual((await confirm_desktop_login())["account_key"], latest)
                self.assertEqual(mcp_server._account_session_path(), account_session_path(root, latest))
                read_roster.side_effect = AuthenticationRequired()
                self.assertEqual((await confirm_desktop_login())["status"], "login_required")
                with self.assertRaises(AuthenticationRequired):
                    mcp_server._account_session_path()
                self.assertEqual((await mcp_server.clear_desktop_login())["status"], "cleared")
                self.assertEqual((await mcp_server.clear_desktop_login())["status"], "cleared")
                self.assertFalse(account_session_path(root, old).exists())
                self.assertFalse(account_session_path(root, latest).exists())
                self.assertFalse(legacy_state.exists())
                self.assertTrue(preferences.is_file())
                self.assertEqual((await confirm_desktop_login())["status"], "login_required")
                self.assertEqual(read_roster.await_count, 2)

    async def test_auto_confirmation_requires_fresh_browser_capture(self):
        with (
            patch("seoultech_lms.mcp_server._desktop_login", DesktopLogin()),
            patch.object(SeoultechLMSClient, "get_login_roster", new_callable=AsyncMock) as read_roster,
        ):
            result = await confirm_desktop_login(use_saved=False)
            self.assertEqual(result["status"], "login_required")
            read_roster.assert_not_awaited()

    async def test_connector_denies_assignment_write_and_upload_paths(self):
        client = SeoultechLMSClient()
        for path in (
            "/ilos/cls/st/report/report_submit.acl",
            "/ilos/cls/st/report/report_modify.acl",
            "/ilos/cls/st/report/report_delete.acl",
            "/ilos/co/efile_upload.acl",
        ):
            for method in ("GET", "POST"):
                with self.subTest(method=method, path=path), self.assertRaises(ReadOnlyViolation):
                    await client._request(method, path)
                self.assertFalse(_allowed_login_request(method, BASE_URL + path, "document"))
        with self.assertRaises(ReadOnlyViolation):
            await client._request("POST", REPORT_VIEW)

    def test_login_window_allows_official_login_but_no_course_navigation(self):
        self.assertTrue(_allowed_login_request("POST", f"{BASE_URL}/ilos/lo/login.acl", "document"))
        self.assertTrue(_allowed_login_request("GET", BASE_URL + MAIN_FORM, "document"))
        self.assertFalse(_allowed_login_request("POST", "https://other.example/ilos/lo/login.acl", "document"))
        self.assertFalse(_allowed_login_request("GET", BASE_URL + REPORT_VIEW, "document"))
