from datetime import date, timedelta
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

from seoultech_lms.dorm_menu import get_dorm_menu


def _menu_page(start: date) -> str:
    def pager(name: str, shift: int) -> str:
        day = start + timedelta(days=shift)
        fields = {"foodtype": "sunglim", "year": day.year, "month": day.month, "day": day.day}
        inputs = "".join(f'<input type="hidden" name="{key}" value="{value}">' for key, value in fields.items())
        return f'<form name="{name}">{inputs}</form>'

    rows = []
    menus = {
        "목": '<font>아침 :</font> 두부국, &lt;선택&gt;우유<br>선택식 - 과일<br>'
             '<font>점심 :</font> 신정 미운영\n(1/1)<br><font>저녁 :</font>',
        "금": "미등록",
    }
    for index, weekday in enumerate("월화수목금토일"):
        day = start + timedelta(days=index)
        rows.append(f"<tr><th>{day.day}일</th><th>{weekday}</th><td>{menus.get(weekday, '')}</td></tr>")
    return (
        '<div class="tab2"><a class="on" href="?foodtype=sunglim">성림학사</a></div>'
        f'<div class="t4">{pager("PREYEAR", -7)}{pager("NEXTYEAR", 7)}'
        '<table class="chang">' + "".join(rows) + "</table></div>"
    )


class DormMenuTests(IsolatedAsyncioTestCase):
    async def test_official_query_and_calendar_boundary(self):
        expected_url = "https://housing.seoultech.ac.kr/livng/dining/?foodtype=sunglim&year=2025&month=12&day=29"

        def handle(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), expected_url)
            return httpx.Response(200, text=_menu_page(date(2025, 12, 29)))

        with patch("seoultech_lms.dorm_menu.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=httpx.MockTransport(handle))):
            week = await get_dorm_menu("seonglim", "week", date(2026, 1, 1))

        self.assertEqual((week["week_start"], week["week_end"], week["source_url"]), ("2025-12-29", "2026-01-04", expected_url))
        self.assertEqual(week["days"][3], {
            "date": "2026-01-01", "weekday": "목",
            "meals": {"breakfast": "두부국", "lunch": "신정 미운영 (1/1)", "dinner": None},
            "notes": ["<선택>우유", "선택식 - 과일"],
        })

    async def test_today_returns_only_the_requested_unpublished_day(self):
        transport = httpx.MockTransport(lambda _: httpx.Response(200, text=_menu_page(date(2025, 12, 29))))
        with patch("seoultech_lms.dorm_menu.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await get_dorm_menu("seonglim", "today", date(2026, 1, 2))
        self.assertEqual(result["days"], [{
            "date": "2026-01-02", "weekday": "금", "meals": {"breakfast": None, "lunch": None, "dinner": None},
            "notes": ["미등록"],
        }])

    async def test_rejects_menu_returned_for_wrong_dorm_or_week(self):
        for dorm, selected, message in (
            ("kb", date(2026, 1, 2), "요청한 학사"),
            ("seonglim", date(2026, 1, 8), "요청한 주"),
        ):
            with self.subTest(dorm=dorm, selected=selected):
                transport = httpx.MockTransport(lambda _: httpx.Response(200, text=_menu_page(date(2025, 12, 29))))
                with patch("seoultech_lms.dorm_menu.httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        await get_dorm_menu(dorm, "today", selected)
