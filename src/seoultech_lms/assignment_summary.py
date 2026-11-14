from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import time
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .auth import write_auth_state_secure
from .content import parse_course_activities, parse_post_list
from .endpoints import ACTIVITY_FORM, absolute
from .models import Assignment, as_jsonable
from .parser import normalize_text, stable_id

_DETAIL_MAX_AGE = 600
_MAX_CACHED_ASSIGNMENTS = 2000
_D_DAY = re.compile(r"\bD\s*(?:[+−-]\s*\d+|-\s*day)\b", re.I)


def assignment_url(assignment_id: str) -> str:
    return f"{absolute(ACTIVITY_FORM)}?{urlencode({'m': 'report', 'n': assignment_id, 'mf': 'report1'})}"


def assignment_markers(html: str, course_id: str, soup: BeautifulSoup) -> list[tuple[Assignment, str]]:
    """Match the home and chat against the same current activity-list fingerprint."""
    posts = parse_post_list(html, "assignment", course_id)
    rows = soup.select('a[id^="class_menu_report_"]')
    by_id = {post.id: post for post in posts}
    if any(not post.title.strip() for post in posts) or any(
        row["id"].removeprefix("class_menu_report_") not in by_id for row in rows
    ):
        raise ValueError("과제 목록에서 일부 과제 번호를 확인하지 못했어요.")

    evidence: dict[str, list[tuple[str, str, dict]]] = {post.id: [] for post in posts}
    status: dict[str, set[bool]] = {post.id: set() for post in posts}
    for row in rows:
        assignment_id = row["id"].removeprefix("class_menu_report_")
        if "not_submit" in row.get("class", []):
            status[assignment_id].add(False)
        if row.select_one(".submit_check_outer > .submit_check"):
            status[assignment_id].add(True)
        for deadline in row.select(".activity_info_dday"):
            due = normalize_text(_D_DAY.sub("", deadline.get_text(" ", strip=True)))
            metadata = {key: value for key, value in sorted(deadline.attrs.items()) if key.startswith("data-") or key == "title"}
            evidence[assignment_id].append((due, str(deadline.get("class", [])), metadata))

    markers = []
    for post in posts:
        statuses = status[post.id]
        submitted = next(iter(statuses)) if len(statuses) == 1 else None
        item = Assignment(post.id, course_id, post.title, submitted=submitted, url=assignment_url(post.id))
        signature = stable_id(item.id, item.title, item.submitted, evidence[item.id])
        markers.append((item, signature))
    return markers


def checked_assignment_markers(html: str, course_id: str) -> list[tuple[Assignment, str]]:
    counts, _ = parse_course_activities(html)
    markers = assignment_markers(html, course_id, BeautifulSoup(html, "html.parser"))
    if counts["assignment"] > len(markers):
        raise ValueError("과제 목록의 일부 항목을 확인하지 못했어요.")
    return markers


class AssignmentSummaryCache:
    """Keep only assignment metadata for the currently authenticated session."""

    def __init__(self) -> None:
        self.session: object = None
        self.details: OrderedDict[tuple[str, str], tuple[str, float, Assignment]] = OrderedDict()
        self.path: Path | None = None
        self.dirty = False

    def bind(self, session: object, path: Path | None) -> None:
        if session != self.session:
            self.session = session
            self.details.clear()
            self.path = path
            self.dirty = False
            if path is not None:
                self.load(path)

    def load(self, path: Path) -> None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("details"), list):
                return
            for signature, checked_at, row in raw["details"][-_MAX_CACHED_ASSIGNMENTS:]:
                if not 0 <= time() - checked_at < _DETAIL_MAX_AGE:
                    continue
                dates = {key: datetime.fromisoformat(row[key]) if row[key] else None
                         for key in ("due_at", "late_due_at", "submitted_at")}
                item = Assignment(row["id"], row["course_id"], row["title"], submitted=row["submitted"],
                                  url=assignment_url(row["id"]), **dates)
                if item.due_at is not None and isinstance(item.submitted, bool):
                    self.details[item.course_id, item.id] = signature, checked_at, item
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            self.details.clear()

    def flush(self) -> None:
        if not self.dirty or self.path is None:
            return
        try:
            details = []
            for signature, checked_at, item in self.details.values():
                if 0 <= time() - checked_at < _DETAIL_MAX_AGE:
                    row = as_jsonable(item)
                    del row["description"], row["url"]
                    details.append((signature, checked_at, row))
            write_auth_state_secure(self.path, {"version": 1, "details": details})
            self.dirty = False
        except OSError:
            pass

    def get(self, item: Assignment, signature: str) -> Assignment | None:
        key = item.course_id, item.id
        record = self.details.get(key)
        if record and record[0] == signature and 0 <= time() - record[1] < _DETAIL_MAX_AGE:
            self.details.move_to_end(key)
            return record[2]
        return None

    def put(self, item: Assignment, signature: str) -> None:
        key = item.course_id, item.id
        if item.due_at is None or item.submitted is None:
            self.discard(item)
            return
        self.details[key] = (signature, time(), replace(item, description=None))
        self.details.move_to_end(key)
        self.dirty = True
        if len(self.details) > _MAX_CACHED_ASSIGNMENTS:
            self.details.popitem(last=False)

    def discard(self, item: Assignment) -> None:
        if self.details.pop((item.course_id, item.id), None) is not None:
            self.dirty = True

    def retain_course_assignments(self, course_id: str, current_ids: set[str]) -> None:
        for key in list(self.details):
            if key[0] == course_id and key[1] not in current_ids:
                del self.details[key]
                self.dirty = True

    def retain_courses(self, course_ids: set[str]) -> None:
        for key in list(self.details):
            if key[0] not in course_ids:
                del self.details[key]
                self.dirty = True
