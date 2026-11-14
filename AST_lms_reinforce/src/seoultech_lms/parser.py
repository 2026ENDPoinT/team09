"""Parsers for the verified server-rendered and AJAX HTML structures."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from .endpoints import ACTIVITY_FORM, COURSE_HOME, NOTICE_FORM, absolute
from .models import Assignment, Course, Notice

_COURSE_ID = re.compile(r"eclassRoom\(['\"]([^'\"]+)['\"]")
_COURSE_KEY = re.compile(r"[A-Za-z0-9가-힣_-]{1,80}")
_PROFESSOR = re.compile(r"\d{6}-\d{5}\s+(.+?)\s+(?:월|화|수|목|금|토|일)\s*\(")
_KOREAN_DATETIME = re.compile(
    r"(?P<year>\d{4})[.-](?P<month>\d{1,2})[.-](?P<day>\d{1,2})"
    r"(?:\s*\([^)]*\))?\s*(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)
_LATE_SUBMISSION_ROW = re.compile(r"지각\s*제출\s*허용\s*\(\s*마감일\s*:\s*(.+)\)")
_NOTICE_DATETIME = re.compile(
    r"(?:(?P<year>\d{4})\s*[년.-]\s*)?"
    r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"(?:\s*\([^)]*\))?\s*(?P<ampm>오전|오후)\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)
_COURSE_YEAR = re.compile(r"^A(?P<year>\d{4})")


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def parse_student_profile(html: str, *, include_contact: bool = False) -> dict[str, str | int | None] | None:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".user_info:has(.user_name)")
    if len(cards) != 1:
        return None
    name = normalize_text(cards[0].select_one(".user_name").get_text(" ", strip=True))
    if not 0 < len(name) <= 100:
        return None
    field = cards[0].select_one(".dept_grade")
    affiliation = normalize_text(field.get_text(" ", strip=True)) if field else ""
    suffix = re.search(r"(?<!\d)([1-9])\s*학년$", affiliation)
    department = affiliation[:suffix.start()].strip() if suffix else affiliation
    profile: dict[str, str | int | None] = {
        "display_name": name,
        "department": department if 0 < len(department) <= 120 else None,
        "year": int(suffix[1]) if suffix else None,
    }
    if include_contact:
        fields = {"전화번호": "phone", "이메일": "email"}
        profile.update(phone=None, email=None)
        for label in soup.select(".contact > span"):
            key = fields.get(normalize_text(label.get_text(" ", strip=True)))
            value = label.find_next_sibling("span") if key else None
            if key and value:
                contact = normalize_text(value.get_text(" ", strip=True))
                profile[key] = contact if 0 < len(contact) <= 254 else None
    return profile


def parse_korean_datetime(value: str) -> datetime | None:
    match = _KOREAN_DATETIME.search(normalize_text(value))
    if not match:
        return None
    hour = int(match.group("hour"))
    if match.group("ampm") == "오전":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        hour,
        int(match.group("minute")),
    )


def parse_notice_datetime(value: str, course_id: str) -> datetime | None:
    """Parse a notice timestamp, using the verified course year when LMS omits it."""
    match = _NOTICE_DATETIME.search(normalize_text(value))
    if not match:
        return None
    year_text = match.group("year")
    if year_text is None:
        course_match = _COURSE_YEAR.match(course_id)
        if not course_match:
            return None
        year_text = course_match.group("year")
    hour = int(match.group("hour"))
    if match.group("ampm") == "오전":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    try:
        return datetime(
            int(year_text),
            int(match.group("month")),
            int(match.group("day")),
            hour,
            int(match.group("minute")),
        )
    except ValueError:
        return None


def parse_courses(html: str) -> list[Course]:
    return _parse_courses(BeautifulSoup(html, "html.parser"), include_non_regular=False)


def parse_summary_courses(html: str, *, include_non_regular: bool) -> list[Course] | None:
    soup = BeautifulSoup(html, "html.parser")
    courses = _parse_courses(soup, include_non_regular=include_non_regular)
    verified_empty = soup.select_one(".my_lecture_container") and soup.select_one('a.logout[href="/ilos/lo/logout.acl"]')
    return courses if courses or verified_empty else None


def _parse_courses(soup: BeautifulSoup, *, include_non_regular: bool) -> list[Course]:
    container = soup.select_one(".my_lecture_container") or soup
    selector = 'a[id^="kj_"][onclick*="eclassRoom"]'
    non_regular_anchors = set()
    for section in container.select(".term_wrap"):
        heading = section.select_one(".container_subtitle")
        if heading and normalize_text(heading.get_text(" ", strip=True)) == "비정규과목":
            non_regular_anchors.update(id(anchor) for anchor in section.select(selector))
    courses: dict[str, Course] = {}
    for anchor in container.select(selector):
        match = _COURSE_ID.search(str(anchor.get("onclick", "")))
        if not match:
            continue
        course_id = match.group(1)
        non_regular = id(anchor) in non_regular_anchors
        if not _COURSE_KEY.fullmatch(course_id):
            continue
        if non_regular and not include_non_regular or not non_regular and not course_id.startswith("A"):
            continue
        title = normalize_text(str(anchor.get("title", "")))
        name = title.removesuffix(" 강의실 들어가기").strip()
        text = normalize_text(anchor.get_text(" ", strip=True))
        professor_match = _PROFESSOR.search(text)
        courses[course_id] = Course(
            id=course_id,
            name=name or text,
            professor=professor_match.group(1).strip() if professor_match else None,
            url=absolute(COURSE_HOME),
        )
    return list(courses.values())


def _direct_child_texts(node: Tag) -> list[str]:
    texts: list[str] = []
    for child in node.find_all(recursive=False):
        text = normalize_text(child.get_text(" ", strip=True))
        if text:
            texts.append(text)
    return texts


def parse_notices(html: str, course_id: str) -> list[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    notices: list[Notice] = []
    for item in soup.select(".board_list_wrap[data-num]"):
        notice_id = str(item.get("data-num", "")).strip()
        text = normalize_text(item.get_text(" ", strip=True))
        title_node = item.select_one(".board_title")
        content_node = item.select_one(".board_text")
        created_node = item.select_one(
            ".board_list_bottom_right .reg_info, .board_list_bottom .reg_info, .board_list_bottom"
        )
        parts = _direct_child_texts(item)
        title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else (parts[0] if parts else text)
        content = normalize_text(content_node.get_text(" ", strip=True)) if content_node else (parts[1] if len(parts) > 1 else None)
        if not notice_id:
            notice_id = stable_id(course_id, title, text)
        notices.append(
            Notice(
                id=notice_id,
                course_id=course_id,
                title=title,
                content=content,
                created_at=(
                    parse_notice_datetime(created_node.get_text(" ", strip=True), course_id)
                    if created_node
                    else None
                ),
                url=absolute(NOTICE_FORM),
            )
        )
    return notices


def enrich_notice(detail_html: str, notice: Notice) -> Notice:
    """Replace a list preview with the full notice body from the detail dialog."""
    soup = BeautifulSoup(detail_html, "html.parser")
    title_node = soup.select_one(".view_title .font_headline2, .view_title")
    content_node = soup.select_one(".editor_content")
    title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else notice.title
    content = normalize_text(content_node.get_text(" ", strip=True)) if content_node else notice.content
    return Notice(
        id=notice.id,
        course_id=notice.course_id,
        title=title,
        content=content,
        created_at=notice.created_at,
        url=notice.url,
    )


def assignment_url(assignment_id: str) -> str:
    query = urlencode({"m": "report", "n": assignment_id, "mf": "report1"})
    return f"{absolute(ACTIVITY_FORM)}?{query}"


def assignment_from_index_row(item: Tag, course_id: str) -> Assignment:
    assignment_id = str(item.get("id", "")).removeprefix("class_menu_report_")
    title_node = item.select_one(".activity_title")
    title = normalize_text((title_node or item).get_text(" ", strip=True))
    if title.startswith("과제 "):
        title = title[3:].split(" 마감 ", 1)[0].strip()
    submitted = False if "not_submit" in item.get("class", []) else (
        True if item.select_one(".submit_check_outer > .submit_check") else None
    )
    return Assignment(assignment_id, course_id, title, submitted=submitted, url=assignment_url(assignment_id))


def parse_assignment_index(html: str, course_id: str) -> list[Assignment]:
    soup = BeautifulSoup(html, "html.parser")
    return [assignment_from_index_row(item, course_id) for item in soup.select('a[id^="class_menu_report_"]')]


def _late_submission_deadline(due_row: Tag) -> datetime | None:
    table = due_row.find_parent("table")
    if table is None:
        return None
    for row in table.select("tr"):
        if row.find_parent("table") is not table or row.find_parent(id="submit_form") is not None:
            continue
        match = _LATE_SUBMISSION_ROW.fullmatch(normalize_text(row.get_text(" ", strip=True)))
        if match:
            try:
                return parse_korean_datetime(match.group(1))
            except ValueError:
                return None
    return None


def enrich_assignment(detail_html: str, assignment: Assignment, *, verify: bool = False) -> Assignment:
    soup = BeautifulSoup(detail_html, "html.parser")
    if verify and not soup.select_one(".view_title, .bbsview, #submit_form"):
        raise ValueError("과제 상세 화면을 확인하지 못했어요.")
    title_node = soup.select_one(".view_title .font_headline2")
    title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else assignment.title
    due_at = None
    late_due_at = None
    for row in soup.select("tr"):
        if row.find_parent(id="submit_form") is not None or row.find_parent(class_="editor_content") is not None:
            continue
        text = normalize_text(row.get_text(" ", strip=True))
        if text.startswith("마감일"):
            due_at = parse_korean_datetime(text)
            late_due_at = _late_submission_deadline(row)
            break
    body = next(
        (node for node in soup.select(".bbsview .editor_content") if not node.find_parent(id="submit_form")),
        None,
    )
    submit = soup.select_one("#submit_form")
    submitted = assignment.submitted
    if submit:
        dates = submit.select(".inner_title_box .submit_info_box .date")
        statuses = {
            "".join(label.get_text(strip=True).split())
            for label in submit.select(".inner_title_box .submit_info_box .txt")
        }
        if statuses & {"정상제출", "지각제출", "제출완료"} or any(
            parse_korean_datetime(label.get_text(" ", strip=True)) is not None for label in dates
        ):
            submitted = True
        else:
            submit_text = normalize_text(" ".join(
                text for text in submit.strings if text.find_parent(class_="editor_content") is None
            ))
            if "제출된 내역이 없습니다" in submit_text:
                submitted = False
    return Assignment(
        id=assignment.id,
        course_id=assignment.course_id,
        title=title,
        description=body.get_text("\n", strip=True) if body is not None else None,
        due_at=due_at,
        submitted=submitted,
        url=assignment.url,
        late_due_at=late_due_at,
    )


def stable_id(*parts: object) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]
