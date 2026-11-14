from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx

from seoultech_lms import mcp_server as server
from seoultech_lms.auth import AuthenticationRequired
from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.content import FileLink
from seoultech_lms.models import Attachment


class AttachmentErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = SeoultechLMSClient()
        self.file_links = self.enterContext(patch.object(self.client, "_course_file_links", new_callable=AsyncMock))
        self.file_links.return_value = [FileLink(
            Attachment("fixture-file", "example.pdf"),
            "/ilos/co/efile_download.acl?FILE_SEQ=fixture-file&CONTENT_SEQ=1&ky=example-course",
        )]

        @asynccontextmanager
        async def query_client():
            yield self.client

        self.enterContext(patch.object(server, "_query_client", query_client))

    async def test_missing_source_identifiers_are_reported_before_listing(self) -> None:
        missing_course = await server.read_attachment("file_collection", "fixture-file")
        missing_post = await server.read_attachment("assignment", "fixture-file", "example-course")
        self.assertEqual(missing_course["code"], "missing_course_id")
        self.assertEqual(missing_post["code"], "missing_post_id")
        self.file_links.assert_not_awaited()

    async def test_file_collection_id_does_not_match_an_assignment_attachment(self) -> None:
        with patch.object(self.client, "_post_with_links", new=AsyncMock(return_value=(None, []))):
            result = await server.read_attachment("assignment", "fixture-file", "example-course", "example-post")
        self.assertEqual((result["status"], result["code"]), ("error", "attachment_not_found"))

    async def test_authentication_error_uses_safe_message(self) -> None:
        self.file_links.side_effect = AuthenticationRequired("synthetic sensitive details")
        result = await server.read_attachment("file_collection", "fixture-file", "example-course")
        self.assertEqual((result["status"], result["code"]), ("login_required", "login_required"))
        self.assertNotIn("synthetic sensitive details", result["message"])

    async def test_download_error_codes_preserve_the_original_guard(self) -> None:
        cases = (
            (302, {"location": "https://example.com/synthetic-token"}, "attachment_request_blocked"),
            (200, {"content-type": "application/pdf", "content-length": "13000000"}, "file_too_large"),
        )
        for status, headers, code in cases:
            calls = []

            def handle(request: httpx.Request) -> httpx.Response:
                calls.append(request.url.path)
                return httpx.Response(status, headers=headers)

            with self.subTest(code=code):
                async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                    self.client._http = http
                    result = await server.read_attachment("file_collection", "fixture-file", "example-course")
                self.assertEqual((result["status"], result["code"]), ("error", code))
                self.assertNotIn("synthetic-token", result["message"])
                self.assertEqual(calls, ["/ilos/co/efile_download.acl"])
