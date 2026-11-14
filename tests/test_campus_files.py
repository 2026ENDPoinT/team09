from __future__ import annotations

import unittest
from urllib.parse import parse_qs
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from seoultech_lms.campus_files import fetch_campus_notice_file
from seoultech_lms.campus_notices import ATTACHMENT_DOWNLOAD_URL


class CampusFileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.notice = {
            "url": "https://www.seoultech.ac.kr/service/info/notice?do=commonview&bnum=4691&bidx=123",
            "attachments": [{
                "id": "attachment-1",
                "name": "안내.pdf",
                "download_fields": {
                    "fpath": "/storage/www/bbs/4691", "fname": "stored.pdf", "ogrfname": "안내.pdf",
                },
            }],
            "images": [],
        }

    async def _fetch(self, response_handler):
        notices = MagicMock()
        notices.__aenter__.return_value.get_notice = AsyncMock(return_value=self.notice)
        transport = httpx.MockTransport(response_handler)
        async_client = httpx.AsyncClient
        with (
            patch("seoultech_lms.campus_files.CampusNoticeClient", return_value=notices),
            patch("seoultech_lms.campus_files.httpx.AsyncClient", side_effect=lambda **kw: async_client(transport=transport, **kw)),
        ):
            return await fetch_campus_notice_file("notice", "4691", "123", "attachment-1")

    async def test_uses_school_download_form_without_lms_cookies(self):
        def respond(request):
            self.assertEqual(str(request.url), ATTACHMENT_DOWNLOAD_URL)
            self.assertEqual(request.method, "POST")
            self.assertNotIn("cookie", request.headers)
            self.assertEqual(parse_qs(request.content.decode())["fname"], ["stored.pdf"])
            return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=httpx.ByteStream(b"%PDF-test"))

        file = await self._fetch(respond)
        self.assertEqual((file.name, file.content), ("안내.pdf", b"%PDF-test"))

    async def test_does_not_download_a_file_outside_the_verified_board(self):
        self.notice["attachments"][0]["download_fields"]["fpath"] = "/storage/www/bbs/999"
        with self.assertRaises(ValueError):
            await self._fetch(lambda request: self.fail(f"Unexpected request: {request.url}"))

    async def test_download_does_not_follow_an_external_redirect(self):
        def respond(request):
            self.assertEqual(str(request.url), ATTACHMENT_DOWNLOAD_URL)
            return httpx.Response(307, headers={"Location": "https://example.com/"})

        with self.assertRaises(httpx.HTTPStatusError):
            await self._fetch(respond)

    async def test_rejects_compressed_http_responses_before_reading(self):
        def respond(_request):
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"unused"))

        with self.assertRaisesRegex(RuntimeError, "원본 파일"):
            await self._fetch(respond)
