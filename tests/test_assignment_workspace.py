from __future__ import annotations

import asyncio
import unittest
from base64 import b64decode
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from pypdf import PdfWriter

from seoultech_lms import mcp_server as server
from seoultech_lms.auth import AuthenticationRequired
from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import ACTIVITY_LIST, COURSE_ATTACHMENT_LIST, ENTER_COURSE, MAIN_FORM, REPORT_VIEW
from seoultech_lms.models import AssignmentMetadata, Attachment, Course, CourseRoster, Post


COURSES = [Course("A-test-a", "테스트 강좌 A"), Course("A-test-b", "테스트 강좌 B")]
POST = Post(
    "1001", "assignment", "테스트 과제", course_id="A-test-a",
    content="교수자 안내: 반드시 재귀 함수를 사용한다.",
    due_at=datetime.fromisoformat("2026-11-20T23:59:00+09:00"),
    late_due_at=datetime.fromisoformat("2026-11-24T18:00:00+09:00"),
    submitted=False,
    attachments=(Attachment("9001", "테스트 안내.pdf"),),
    assignment_metadata=AssignmentMetadata(
        submission_method="온라인", submission_format="글 입력 / 파일첨부", published_at="2026-11-13T10:16:00+09:00",
        points="0점", score_visibility="비공개",
    ),
)
COOKIES = [{
    "name": "fixture_session", "value": "synthetic-session-only",
    "domain": "eclass.seoultech.ac.kr", "path": "/", "secure": True,
}]


class MockLmsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = MagicMock(spec=SeoultechLMSClient)
        self.client.__aenter__.return_value = self.client
        self.client.get_courses = AsyncMock(return_value=COURSES)
        self.client.get_login_roster = AsyncMock(return_value=CourseRoster(COURSES, True))
        self.client.get_student_profile = AsyncMock(return_value=None)
        self.client.get_post = AsyncMock(return_value=POST)
        self.client.list_posts = AsyncMock(return_value=[])
        self.factory = self.enterContext(patch.object(server, "SeoultechLMSClient", return_value=self.client))
        self.write = self.enterContext(patch.object(server, "write_auth_state_secure"))
        self.clear = self.enterContext(patch.object(server._desktop_login, "clear"))
        self.path = Path("/synthetic-fixture/auth_state.json")
        self.enterContext(patch.object(server, "auth_state_path", return_value=self.path))


