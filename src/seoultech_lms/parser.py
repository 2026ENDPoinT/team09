"""Parsers for the verified server-rendered and AJAX HTML structures."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from html import escape
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag

from .campus_notices import campus_image_url
from .endpoints import ACTIVITY_FORM, COURSE_HOME, NOTICE_FORM, absolute
from .models import Assignment, AssignmentMetadata, Course, CourseMeeting, CourseRoster, Notice, StudentProfile

_COURSE_ID = re.compile(r"eclassRoom\(['\"]([^'\"]+)['\"]")
_COURSE_KEY = re.compile(r"[A-Za-z0-9가-힣_-]{1,80}")
_COURSE_CODE = r"(?<![\w-])[0-9]{6}-[0-9]{5}(?![\w-])"
_PROFESSOR = re.compile(r"\d{6}-\d{5}\s+(.+?)\s+(?:월|화|수|목|금|토|일)\s*\(")
_COURSE_MEETING = re.compile(r"(?<!\w)(?P<weekday>[월화수목금토일])\s*\((?P<periods>[^()]+)\)")
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
    return _parse_course_roster(BeautifulSoup(html, "html.parser")).courses


def parse_authenticated_roster(html: str) -> CourseRoster | None:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select_one('.my_lecture_container') or not soup.select_one('a.logout[href="/ilos/lo/logout.acl"]'):
        return None
    return _parse_course_roster(soup)


def parse_student_profile(html: str, *, include_contact: bool = False) -> StudentProfile | None:
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
    contacts: dict[str, str] = {}
    if include_contact:
        labels = {"전화번호", "이메일"}
        for label in soup.select(".contact > span"):
            key = normalize_text(label.get_text(" ", strip=True))
            if key not in labels:
                continue
            value = label.find_next_sibling("span")
            if value is not None:
                text = normalize_text(value.get_text(" ", strip=True))
                if 0 < len(text) <= 254 and text not in labels and text != "-":
                    contacts[key] = text
    return StudentProfile(
        name, department if 0 < len(department) <= 120 else None, int(suffix[1]) if suffix else None,
        phone=contacts.get("전화번호"), email=contacts.get("이메일"),
    )


def _parse_course_schedule(anchor: Tag, legacy_text: str) -> tuple[str | None, tuple[CourseMeeting, ...]]:
    metadata = anchor.select(".card_bottom .info_txt > span")
    text = normalize_text(" ".join(span.get_text(" ", strip=True) for span in metadata)) if metadata else legacy_text
    matches = tuple(match for match in _COURSE_MEETING.finditer(text) if match["periods"].strip())
    schedule_text = ", ".join(match[0] for match in matches) or None
    meetings = tuple(CourseMeeting(match["weekday"], match["periods"].strip()) for match in matches)
    return schedule_text, meetings


def _parse_course_roster(soup: BeautifulSoup) -> CourseRoster:
    courses: dict[str, Course] = {}
    container = soup.select_one(".my_lecture_container") or soup
    non_regular_sections = []
    for section in container.select(".term_wrap"):
        heading = section.select_one('.container_subtitle')
        if heading and normalize_text(heading.get_text(" ", strip=True)) == "비정규과목":
            non_regular_sections.append(section)

    selector = 'a[id^="kj_"][onclick*="eclassRoom"]'
    non_regular_anchors = {id(anchor) for section in non_regular_sections for anchor in section.select(selector)}
    for anchor in container.select(selector):
        match = _COURSE_ID.search(str(anchor.get("onclick", "")))
        if not match:
            continue
        course_id = match.group(1)
        non_regular = id(anchor) in non_regular_anchors
        if not _COURSE_KEY.fullmatch(course_id) or (not non_regular and not course_id.startswith("A")):
            continue
        title = normalize_text(str(anchor.get("title", "")))
        name = title.removesuffix(" 강의실 들어가기").strip()
        text = normalize_text(anchor.get_text(" ", strip=True))
        professor_match = _PROFESSOR.search(text)
        codes = set(re.findall(_COURSE_CODE, text.removeprefix(name))) if not non_regular else set()
        legacy_schedule = text[professor_match.end(1):] if professor_match and not non_regular else ""
        schedule_text, meetings = _parse_course_schedule(anchor, legacy_schedule)
        courses[course_id] = Course(
            id=course_id,
            name=name or text,
            professor=professor_match.group(1).strip() if professor_match else None,
            url=absolute(COURSE_HOME),
            category="non_regular" if non_regular else "regular",
            schedule_text=schedule_text,
            meetings=meetings,
            course_code=next(iter(codes)) if len(codes) == 1 else None,
        )
    name_node = soup.select_one("#my_page_menu_pop .user_info .user_name")
    name = normalize_text(name_node.get_text(" ", strip=True)) if name_node else ""
    return CourseRoster(
        list(courses.values()),
        non_regular_available=bool(non_regular_sections),
        display_name=name if 0 < len(name) <= 100 else None,
    )


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


_NOTICE_BODY_TAGS = frozenset({
    "p", "div", "br", "b", "strong", "i", "em", "u", "s", "sub", "sup", "mark",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "hr",
    "ul", "ol", "li", "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td", "a",
})


def course_notice_editor(detail_html: str) -> Tag:
    body = BeautifulSoup(detail_html, "html.parser").select_one(".editor_content")
    if body is None:
        raise RuntimeError("e-Class에서 공지 원문을 확인하지 못했어요.")
    for node in reversed(body.select("script, style, template, iframe, object, embed, svg, math, [hidden], [aria-hidden=true]")):
        node.decompose()
    return body


def parse_course_notice_body(body: Tag, inline_images: dict[str, str], *, allow_remote_images: bool = True) -> str:
    """Keep the notice's structure without carrying over active HTML or page styles."""
    def render(node: object) -> str:
        if type(node) is NavigableString:
            return escape(str(node))
        if not isinstance(node, Tag):
            return ""
        tag = node.name
        if tag == "img":
            raw = node.get("src", "").strip()
            alt = escape(node.get("alt") or "본문 이미지", quote=True)
            src = inline_images.get(raw) or (campus_image_url(raw) if allow_remote_images else None)
            if src:
                return f'<img src="{escape(src, quote=True)}" alt="{alt}" loading="lazy" referrerpolicy="no-referrer">'
            return f'<button type="button" class="course-notice-image-source">{alt} · e-Class에서 확인 ↗</button>'
        if tag in ("br", "hr"):
            return f"<{tag}>"
        children = "".join(render(child) for child in node.children)
        if tag not in _NOTICE_BODY_TAGS:
            return children
        attrs = ""
        if tag == "a":
            if 'class="course-notice-image-source"' in children:
                return children  # A fallback image opens the notice and cannot sit inside another link.
            raw = node.get("href", "").strip()
            try:
                href = urljoin(absolute(NOTICE_FORM), raw)
                target = urlsplit(href)
                if raw and target.scheme in ("https", "http") and target.hostname and not target.username and not target.password:
                    attrs = f' href="{escape(href, quote=True)}"'
            except ValueError:
                pass
            if not attrs:
                return children
        if tag in ("th", "td"):
            for attr in ("colspan", "rowspan"):
                value = node.get(attr, "")
                if re.fullmatch(r"[1-9][0-9]{0,2}", value):
                    attrs += f' {attr}="{value}"'
        return f"<{tag}{attrs}>{children}</{tag}>"

    return "".join(render(child) for child in body.children).strip()


