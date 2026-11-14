from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from seoultech_lms.assignment_summary import AssignmentSummaryCache
from seoultech_lms.auth import write_auth_state_secure
from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import ACTIVITY_LIST, ENTER_COURSE, HOME_TODO_LIST, MAIN_FORM, NOTICE_LIST, REPORT_VIEW


class AssignmentSummaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cache = AssignmentSummaryCache()
        self.calls: list[tuple[str, str | None]] = []
        self.rows = {"10": (20, "not_submit")}
        self.details = {"10": 20, "20": 21, "30": 22}
        self.todo = {}
        self.day_badge = "D-3"
        self.fail_index = False
        self.fail_details: set[str] = set()

    def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assignment_id = request.url.params.get("RT_SEQ")
        self.calls.append((path, assignment_id))
        if path == MAIN_FORM:
            return httpx.Response(200, text="""
                <a class="logout" href="/ilos/lo/logout.acl"></a>
                <div class="my_lecture_container"><a id="kj_1" onclick="eclassRoom('A20260001')">예시 수업</a></div>
            """)
        if path == HOME_TODO_LIST:
            return httpx.Response(200, text="".join(
                f"""<a class="aside_list_todo_item" onclick="goLecture('A20260001','report','{item}')">
                    <span class="aside_list_title">예시 {item}</span>
                    <span class="aside_list_date">11월 {day}일 오후 11:59</span></a>"""
                for item, day in self.todo.items()
            ) + f"""<script>$('#asideTodoCnt').text('{len(self.todo)}'); $("#btnAsideTodoListMore").remove();</script>""")
        if path == ENTER_COURSE:
            return httpx.Response(200, json={"isError": False})
        if path == ACTIVITY_LIST:
            if self.fail_index:
                return httpx.Response(200, text="<p>예상하지 못한 응답</p>")
            return httpx.Response(200, text='<div class="activity_week">' + "".join(
                f"""<a class="activity {state}" id="class_menu_report_{item}">
                    <span class="activity_title">예시 {item}</span>
                    <span class="activity_info_dday">{self.day_badge} 2026.11.{day} 오후 11:59</span>
                    {'<span class="submit_check_outer"><span class="submit_check"></span></span>' if state == "submitted" else ""}
                    </a>"""
                for item, (day, state) in self.rows.items()
            ) + "</div>")
        if path == NOTICE_LIST:
            return httpx.Response(200, text="")
        if path == REPORT_VIEW:
            if assignment_id in self.fail_details:
                return httpx.Response(500)
            day = self.details[assignment_id]
            return httpx.Response(200, text=f"""
                <table><tr><td>마감일</td><td>2026.11.{day} 오후 11:59</td></tr>
                <tr><td>지각 제출 허용 (마감일: 2026.11.30 오후 11:59)</td></tr></table>
                <div class="bbsview"><div class="editor_content">본문 보관 금지</div></div>
                <div id="submit_form">제출된 내역이 없습니다.</div>
            """)
        self.fail(f"Unexpected route: {path}")

    async def read(self, *, refresh_details=False):
        self.calls.clear()
        client = SeoultechLMSClient(assignment_cache=self.cache)
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.respond)) as http:
            client._http = http
            result = await client.get_assignment_summary(refresh_details=refresh_details)
        self.assertEqual([path for path, _ in self.calls[:4]], [MAIN_FORM, HOME_TODO_LIST, ENTER_COURSE, ACTIVITY_LIST])
        return result

    def detail_calls(self):
        return [item for path, item in self.calls if path == REPORT_VIEW]

    async def test_reuses_verified_details_but_always_checks_latest_lists(self) -> None:
        first = await self.read()
        self.assertEqual(self.detail_calls(), ["10"])
        self.assertTrue(first["todo_checked"])
        self.assertEqual(first["assignments"][0]["late_due_at"], "2026-11-30T23:59:00+09:00")
        self.day_badge = "D-2"
        self.assertEqual((await self.read())["assignments"], first["assignments"])
        self.assertEqual(self.detail_calls(), [])

        self.rows["20"] = (21, "not_submit")
        self.todo["30"] = 22
        result = await self.read()
        self.assertEqual(set(self.detail_calls()), {"20", "30"})
        self.assertEqual([row["id"] for row in result["assignments"]], ["10", "20", "30"])
        await self.read()
        self.assertEqual(self.detail_calls(), [])

        self.rows["10"] = (23, "not_submit")
        self.rows["20"] = (21, "submitted")
        self.details["10"] = 23
        del self.todo["30"]
        result = await self.read()
        self.assertEqual(self.detail_calls(), ["10"])
        self.assertEqual([row["id"] for row in result["assignments"]], ["10"])
        self.assertEqual(result["assignments"][0]["due_at"], "2026-11-23T23:59:00+09:00")

    async def test_failures_keep_verified_rows_and_retry_missing_detail(self) -> None:
        await self.read()
        self.rows["20"] = (21, "not_submit")
        self.fail_details.add("20")
        result = await self.read()
        self.assertEqual(self.detail_calls(), ["20"])
        self.assertIn("unavailable", result)
        self.assertTrue(result["assignments"][0]["deadline_checked"])
        self.assertFalse(result["assignments"][1]["deadline_checked"])
        self.fail_details.clear()
        result = await self.read()
        self.assertEqual(self.detail_calls(), ["20"])
        self.assertNotIn("unavailable", result)

        self.fail_index = True
        self.todo["30"] = 22
        result = await self.read()
        self.assertIn("unavailable", result)
        self.assertEqual(self.detail_calls(), ["30"])
        self.assertEqual([row["id"] for row in result["assignments"]], ["30"])

    async def test_todo_deadline_changes_invalidate_unchanged_index_and_force_is_available(self) -> None:
        self.todo["10"] = 20
        await self.read()
        self.todo["10"] = 21
        self.details["10"] = 21
        self.assertEqual((await self.read())["assignments"][0]["due_at"], "2026-11-21T23:59:00+09:00")
        self.assertEqual(self.detail_calls(), ["10"])
        await self.read()
        self.assertEqual(self.detail_calls(), [])
        await self.read(refresh_details=True)
        self.assertEqual(self.detail_calls(), ["10"])

    async def test_todo_only_assignment_link_opens_verified_detail(self) -> None:
        self.todo["30"] = 22
        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.respond)) as http:
            client._http = http
            post = await client.get_post("assignment", "30", "A20260001")
        self.assertEqual(post.id, "30")
        self.assertEqual(post.due_at.day, 22)
        self.assertEqual(self.detail_calls(), ["30"])

    async def test_home_seeds_private_cache_and_fresh_process_reuses_only_same_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / "one" / "auth_state.json"
            state = {"cookies": [{"name": "fake_session", "value": "fixture", "domain": "eclass.seoultech.ac.kr"}]}
            write_auth_state_secure(auth, state)
            other = root / "two" / "auth_state.json"
            write_auth_state_secure(other, state)
            transport = httpx.MockTransport(self.respond)
            make_http = httpx.AsyncClient

            def offline_http(**kwargs):
                return make_http(**kwargs, transport=transport)

            with patch("seoultech_lms.client.httpx.AsyncClient", side_effect=offline_http):
                async with SeoultechLMSClient(session_path=auth, assignment_cache=self.cache) as client:
                    await client.get_home_course_details("A20260001", ["10"], False, False)
                self.assertEqual(self.detail_calls(), ["10"])
                cache_file = auth.with_name("assignment-summary.json")
                self.assertNotIn("본문 보관 금지", cache_file.read_text())
                self.assertNotIn("fake_session", cache_file.read_text())
                self.assertEqual(cache_file.stat().st_mode & 0o777, 0o600)

                self.cache = AssignmentSummaryCache()
                self.calls.clear()
                async with SeoultechLMSClient(session_path=auth, assignment_cache=self.cache) as client:
                    await client.get_assignment_summary()
                self.assertEqual(self.detail_calls(), [])

                self.calls.clear()
                async with SeoultechLMSClient(session_path=other, assignment_cache=self.cache) as client:
                    await client.get_assignment_summary()
                self.assertEqual(self.detail_calls(), ["10"])