class AssignmentWorkspaceTests(MockLmsTest):
    async def test_enrolled_course_returns_verified_teacher_text_and_attachments(self):
        result = await server.get_assignment_workspace("1001", "A-test-a")

        self.assertEqual(result, {"status": "ok", "assignment": {
            "courseId": "A-test-a", "courseName": "테스트 강좌 A", "assignmentId": "1001",
            "title": "테스트 과제", "dueAt": "2026-11-20T23:59:00+09:00",
            "lateDueAt": "2026-11-24T18:00:00+09:00", "submitted": False,
            "description": POST.content,
            "attachments": ({"id": "9001", "name": "테스트 안내.pdf"},),
            "submissionMethod": "온라인", "submissionFormat": "글 입력 / 파일첨부", "publishedAt": "2026-11-13T10:16:00+09:00",
            "points": "0점", "scoreVisibility": "비공개",
        }})
        self.client.get_post.assert_awaited_once_with("assignment", "1001", "A-test-a")
        self.client.list_posts.assert_not_awaited()
        self.write.assert_not_called()

    async def test_unenrolled_course_is_rejected_without_reading_assignment(self):
        result = await server.get_assignment_workspace("1001", "not-enrolled")

        self.assertEqual(result["status"], "error")
        self.client.get_post.assert_not_awaited()
        self.client.list_posts.assert_not_awaited()

    async def test_legacy_link_resolves_only_unique_matching_course(self):
        self.client.list_posts.side_effect = [[POST], []]

        result = await server.get_assignment_workspace("1001")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["assignment"]["courseId"], "A-test-a")
        self.assertEqual(self.client.list_posts.await_count, 2)
        self.client.get_post.assert_awaited_once_with("assignment", "1001", "A-test-a")

    async def test_ambiguous_or_missing_legacy_link_never_reads_a_guessed_course(self):
        for responses in ([[POST], [POST]], [[], []]):
            with self.subTest(responses=responses):
                self.client.list_posts.side_effect = responses
                result = await server.get_assignment_workspace("1001")
                self.assertEqual(result["status"], "error")
                self.client.get_post.assert_not_awaited()

    async def test_assignment_not_in_selected_course_is_not_retried_in_another_course(self):
        self.client.get_post.side_effect = ValueError("synthetic course mismatch")

        result = await server.get_assignment_workspace("1001", "A-test-b")

        self.assertEqual(result["status"], "error")
        self.client.get_post.assert_awaited_once_with("assignment", "1001", "A-test-b")
        self.client.list_posts.assert_not_awaited()

    async def test_expired_session_returns_login_required_without_reading_details(self):
        self.client.get_courses.side_effect = AuthenticationRequired("synthetic expired login")

        result = await server.get_assignment_workspace("1001", "A-test-a")

        self.assertEqual(result["status"], "login_required")
        self.client.get_post.assert_not_awaited()
        self.write.assert_not_called()

    async def test_invalid_assignment_id_is_rejected_before_opening_client(self):
        result = await server.get_assignment_workspace("../invalid", "A-test-a")

        self.assertEqual(result["status"], "error")
        self.factory.assert_not_called()


