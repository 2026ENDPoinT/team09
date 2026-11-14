from __future__ import annotations

import unittest

import httpx

from seoultech_lms.campus_notices import CampusNoticeClient, campus_image_url


def _row(board_id: int, notice_id: int, *, pinned: bool = False) -> str:
    number = '<img alt="공지">' if pinned else str(notice_id)
    return f"""
    <tr class="body_tr">
      <td>{number}</td>
      <td><a href="?do=commonview&amp;bnum={board_id}&amp;bidx={notice_id}">제목 {notice_id}</a></td>
      <td class="file"><img alt="한글파일"></td><td>학사지원과</td><td>2026-11-01</td><td>1</td>
    </tr>
    """


def _list_page(page: int) -> str:
    next_link = f'<a href="javascript:dcPaging({page + 1})">다음</a>' if page < 4 else ""
    return f"""
    <table class="tbl_list"><tbody>
      {_row(6112, 100, pinned=True)}
      {_row(57139, 100 + page)}
    </tbody></table>
    <div class="dc-paging"><a class="on">{page}</a>{next_link}</div>
    """


class CampusNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_pages_deduplicate_and_more_resumes(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "www.seoultech.ac.kr")
            self.assertEqual(request.url.path, "/service/info/matters")
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.params["size"], "15")
            self.assertNotIn("cookie", request.headers)
            page = int(request.url.params["page"])
            requests.append(page)
            return httpx.Response(200, text=_list_page(page))

        client = CampusNoticeClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            result = await client.list_notices("matters")
            more = await client.list_notices("matters", start_page=result["next_page"], pages=1)

        self.assertEqual(requests, [1, 2, 3, 4])
        self.assertEqual([row["id"] for row in result["notices"]], ["100", "101", "102", "103"])
        self.assertEqual([row["pinned"] for row in result["notices"]], [True, False, False, False])
        self.assertEqual(result["notices"][1]["board_id"], "57139")
        self.assertTrue(result["notices"][1]["has_attachments"])
        self.assertEqual(result["next_page"], 4)
        self.assertEqual([row["id"] for row in more["notices"]], ["100", "104"])
        self.assertIsNone(more["next_page"])

    async def test_read_detail_and_keep_only_verified_asset_references(self) -> None:
        html = """
        <table class="tbl_view"><tbody>
          <tr><th>제목</th><td>예시 공지</td></tr>
          <tr><th>작성자</th><td>예시 부서</td><th>날짜</th><td>2026-11-01</td></tr>
          <tr><th>첨부파일</th><td><ul class="list_attach">
            <li><a href="javascript:downloadfile('/storage/www/bbs/57139','TEST_FILE.hwpx','예시 파일.hwpx');">예시 파일.hwpx</a></li>
            <li><a href="javascript:downloadfile('/storage/www/bbs/6112','OTHER_FILE.zip','다른 게시판.zip');">다른 게시판.zip</a></li>
          </ul></td></tr>
          <tr><td class="cont">
            <p>예시 <b>본문</b><br>둘째 줄</p>
            <table><tr><th>제목</th><td>본문 표의 제목</td></tr></table>
            <img src="/storage/www/ckfinder/images/sample.png" alt="예시 이미지">
            <img src="https://external.example/image.png" alt="외부 이미지">
            <a href="https://external.example/info">참고 링크</a>
            <a href="javascript:alert(1)">실행 링크</a>
            <script>prompt("sample")</script>
          </td></tr>
        </tbody></table>
        """

        def respond(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/service/info/matters")
            self.assertEqual(dict(request.url.params), {"do": "commonview", "bnum": "57139", "bidx": "101"})
            return httpx.Response(200, text=html)

        client = CampusNoticeClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            result = await client.get_notice("matters", "57139", "101")

        self.assertEqual(result["title"], "예시 공지")
        self.assertIn("예시 본문\n둘째 줄", result["content"])
        self.assertNotIn("prompt(", result["content"])
        self.assertEqual(result["links"], [{"url": "https://external.example/info", "text": "참고 링크"}])
        self.assertEqual(len(result["attachments"]), 1)
        self.assertEqual(result["attachments"][0]["download_fields"], {
            "fpath": "/storage/www/bbs/57139", "fname": "TEST_FILE.hwpx", "ogrfname": "예시 파일.hwpx",
        })
        self.assertEqual(len(result["images"]), 1)
        self.assertEqual(result["images"][0]["url"], "https://www.seoultech.ac.kr/storage/www/ckfinder/images/sample.png")
        self.assertNotEqual(result["images"][0]["id"], result["attachments"][0]["id"])

    async def test_invalid_board_id_and_reset_pager(self) -> None:
        client = CampusNoticeClient()
        with self.assertRaises(ValueError):
            await client.get_notice("matters", "57925", "101")
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=_list_page(1)),
        )) as http:
            client._http = http
            with self.assertRaisesRegex(RuntimeError, "요청한 공지 페이지"):
                await client.list_notices("matters", start_page=2, pages=1)

    def test_rejects_image_traversal_and_external_hosts(self) -> None:
        for url in (
            "/storage/www/ckfinder/images/%2e%2e/secret.png",
            "/storage/www/ckfinder/images/%252e%252e/secret.png",
            "/storage/www/ckfinder/images/example.svg",
            "//www.seoultech.ac.kr.external.example/storage/www/ckfinder/images/sample.png",
            "http://www.seoultech.ac.kr/storage/www/ckfinder/images/sample.png",
        ):
            with self.subTest(url=url):
                self.assertIsNone(campus_image_url(url))
