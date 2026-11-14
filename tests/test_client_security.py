from __future__ import annotations

import asyncio
import unittest

import httpx

from seoultech_lms.client import ReadOnlyViolation, SeoultechLMSClient
from seoultech_lms.endpoints import BASE_URL, DISCUSSION_COMMENT_LIST, MAIN_FORM


class ClientSecurityTests(unittest.TestCase):
    def _run_request(self, handler, method: str = "GET", target: str = MAIN_FORM):
        async def run():
            client = SeoultechLMSClient()
            client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                return await client._request(method, target)
            finally:
                await client._http.aclose()

        return asyncio.run(run())

    def test_external_origin_with_allowed_path_is_blocked_before_network(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, request=request)

        with self.assertRaises(ReadOnlyViolation):
            self._run_request(handler, target=f"https://example.com{MAIN_FORM}")
        self.assertEqual(calls, [])

    def test_external_redirect_is_blocked(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": f"https://example.com{MAIN_FORM}"},
                request=request,
            )

        with self.assertRaises(ReadOnlyViolation):
            self._run_request(handler)

    def test_same_origin_redirect_to_non_allowlisted_path_is_blocked(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"location": "/ilos/cls/st/report/report_submit.acl"},
                request=request,
            )

        with self.assertRaises(ReadOnlyViolation):
            self._run_request(handler)

    def test_discussion_writes_are_blocked_before_network(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.fail(f"Unexpected LMS request: {request.method} {request.url.path}")

        for target in (
            "/ilos/cls/st/discuss/discuss_detail_insert_pop.acl",
            "/ilos/cls/st/discuss/discuss_detail_insert.acl",
            "/ilos/cls/st/discuss/discuss_detail_update_pop.acl",
            "/ilos/cls/st/discuss/discuss_detail_update.acl",
            "/ilos/cls/st/discuss/discuss_detail_delete.acl",
            "/ilos/cls/st/discuss/artl_good_insert.acl",
            "/ilos/cls/st/discuss/artl_good_cancel.acl",
            "/ilos/cls/st/co/cmmt_insert.acl",
            "/ilos/cls/st/co/cmmt_update.acl",
            "/ilos/cls/st/co/cmmt_delete.acl",
        ):
            for method in ("GET", "POST"):
                with self.subTest(target=target, method=method), self.assertRaises(ReadOnlyViolation):
                    self._run_request(handler, method=method, target=target)

    def test_comment_read_cannot_redirect_to_write(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(307, headers={"location": "/ilos/cls/st/co/cmmt_insert.acl"})

        with self.assertRaises(ReadOnlyViolation):
            self._run_request(handler, method="POST", target=DISCUSSION_COMMENT_LIST)
        self.assertEqual(calls, [DISCUSSION_COMMENT_LIST])

    def test_allowlisted_response_succeeds(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok", request=request)

        response = self._run_request(handler, target=f"{BASE_URL}{MAIN_FORM}")
        self.assertEqual(response.text, "ok")

    def test_pdf_download_uses_only_the_verified_same_origin_redirect(self):
        initial = "/ilos/co/efile_download.acl?FILE_SEQ=PUBLIC&CONTENT_SEQ=1&ky=A1"
        allowed = f"{BASE_URL}//ilos/co/file_download_v2.acl?FILE_SEQ=OPAQUE&CONTENT_SEQ=1&ky=A1"
        rejected = (
            "https://example.com/ilos/co/file_download_v2.acl?FILE_SEQ=OPAQUE&CONTENT_SEQ=1&ky=A1",
            f"{BASE_URL}/ilos/cls/st/report/report_submit.acl?FILE_SEQ=OPAQUE&CONTENT_SEQ=1&ky=A1",
            f"{BASE_URL}/ilos/co/file_download_v2.acl?FILE_SEQ=OPAQUE&CONTENT_SEQ=2&ky=A1",
        )
        for location in (allowed, *rejected):
            calls = []

            def handler(request: httpx.Request) -> httpx.Response:
                calls.append(request.url)
                if len(calls) == 1:
                    return httpx.Response(302, headers={"location": location})
                return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"%PDF-test")

            async def run() -> bytes:
                client = SeoultechLMSClient()
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
                    client._http = transport
                    return await client._download_pdf(initial)

            with self.subTest(location=location):
                if location == allowed:
                    self.assertEqual(asyncio.run(run()), b"%PDF-test")
                    self.assertEqual(len(calls), 2)
                else:
                    with self.assertRaises(ReadOnlyViolation):
                        asyncio.run(run())
                    self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