class AssignmentAttachmentFileTests(unittest.IsolatedAsyncioTestCase):
    download = "/ilos/co/efile_download.acl"
    redirect = "/ilos/co/file_download_v2.acl"
    course_id = "A-test-a"
    assignment_id = "1001"
    attachment_id = "9001"
    content_seq = "assignment-list-key"
    download_content_seq = "attachment-download-key"

    def setUp(self):
        self.client = SeoultechLMSClient()
        self.requests = []
        self.query = f"FILE_SEQ={self.attachment_id}&CONTENT_SEQ={self.download_content_seq}&ky={self.course_id}"
        self.file_name = "과제 자료.txt"
        self.original = b"original assignment bytes"
        self.response_headers = {"content-type": "text/plain; charset=utf-8"}
        self.download_location = None
        self.download_status = 200

        @asynccontextmanager
        async def query_client():
            yield self.client

        self.enterContext(patch.object(server, "_query_client", query_client))

    def respond(self, request):
        path = request.url.path
        self.requests.append((request.method, path))
        if path == MAIN_FORM:
            return httpx.Response(200, text=f"""
                <a class="logout" href="/ilos/lo/logout.acl"></a>
                <div class="my_lecture_container"><a id="kj_1" onclick="eclassRoom('{self.course_id}')">테스트 강좌</a></div>""")
        if path == ENTER_COURSE:
            return httpx.Response(200, json={"isError": False})
        if path == ACTIVITY_LIST:
            return httpx.Response(200, text=f"""
                <a class="activity not_submit" id="class_menu_report_{self.assignment_id}">
                <span class="activity_title">테스트 과제</span></a>""")
        if path == REPORT_VIEW:
            self.assertEqual(request.url.params["RT_SEQ"], self.assignment_id)
            return httpx.Response(200, text=f"""
                <div class="bbsview"><div class="editor_content">교수자 안내</div></div>
                <script>$.ajax({{
                    url: "{COURSE_ATTACHMENT_LIST}", type: "POST",
                    data: {{ud: "synthetic", ky: "{self.course_id}", pf_st_flag: "2",
                            CONTENT_SEQ: "{self.content_seq}", encoding: "utf-8"}}
                }});</script>""")
        if path == COURSE_ATTACHMENT_LIST:
            self.assertEqual(httpx.QueryParams(request.content.decode())["CONTENT_SEQ"], self.content_seq)
            return httpx.Response(200, text=f"""
                <ul class="attach_list"><li>
                <a href="{self.download}?{self.query.replace("&", "&amp;")}">{self.file_name}</a>
                </li></ul>""")
        if path in (self.download, self.redirect):
            self.assertEqual(request.url.params["CONTENT_SEQ"], self.download_content_seq)
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            if path == self.download and self.download_location:
                return httpx.Response(302, headers={"location": self.download_location})
            return httpx.Response(self.download_status, content=self.original, headers=self.response_headers)
        self.fail(f"검증되지 않은 테스트 요청 {request.method} {path}")

    async def fetch(self, attachment_id=None, *, for_analysis=False):
        self.requests.clear()
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.respond)) as http:
            self.client._http = http
            return await server.get_assignment_attachment_file(
                self.course_id, self.assignment_id, attachment_id or self.attachment_id, for_analysis=for_analysis,
            )

    async def test_original_is_returned_in_structured_content_only(self):
        result = await self.fetch()

        self.assertEqual(result.content, [])
        data = dict(result.structuredContent)
        self.assertEqual(b64decode(data.pop("base64")), self.original)
        self.assertEqual(data, {
            "status": "ok", "course_id": self.course_id, "assignment_id": self.assignment_id,
            "attachment_id": self.attachment_id, "name": self.file_name, "mime": "text/plain",
            "size_bytes": len(self.original),
        })
        self.assertEqual(self.requests[-1], ("GET", self.download))

    async def test_encrypted_pdf_is_blocked_for_analysis_but_available_as_an_original(self):
        self.file_name = "과제.pdf"
        self.response_headers = {"content-type": "application/pdf"}
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_metadata({"/Title": "Synthetic text mentioning /Encrypt"})
        stream = BytesIO()
        writer.write(stream)
        self.original = stream.getvalue()
        plain = (await self.fetch(for_analysis=True)).structuredContent
        self.assertEqual(b64decode(plain["base64"]), self.original)

        writer.encrypt("fixture-password")
        stream = BytesIO()
        writer.write(stream)
        self.original = stream.getvalue()
        encrypted = (await self.fetch(for_analysis=True)).structuredContent
        self.assertEqual(encrypted, {
            "status": "error", "code": "pdf_encrypted", "message": "암호화된 PDF라 열 수 없어요.",
        })
        original = (await self.fetch()).structuredContent
        self.assertEqual(b64decode(original["base64"]), self.original)

        self.original = self.original.replace(b"/Standard", b"/TestDRM ")
        unsupported_encryption = (await self.fetch(for_analysis=True)).structuredContent
        self.assertEqual(unsupported_encryption, encrypted)

    async def test_wrong_attachment_or_inconsistent_scope_is_never_downloaded(self):
        wrong_id = (await self.fetch("9002")).structuredContent
        self.assertEqual(wrong_id["code"], "attachment_not_found")
        self.assertNotIn(("GET", self.download), self.requests)

        original_query = self.query
        for query in (
            original_query + "&CONTENT_SEQ=another-download-key",
            original_query.replace(self.download_content_seq, ""),
            original_query.replace(self.course_id, "other-course"),
            original_query + f"&FILE_SEQ={self.attachment_id}",
        ):
            with self.subTest(query=query):
                self.query = query
                result = (await self.fetch()).structuredContent
                self.assertEqual(result["code"], "attachment_not_found")
                self.assertNotIn(("GET", self.download), self.requests)

    async def test_only_verified_redirect_preserves_assignment_scope(self):
        query = self.query.replace(self.attachment_id, "opaque-token")
        self.download_location = f"{self.redirect}?{query}"
        result = (await self.fetch()).structuredContent
        self.assertEqual(b64decode(result["base64"]), self.original)
        self.assertEqual(self.requests[-2:], [("GET", self.download), ("GET", self.redirect)])

        for location in (
            f"https://outside.example{self.redirect}?{query}",
            f"{self.redirect}?{query.replace(self.download_content_seq, 'other-seq')}",
        ):
            with self.subTest(location=location):
                self.download_location = location
                result = (await self.fetch()).structuredContent
                self.assertEqual(result["code"], "attachment_request_blocked")
                self.assertEqual(self.requests[-1], ("GET", self.download))

    async def test_html_attachments_require_a_file_disposition(self):
        self.original = b"<script>example()</script>"
        self.file_name = "sample.html"
        self.response_headers = {"content-type": "text/html"}
        result = (await self.fetch()).structuredContent
        self.assertEqual(result["code"], "attachment_download_failed")
        self.assertNotIn("base64", result)

        self.response_headers["content-disposition"] = 'attachment; filename="sample.html"'
        result = (await self.fetch()).structuredContent
        self.assertEqual(result["mime"], "text/html")
        self.assertEqual(b64decode(result["base64"]), self.original)

    async def test_size_limits_apply_with_and_without_a_response_length(self):
        self.response_headers["content-length"] = str(32 * 1024 * 1024 + 1)
        result = (await self.fetch()).structuredContent
        self.assertEqual(result["code"], "file_too_large")
        self.assertNotIn("base64", result)

        del self.response_headers["content-length"]
        with patch("seoultech_lms.client._MAX_ASSIGNMENT_ATTACHMENT_BYTES", len(self.original) - 1):
            result = (await self.fetch()).structuredContent
        self.assertEqual(result["code"], "file_too_large")
        self.assertNotIn("base64", result)

    async def test_login_redirect_reports_a_session_error(self):
        self.download_location = "/ilos/main/member/login_form.acl"
        result = (await self.fetch()).structuredContent
        self.assertEqual(result["status"], "login_required")
        self.assertNotIn("base64", result)


