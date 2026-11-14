from __future__ import annotations

import asyncio
import unittest
from base64 import b64decode
from contextlib import asynccontextmanager
from io import BytesIO
from unittest.mock import AsyncMock, patch

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from seoultech_lms import mcp_server as server
from seoultech_lms.client import SeoultechLMSClient, _extract_course_pdf
from seoultech_lms.content import FileLink
from seoultech_lms.models import Attachment


def pdf(*page_texts: str) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for text in page_texts:
        page = writer.add_blank_page(width=200, height=200)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def link(number: int, extension: str = "pdf") -> FileLink:
    file_id = f"example-{number}"
    return FileLink(Attachment(file_id, f"sample-{number}.{extension}"),
                    f"/ilos/co/efile_download.acl?FILE_SEQ={file_id}&CONTENT_SEQ=1&ky=example-course")


class CoursePdfTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = SeoultechLMSClient()
        self.listing = self.enterContext(patch.object(self.client, "_course_file_links", new_callable=AsyncMock))

        @asynccontextmanager
        async def query_client():
            yield self.client

        self.enterContext(patch.object(server, "_query_client", query_client))

    async def test_bulk_reads_eleven_files_and_all_pages_from_one_course_listing(self) -> None:
        self.listing.return_value = [link(number) for number in range(11)] + [link(99, "txt")]
        content = pdf(*(f"Synthetic page {index + 1}" for index in range(13)))
        calls = []
        inflight = 0
        peak = 0

        async def handle(request: httpx.Request) -> httpx.Response:
            nonlocal inflight, peak
            calls.append(request.url.params["FILE_SEQ"])
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0)
            inflight -= 1
            return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
            self.client._http = transport
            result = await server.read_course_pdfs("example-course")

        self.listing.assert_awaited_once_with("example-course")
        self.assertCountEqual(calls, [f"example-{index}" for index in range(11)])
        self.assertEqual(peak, 3)
        self.assertEqual((result["status"], result["total_files"], result["next_file"]), ("ok", 11, None))
        self.assertEqual([file["id"] for file in result["files"]], [f"example-{index}" for index in range(11)])
        for file in result["files"]:
            self.assertEqual((file["status"], file["read_pages"], file["total_pages"]), ("ok", 13, 13))
            self.assertEqual(file["pages"][-1], "Synthetic page 13")

    async def test_blocked_redirect_and_empty_text_preserve_other_file_results(self) -> None:
        self.listing.return_value = [link(index) for index in range(3)]
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request.url.host)
            file_id = request.url.params["FILE_SEQ"]
            if file_id == "example-0":
                return httpx.Response(302, headers={"location": "https://outside.test/synthetic-token"})
            text = "" if file_id == "example-1" else "Still readable"
            return httpx.Response(200, content=pdf(text), headers={"content-type": "application/pdf"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
            self.client._http = transport
            result = await server.read_course_pdfs("example-course")

        blocked, scan, ok = result["files"]
        self.assertEqual((blocked["status"], blocked["code"]), ("error", "attachment_request_blocked"))
        self.assertNotIn("synthetic-token", blocked["message"])
        self.assertEqual((scan["status"], scan["read_pages"], scan["text_pages"], scan["pages"]), ("no_text", 1, 0, [""]))
        self.assertEqual((ok["status"], ok["pages"]), ("ok", ["Still readable"]))
        self.assertEqual(len(set(requests)), 1)

    async def test_next_file_counts_pdfs_only_and_respects_requested_slice(self) -> None:
        self.listing.return_value = [link(0), link(9, "txt"), link(1), link(2)]
        downloader = AsyncMock(return_value=pdf("Synthetic page"))
        with patch.object(self.client, "_download_pdf", downloader):
            result = await server.read_course_pdfs("example-course", start_file=2, max_files=1)
        self.assertEqual((result["total_files"], result["start_file"], result["next_file"]), (3, 2, 3))
        self.assertEqual([file["id"] for file in result["files"]], ["example-1"])
        downloader.assert_awaited_once_with(link(1).href, budget=None)

    def test_truncating_long_pages_retains_text_from_later_pages(self) -> None:
        content = pdf("Long first page", "end")
        with patch("seoultech_lms.client._MAX_COURSE_PDF_CHARS", 10):
            result = _extract_course_pdf(Attachment("fixture", "fixture.pdf"), content)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["shortened_pages"], [1])
        self.assertEqual(result["pages"], ["Long ", "end"])
        self.assertEqual(result["read_pages"], 2)

    async def test_originals_keep_every_pdf_byte_without_local_extraction(self) -> None:
        self.listing.return_value = [link(index) for index in range(11)] + [link(99, "txt")]
        contents = {f"example-{index}": pdf("", f"Original {index}") for index in range(11)}

        def handle(request: httpx.Request) -> httpx.Response:
            content = contents[request.url.params["FILE_SEQ"]]
            return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})

        with patch("seoultech_lms.client._open_pdf", side_effect=AssertionError("Raw downloads must not parse PDFs")):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
                self.client._http = transport
                reply = await server.get_course_pdf_originals("example-course")

        self.listing.assert_awaited_once_with("example-course")
        self.assertEqual(reply.content, [])  # Do not serialize the large result twice in stdio.
        result = reply.structuredContent
        self.assertEqual((result["status"], result["course_id"], result["total_files"]), ("ok", "example-course", 11))
        self.assertEqual([file["id"] for file in result["files"]], list(contents))
        for file in result["files"]:
            self.assertEqual(file["status"], "ok")
            self.assertEqual(file["size_bytes"], len(contents[file["id"]]))
            self.assertEqual(b64decode(file["base64"]), contents[file["id"]])

    async def test_originals_exceeding_the_combined_byte_limit_return_no_partial_bundle(self) -> None:
        self.listing.return_value = [link(0), link(1)]
        content = pdf("Synthetic page")

        def handle(request: httpx.Request) -> httpx.Response:
            # No Content-Length, so the limit must be enforced on the actual stream.
            return httpx.Response(200, stream=httpx.ByteStream(content), headers={"content-type": "application/pdf"})

        with patch("seoultech_lms.client._MAX_COURSE_PDF_BYTES", len(content) + 1):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
                self.client._http = transport
                reply = await server.get_course_pdf_originals("example-course")

        self.assertEqual(reply.structuredContent["code"], "pdf_batch_too_large")
        self.assertNotIn("files", reply.structuredContent)
