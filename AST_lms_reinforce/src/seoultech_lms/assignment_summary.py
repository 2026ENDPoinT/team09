"""Assignment index validation and short-lived, session-local detail reuse."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from time import monotonic
from typing import Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .content import is_item_id
from .models import Assignment
from .parser import assignment_from_index_row, normalize_text


_RELATIVE_DEADLINE = re.compile(r"\bD\s*(?:[+−-]\s*\d+|-\s*day)\b", re.I)
_EMPTY_INDEX = re.compile(r"(?:조회할|등록된|검색된|표시할).{0,40}없습니다")
_DETAIL_TTL_SECONDS = 600
SEOUL_TIME = ZoneInfo("Asia/Seoul")


class AssignmentSummaryItem(TypedDict):
    id: str
    course_id: str
    course_name: str
    title: str
    description: None
    due_at: str | None
    late_due_at: str | None
    submitted: bool | None
    url: str | None


class AssignmentSummary(TypedDict):
    status: Literal["ok"]
    as_of: str
    assignments: list[AssignmentSummaryItem]
    todo_checked: bool
    unavailable: NotRequired[list[str]]


def summary_item(item: Assignment, course_name: str) -> AssignmentSummaryItem:
    def iso(value: datetime | None) -> str | None:
        return value.replace(tzinfo=SEOUL_TIME).isoformat() if value is not None else None

    return {
        "id": item.id, "course_id": item.course_id, "course_name": course_name, "title": item.title,
        "description": None, "due_at": iso(item.due_at), "late_due_at": iso(item.late_due_at),
        "submitted": item.submitted, "url": item.url,
    }


@dataclass(frozen=True)
class AssignmentIndexRow:
    assignment: Assignment
    markers: tuple[str, ...]


def parse_summary_index(html: str, course_id: str) -> dict[str, AssignmentIndexRow]:
    soup = BeautifulSoup(html, "html.parser")
    activity = soup.select_one('a.activity[id^="class_menu_"], .activity_week')
    explicit_empty = any(
        _EMPTY_INDEX.search(normalize_text(node.get_text(" ", strip=True)))
        for node in soup.select(".list_error_msg, .error_message, .empty_content")
    )
    raw_rows = soup.select('a[id^="class_menu_report_"]')
    if not raw_rows and not activity and not explicit_empty:
        raise ValueError("강의실 활동 목록 구조를 확인하지 못했어요.")

    rows: dict[str, AssignmentIndexRow] = {}
    for raw in raw_rows:
        item = assignment_from_index_row(raw, course_id)
        if not is_item_id(item.id) or not item.title:
            raise ValueError("과제 목록에 확인할 수 없는 항목이 있어요.")
        deadline = raw.select_one(".activity_info_dday")
        markers: tuple[str, ...] = ()
        if deadline:
            text = normalize_text(_RELATIVE_DEADLINE.sub("", deadline.get_text(" ", strip=True)))
            attributes = (f"{key}={value}" for key, value in sorted(deadline.attrs.items())
                          if key.startswith("data-") or key == "title")
            markers = (text, *attributes)
        row = AssignmentIndexRow(item, markers)
        old = rows.get(item.id)
        if old is None or old == row:
            rows[item.id] = row
            continue
        # Duplicate renders may disagree. Keep the item and check its detail.
        rows[item.id] = AssignmentIndexRow(replace(old.assignment, submitted=None), old.markers + row.markers)
    return rows


@dataclass(frozen=True)
class _CheckedAssignment:
    index: AssignmentIndexRow | None
    todo_deadline: str | None
    detail: Assignment
    checked_at: float


class AssignmentSummaryCache:
    """A single authenticated session's assignment metadata, kept in memory."""

    def __init__(self) -> None:
        self._session: tuple[int, int, int] | None = None
        self._entries: dict[tuple[str, str], _CheckedAssignment] = {}

    def bind_session(self, session: tuple[int, int, int]) -> None:
        if self._session != session:
            self._entries.clear()
            self._session = session

    def clear(self) -> None:
        self._entries.clear()
        self._session = None

    def retain_courses(self, course_ids: set[str]) -> None:
        self._entries = {key: value for key, value in self._entries.items() if key[0] in course_ids}

    def retain_assignments(self, course_id: str, assignment_ids: set[str]) -> None:
        self._entries = {key: value for key, value in self._entries.items() if key[0] != course_id or key[1] in assignment_ids}

    def discard(self, item: Assignment) -> None:
        self._entries.pop((item.course_id, item.id), None)

    def get(
        self, item: Assignment, index: AssignmentIndexRow | None, todo_deadline: str | None,
    ) -> Assignment | None:
        entry = self._entries.get((item.course_id, item.id))
        if entry and entry.index == index and (
            todo_deadline is None or entry.todo_deadline == todo_deadline
        ) and monotonic() - entry.checked_at < _DETAIL_TTL_SECONDS:
            if item.submitted is None or entry.detail.submitted is item.submitted:
                return entry.detail
        return None

    def store(
        self, item: Assignment, index: AssignmentIndexRow | None, todo_deadline: str | None,
    ) -> None:
        key = (item.course_id, item.id)
        previous = self._entries.get(key)
        observed_deadline = todo_deadline or (previous.todo_deadline if previous else None)
        self._entries[key] = _CheckedAssignment(index, observed_deadline, item, monotonic())