class BrowserLoginConfirmationTests(MockLmsTest):
    async def test_invalid_cookies_never_open_client_or_replace_saved_session(self):
        invalid_sets = [
            [], COOKIES * 65,
            [{**COOKIES[0], "domain": "other.example"}],
            [{**COOKIES[0], "path": "relative"}],
            [{**COOKIES[0], "path": None}],
            [{**COOKIES[0], "name": ""}],
            [{**COOKIES[0], "value": "x" * 4097}],
        ]
        for cookies in invalid_sets:
            with self.subTest(cookies=cookies):
                self.assertEqual((await server.confirm_browser_login(cookies))["status"], "login_required")
        self.factory.assert_not_called()
        self.write.assert_not_called()
        self.clear.assert_not_called()

    async def test_rejected_or_unreachable_login_does_not_replace_saved_session(self):
        for error, expected in [
            (AuthenticationRequired("synthetic expired session"), "login_required"),
            (httpx.ConnectError("synthetic connection failure"), "error"),
        ]:
            with self.subTest(error=type(error).__name__):
                self.client.get_login_roster.side_effect = error
                self.assertEqual((await server.confirm_browser_login(COOKIES))["status"], expected)
                self.write.assert_not_called()
                self.clear.assert_not_called()

    async def test_session_is_saved_only_after_authentication_finishes_successfully(self):
        entered = asyncio.Event()
        verified = asyncio.Event()

        async def verify_login():
            entered.set()
            await verified.wait()
            return CourseRoster(COURSES, True)

        self.client.get_login_roster.side_effect = verify_login
        task = asyncio.create_task(server.confirm_browser_login(COOKIES))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            self.write.assert_not_called()
            self.clear.assert_not_called()
            verified.set()
            result = await asyncio.wait_for(task, timeout=2)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        state = {"cookies": COOKIES, "origins": []}
        self.factory.assert_called_once_with(browser_state=state)
        self.assertEqual(result["status"], "authenticated")
        self.write.assert_called_once_with(self.path, state)
        self.clear.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
