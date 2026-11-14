from __future__ import annotations

import unittest
from urllib.parse import parse_qs

import httpx

from seoultech_lms.client import SeoultechLMSClient
from seoultech_lms.endpoints import (
    ACTIVITY_FORM, ACTIVITY_LIST, BOARD_FORM, COURSE_HOME, COURSE_TIMETABLE, ENTER_COURSE, MAIN_FORM,
    NOTICE_LIST, NOTICE_VIEW, SYLLABUS_POP, SYLLABUS_VIEW, absolute,
)
from test_timetable import time_item, timetable_grid

COURSE_ID = "A20260001"
ROSTER = f"""
<a class="logout" href="/ilos/lo/logout.acl"></a>
<div class="my_lecture_container"><a id="kj_1" onclick="eclassRoom('{COURSE_ID}')">예시 수업</a></div>
"""


class ClassroomClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_indexed_bodies_are_limited_to_the_verified_page_and_do_not_fetch_assets(self) -> None:
        read_ids = []

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == MAIN_FORM:
                return httpx.Response(200, text=ROSTER)
            if path == ENTER_COURSE:
                return httpx.Response(200, json={"isError": False})
            data = parse_qs(request.content.decode())
            if path == NOTICE_LIST:
                self.assertEqual(data["start"], ["21"])
                return httpx.Response(200, text='''
                    <button class="board_list_wrap" data-num="21"><strong class="board_title">예시 공지</strong></button>
                    <button class="board_list_wrap" data-num="22"><strong class="board_title">지연된 공지</strong></button>
                    <div class="file_paging"><button class="paging_num_btn on">2</button></div>
                ''')
            if path == NOTICE_VIEW:
                id_ = data["ARTL_NUM"][0]
                read_ids.append(id_)
                if id_ == "22":
                    return httpx.Response(503)
                return httpx.Response(200, text='''<div class="editor_content">
                    <p>미리보기에는 없는 전체 본문</p><script>untrusted()</script>
                    <img src="/ilosfiles/editor-file/SYNTHETIC/2026/sample.png" alt="안내 이미지">
                </div>''')
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            result = await client.get_course_notice_bodies(COURSE_ID, 2, ["21", "22", "99", "21"])
        self.assertCountEqual(read_ids, ["21", "22"])
        self.assertEqual(len(result["bodies"]), 1)
        body = result["bodies"][0]
        self.assertEqual(body["id"], "21")
        self.assertEqual(body["text"], "미리보기에는 없는 전체 본문")
        self.assertIn("안내 이미지 · e-Class에서 확인", body["body_html"])
        self.assertNotIn("untrusted", body["body_html"])

    async def test_header_uses_selected_course_times_and_only_confirmed_rooms(self) -> None:
        timetable_available = True
        roster = ROSTER.replace("예시 수업</a>", """예시 수업 123456-31001 예시 교수
            월(1~2) 화(3) 화(5) 수(4) 금(7)</a>
            <a id="kj_2" onclick="eclassRoom('A20260002')">다른 수업</a>""")

        def syllabus_form(path: str) -> str:
            return f'''<script>$.ajax({{url: "{path}", type: "POST", data: {{
                KJKEY: "{COURSE_ID}", ORG_SECT: "A", YEAR: "2026", TERM: "2", LEDG_YEAR: "2026",
                LEDG_SESSN: "2", LSSN_CD: "123456", SUBJT_NO: "31001", encoding: "utf-8"
            }}}});</script>'''

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == MAIN_FORM:
                return httpx.Response(200, text=roster)
            if path == COURSE_TIMETABLE:
                if not timetable_available:
                    return httpx.Response(503)
                return httpx.Response(200, text=timetable_grid({
                    "월": time_item(COURSE_ID, "09:00", "10:00", "시간표관 101"),
                    "화": time_item(COURSE_ID, "10:00", "11:00", "-"),
                    "수": time_item(COURSE_ID, "13:00", "14:00", "-"),
                    "목": time_item("A20260002", "09:00", "10:00", "다른 과목 강의실"),
                }))
            if path == ENTER_COURSE:
                self.assertEqual(parse_qs(request.content.decode())["KJKEY"], [COURSE_ID])
                return httpx.Response(200, json={"isError": False})
            if path == COURSE_HOME:
                return httpx.Response(200, text=syllabus_form(SYLLABUS_POP))
            if path == SYLLABUS_POP:
                return httpx.Response(200, text=syllabus_form(SYLLABUS_VIEW))
            if path == SYLLABUS_VIEW:
                return httpx.Response(200, text="""<table><tr><th>강의시간/강의실</th>
                    <td>월(1~2) / 계획서관 100, 화(3) / 계획서관 201, 화(5) / 계획서관 202,
                    수(4) / 계획서관 301, 금(7) / 계획서관 401</td></tr></table>""")
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            result = await client.get_course_classroom_info(COURSE_ID)
            timetable_available = False
            fallback = await client.get_course_classroom_info(COURSE_ID)

        self.assertEqual(result, {"course_code": "123456-31001", "meetings": [
            {"weekday": "월", "start_time": "09:00", "end_time": "10:00", "room": "시간표관 101"},
            {"weekday": "화", "start_time": "10:00", "end_time": "11:00", "room": None},
            {"weekday": "수", "start_time": "13:00", "end_time": "14:00", "room": "계획서관 301"},
            {"weekday": "금", "periods": "7", "room": "계획서관 401"},
        ]})
        self.assertEqual(fallback["course_code"], "123456-31001")
        self.assertEqual(fallback["meetings"][1:3], [
            {"weekday": "화", "periods": "3", "room": "계획서관 201"},
            {"weekday": "화", "periods": "5", "room": "계획서관 202"},
        ])

    async def test_reads_one_course_and_keeps_verified_week_order_status_and_targets(self) -> None:
        calls = []

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append(path)
            if path == MAIN_FORM:
                return httpx.Response(200, text=ROSTER)
            if path == ENTER_COURSE:
                self.assertEqual(parse_qs(request.content.decode())["KJKEY"], [COURSE_ID])
                return httpx.Response(200, json={"isError": False})
            if path == ACTIVITY_LIST:
                return httpx.Response(200, text=f"""
                    <div class="activity_week font_subtitle5">1 주</div>
                    <a class="activity week_1" id="class_menu_lecture_material_10">
                      <div class="activity_top"><div class="activity_title font_subtitle2">강의 자료</div></div>
                      <span class="submit_check_outer"><b class="submit_check"></b></span>
                    </a>
                    <div class="activity_week font_subtitle5">2주</div>
                    <a class="activity week_2 not_submit" id="class_menu_report_11">
                      <span class="activity_title">제출 전 과제</span>
                      <div class="activity_info"><span class="activity_info_title">마감</span><span class="activity_info_text">2026.09.12 오후 11:59</span></div>
                    </a>
                    <a class="activity week_2" id="class_menu_test_12" href="https://example.test{ACTIVITY_FORM}?m=test&amp;n=12">
                      <span class="activity_title">확인되지 않은 경로</span>
                    </a>
                    <div class="activity_week font_subtitle5">3주</div>
                """)
            if path == COURSE_HOME:
                return httpx.Response(200, text=f"""
                    <a href="{BOARD_FORM}?ARTL_GRP_ID=3">팀 자료실</a>
                    <a href="https://example.test{BOARD_FORM}?ARTL_GRP_ID=4">외부 사이트</a>
                    <div class="week_list_container">
                      <div class="week_title"><span class="font_headline2">1 주</span><span class="week_period">9월 1일 ~ 9월 7일</span></div>
                      <div class="week_chapter_activity_list">
                        <a class="week_activity" href="{ACTIVITY_FORM}?m=lecture_material&amp;n=10"><span class="activity_title">강의 자료</span></a>
                        <a class="week_activity" href="{ACTIVITY_FORM}?m=lecture_weeks&amp;n=14">
                          <span class="activity_title">영상</span>
                          <div class="activity_info"><span class="activity_info_title">학습시간</span><span class="activity_info_text">1:00:00</span></div>
                        </a>
                      </div>
                    </div>
                """)
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            classroom = await client.get_course_classroom(COURSE_ID)
            with self.assertRaises(ValueError):
                await client.get_course_classroom("different-course")
        self.assertEqual(calls, [MAIN_FORM, ENTER_COURSE, ACTIVITY_LIST, COURSE_HOME])
        weeks = classroom["weeks"]
        self.assertEqual([week["number"] for week in weeks], [1, 2, 3])
        self.assertEqual(weeks[0]["date_label"], "9월 1일 ~ 9월 7일")
        self.assertEqual(weeks[0]["activities"][0]["url"], absolute(f"{ACTIVITY_FORM}?m=lecture_material&n=10"))
        self.assertEqual(weeks[0]["activities"][0]["status"], "complete")
        self.assertEqual(weeks[0]["activities"][1]["details"], "학습시간 1:00:00")
        self.assertEqual(weeks[1]["activities"][0]["status"], "not_submitted")
        self.assertEqual(weeks[1]["activities"][0]["due_at"], "2026-09-12T23:59:00")
        self.assertEqual(weeks[1]["activities"][1]["url"], None)
        self.assertEqual(weeks[2]["activities"], [])
        self.assertEqual(classroom["open_boards"], [{"id": "3", "title": "팀 자료실"}])

    async def test_search_reads_full_text_on_source_pages_and_reports_incomplete_reads(self) -> None:
        detail_calls = []
        pages = []
        second_page_unavailable = False

        def listing(page: int, notices: list[tuple[int, str]]) -> str:
            rows = "".join(f'<div class="board_list_wrap" data-num="{id}">'
                           f'<div class="board_title">{title}</div><div class="board_text">미리보기</div>'
                           f'<div class="board_list_bottom"><span class="reg_info">9월 {id}일 오전 10:00</span></div></div>'
                           for id, title in notices)
            buttons = "".join(f'<button class="paging_num_btn{" on" if num == page else ""}">{num}</button>'
                              for num in (1, 2))
            return rows + f'<div class="file_paging">{buttons}</div>'

        def respond(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == MAIN_FORM:
                return httpx.Response(200, text=ROSTER)
            if path == ENTER_COURSE:
                return httpx.Response(200, json={"isError": False})
            data = parse_qs(request.content.decode())
            if path == NOTICE_LIST:
                self.assertEqual(data["display"], ["20"])
                offset = data["start"][0]
                pages.append(offset)
                if offset == "1":
                    return httpx.Response(200, text=listing(1, [(10, "일반 안내")]))
                if offset == "21":
                    if second_page_unavailable:
                        return httpx.Response(503)
                    return httpx.Response(200, text=listing(2, [(20, "예전 공지"), (21, "키워드 안내"), (22, "본문 확인 실패")]))
            if path == NOTICE_VIEW:
                notice = data["ARTL_NUM"][0]
                detail_calls.append(notice)
                if notice == "22":
                    return httpx.Response(200, text="<p>공지 원문이 없음</p>")
                body = "본문 키워드" if notice == "20" else "다른 내용"
                return httpx.Response(200, text=f'<div class="editor_content"><p>{body}</p></div>')
            self.fail(f"Unexpected LMS request: {request.method} {path}")

        client = SeoultechLMSClient()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client._http = http
            first = await client.get_course_notice_page(COURSE_ID, 1, "키워드")
            second = await client.get_course_notice_page(COURSE_ID, 2, "키워드")
            with self.assertRaises(ValueError):
                await client.get_course_notice(COURSE_ID, "20", page=1)
            full = await client.get_course_notice(COURSE_ID, "20", page=2)
            recent = await client.get_course_recent_notices(COURSE_ID)
            second_page_unavailable = True
            partial_recent = await client.get_course_recent_notices(COURSE_ID)

        self.assertEqual(first, {"notices": [], "has_next": True, "partial": False})
        self.assertEqual([notice["id"] for notice in second["notices"]], ["20", "21"])
        self.assertEqual(second["notices"][0]["page"], 2)
        self.assertIn("본문 키워드", second["notices"][0]["content"])
        self.assertTrue(second["partial"])
        self.assertFalse(second["has_next"])
        self.assertIn("본문 키워드", full["body_html"])
        self.assertEqual([(notice["id"], notice["page"]) for notice in recent["notices"]], [("22", 2), ("21", 2), ("20", 2)])
        self.assertFalse(recent["partial"])
        self.assertEqual([notice["id"] for notice in partial_recent["notices"]], ["10"])
        self.assertTrue(partial_recent["partial"])
        self.assertEqual(pages, ["1", "21"] * 4)
        self.assertCountEqual(detail_calls, ["10", "20", "22", "20"])