def parse_assignment_index(html: str, course_id: str) -> list[Assignment]:
    soup = BeautifulSoup(html, "html.parser")
    assignments: list[Assignment] = []
    for item in soup.select('a[id^="class_menu_report_"]'):
        assignment_id = str(item.get("id", "")).removeprefix("class_menu_report_")
        title_node = item.select_one(".activity_title")
        title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else normalize_text(item.get_text(" ", strip=True))
        if title.startswith("과제 "):
            title = title[3:].split(" 마감 ", 1)[0].strip()
        classes = {str(value) for value in item.get("class", [])}
        query = urlencode({"m": "report", "n": assignment_id, "mf": "report1"})
        assignments.append(
            Assignment(
                id=assignment_id,
                course_id=course_id,
                title=title,
                submitted=False if "not_submit" in classes else True,
                url=f"{absolute(ACTIVITY_FORM)}?{query}",
            )
        )
    return assignments


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


def _assignment_row_label(row: Tag) -> str:
    cell = row.find(["th", "td"], recursive=False)
    return "".join(cell.get_text().split()) if cell else ""


def _assignment_metadata(rows: list[Tag], table: Tag) -> AssignmentMetadata:
    fields: dict[str, str] = {}
    for row in rows:
        if row.find_parent("table") is not table:
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            value = normalize_text(cells[1].get_text(" ", strip=True))
            fields.setdefault(_assignment_row_label(row), value)
    published = fields.get("공개일", "")
    try:
        published_time = parse_korean_datetime(published)
    except ValueError:
        published_time = None
    return AssignmentMetadata(
        submission_method=fields.get("제출방식") or fields.get("제출방법") or None,
        submission_format=fields.get("제출형태") or fields.get("제출양식") or None,
        published_at=published_time.replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat() if published_time else None,
        points=fields.get("배점") or None,
        score_visibility=fields.get("점수공개") or None,
    )


