from __future__ import annotations

import unittest
from urllib.parse import parse_qs

import httpx

from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import (
    ACTIVITY_LIST, BASE_URL, DISCUSSION_COMMENT_LIST, DISCUSSION_OPINION_LIST,
    DISCUSSION_OPINION_VIEW, DISCUSSION_VIEW, ENTER_COURSE, MAIN_FORM,
)


ROSTER = """
<a class="logout" href="/ilos/lo/logout.acl">로그아웃</a>
<div class="my_lecture_container">
  <a id="kj_1" onclick="eclassRoom('A20260001')">예시 수업</a>
</div>
"""
OPINIONS = """
<input id="discuss_detail_cnt" value="1">
<button class="discuss_list_wrap" onclick="viewDiscussDetailPop('201');">
  <div class="discuss_list" data-num="201">
    <div class="reg_nm">익명</div>
    <div class="discuss_title">예시 의견</div>
    <div class="discuss_text">미리보기</div>
    <div class="idea_comment"></div><div>2</div>
  </div>
</button>
"""
OPINION_DETAIL = """
<div class="discuss_detail_content">
  <div class="editor_content"><p>전체 본문 첫 문단</p><p>전체 본문 두 번째 문단</p></div>
</div>
<button id="cmmt_btn201"><span id="cmmt_cnt201">2</span></button>
<script>cmmtList('201','K009','KC09','st','101');</script>
"""
COMMENTS = """
<div class="comment_container">
  <div class="comment_list" id="comment_301">
    <div class="comment_body_wrap">
      <div class="comment_body">
        <div class="comment_reg_user_nm">예시 작성자</div>
        <div class="comment_view">댓글 첫 줄<br>댓글 두 번째 줄<span class="comment_update_info">수정됨</span></div>
        <div class="comment_reply_body"><textarea>입력 폼 값</textarea></div>
      </div>
    </div>
  </div>
  <div class="comment_reply_list_wrap" id="comment_reply_list_wrap_301">
    <div class="comment_list" id="comment_302">
      <div class="comment_body_wrap">
        <div class="comment_body"><div class="comment_view">답글 본문</div></div>
      </div>
    </div>
  </div>
</div>
"""


class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.detail_html = OPINION_DETAIL
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._respond))
        self.addAsyncCleanup(self.http.aclose)
        self.client = SeoultechLMSClient()
        self.client._http = self.http

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        data = parse_qs(request.content.decode(), keep_blank_values=True)
        match request.url.path:
            case path if path == MAIN_FORM:
                return httpx.Response(200, text=ROSTER)
            case path if path == ENTER_COURSE:
                self.assertEqual(data["KJKEY"], ["A20260001"])
                return httpx.Response(200, json={"isError": False})
            case path if path == ACTIVITY_LIST:
                return httpx.Response(200, text='<a id="class_menu_discuss_101">예시 토론</a>')
            case path if path == DISCUSSION_VIEW:
                self.assertEqual(request.url.params["TOPIC_NO"], "101")
                return httpx.Response(200, text=f"""
                    <script>$.ajax({{
                        url: "{DISCUSSION_OPINION_LIST}", type: "POST",
                        data: {{ TOPIC_NO: "101", UNSIGN_YN: "Y", encoding: "utf-8" }}
                    }});</script>
                """)
            case path if path == DISCUSSION_OPINION_LIST:
                self.assertEqual(data["UNSIGN_YN"], ["Y"])
                return httpx.Response(200, text=OPINIONS)
            case path if path == DISCUSSION_OPINION_VIEW:
                self.assertEqual(data["TOPIC_NO"], ["101"])
                self.assertEqual(data["ARTL_NUM"], ["201"])
                return httpx.Response(200, text=self.detail_html)
            case path if path == DISCUSSION_COMMENT_LIST:
                self.assertEqual(data, {
                    "KJKEY": ["A20260001"], "MENU_SEQ": ["201"], "MENU_SEQ2": ["101"],
                    "BRD_ID": ["K009"], "CMMT_BRD_ID": ["KC09"], "auth": ["st"], "encoding": ["utf-8"],
                })
                return httpx.Response(200, text=COMMENTS)
            case _:
                self.fail(f"Unexpected LMS request: {request.method} {request.url.path}")

    async def test_reads_opinion_and_comment_bodies(self):
        opinions = await self.client.list_discussion_opinions("A20260001", "101")
        self.assertEqual([opinion.id for opinion in opinions], ["201"])
        self.assertEqual(opinions[0].author, "익명")
        self.assertEqual(opinions[0].comment_count, 2)
        self.assertIsNone(opinions[0].content)
        self.assertNotIn(("POST", DISCUSSION_OPINION_VIEW), self.calls)

        detail = await self.client.get_discussion_opinion("A20260001", "101", "201")
        self.assertEqual(detail.content, "전체 본문 첫 문단\n전체 본문 두 번째 문단")
        self.assertEqual(
            [(comment.content, comment.parent_id) for comment in detail.comments],
            [("댓글 첫 줄\n댓글 두 번째 줄", None), ("답글 본문", "301")],
        )

    async def test_opinion_from_outside_the_topic_is_rejected_before_view(self):
        with self.assertRaises(ValueError):
            await self.client.get_discussion_opinion("A20260001", "101", "202")
        self.assertNotIn(("POST", DISCUSSION_OPINION_VIEW), self.calls)

    async def test_mismatched_comment_context_is_not_requested(self):
        self.detail_html = OPINION_DETAIL.replace("'st','101'", "'st','102'")
        detail = await self.client.get_discussion_opinion("A20260001", "101", "201")
        self.assertIsNone(detail.comments)
        self.assertNotIn(("POST", DISCUSSION_COMMENT_LIST), self.calls)
