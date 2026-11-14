from __future__ import annotations

import re
import ssl
from datetime import date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import truststore
from bs4 import BeautifulSoup, Tag

Dorm = Literal["kb", "seonglim", "surim"]
DormMenuPeriod = Literal["today", "week"]

_DINING_URL = "https://housing.seoultech.ac.kr/livng/dining/"
_DORMS = {"kb": ("kb", "KB학사"), "seonglim": ("sunglim", "성림학사"), "surim": ("surim", "수림학사")}
_WEEKDAYS = "월화수목금토일"
_MEAL_KEYS = {
    "아침": "breakfast", "조식": "breakfast", "점심": "lunch", "중식": "lunch", "저녁": "dinner", "석식": "dinner",
}
_MEAL = re.compile(rf"^({'|'.join(_MEAL_KEYS)})\s*[:：]\s*(.*)$")
_CHOICE = re.compile(r"<\s*선택(?:식)?\s*>|선택식\s*[-:：]")
_LINE_BREAK = "\x1e"


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text().split())


def _matches_pager(region: Tag, name: str, foodtype: str, expected: date) -> bool:
    form = region.select_one(f'form[name="{name}"]')
    if form is None:
        return False
    fields = {tag.get("name"): tag.get("value") for tag in form.select('input[type="hidden"][name][value]')}
    try:
        target = date(int(fields["year"]), int(fields["month"]), int(fields["day"]))
    except (KeyError, TypeError, ValueError):
        return False
    return fields.get("foodtype") == foodtype and target == expected


def _parse_meals(cell: Tag) -> tuple[dict[str, str | None], list[str]]:
    meals: dict[str, str | None] = dict.fromkeys(_MEAL_KEYS.values())
    notes = []
    # <br> separates posted lines. Newlines in the HTML source can also occur mid-menu.
    for marker in cell.select("br, font"):
        if marker.name == "br":
            marker.replace_with(_LINE_BREAK)
        elif (label := _MEAL.fullmatch(_text(marker))) and not label[2]:
            marker.insert_before(_LINE_BREAK)

    for segment in cell.get_text().split(_LINE_BREAK):
        line = " ".join(segment.split())
        if not line:
            continue
        if match := _MEAL.fullmatch(line):
            content = match[2]
            if choice := _CHOICE.search(content):
                notes.append(content[choice.start():])
                content = content[:choice.start()].rstrip(" ,")
            meals[_MEAL_KEYS[match[1]]] = content or None
        else:
            notes.append(line)
    return meals, notes


def _parse_week(html: str, foodtype: str, dorm_name: str, week_start: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    selected = soup.select_one(".tab2 a.on[href]")
    if selected is None or _text(selected) != dorm_name or parse_qs(urlsplit(selected["href"]).query).get("foodtype") != [foodtype]:
        raise RuntimeError("생활관 페이지에서 요청한 학사의 식단을 확인하지 못했어요.")

    region = soup.select_one(".t4")
    if region is None or not (
        _matches_pager(region, "PREYEAR", foodtype, week_start - timedelta(days=7))
        and _matches_pager(region, "NEXTYEAR", foodtype, week_start + timedelta(days=7))
    ):
        raise RuntimeError("생활관 페이지에서 요청한 주의 식단을 확인하지 못했어요.")

    rows = region.select("table.chang tr")
    if len(rows) != len(_WEEKDAYS):
        raise RuntimeError("생활관 페이지의 주간 식단표를 확인하지 못했어요.")
    result = []
    for index, row in enumerate(rows):
        day = week_start + timedelta(days=index)
        weekday = _WEEKDAYS[index]
        headers = row.find_all("th", recursive=False)
        cell = row.find("td", recursive=False)
        if [_text(header) for header in headers] != [f"{day.day}일", weekday] or cell is None:
            raise RuntimeError("생활관 식단표의 날짜를 확인하지 못했어요.")
        meals, notes = _parse_meals(cell)
        result.append({"date": day.isoformat(), "weekday": weekday, "meals": meals, "notes": notes})
    return result


async def get_dorm_menu(
    dorm: Dorm = "kb", period: DormMenuPeriod = "today", on_date: date | None = None,
) -> dict[str, Any]:
    if dorm not in _DORMS or period not in ("today", "week"):
        raise ValueError("지원하는 학사와 식단 기간을 선택해 주세요.")
    foodtype, dorm_name = _DORMS[dorm]
    selected = on_date or datetime.now(ZoneInfo("Asia/Seoul")).date()
    week_start = selected - timedelta(days=selected.weekday())
    week_end = week_start + timedelta(days=6)
    url = httpx.URL(_DINING_URL, params={
        "foodtype": foodtype, "year": week_start.year, "month": week_start.month, "day": week_start.day,
    })
    async with httpx.AsyncClient(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), follow_redirects=False, timeout=15,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    days = _parse_week(response.text, foodtype, dorm_name, week_start)
    if period == "today":
        days = [days[selected.weekday()]]
    return {
        "dorm": dorm, "dorm_name": dorm_name, "period": period, "on_date": selected.isoformat(),
        "week_start": week_start.isoformat(), "week_end": week_end.isoformat(), "days": days, "source_url": str(url),
    }
