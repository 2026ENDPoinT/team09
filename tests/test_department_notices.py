import unittest

import httpx

from seoultech_lms.department_notices import DepartmentNoticeClient


def response(request, html):
    return httpx.Response(200, text=html, request=request)


def pager(page, next_page):
    return f'<div class="dc-paging"><a class="on">{page}</a><a href="javascript:dcPaging({next_page})">다음</a></div>'


def standard_row(board, notice, title):
    return f"""<tr><td><img alt="notice"></td>
      <td><a href="?do=view&bnum={board}&bidx={notice}">{title}</a></td>
      <td><img alt="pdf"></td><td>학과</td><td>2026-11-12</td><td>1</td></tr>"""


class DepartmentNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self, handler):
        client = DepartmentNoticeClient()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client._http.aclose)
        return client

    async def test_standard_college_rows_are_scoped_and_paged(self):
        calls = []

        def handler(request):
            calls.append(request.url)
            page = int(request.url.params["page"])
            rows = standard_row("2836", f"100{page}", f"공식 공지 {page}")
            rows += standard_row("8888", "9000", "다른 게시판")
            return response(request, f'<table class="board"><tbody>{rows}</tbody></table>' + pager(page, 2))

        client = await self.fixture(handler)
        result = await client.list_notices("college:information", pages=2)
        self.assertEqual([row["id"] for row in result["notices"]], ["1001", "1002"])
        self.assertEqual(result["notices"][0]["url"],
                         "https://ice.seoultech.ac.kr/community/notice/bulletin?do=commonview&bnum=2836&bidx=1001")
        self.assertTrue(result["notices"][0]["pinned"])
        self.assertIsNone(result["next_page"])
        with self.assertRaises(ValueError):
            await client.get_notice("college:information", "8888", "1001")
        with self.assertRaises(ValueError):
            await client.list_notices("https://unknown.example/")
        self.assertEqual(len(calls), 2)

    async def test_international_card_and_standard_detail_use_body_and_resources(self):
        def handler(request):
            self.assertEqual(request.url.host, "ic.seoultech.ac.kr")
            if request.url.params.get("do") != "commonview":
                return response(request, """
                  <div class="blog_list"><div class="list">
                    <h2><a href="?do=commonview&amp;bnum=58128&amp;bidx=1001">No.15 유학생 공지</a></h2>
                    <div class="date">등록날짜 : 2026-11-10 조회수 : 10</div>
                    <div class="box"><div class="text">미리보기</div></div>
                  </div></div>""")
            return response(request, """
              <table class="tbl_view">
                <tr><th>Title</th><td>유학생 공지</td></tr>
                <tr><th>Date</th><td>2026-11-10</td><th>Writer</th><td>국제대학</td></tr>
                <tr><th>Files</th><td><ul class="list_attach">
                  <li><a href="javascript:downloadfile('/storage/ic/bbs/58128','file.pdf','안내.pdf');">안내.pdf</a></li>
                  <li><a href="javascript:downloadfile('/storage/ic/bbs/555','other.pdf','다른 글.pdf');">다른 글.pdf</a></li>
                </ul></td></tr>
                <tr><td class="cont"><p>신청 방법</p><p hidden>숨은 글</p>
                  <img src="/storage/ic/ckfinder/images/test.png" alt="포스터">
                  <img src="https://unrelated.example/test.png" alt="외부">
                  <img src="/storage/ic/ckfinder/images/%2e%2e/test.png" alt="이탈">
                </td></tr>
              </table>""")

        client = await self.fixture(handler)
        row = (await client.list_notices("college:international"))["notices"][0]
        self.assertEqual((row["title"], row["published_at"], row["preview"]), ("유학생 공지", "2026-11-10", "미리보기"))
        article = await client.get_notice("college:international", row["board_id"], row["id"])
        self.assertEqual(article["content"], "신청 방법")
        self.assertEqual((article["published_at"], article["department"]), ("2026-11-10", "국제대학"))
        self.assertEqual(article["images"][0]["url"], "https://ic.seoultech.ac.kr/storage/ic/ckfinder/images/test.png")
        self.assertEqual(len(article["images"]), 1)
        self.assertEqual([file["name"] for file in article["attachments"]], ["안내.pdf"])
        self.assertNotIn("download_fields", article["attachments"][0])

    async def test_architecture_cards_use_offset_and_custom_detail_route(self):
        calls = []

        def handler(request):
            calls.append(dict(request.url.params))
            if request.url.params.get("bgu") == "view":
                return response(request, """
                  <article class="bbs-view-con">
                    <aside class="bbs-view-top"><h1 class="bbs-tit">건축 실습 공지</h1>
                      <dl class="bbs-write-info"><dt>등록일</dt><dd>2026-11-12</dd></dl></aside>
                    <div class="bbs-file-list-wrap">
                      <a class="file-item" href="/bbs/bbs_download.php?idx=1001&amp;download=2"><dd>신청서.pdf</dd></a>
                      <a class="file-item" href="/bbs/bbs_download.php?idx=9999&amp;download=1"><dd>외부.pdf</dd></a>
                    </div><div class="bbs-view-content"><p>실습 시간표</p></div>
                  </article>""")
            first = request.url.params["startPage"] == "0"
            current = 1 if first else 2
            return response(request, f"""
              <article class="bbs-gallery-list-con"><ul class="bbs-basic-gallery-con">
                <li><a href="/kr/info/notice.php?bgu=view&amp;idx=100{current}">
                  <strong class="gal-tit">건축 실습 공지 <span class="file-icon"></span></strong>
                  <span class="gal-day">26.11.12</span>
                </a></li>
              </ul></article><div class="paging"><a class="cur">{current}</a>
                <a href="?startPage=10">2</a></div>""")

        client = await self.fixture(handler)
        page = await client.list_notices("department:architecture-design", pages=2)
        self.assertEqual([notice["id"] for notice in page["notices"]], ["1001", "1002"])
        self.assertEqual(page["notices"][0]["published_at"], "2026-11-12")
        self.assertTrue(page["notices"][0]["has_attachments"])
        article = await client.get_notice("department:architecture-design", "1", "1001")
        self.assertEqual(article["content"], "실습 시간표")
        self.assertEqual([file["name"] for file in article["attachments"]], ["신청서.pdf"])
        self.assertEqual(calls, [{"startPage": "0"}, {"startPage": "10"}, {"bgu": "view", "idx": "1001"}])