def enrich_assignment(detail_html: str, assignment: Assignment, *, verify: bool = False) -> Assignment:
    soup = BeautifulSoup(detail_html, "html.parser")
    if verify and not soup.select_one(".view_title, .bbsview, #submit_form"):
        raise ValueError("과제 상세 화면을 확인하지 못했어요.")
    title_node = soup.select_one(".view_title .font_headline2")
    title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else assignment.title
    due_at = None
    late_due_at = None
    rows = [
        row for row in soup.select("table tr")
        if not row.find_parent(id="submit_form") and not row.find_parent(class_="editor_content")
    ]
    due_row = next((row for row in rows if _assignment_row_label(row) == "마감일"), None)
    if due_row is not None:
        due_at = parse_korean_datetime(due_row.get_text(" ", strip=True))
        late_due_at = _late_submission_deadline(due_row)
    metadata_row = due_row or next((
        row for row in rows
        if _assignment_row_label(row) in {"제출방식", "제출방법", "제출형태", "제출양식", "공개일", "배점", "점수공개"}
    ), None)
    metadata_table = metadata_row.find_parent("table") if metadata_row else None
    body = next(
        (node for node in soup.select(".bbsview .editor_content") if not node.find_parent(id="submit_form")),
        None,
    )
    submit = soup.select_one("#submit_form")
    submitted = assignment.submitted
    submitted_at = None
    if submit:
        # The status and timestamp are in the metadata header, above the student's submission.
        stamps = (
            parse_korean_datetime(label.get_text(" ", strip=True))
            for label in submit.select(".inner_title_box .submit_info_box .date")
        )
        submitted_at = max((stamp for stamp in stamps if stamp is not None), default=None)
        statuses = {
            "".join(label.get_text(strip=True).split())
            for label in submit.select(".inner_title_box .submit_info_box .txt")
        }
        if submitted_at is not None or statuses & {"정상제출", "지각제출", "제출완료"}:
            submitted = True
        else:
            status_text = normalize_text(" ".join(
                text for text in submit.strings
                if text.find_parent(class_="editor_content") is None
            ))
            if "제출된 내역이 없습니다" in status_text:
                submitted = False
    return Assignment(
        id=assignment.id,
        course_id=assignment.course_id,
        title=title,
        description=body.get_text("\n", strip=True) if body is not None else None,
        due_at=due_at,
        submitted=submitted,
        url=assignment.url,
        submitted_at=submitted_at,
        late_due_at=late_due_at,
        metadata=_assignment_metadata(rows, metadata_table) if metadata_table else None,
    )


def stable_id(*parts: object) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]
