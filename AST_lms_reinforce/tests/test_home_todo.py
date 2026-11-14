from __future__ import annotations

import unittest

import httpx

from seoultech_lms.auth import AuthenticationRequired
from seoultech_lms.endpoints import ALLOWED_GET_PATHS, ALLOWED_POST_PATHS, HOME_TODO_LIST
from seoultech_lms.home_todo import read_home_todo


def card(course_id: str, kind: str, activity_id: int, title: str) -> str:
    return f"""
    <a class="aside_list aside_list_todo_item" href="javascript:void(0);"
       onclick="goLecture('{course_id}', '{kind}', '{activity_id}')">
      <div class="aside_list_top">활동</div>
      <div class="aside_list_title">{title}</div>
      <div class="aside_list_date">4월 30일 (목) 오후 11:59</div>
    </a>"""


def page(total: int, more: bool, *cards: str) -> httpx.Response:
    toggle = "show" if more else "remove"
    html = f"""
    <script>
      $("#btnAsideTodoListMore").{toggle}();
      $('#asideTodoCnt').text("{total}");
    </script>
    """ + "".join(cards)
    return httpx.Response(200, text=html)


class HomeTodoTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_offset_uses_all_card_types_and_returns_assignments_only(self):
        calls: list[tuple[str, str, object]] = []
        responses = iter([
            page(6, True, card("course-1", "report", 11, "첫 실습"), *(
                card("course-2", "video", index, "영상") for index in range(21, 25)
            )),
            page(6, False, card("course-2", "report", 12, "다른  실습")),
        ])

        async def request(method, path, **kwargs):
            calls.append((method, path, kwargs["data"]))
            return next(responses)

        result = await read_home_todo(request)
        self.assertTrue(result["complete"])
        self.assertEqual(result["assignments"], [
            {"course_id": "course-1", "id": "11", "title": "첫 실습", "deadline_text": "4월 30일 (목) 오후 11:59"},
            {"course_id": "course-2", "id": "12", "title": "다른 실습", "deadline_text": "4월 30일 (목) 오후 11:59"},
        ])
        self.assertEqual(calls, [
            ("POST", HOME_TODO_LIST, {"start": "0", "display": "5", "encoding": "utf-8"}),
            ("POST", HOME_TODO_LIST, {"start": "5", "display": "5", "encoding": "utf-8"}),
        ])
        self.assertIn(HOME_TODO_LIST, ALLOWED_POST_PATHS)
        self.assertNotIn(HOME_TODO_LIST, ALLOWED_GET_PATHS)

    async def test_repeated_page_retains_positive_hints_but_remains_partial(self):
        calls = 0

        async def request(*_, **__):
            nonlocal calls
            calls += 1
            return page(10, True, card("course-1", "report", 11, "첫 실습"), *(
                card("course-2", "video", index, "영상") for index in range(21, 25)
            ))

        result = await read_home_todo(request)
        self.assertFalse(result["complete"])
        self.assertEqual(calls, 2)
        self.assertEqual([item["id"] for item in result["assignments"]], ["11"])

    async def test_unfamiliar_fragment_does_not_confirm_empty_list(self):
        async def request(*_, **__):
            return httpx.Response(200, text="<p>일시적인 오류</p>")

        self.assertEqual(await read_home_todo(request), {"complete": False, "assignments": []})

    async def test_malformed_assignment_does_not_confirm_complete_list(self):
        async def request(*_, **__):
            return page(1, False, card("course/1", "report", 11, "첫 실습"))

        self.assertEqual(await read_home_todo(request), {"complete": False, "assignments": []})

    async def test_empty_fragment_requires_verified_count_and_end(self):
        async def request(*_, **__):
            return page(0, False)

        self.assertEqual(await read_home_todo(request), {"complete": True, "assignments": []})

    async def test_request_error_keeps_successful_first_page(self):
        async def request(*_, data, **__):
            if data["start"] != "0":
                raise httpx.ReadTimeout("fixture")
            return page(6, True, card("course-1", "report", 11, "첫 실습"))

        result = await read_home_todo(request)
        self.assertFalse(result["complete"])
        self.assertEqual([item["id"] for item in result["assignments"]], ["11"])

    async def test_expired_session_propagates(self):
        async def request(*_, **__):
            raise AuthenticationRequired("fixture")

        with self.assertRaises(AuthenticationRequired):
            await read_home_todo(request)
