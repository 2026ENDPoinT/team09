from __future__ import annotations

import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx

from seoultech_lms import mcp_server
from seoultech_lms.assignment_summary import AssignmentSummaryCache
from seoultech_lms.auth import write_auth_state_secure
from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import ACTIVITY_LIST, ENTER_COURSE, HOME_TODO_LIST, MAIN_FORM, REPORT_VIEW


COURSE_ID = "A2026000000031001"
NON_REGULAR_ID = "비정규예시_01"
BASE_URL = "https://eclass.seoultech.ac.kr"


class AssignmentSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = AssignmentSummaryCache()
        self.auth_path = self.root / "data" / "auth_state.json"
        write_auth_state_secure(self.auth_path, {"cookies": []})
        self.calls = []
        self.days_left = 4
        self.index_items = {"100": ("기존 과제", "12", False)}
        self.todo_items = {"100": ("기존 과제", "12")}
        self.todo_fails = False
        self.index_fails = False
        self.non_regular = False
        self.active_course = None
        self.detail_failure = set()
        self.detail_days = {"100": "12", "200": "14", "300": "18"}

    def handle(self, request):
        path = request.url.path
        self.calls.append(request.url.params.get("RT_SEQ") if path == REPORT_VIEW else path)
        if path == MAIN_FORM:
            regular = f'<a id="kj_1" onclick="eclassRoom(\'{COURSE_ID}\')" title="예시 과목 강의실 들어가기">예시 과목</a>'
            non_regular = (
                f'<div class="term_wrap"><b class="container_subtitle">비정규과목</b>'
                f'<a id="kj_2" onclick="eclassRoom(\'{NON_REGULAR_ID}\')">비정규 예시 과목</a></div>'
                if self.non_regular else ""
            )
            return httpx.Response(200, text=f'<div class="my_lecture_container">{regular}{non_regular}</div>')
        if path == ENTER_COURSE:
            self.active_course = parse_qs(request.content.decode())["KJKEY"][0]
            return httpx.Response(200, json={"isError": False})
        if path == ACTIVITY_LIST:
            if self.index_fails:
                return httpx.Response(200, text="<h1>예기치 못한 페이지</h1>")
            items = []
            index_items = {"300": ("비정규 과제", "18", False)} if self.active_course == NON_REGULAR_ID else self.index_items
            for item_id, (title, day, submitted) in index_items.items():
                status = "" if submitted else " not_submit"
                check = '<span class="submit_check_outer"><b class="submit_check"></b></span>' if submitted else ""
                items.append(f'<a id="class_menu_report_{item_id}" class="activity{status}">'
                             f'<b class="activity_title">{title}</b>{check}<span class="activity_info_dday">'
                             f'D-{self.days_left} 12월 {day}일 오후 11:59</span></a>')
            return httpx.Response(200, text='<div class="activity_week"></div>' + "".join(items))
        if path == HOME_TODO_LIST:
            if self.todo_fails:
                return httpx.Response(503)
            items = [
                f'<a class="aside_list_todo_item" onclick="goLecture(\'{COURSE_ID}\', \'report\', \'{item_id}\')">'
                f'<b class="aside_list_title">{title}</b><span class="aside_list_date">12월 {day}일 오후 11:59</span></a>'
                for item_id, (title, day) in self.todo_items.items()
            ]
            return httpx.Response(200, text="".join(items) + (
                f"<script>$('#asideTodoCnt').text('{len(items)}'); $('#btnAsideTodoListMore').hide();</script>"
            ))
        self.assertEqual(path, REPORT_VIEW)
        item_id = request.url.params["RT_SEQ"]
        if item_id in self.detail_failure:
            return httpx.Response(503)
        day = self.detail_days[item_id]
        submitted = self.index_items.get(item_id, ("", "", False))[2]
        submit = ('<div class="inner_title_box"><div class="submit_info_box"><span class="txt">제출완료</span></div></div>'
                  if submitted else "제출된 내역이 없습니다.")
        return httpx.Response(200, text=(
            '<div class="view_title"></div><table><tr><td>마감일</td>'
            f'<td>2026.12.{day} 오후 11:59</td></tr><tr><td>지각 제출 허용 (마감일 : 2026.12.29 오후 11:59)</td></tr>'
            f'</table><div class="bbsview"><div class="editor_content">예시 교수자 안내</div></div><div id="submit_form">{submit}</div>'
        ))

    async def query(self, *, refresh_details=False, include_non_regular=True):
        client = SeoultechLMSClient(self.root, assignment_cache=self.cache)
        client._cookies()  # Apply the same auth-file session binding as the MCP.
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url=BASE_URL) as http:
            client._http = http
            return await client.get_assignment_summary(refresh_details=refresh_details, include_non_regular=include_non_regular)

    async def test_fresh_index_reuses_unchanged_details_and_reads_new_items(self):
        first = await self.query()
        self.assertEqual(self.calls, [MAIN_FORM, HOME_TODO_LIST, ENTER_COURSE, ACTIVITY_LIST, "100"])
        self.assertTrue(first["todo_checked"])
        self.assertEqual(first["assignments"][0]["late_due_at"], "2026-12-29T23:59:00+09:00")
        self.assertIsNone(first["assignments"][0]["description"])
        self.calls.clear()
        self.days_left = 3
        self.index_items["200"] = ("새 과제", "14", False)
        self.todo_items["300"] = ("할일에서 발견한 과제", "18")
        next_result = await self.query()
        self.assertEqual(self.calls, [MAIN_FORM, HOME_TODO_LIST, ENTER_COURSE, ACTIVITY_LIST, "200", "300"])
        self.assertEqual([item["id"] for item in next_result["assignments"]], ["100", "200", "300"])
        self.calls.clear()
        await self.query()
        self.assertEqual(self.calls, [MAIN_FORM, HOME_TODO_LIST, ENTER_COURSE, ACTIVITY_LIST])

    async def test_feed_absence_does_not_mean_submission_and_markers_detect_deadline_changes(self):
        await self.query()
        self.calls.clear()
        self.todo_items["100"] = ("기존 과제", "18")
        self.detail_days["100"] = "18"
        result = await self.query()
        self.assertIn("100", self.calls)
        self.assertEqual(result["assignments"][0]["due_at"], "2026-12-18T23:59:00+09:00")
        self.calls.clear()
        self.todo_fails = True
        result = await self.query()
        self.assertNotIn("100", self.calls)
        self.assertFalse(result["todo_checked"])
        self.assertEqual(result["assignments"][0]["id"], "100")
        self.calls.clear()
        self.index_items["100"] = ("기존 과제", "12", True)
        result = await self.query()
        self.assertNotIn("100", self.calls)
        self.assertEqual(result["assignments"], [])

    async def test_failed_reads_are_explicit_and_not_replaced_by_stale_details(self):
        await self.query()
        self.index_fails = True
        self.detail_failure.add("100")
        result = await self.query()
        self.assertEqual(len(result["unavailable"]), 2)
        self.assertIsNone(result["assignments"][0]["due_at"])
        @asynccontextmanager
        async def partial_client():
            yield AsyncMock(get_assignment_summary=AsyncMock(return_value=result))

        with patch.object(mcp_server, "_query_client", partial_client):
            with self.assertRaisesRegex(RuntimeError, "일부 과제"):
                await mcp_server.get_pending_assignments()

    async def test_rich_summary_includes_enrolled_non_regular_courses(self):
        self.non_regular = True
        rich = await self.query()
        self.assertEqual([item["course_id"] for item in rich["assignments"]], [COURSE_ID, NON_REGULAR_ID])
        self.calls.clear()
        regular = await self.query(include_non_regular=False)
        self.assertEqual([item["course_id"] for item in regular["assignments"]], [COURSE_ID])
        self.assertEqual(self.calls, [MAIN_FORM, HOME_TODO_LIST, ENTER_COURSE, ACTIVITY_LIST])

    async def test_summary_assignments_are_openable_from_todo_and_non_regular_courses(self):
        self.non_regular = True
        self.todo_items["200"] = ("할일 과제", "14")
        client = SeoultechLMSClient(self.root)
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url=BASE_URL) as http:
            client._http = http
            todo_post = await client.get_post("assignment", "200", COURSE_ID)
            non_regular_post = await client.get_post("assignment", "300", NON_REGULAR_ID)
        self.assertEqual(todo_post.content, "예시 교수자 안내")
        self.assertEqual(non_regular_post.course_id, NON_REGULAR_ID)

    async def test_legacy_deadline_range_does_not_silently_omit_unconfirmed_dates(self):
        with patch.object(mcp_server, "get_pending_assignments", return_value=[{"due_at": None}]):
            with self.assertRaisesRegex(RuntimeError, "마감일을 확인하지 못한 과제"):
                await mcp_server.get_upcoming_deadlines()

    async def test_failed_forced_refresh_invalidates_previous_detail(self):
        await self.query()
        self.detail_failure.add("100")
        result = await self.query(refresh_details=True)
        self.assertIn("unavailable", result)
        self.detail_failure.clear()
        self.detail_days["100"] = "19"
        self.calls.clear()
        result = await self.query()
        self.assertIn("100", self.calls)
        self.assertEqual(result["assignments"][0]["due_at"], "2026-12-19T23:59:00+09:00")

    async def test_cache_is_invalidated_on_relogin_expiry_and_explicit_refresh(self):
        with patch("seoultech_lms.assignment_summary.monotonic", return_value=1):
            await self.query()
        with patch("seoultech_lms.assignment_summary.monotonic", return_value=601):
            self.calls.clear()
            await self.query()
            self.assertIn("100", self.calls)
            self.calls.clear()
            await self.query(refresh_details=True)
            self.assertIn("100", self.calls)
            self.calls.clear()
            write_auth_state_secure(self.auth_path, {"cookies": []})
            await self.query()
            self.assertIn("100", self.calls)
