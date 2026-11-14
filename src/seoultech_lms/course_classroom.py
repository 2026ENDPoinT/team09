"""Parse the read-only student course activity listing for the AST classroom."""
from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .assignment_summary import assignment_url
from .content import ACTIVITY_ID, ACTIVITY_TYPES, assignment_submission_status, is_empty_listing
from .endpoints import ACTIVITY_FORM, BASE_URL
from .parser import normalize_text, parse_korean_datetime, parse_notice_datetime

_WEEK_NUMBER = re.compile(r"(?<!\d)([1-9]\d?)\s*주(?:차)?(?![가-힣])")
_WEEK_DATES = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일\s*[~～–—-]\s*\d{1,2}\s*월\s*\d{1,2}\s*일")
_ROW_WEEK = re.compile(r"week_([1-9]\d?)")
_ACTIVITY_ROW = 'a.activity[id^="class_menu_"]'
_TARGET_ID = re.compile(r"[A-Za-z0-9-]{1,80}")


class CourseActivity(TypedDict):
    id: str
    kind: str
    title: str
    status: str | None
    due_at: str | None
    details: str | None
    url: str | None


class CourseWeek(TypedDict):
    number: int | None
    date_label: str | None
    activities: list[CourseActivity]


def _activity_target(row: Tag) -> tuple[str, str, str] | None:
    try:
        target = urlsplit(urljoin(BASE_URL + "/", row.get("href", "")))
    except ValueError:
        return None
    if target.scheme != "https" or target.netloc != urlsplit(BASE_URL).netloc or target.path != ACTIVITY_FORM:
        return None
    params = parse_qs(target.query, keep_blank_values=True)
    modes, ids = params.get("m", []), params.get("n", [])
    if len(modes) != 1 or len(ids) != 1 or modes[0] not in ACTIVITY_TYPES or not _TARGET_ID.fullmatch(ids[0]):
        return None
    return modes[0], ids[0], target._replace(fragment="").geturl()


def _activity_details(row: Tag, course_id: str, assignment: bool) -> tuple[str | None, str | None]:
    labels = []
    due_at = None
    for info in row.select(".activity_info"):
        label = info.select_one(".activity_info_title")
        text = info.select_one(".activity_info_text, .activity_info_error_text")
        if label and text:
            labels.append(normalize_text(info.get_text(" ", strip=True)))
            if "마감" in label.get_text(strip=True):
                due_at = _activity_due(labels[-1], course_id)
    if due_at is None and assignment and not labels and (deadline := row.select_one(".activity_info_dday")):
        due_at = _activity_due(deadline.get_text(" ", strip=True), course_id)
    return " · ".join(labels) or None, due_at


def _activity_due(text: str, course_id: str) -> str | None:
    try:
        due = parse_korean_datetime(text) or parse_notice_datetime(text, course_id)
    except ValueError:
        return None
    return due.isoformat() if due else None


def _parse_activity(row: Tag, course_id: str, mode: str, activity_id: str, url: str | None) -> CourseActivity | None:
    kind = ACTIVITY_TYPES.get(mode, "other_activity")
    title_node = row.select_one(".activity_title")
    title = normalize_text((title_node or row).get_text(" ", strip=True))
    if not title:
        return None
    status = None
    if kind == "assignment":
        submitted = assignment_submission_status(row)
        if submitted is not None:
            status = "submitted" if submitted else "not_submitted"
    elif row.select_one(".submit_check_outer > .submit_check"):
        status = "complete"
    elif kind == "lecture" and "not_submit" in row.get("class", []):
        status = "incomplete"
    details, due_at = _activity_details(row, course_id, kind == "assignment")
    return {
        "id": activity_id, "kind": kind, "title": title, "status": status,
        "due_at": due_at, "details": details, "url": url,
    }


def parse_course_weeks(html: str, course_id: str) -> list[CourseWeek]:
    soup = BeautifulSoup(html, "html.parser")
    listing = soup.select(f".activity_week, {_ACTIVITY_ROW}")
    if not listing and not is_empty_listing(soup):
        raise ValueError("강의실 활동 목록 구조를 확인할 수 없습니다.")

    weeks: dict[int | None, CourseWeek] = {}
    current = None
    seen: set[tuple[int | None, str]] = set()

    def week(number: int | None) -> CourseWeek:
        return weeks.setdefault(number, {"number": number, "date_label": None, "activities": []})

    for node in listing:
        if "activity_week" in node.get("class", []):
            header = normalize_text(node.get_text(" ", strip=True))
            number = _WEEK_NUMBER.search(header)
            current = int(number[1]) if number else None
            if number:
                dates = _WEEK_DATES.search(header)
                section = week(current)
                if dates:
                    section["date_label"] = dates[0]
            continue
        row_week = next((match for value in node.get("class", []) if (match := _ROW_WEEK.fullmatch(value))), None)
        number = int(row_week[1]) if row_week else current
        key = number, node["id"]
        match = ACTIVITY_ID.fullmatch(node["id"])
        if key in seen or match is None:
            continue
        mode, activity_id = match["type"], match["id"]
        target = _activity_target(node)
        url = target[2] if target and target[:2] == (mode, activity_id) else None
        if url is None and mode == "report" and re.fullmatch(r"[0-9]{1,20}", activity_id):
            url = assignment_url(activity_id)
        activity = _parse_activity(node, course_id, mode, activity_id, url)
        if activity is None:
            continue
        week(number)["activities"].append(activity)
        seen.add(key)
    return list(weeks.values())


def merge_course_home_weeks(weeks: list[CourseWeek], html: str, course_id: str) -> list[CourseWeek]:
    """The course home includes date ranges and links absent from the AJAX activity listing."""
    soup = BeautifulSoup(html, "html.parser")
    by_number = {week["number"]: week for week in weeks}
    for section in soup.select(".week_list_container"):
        heading = section.select_one(".week_title")
        if heading is None:
            continue
        number = _WEEK_NUMBER.search(heading.get_text(" ", strip=True))
        if number is None:
            continue
        week_number = int(number[1])
        week = by_number.setdefault(week_number, {"number": week_number, "date_label": None, "activities": []})
        if (period := heading.select_one(".week_period")) is not None:
            week["date_label"] = normalize_text(period.get_text(" ", strip=True)) or week["date_label"]
        merged = {(item["kind"], item["id"]): item for item in week["activities"]}
        for row in section.select("a.week_activity[href]"):
            target = _activity_target(row)
            if not target or not (item := _parse_activity(row, course_id, *target)):
                continue
            key = item["kind"], item["id"]
            indexed = merged.get(key)
            if indexed is not None:
                item["status"] = indexed["status"] or item["status"]
                item["due_at"] = item["due_at"] or indexed["due_at"]
                item["details"] = item["details"] or indexed["details"]
            merged[key] = item
        week["activities"] = list(merged.values())
    return sorted(by_number.values(), key=lambda week: week["number"] or 0)
