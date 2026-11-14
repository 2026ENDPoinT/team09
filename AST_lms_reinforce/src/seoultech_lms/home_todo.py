"""Read the e-Class home 할일 widget for additional assignment locators."""
from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Protocol, TypedDict

import httpx
from bs4 import BeautifulSoup

from .auth import AuthenticationRequired
from .endpoints import HOME_TODO_LIST
from .parser import normalize_text

_PAGE_SIZE = 5
_MAX_PAGES = 20
_CARD = "a.aside_list_todo_item"
_ASSIGNMENT_LINK = re.compile(
    r"""goLecture\(\s*(?P<course_quote>['"])(?P<course_id>[A-Za-z0-9가-힣_-]{1,80})(?P=course_quote)\s*,
    \s*(?P<kind_quote>['"])report(?P=kind_quote)\s*,\s*(?P<id_quote>['"]?)(?P<id>[0-9]{1,20})(?P=id_quote)\s*\)\s*;?""",
    re.VERBOSE,
)
_REPORT_TYPE = re.compile(r""",\s*['"]report['"]\s*,""")
_TOTAL = re.compile(r"""\$\(\s*['"]\#asideTodoCnt['"]\s*\)\.text\(\s*['"]([0-9]{1,6})['"]\s*\)""")
_MORE = re.compile(r"""\$\(\s*['"]\#btnAsideTodoListMore['"]\s*\)\.(show|hide|remove)\(\s*\)""")


class HomeTodoAssignment(TypedDict):
    course_id: str
    id: str
    title: str
    deadline_text: str


class HomeTodo(TypedDict):
    assignments: list[HomeTodoAssignment]
    complete: bool


class _Request(Protocol):
    def __call__(self, method: str, path: str, **kwargs: object) -> Awaitable[httpx.Response]: ...


async def read_home_todo(request: _Request) -> HomeTodo:
    """Return positive assignment hints. Completeness refers only to this widget."""
    assignments: dict[tuple[str, str], HomeTodoAssignment] = {}
    seen_handlers: set[str] = set()
    total = None
    start = 0
    complete = False
    valid_assignments = True

    for _ in range(_MAX_PAGES):
        try:
            response = await request("POST", HOME_TODO_LIST, data={
                "start": str(start), "display": str(_PAGE_SIZE), "encoding": "utf-8",
            }, timeout=5)
        except AuthenticationRequired:
            raise
        except (httpx.HTTPError, OSError, RuntimeError, ValueError):
            break

        fragment = BeautifulSoup(response.text, "html.parser")
        cards = fragment.select(_CARD)
        repeated = False
        for card in cards:
            handler = str(card.get("onclick", "")).strip()
            if handler:
                repeated |= handler in seen_handlers
                seen_handlers.add(handler)
            match = _ASSIGNMENT_LINK.fullmatch(handler)
            if match is None:
                label = card.select_one(".aside_list_top")
                if _REPORT_TYPE.search(handler) or (label and label.get_text(" ", strip=True).startswith(("과제", "Assignment"))):
                    valid_assignments = False
                continue
            title = card.select_one(".aside_list_title")
            deadline = card.select_one(".aside_list_date")
            title_text = normalize_text(title.get_text(" ", strip=True)) if title else ""
            if not title_text:
                valid_assignments = False
                continue
            course_id, assignment_id = match.group("course_id", "id")
            assignments[(course_id, assignment_id)] = {
                "course_id": course_id, "id": assignment_id, "title": title_text,
                "deadline_text": normalize_text(deadline.get_text(" ", strip=True)) if deadline else "",
            }

        scripts = "\n".join(script.get_text() for script in fragment.find_all("script"))
        totals = {int(value) for value in _TOTAL.findall(scripts)}
        controls = set(_MORE.findall(scripts))
        page_total = next(iter(totals)) if len(totals) == 1 else None
        if page_total is None or (total is not None and page_total != total) or len(controls) != 1 or repeated or len(cards) > _PAGE_SIZE:
            break

        total = page_total
        start += len(cards)
        if "show" not in controls:
            complete = start == total and valid_assignments
            break
        if not cards or start >= total:
            break

    return {"assignments": list(assignments.values()), "complete": complete}
