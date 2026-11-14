from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
from base64 import b64encode
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo
from zlib import error as ZlibError

import httpx
import truststore
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .assignment_summary import AssignmentSummaryCache, assignment_markers, assignment_url, checked_assignment_markers
from .auth import AuthenticationRequired, require_auth_state
from .briefing import build_course_briefing
from .course_classroom import merge_course_home_weeks, parse_course_weeks
from .content import (
    ACTIVITY_COUNT_KEYS,
    AttachmentSource,
    FileLink,
    PostKind,
    ajax_fields,
    is_empty_listing,
    is_item_id,
    parse_course_activities,
    parse_board_ids,
    parse_board_page,
    parse_discussion_comments,
    parse_discussion_opinion,
    parse_discussion_opinions,
    parse_file_links,
    parse_open_boards,
    parse_post_body,
    parse_post_list,
    parse_syllabus,
    qna_attachment_seq,
)
from .attendance import parse_attendance
from .endpoints import (
    ACTIVITY_LIST,
    ALLOWED_GET_PATHS,
    ALLOWED_POST_PATHS,
    ATTACHMENT_DOWNLOAD_PATHS,
    ATTACHMENT_REDIRECT_PATHS,
    ATTENDANCE_LIST,
    BASE_URL,
    BOARD_LIST,
    BOARD_VIEW,
    COURSE_ATTACHMENT_LIST,
    COURSE_FILES,
    COURSE_HOME,
    COURSE_TIMETABLE,
    DISCUSSION_COMMENT_LIST,
    DISCUSSION_OPINION_LIST,
    DISCUSSION_OPINION_VIEW,
    DISCUSSION_VIEW,
    ENTER_COURSE,
    MAIN_FORM,
    MY_INFO,
    NOTICE_LIST,
    NOTICE_VIEW,
    MATERIAL_VIEW,
    QNA_LIST,
    QNA_VIEW,
    REPORT_VIEW,
    SYLLABUS_POP,
    SYLLABUS_VIEW,
    SYSTEM_ATTACHMENT_LIST,
    SYSTEM_NOTICE_LIST,
    SYSTEM_NOTICE_VIEW,
)
from .home_todo import HomeTodoAssignment, read_home_todo
from .models import (
    Assignment, Attachment, AttachmentText, Course, CourseAttendance, CourseOverview, CourseRoster, CourseStats,
    DiscussionOpinion, LearningActivity, Notice, Post, StudentProfile, Syllabus, as_jsonable,
)
from .parser import (
    course_notice_editor, enrich_assignment, enrich_notice, normalize_text, parse_assignment_index,
    parse_authenticated_roster, parse_course_notice_body, parse_notice_datetime, parse_notices, parse_student_profile, stable_id,
)
from .timetable import TIMETABLE_TIMEZONE, parse_course_timetable, syllabus_rooms_by_meeting, syllabus_rooms_by_weekday


class ReadOnlyViolation(RuntimeError):
    pass


class AttachmentReadError(ValueError):
    """An attachment failure whose code and message can be returned to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_BASE_PARTS = urlsplit(BASE_URL)
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_MAX_PDF_BYTES = 12 * 1024 * 1024
_MAX_ASSIGNMENT_ATTACHMENT_BYTES = 32 * 1024 * 1024
_COURSE_NOTICE_IMAGE_BUDGET = 8 * 1024 * 1024
_COURSE_NOTICE_IMAGE_LIMIT = 12
_COURSE_NOTICE_BODY_BATCH = 6
_COURSE_NOTICE_IMAGE_PATH = re.compile(
    r"/ilosfiles/editor-file/(?:[A-Za-z0-9_-]+/)+[\w .()-]+\.(?:png|jpe?g|gif|webp)$", re.I,
)
_COURSE_NOTICE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_MAX_PDF_CHARS = 24_000
_MAX_COURSE_PDF_FILES = 16
_MAX_COURSE_PDF_PAGES = 1_000
_MAX_COURSE_PDF_CHARS = 120_000
_MAX_COURSE_PDF_PAGE_CHARS = 8_000
_COURSE_PDF_CONCURRENCY = 3
# OpenAI accepts less than 50 MB per file and at most 50 MB in one request.
_MAX_COURSE_PDF_BYTES = 50_000_000
_PDF_PARSE_ERRORS = (PdfReadError, RecursionError, KeyError, OSError, OverflowError, TypeError, ValueError, ZlibError)
_ENCODING = {"encoding": "utf-8"}
_ACTIVITY_ARGS = {"MENU_ID": "", "ARTL_NUM": "", **_ENCODING}
_ACTIVITY_KINDS = frozenset({"assignment", "material", "discussion"})
_COURSE_BOARD_KINDS: tuple[PostKind, ...] = ("course_notice", "qna", "open_board")
_MAX_BOARD_PAGES = 100
_LIST_READ_ERRORS = (httpx.HTTPError, RuntimeError, ValueError)
_ASSIGNMENT_READ_ERRORS = (*_LIST_READ_ERRORS, OSError)
_COURSE_FILE_FIELDS = frozenset({"ud", "ky", "pf_st_flag", "CONTENT_SEQ", "encoding"})
_SYSTEM_FILE_FIELDS = frozenset({"CONTENT_SEQ", "encoding"})
_DISCUSSION_LIST_FIELDS = frozenset({"TOPIC_NO", "UNSIGN_YN", "encoding"})
_SYLLABUS_FIELDS = frozenset({
    "KJKEY", "ORG_SECT", "YEAR", "TERM", "LEDG_YEAR", "LEDG_SESSN", "LSSN_CD", "SUBJT_NO", "encoding",
})


def attachment_failure(error: Exception) -> dict[str, str]:
    if isinstance(error, AuthenticationRequired):
        return {"status": "login_required", "code": "login_required", "message": "e-Class 로그인을 확인해 주세요."}
    if isinstance(error, AttachmentReadError):
        return {"status": "error", "code": error.code, "message": str(error)}
    if isinstance(error, ReadOnlyViolation):
        return {
            "status": "error", "code": "attachment_request_blocked",
            "message": "검증한 e-Class 첨부 조회 경로를 벗어나 요청을 차단했어요.",
        }
    return {
        "status": "error", "code": "attachment_lookup_failed",
        "message": "e-Class 첨부 조회를 완료하지 못했어요. 연결과 조회 조건을 확인해 주세요.",
    }


class _CoursePdfBudget:
    def __init__(self) -> None:
        self.used = 0
        self.exceeded = False

    def check(self, file_size: int, additional: int) -> None:
        if self.exceeded or file_size >= _MAX_COURSE_PDF_BYTES or self.used + additional > _MAX_COURSE_PDF_BYTES:
            self.exceeded = True
            raise AttachmentReadError(
                "pdf_batch_too_large", "PDF 원본이 한 요청의 50 MB 한도를 넘어요. 보낼 파일 범위를 줄여 주세요.",
            )


def _allowed_paths(method: str) -> frozenset[str]:
    if method == "GET":
        return ALLOWED_GET_PATHS
    if method == "POST":
        return ALLOWED_POST_PATHS
    return frozenset()


def _validated_url(
    method: str, target: str, *, paths: frozenset[str] | None = None,
) -> str:
    absolute_url = urljoin(f"{BASE_URL}/", target)
    parsed = urlsplit(absolute_url)
    same_origin = (
        parsed.scheme == "https"
        and parsed.hostname == _BASE_PARTS.hostname
        and parsed.port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )
    if not same_origin:
        raise ReadOnlyViolation("공식 e-Class 도메인이 아닌 요청을 차단했습니다.")
    if parsed.path not in (paths if paths is not None else _allowed_paths(method)):
        raise ReadOnlyViolation(
            f"읽기 전용 allowlist에 없는 요청을 차단했습니다: {method} {parsed.path}"
        )
    return absolute_url


def _is_login_url(target: str) -> bool:
    parsed = urlsplit(target)
    return parsed.hostname == _BASE_PARTS.hostname and "login" in parsed.path.casefold()


class SeoultechLMSClient:
    """Read-only client for the verified e-Class HTML/AJAX endpoints."""

    def __init__(self, project_root: Path | None = None, *, browser_state: dict[str, Any] | None = None,
                 session_path: Path | None = None, assignment_cache: AssignmentSummaryCache | None = None) -> None:
        self.project_root = project_root
        self._browser_state = browser_state
        self._session_path = session_path
        self._http: httpx.AsyncClient | None = None
        self._roster_cache: CourseRoster | None = None
        self._assignment_cache = assignment_cache or AssignmentSummaryCache()

    def _cookies(self) -> httpx.Cookies:
        state = self._browser_state
        if state is None:
            path = self._session_path or require_auth_state(self.project_root)
            try:
                with path.open(encoding="utf-8") as saved:
                    state = json.load(saved)
                    file = os.fstat(saved.fileno())
            except FileNotFoundError as exc:
                raise AuthenticationRequired("e-Class 로그인 세션이 없어요.") from exc
            self._assignment_cache.bind((path, file.st_dev, file.st_ino, file.st_mtime_ns),
                                        path.with_name("assignment-summary.json") if self._session_path else None)
        cookies = httpx.Cookies()
        for cookie in state.get("cookies", []):
            domain = str(cookie.get("domain", "")).lstrip(".").lower()
            if domain == _BASE_PARTS.hostname:
                cookies.set(cookie["name"], cookie["value"], domain=domain, path=cookie.get("path", "/"))
        if not cookies:
            raise AuthenticationRequired("e-Class 로그인 쿠키를 확인할 수 없습니다.")
        return cookies

    async def __aenter__(self) -> SeoultechLMSClient:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            cookies=self._cookies(),
            # macOS can build the complete certificate chain via the system trust store.
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            follow_redirects=False,
            timeout=30,
            headers={
                "Accept-Language": "ko-KR,ko;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
                ),
            },
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        self._assignment_cache.flush()
        if self._http:
            await self._http.aclose()
        self._http = None

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        normalized_method = method.upper()
        target = _validated_url(normalized_method, path)
        if self._http is None:
            raise RuntimeError("SeoultechLMSClient는 'async with' 문 안에서 사용해야 합니다.")
        request_kwargs = dict(kwargs)
        for redirect_count in range(_MAX_REDIRECTS + 1):
            response = await self._http.request(normalized_method, target, **request_kwargs)
            if response.status_code in (401, 403) or _is_login_url(str(response.url)):
                raise AuthenticationRequired(
                    "LMS 로그인 세션이 만료되었습니다. start_login 도구를 호출해 로그인 창을 열어주세요. "
                    "터미널에서는 'seoultech-lms login'을 사용할 수 있습니다."
                )
            if response.status_code not in _REDIRECT_STATUS_CODES:
                _validated_url(normalized_method, str(response.url))
                response.raise_for_status()
                if response.text.lstrip().startswith("<script") and "접속이 종료 되었습니다" in response.text:
                    raise AuthenticationRequired("LMS 로그인 세션이 만료되었습니다.")
                return response

            location = response.headers.get("location")
            if not location:
                raise RuntimeError("LMS가 목적지 없는 리다이렉트 응답을 반환했습니다.")
            redirected_target = urljoin(str(response.url), location)
            if _is_login_url(redirected_target):
                raise AuthenticationRequired(
                    "LMS 로그인 세션이 만료되었습니다. start_login 도구를 호출해 로그인 창을 열어주세요. "
                    "터미널에서는 'seoultech-lms login'을 사용할 수 있습니다."
                )
            if response.status_code == 303 or (
                response.status_code in (301, 302) and normalized_method == "POST"
            ):
                normalized_method = "GET"
                for body_key in ("content", "data", "files", "json"):
                    request_kwargs.pop(body_key, None)
            target = _validated_url(normalized_method, redirected_target)
            if redirect_count == _MAX_REDIRECTS:
                break
        raise RuntimeError("LMS 리다이렉트가 허용 횟수를 초과했습니다.")

    async def _enter_course(self, course_id: str) -> None:
        response = await self._request(
            "POST",
            ENTER_COURSE,
            data={
                "KJKEY": course_id,
                "returnData": "json",
                "returnURI": "/ilos/cls/st/submain/submain_form.acl",
                "encoding": "utf-8",
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthenticationRequired(
                "강좌 세션을 열지 못했습니다. start_login 도구를 호출해 로그인 창을 열어주세요. "
                "터미널에서는 'seoultech-lms login'을 사용할 수 있습니다."
            ) from exc
        if not isinstance(payload, dict) or payload.get("isError") is not False:
            raise RuntimeError("강좌 세션 진입에 실패했습니다.")

    async def _get_roster(self) -> CourseRoster:
        if self._roster_cache is None:
            response = await self._request("GET", MAIN_FORM, headers={"Accept": "text/html"})
            self._roster_cache = parse_authenticated_roster(response.text)
            if self._roster_cache is None:
                raise AuthenticationRequired("e-Class 로그인 메인 화면을 확인할 수 없습니다.")
        return self._roster_cache

    async def get_courses(self) -> list[Course]:
        return list((await self._get_roster()).courses)

    async def get_login_roster(self) -> CourseRoster:
        return await self._get_roster()

    async def get_student_profile(
        self, expected_name: str | None, *, include_contact: bool = False,
    ) -> StudentProfile | None:
        try:
            async with asyncio.timeout(4):
                response = await self._request(
                    "POST", MY_INFO, data=_ENCODING, headers={"Referer": BASE_URL + MAIN_FORM},
                )
                profile = parse_student_profile(response.text, include_contact=include_contact)
        except AuthenticationRequired:
            if include_contact:
                raise
            return None
        except (httpx.HTTPError, OSError, RuntimeError, ValueError):
            return None
        if profile and (expected_name is None or profile.display_name == expected_name):
            return profile
        return None

    async def get_course_timetable(
        self, on_date: date | None = None, course_id: str | None = None, *, include_rooms: bool = False,
    ) -> dict[str, Any]:
        selected_date = on_date or datetime.now(ZoneInfo(TIMETABLE_TIMEZONE)).date()
        courses = {course.id: course for course in await self.get_courses()}
        if course_id is not None:
            if course_id not in courses:
                raise ValueError("수강 목록에서 확인한 강좌 ID를 지정해 주세요.")
            courses = {course_id: courses[course_id]}
        response = await self._request("POST", COURSE_TIMETABLE, data={
            "startDate": selected_date.isoformat().replace("-", ""), **_ENCODING,
        })
        timetable = parse_course_timetable(response.text, selected_date, courses)
        if include_rooms:
            missing: dict[str, list[dict[str, Any]]] = {}
            for entry in timetable["entries"]:
                enrolled_course = courses[entry["course_id"]]
                if entry["room"] is None and enrolled_course.meetings:
                    missing.setdefault(enrolled_course.id, []).append(entry)
            try:
                async with asyncio.timeout(12):
                    for missing_id, entries in missing.items():
                        try:
                            syllabus = await self.get_syllabus(missing_id)
                        except AuthenticationRequired:
                            break
                        except _LIST_READ_ERRORS:
                            continue
                        rooms = syllabus_rooms_by_weekday(syllabus, courses[missing_id])
                        for entry in entries:
                            if room := rooms.get(entry["weekday"]):
                                entry["room"] = room
                                entry["room_source"] = "syllabus"
            except TimeoutError:
                pass
        return timetable

    async def get_course_overview(self, *, include_attendance: bool = False) -> CourseOverview:
        roster = await self._get_roster()
        regular_count = sum(course.category == "regular" for course in roster.courses)
        stats = []
        # e-Class stores the active course on the session, so courses must be visited in order.
        for course in roster.courses:
            stats.append(await self._read_course_stats(course, include_attendance=include_attendance))
        return CourseOverview(
            regular=regular_count,
            non_regular=len(roster.courses) - regular_count if roster.non_regular_available else None,
            courses=stats,
        )

    async def _read_course_stats(self, course: Course, *, include_attendance: bool) -> CourseStats:
        counts: dict[str, int | None] = dict.fromkeys((*ACTIVITY_COUNT_KEYS, *_COURSE_BOARD_KINDS, "files"))
        try:
            await self._enter_course(course.id)
        except AuthenticationRequired:
            raise
        except _LIST_READ_ERRORS:
            return CourseStats(course, counts, None)

        learning_activity = None
        try:
            response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
            activity_counts, learning_activity = parse_course_activities(response.text)
            counts.update(activity_counts)
        except AuthenticationRequired:
            raise
        except _LIST_READ_ERRORS:
            pass

        return await self._read_course_stats_details(course, counts, learning_activity, include_attendance=include_attendance)

    async def _read_course_stats_details(
        self, course: Course, counts: dict[str, int | None],
        learning_activity: LearningActivity | None, *, include_attendance: bool,
    ) -> CourseStats:
        for kind in _COURSE_BOARD_KINDS:
            try:
                if kind == "open_board":
                    home = await self._request("GET", COURSE_HOME)
                    groups = parse_board_ids(home.text)
                    counts[kind] = sum([await self._count_board(kind, course.id, group) for group in groups])
                else:
                    counts[kind] = await self._count_board(kind, course.id)
            except AuthenticationRequired:
                raise
            except _LIST_READ_ERRORS:
                continue

        try:
            response = await self._request("POST", COURSE_FILES, data={"SCH_VALUE": "", **_ENCODING})
            files = parse_file_links(response.text)
            if files or is_empty_listing(BeautifulSoup(response.text, "html.parser")):
                counts["files"] = len(files)
        except AuthenticationRequired:
            raise
        except _LIST_READ_ERRORS:
            pass
        attendance = await self._read_attendance() if include_attendance and course.category == "regular" else None
        known_posts = [count for kind, count in counts.items() if kind != "files" and count is not None]
        return CourseStats(course, counts, sum(known_posts) if known_posts else None, attendance, learning_activity)

    async def _read_attendance(self) -> CourseAttendance | None:
        try:
            response = await self._request("POST", ATTENDANCE_LIST, data={"SCH_WEEK_NO": "", **_ENCODING})
            return parse_attendance(response.text)
        except AuthenticationRequired:
            raise
        except _LIST_READ_ERRORS:
            return None

    async def get_home_course_index(self, course_id: str) -> dict[str, Any]:
        # The desktop supplies IDs from the authenticated roster. e-Class checks enrollment at entry.
        await self._enter_course(course_id)
        response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
        counts, activity = parse_course_activities(response.text)
        soup = BeautifulSoup(response.text, "html.parser")
        rows = {node["id"]: node for node in soup.select('a[id^="class_menu_"]')}
        markers = [
            {"id": item.id, "title": item.title, "submitted": item.submitted, "signature": signature}
            for item, signature in assignment_markers(response.text, course_id, soup)
        ]
        notices = await self._read_course_notice_index(course_id)
        return {
            "assignments": markers,
            "notices": [as_jsonable(item) for item in notices],
            "counts": counts,
            "learning_activity": as_jsonable(activity) if activity else None,
            "signature": stable_id(sorted(rows), counts, sorted(item.id for item in notices)),
        }

    async def get_course_classroom(self, course_id: str) -> dict[str, Any]:
        await self._open_course(course_id)
        weeks = None
        try:
            async with asyncio.timeout(8):
                activity = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
            weeks = parse_course_weeks(activity.text, course_id)
        except AuthenticationRequired:
            raise
        except (OSError, *_LIST_READ_ERRORS):
            pass
        open_boards = []
        try:
            async with asyncio.timeout(5):
                home = await self._request("GET", COURSE_HOME)
            open_boards = parse_open_boards(home.text)
            merged = merge_course_home_weeks(weeks or [], home.text, course_id)
            if merged:
                weeks = merged
        except AuthenticationRequired:
            raise
        except (OSError, *_LIST_READ_ERRORS):
            pass
        if weeks is None:
            raise ValueError("강의실 활동 목록 구조를 확인할 수 없습니다.")
        return {"weeks": weeks, "open_boards": open_boards}

    async def get_course_classroom_info(self, course_id: str) -> dict[str, Any]:
        course = next((course for course in await self.get_courses() if course.id == course_id), None)
        if course is None:
            raise ValueError("수강 중인 과목의 course_id를 지정해 주세요.")

        entries = []
        try:
            async with asyncio.timeout(6):
                timetable = await self.get_course_timetable(course_id=course_id)
            entries = timetable["entries"]
        except AuthenticationRequired:
            raise
        except (OSError, *_LIST_READ_ERRORS):
            pass

        displayed_days = {entry["weekday"] for entry in entries}
        remaining_meetings = [slot for slot in course.meetings if slot.weekday not in displayed_days]
        syllabus_rooms = {}
        if course.meetings and (remaining_meetings or any(not entry["room"] for entry in entries)):
            try:
                async with asyncio.timeout(8):
                    syllabus = await self.get_syllabus(course_id)
                syllabus_rooms = syllabus_rooms_by_meeting(syllabus, course)
            except AuthenticationRequired:
                raise
            except (OSError, *_LIST_READ_ERRORS):
                pass

        def meeting_room(weekday: str, periods: str) -> str | None:
            return syllabus_rooms.get((weekday, "".join(periods.split())))

        meetings = []
        for entry in entries:
            weekday = entry["weekday"]
            room = entry["room"]
            if not room:
                rooms = {meeting_room(weekday, slot.periods) for slot in course.meetings if slot.weekday == weekday}
                if len(rooms) == 1:
                    room = rooms.pop()
            meetings.append({"weekday": weekday, "start_time": entry["start_time"], "end_time": entry["end_time"], "room": room})

        meetings.extend({"weekday": slot.weekday, "periods": slot.periods, "room": meeting_room(slot.weekday, slot.periods)}
                        for slot in remaining_meetings)
        meetings.sort(key=lambda meeting: "월화수목금토일".index(meeting["weekday"]))
        return {"course_code": course.course_code, "meetings": meetings}

    async def get_home_course_details(
        self, course_id: str, assignment_ids: list[str], include_stats: bool, include_attendance: bool,
    ) -> dict[str, Any]:
        course = await self._open_course(course_id)
        details = []
        listed = {}
        if assignment_ids:
            response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
            listed = {item.id: (item, signature) for item, signature in checked_assignment_markers(response.text, course_id)}
        for assignment_id in assignment_ids:
            marker = listed.get(assignment_id)
            if marker is None:
                continue
            try:
                indexed, signature = marker
                item = self._assignment_cache.get(indexed, signature)
                if item is None or (item.submitted is True and item.submitted_at is None):
                    item = await self._read_assignment_detail(indexed, verify=True)
                    self._assignment_cache.put(item, signature)
                details.append({
                    **{key: value for key, value in as_jsonable(item).items()
                       if key in {"id", "due_at", "submitted", "submitted_at", "late_due_at"}},
                    "signature": signature,
                })
            except AuthenticationRequired:
                raise
            except _LIST_READ_ERRORS:
                continue
        stats = None
        if include_stats:
            counts: dict[str, int | None] = dict.fromkeys((*_COURSE_BOARD_KINDS, "files"))
            stats = as_jsonable(await self._read_course_stats_details(
                course, counts, None, include_attendance=include_attendance,
            ))
        elif include_attendance and course.category == "regular":
            stats = as_jsonable(CourseStats(course, {}, None, await self._read_attendance()))
        return {"assignments": details, "stats": stats}

    async def _count_board(self, kind: PostKind, course_id: str, board_id: str | None = None) -> int:
        seen: set[str] = set()
        for page in range(1, _MAX_BOARD_PAGES + 1):
            response = await self._board_response(kind, page, board_id)
            ids, has_next = parse_board_page(response.text, kind, course_id, board_id, page, self._board_page_size(kind))
            seen.update(ids)
            if not has_next:
                return len(seen)
        raise RuntimeError("게시판 집계에 허용된 페이지 수를 초과했습니다.")

    async def get_notices(
        self,
        course_id: str | None = None,
        *,
        include_content: bool = True,
    ) -> list[Notice]:
        courses = await self.get_courses()
        selected = [course for course in courses if course.id == course_id] if course_id else courses
        if course_id and not selected:
            raise ValueError(f"수강 중인 과목 ID가 아닙니다: {course_id}")
        results: list[Notice] = []
        for course in selected:
            await self._enter_course(course.id)
            notices = await self._read_course_notice_index(course.id)
            if not include_content:
                results.extend(notices)
                continue
            for notice in notices:
                detail = await self._request(
                    "POST",
                    NOTICE_VIEW,
                    data={"ARTL_NUM": notice.id, "encoding": "utf-8"},
                )
                results.append(enrich_notice(detail.text, notice))
        return results

    async def _read_course_notice_index(self, course_id: str) -> list[Notice]:
        response = await self._request(
            "POST", NOTICE_LIST, data={"start": "", "display": "100", "SCH_VALUE": "", "ODR": "", **_ENCODING},
        )
        return parse_notices(response.text, course_id)

    async def _read_course_notice_page(self, course_id: str, page: int) -> tuple[list[Notice], bool]:
        if not 1 <= page <= _MAX_BOARD_PAGES:
            raise ValueError("공지 페이지 번호를 확인해 주세요.")
        async with asyncio.timeout(8):
            response = await self._board_response("course_notice", page, None)
        ids, has_next = parse_board_page(
            response.text, "course_notice", course_id, None, page, self._board_page_size("course_notice"),
        )
        notices = {item.id: item for item in parse_notices(response.text, course_id) if item.id in ids}
        return list(notices.values()), has_next

    async def get_course_recent_notices(self, course_id: str) -> dict[str, Any]:
        found: dict[str, tuple[Notice, int]] = {}
        has_next = True
        page = 1
        try:
            async with asyncio.timeout(20):
                course = await self._open_course(course_id)
                while has_next and page <= _MAX_BOARD_PAGES:
                    notices, has_next = await self._read_course_notice_page(course_id, page)
                    for notice in notices:
                        found.setdefault(notice.id, (notice, page))
                    page += 1
        except AuthenticationRequired:
            raise
        except (OSError, *_LIST_READ_ERRORS):
            if page == 1:
                raise
            has_next = True
        # The server's page order does not always match the notices' timestamps.
        latest = sorted(found.values(), key=lambda item: item[0].created_at or datetime.min, reverse=True)[:3]
        return {
            "notices": [{**as_jsonable(item), "course_name": course.name, "page": page} for item, page in latest],
            "partial": has_next,
        }

    async def get_course_notice_page(self, course_id: str, page: int, query: str) -> dict[str, Any]:
        course = await self._open_course(course_id)
        notices, has_next = await self._read_course_notice_page(course_id, page)
        needle = normalize_text(query).casefold()
        partial = has_next and page == _MAX_BOARD_PAGES
        if needle:
            gate = asyncio.Semaphore(4)

            async def match(notice: Notice) -> tuple[Notice | None, bool]:
                if needle in normalize_text(notice.title).casefold():
                    return notice, False
                try:
                    async with gate, asyncio.timeout(4):
                        detail = await self._request("POST", NOTICE_VIEW, data={"ARTL_NUM": notice.id, **_ENCODING})
                    editor = course_notice_editor(detail.text)
                    body = normalize_text(editor.get_text(" ", strip=True))
                except AuthenticationRequired:
                    raise
                except (OSError, *_LIST_READ_ERRORS):
                    preview = normalize_text(notice.content or "").casefold()
                    return (notice if needle in preview else None), True
                position = body.casefold().find(needle)
                if position == -1:
                    return None, False
                start = max(0, position - 60)
                end = position + len(needle) + 120
                snippet = ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")
                return replace(notice, content=snippet), False

            results = await asyncio.gather(*(match(notice) for notice in notices), return_exceptions=True)
            notices = []
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                notice, failed = result
                partial |= failed
                if notice is not None:
                    notices.append(notice)
        return {
            "notices": [{**as_jsonable(item), "course_name": course.name, "page": page} for item in notices],
            "has_next": has_next and page < _MAX_BOARD_PAGES,
            "partial": partial,
        }

    async def get_course_notice(self, course_id: str, notice_id: str, *, page: int | None = None) -> dict[str, Any]:
        await self._open_course(course_id)
        if page is None:
            notices = await self._read_course_notice_index(course_id)
        else:
            notices, _ = await self._read_course_notice_page(course_id, page)
        notice = next((item for item in notices if item.id == notice_id), None)
        if notice is None:
            raise ValueError("해당 강좌의 공지 목록에서 글을 찾지 못했어요.")
        detail = await self._request("POST", NOTICE_VIEW, data={"ARTL_NUM": notice.id, **_ENCODING})
        editor = course_notice_editor(detail.text)
        images: dict[str, str] = {}
        remaining = _COURSE_NOTICE_IMAGE_BUDGET
        sources = dict.fromkeys(image.get("src", "").strip() for image in editor.select("img[src]"))
        try:
            async with asyncio.timeout(12):
                for src in list(sources)[:_COURSE_NOTICE_IMAGE_LIMIT]:
                    if remaining <= 0:
                        break
                    try:
                        image = await self._read_course_notice_image(src, remaining)
                    except (httpx.HTTPError, ValueError):
                        continue
                    if image:
                        mime, content = image
                        remaining -= len(content)
                        images[src] = f"data:{mime};base64,{b64encode(content).decode('ascii')}"
        except TimeoutError:
            pass  # A slow image must not prevent the notice from opening.
        body_html = parse_course_notice_body(editor, images)
        try:
            post = Post(notice.id, "course_notice", notice.title, course_id)
            links = await self._attachment_links(post, detail.text)
        except _LIST_READ_ERRORS:
            links = None
        return {
            "body_html": body_html,
            "attachments": [{"id": link.attachment.id, "name": link.attachment.name} for link in links or []],
        }

    async def get_course_notice_bodies(self, course_id: str, page: int, notice_ids: list[str]) -> dict[str, Any]:
        """Index the full text and markup of listed notices without fetching files or images."""
        if not 1 <= len(notice_ids) <= _COURSE_NOTICE_BODY_BATCH or not all(is_item_id(id_) for id_ in notice_ids):
            raise ValueError("공지 번호를 확인해 주세요.")
        await self._open_course(course_id)
        notices, _ = await self._read_course_notice_page(course_id, page)
        listed = {notice.id for notice in notices}
        gate = asyncio.Semaphore(3)

        async def read_body(notice_id: str) -> dict[str, str] | None:
            try:
                async with gate, asyncio.timeout(4):
                    detail = await self._request("POST", NOTICE_VIEW, data={"ARTL_NUM": notice_id, **_ENCODING})
                editor = course_notice_editor(detail.text)
                return {
                    "id": notice_id,
                    "text": normalize_text(editor.get_text(" ", strip=True)),
                    "body_html": parse_course_notice_body(editor, {}, allow_remote_images=False),
                }
            except AuthenticationRequired:
                raise
            except (OSError, *_LIST_READ_ERRORS):
                return None

        results = await asyncio.gather(*(read_body(id_) for id_ in dict.fromkeys(notice_ids) if id_ in listed),
                                       return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return {"bodies": [result for result in results if result is not None]}

    async def _read_course_notice_image(self, src: str, remaining: int) -> tuple[str, bytes] | None:
        url = urlsplit(urljoin(f"{BASE_URL}/", src))
        path = unquote(url.path)
        if url.query or url.fragment or not _COURSE_NOTICE_IMAGE_PATH.fullmatch(path):
            return None
        if (url.scheme, url.netloc) != ("https", _BASE_PARTS.netloc):
            return None
        assert self._http is not None
        async with self._http.stream("GET", url.geturl(), follow_redirects=False, timeout=5) as response:
            mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            if not response.is_success or mime not in _COURSE_NOTICE_IMAGE_TYPES:
                return None
            declared = response.headers.get("content-length", "")
            if declared.isascii() and declared.isdecimal() and int(declared) > remaining:
                return None
            content = bytearray()
            async for chunk in response.aiter_bytes(64 * 1024):
                if len(content) + len(chunk) > remaining:
                    return None
                content.extend(chunk)
            return (mime, bytes(content)) if content else None

    async def get_assignments(self, course_id: str | None = None, include_completed: bool = True) -> list[Assignment]:
        courses = await self.get_courses()
        selected = [course for course in courses if course.id == course_id] if course_id else courses
        if course_id and not selected:
            raise ValueError(f"수강 중인 과목 ID가 아닙니다: {course_id}")
        results: list[Assignment] = []
        for course in selected:
            await self._enter_course(course.id)
            for assignment in await self._read_course_assignment_index(course.id):
                if not include_completed and assignment.submitted is True:
                    continue
                results.append(await self._read_assignment_detail(assignment))
        return results

    async def get_assignment_summary(self, course_id: str | None = None, *, refresh_details: bool = False) -> dict[str, Any]:
        seoul = ZoneInfo(TIMETABLE_TIMEZONE)

        def in_seoul(value: datetime | None) -> str | None:
            return value.replace(tzinfo=seoul).isoformat() if value else None

        roster = await self._get_roster()
        courses = {course.id: course for course in roster.courses if course_id is None or course.id == course_id}
        if course_id is not None and not courses:
            raise ValueError("수강 목록에서 확인한 강좌 ID를 지정해 주세요.")
        if course_id is None:
            self._assignment_cache.retain_courses(set(courses))

        hints = await read_home_todo(self._request)
        by_course: dict[str, dict[str, HomeTodoAssignment]] = {}
        unavailable: list[str] = []
        for hint in hints["assignments"]:
            hint_course, hint_id = hint["course_id"], hint["id"]
            if hint_course not in courses:
                if course_id is None:
                    message = "할일에 표시된 일부 과제의 수강 강좌를 확인하지 못했어요."
                    if message not in unavailable:
                        unavailable.append(message)
                continue
            by_course.setdefault(hint_course, {})[hint_id] = hint

        assignments = []
        for course in courses.values():
            todo = by_course.get(course.id, {})
            current = {
                hint_id: (Assignment(hint_id, course.id, hint["title"], url=assignment_url(hint_id)),
                          stable_id("home-todo", hint_id, hint["title"], hint["deadline_text"]))
                for hint_id, hint in todo.items()
            }
            try:
                await self._enter_course(course.id)
            except AuthenticationRequired:
                raise
            except _ASSIGNMENT_READ_ERRORS:
                unavailable.append(f"{course.name}의 강의실을 열지 못했어요.")
                continue
            try:
                response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
                indexed = {item.id: (item, signature) for item, signature in checked_assignment_markers(response.text, course.id)}
                current.update(indexed)
                self._assignment_cache.retain_course_assignments(course.id, set(current))
                index_checked = True
            except AuthenticationRequired:
                raise
            except _ASSIGNMENT_READ_ERRORS:
                unavailable.append(f"{course.name}의 최신 과제 목록을 확인하지 못했어요.")
                index_checked = False

            incomplete = False
            for item, signature in current.values():
                hint = todo.get(item.id)
                if item.submitted is True and hint is None:
                    self._assignment_cache.discard(item)
                    continue
                detail = None if refresh_details or not index_checked else self._assignment_cache.get(item, signature)
                if detail and item.submitted is not None and detail.submitted is not item.submitted:
                    detail = None
                if detail and hint:
                    # The widget omits the year. A mismatch invalidates the cache but supplies no deadline.
                    displayed = parse_notice_datetime(
                        f"{detail.due_at.year}년 {hint['deadline_text']}", course.id,
                    )
                    if (detail.submitted is True and item.submitted is not True or
                            displayed and displayed not in (detail.due_at, detail.late_due_at)):
                        detail = None
                if detail is None:
                    try:
                        candidate = replace(item, submitted=None) if hint and item.submitted is True else item
                        detail = await self._read_assignment_detail(candidate, verify=True)
                        if index_checked:
                            self._assignment_cache.put(detail, signature)
                    except AuthenticationRequired:
                        raise
                    except _ASSIGNMENT_READ_ERRORS:
                        self._assignment_cache.discard(item)
                        detail = replace(item, submitted=None) if item.submitted is True else item
                if detail.submitted is True:
                    continue
                checked = detail.due_at is not None
                incomplete |= not checked or detail.submitted is None
                assignments.append({
                    "id": detail.id, "course_id": course.id, "course_name": course.name,
                    "title": detail.title, "url": detail.url, "submitted": detail.submitted,
                    "due_at": in_seoul(detail.due_at), "late_due_at": in_seoul(detail.late_due_at),
                    "submitted_at": in_seoul(detail.submitted_at),
                    "deadline_checked": checked,
                })
            if incomplete:
                unavailable.append(f"{course.name}의 일부 과제 마감이나 제출 상태를 확인하지 못했어요.")

        assignments.sort(key=lambda row: (row["due_at"] is None, row["due_at"] or "", row["title"]))
        return {
            "status": "ok", "as_of": datetime.now(seoul).isoformat(),
            "assignments": assignments, "todo_checked": hints["complete"],
            **({"unavailable": unavailable} if unavailable else {}),
        }

    async def _read_course_assignment_index(self, course_id: str) -> list[Assignment]:
        response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
        return parse_assignment_index(response.text, course_id)

    async def _read_assignment_detail(self, assignment: Assignment, *, verify: bool = False) -> Assignment:
        response = await self._request(
            "GET", REPORT_VIEW, params={"RT_SEQ": assignment.id, **_ENCODING}, headers={"Accept": "text/html"},
        )
        return enrich_assignment(response.text, assignment, verify=verify)

    async def find_assignment_todo(self, assignment_id: str, course_id: str) -> HomeTodoAssignment | None:
        todo = await read_home_todo(self._request)
        return next((item for item in todo["assignments"]
                     if item["id"] == assignment_id and item["course_id"] == course_id), None)

    async def get_course_briefing(self) -> dict[str, Any]:
        courses = await self.get_courses()
        assignments: list[Assignment] = []
        notices: list[Notice] = []
        unavailable: list[str] = []
        # The LMS keeps the selected course in the current session.
        for course in courses:
            try:
                await self._enter_course(course.id)
            except AuthenticationRequired:
                raise
            except _LIST_READ_ERRORS:
                unavailable.append(f"{course.name}의 강의실을 열지 못했어요.")
                continue

            try:
                notices.extend(await self._read_course_notice_index(course.id))
            except AuthenticationRequired:
                raise
            except _LIST_READ_ERRORS:
                unavailable.append(f"{course.name}의 강의 공지를 불러오지 못했어요.")

            try:
                course_assignments = await self._read_course_assignment_index(course.id)
            except AuthenticationRequired:
                raise
            except _LIST_READ_ERRORS:
                unavailable.append(f"{course.name}의 과제 목록을 불러오지 못했어요.")
                continue

            incomplete = False
            for item in course_assignments:
                # An absent "not_submit" marker alone does not confirm a submission.
                assignment = replace(item, submitted=None) if item.submitted is True else item
                try:
                    assignment = await self._read_assignment_detail(assignment)
                except AuthenticationRequired:
                    raise
                except _LIST_READ_ERRORS:
                    incomplete = True
                assignments.append(assignment)
                if assignment.submitted is True and assignment.submitted_at is None:
                    incomplete = True
            if incomplete:
                unavailable.append(f"{course.name}의 일부 과제 상세 정보 또는 제출 시각을 확인하지 못했어요.")

        return build_course_briefing(courses, assignments, notices, unavailable)

    async def _open_course(self, course_id: str | None) -> Course:
        course = next((course for course in await self.get_courses() if course.id == course_id), None)
        if course is None:
            raise ValueError("수강 중인 과목의 course_id를 지정해 주세요.")
        await self._enter_course(course.id)
        return course

    @staticmethod
    def _board_page_size(kind: PostKind) -> int:
        return 8 if kind == "qna" else 20

    async def _board_response(self, kind: PostKind, page: int, board_id: str | None) -> httpx.Response:
        size = self._board_page_size(kind)
        # e-Class calls this a page in the UI, but the request takes a 1-based row offset.
        listing = {
            "start": str((page - 1) * size + 1), "display": str(size),
            "SCH_VALUE": "", "ODR": "", **_ENCODING,
        }
        if kind == "course_notice":
            return await self._request("POST", NOTICE_LIST, data=listing)
        if kind == "system_notice":
            return await self._request("POST", SYSTEM_NOTICE_LIST, data={**listing, "SCH_TARGET": ""})
        if kind == "qna":
            return await self._request("POST", QNA_LIST, data={**listing, "SCH_FAQ": "", "SCH_STATUS": ""})
        if kind == "open_board":
            return await self._request("POST", BOARD_LIST, data={**listing, "ARTL_GRP_ID": board_id})
        raise ValueError("지원하지 않는 게시판 종류입니다.")

    async def _list_posts(
        self, kind: PostKind, course_id: str | None, page: int, board_id: str | None,
    ) -> list[Post]:
        if page < 1:
            raise ValueError("page는 1 이상이어야 합니다.")
        if board_id is not None and kind != "open_board":
            raise ValueError("board_id는 열린게시판에서만 지정할 수 있습니다.")
        if kind == "system_notice":
            if course_id is not None:
                raise ValueError("학교 전체 공지는 course_id 없이 조회해 주세요.")
        else:
            await self._open_course(course_id)

        if kind in _ACTIVITY_KINDS:
            if page != 1:
                return []
            response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
        elif kind == "open_board":
            home = await self._request("GET", COURSE_HOME)
            groups = parse_board_ids(home.text)
            if board_id is not None:
                if board_id not in groups:
                    raise ValueError("강좌에서 확인할 수 있는 열린게시판 ID를 지정해 주세요.")
                groups = [board_id]
            posts = []
            for group in groups:
                response = await self._board_response(kind, page, group)
                posts.extend(parse_post_list(response.text, kind, course_id, group))
            return posts
        else:
            response = await self._board_response(kind, page, board_id)
        return parse_post_list(response.text, kind, course_id)

    async def list_posts(
        self, kind: PostKind, course_id: str | None = None, *, page: int = 1, board_id: str | None = None,
    ) -> list[Post]:
        return await self._list_posts(kind, course_id, page, board_id)

    async def list_discussion_opinions(self, course_id: str, topic_id: str) -> list[DiscussionOpinion]:
        if not is_item_id(topic_id):
            raise ValueError("올바른 토론 주제 ID를 지정해 주세요.")
        topics = await self.list_posts("discussion", course_id)
        if not any(topic.id == topic_id for topic in topics):
            raise ValueError("강좌의 토론 목록에서 확인한 주제 ID를 지정해 주세요.")
        topic = await self._request("GET", DISCUSSION_VIEW, params={"TOPIC_NO": topic_id, **_ENCODING})
        fields = ajax_fields(topic.text, DISCUSSION_OPINION_LIST, _DISCUSSION_LIST_FIELDS)
        if fields is None or fields["TOPIC_NO"] != topic_id or fields["UNSIGN_YN"] not in ("Y", "N"):
            raise RuntimeError("e-Class의 토론 의견 조회 정보를 확인하지 못했습니다.")
        response = await self._request("POST", DISCUSSION_OPINION_LIST, data={
            **fields, "start": "1", "display": "10", "SCH_VALUE": "", "SCH_MINE_YN": "N", "ODR": "",
        })
        return parse_discussion_opinions(response.text, course_id, topic_id)

    async def get_discussion_opinion(self, course_id: str, topic_id: str, opinion_id: str) -> DiscussionOpinion:
        if not is_item_id(opinion_id):
            raise ValueError("올바른 토론 의견 ID를 지정해 주세요.")
        opinions = await self.list_discussion_opinions(course_id, topic_id)
        opinion = next((item for item in opinions if item.id == opinion_id), None)
        if opinion is None:
            raise ValueError("이 토론의 의견 목록에서 확인한 ID를 지정해 주세요.")
        response = await self._request("POST", DISCUSSION_OPINION_VIEW, data={
            "TOPIC_NO": topic_id, "ARTL_NUM": opinion.id, **_ENCODING,
        })
        detail, comment_fields = parse_discussion_opinion(response.text, opinion)
        if comment_fields is None:
            return detail
        response = await self._request("POST", DISCUSSION_COMMENT_LIST, data=comment_fields)
        return replace(detail, comments=parse_discussion_comments(response.text))

    async def _post_with_links(
        self, kind: PostKind, post_id: str, course_id: str | None, page: int, board_id: str | None,
        *, verify_download_target: bool = False,
    ) -> tuple[Post, list[FileLink] | None]:
        matches = [
            item for item in await self._list_posts(kind, course_id, page, board_id) if item.id == post_id
        ]
        from_todo = False
        if not matches and kind == "assignment" and course_id is not None and page == 1:
            hint = await self.find_assignment_todo(post_id, course_id)
            if hint:
                matches.append(Post(post_id, kind, hint["title"], course_id=course_id))
                from_todo = True
        if len(matches) != 1:
            raise ValueError("목록에서 확인한 게시물 ID와 해당 페이지를 지정해 주세요.")
        post = matches[0]
        data = {"ARTL_NUM": post.id, **_ENCODING}
        if kind == "assignment":
            response = await self._request("GET", REPORT_VIEW, params={"RT_SEQ": post.id, **_ENCODING})
            assignment = enrich_assignment(response.text, Assignment(
                post.id, post.course_id or "", post.title, submitted=post.submitted,
            ), verify=from_todo)
            post = replace(post, title=assignment.title, content=assignment.description,
                           due_at=assignment.due_at, submitted=assignment.submitted, late_due_at=assignment.late_due_at,
                           assignment_metadata=assignment.metadata)
        elif kind == "discussion":
            response = await self._request("GET", DISCUSSION_VIEW, params={"TOPIC_NO": post.id, **_ENCODING})
        elif kind == "material":
            response = await self._request("GET", MATERIAL_VIEW, params=data)
        else:
            views = {
                "course_notice": NOTICE_VIEW,
                "system_notice": SYSTEM_NOTICE_VIEW,
                "qna": QNA_VIEW,
                "open_board": BOARD_VIEW,
            }
            if post.board_id is not None:
                data["ARTL_GRP_ID"] = post.board_id
            response = await self._request("POST", views[kind], data=data)
        if kind != "assignment":
            title, body = parse_post_body(response.text)
            post = replace(post, title=title or post.title, content=body)
        return post, await self._attachment_links(post, response.text, verify_download_target=verify_download_target)

    async def _attachment_links(
        self, post: Post, html: str, *, verify_download_target: bool = False,
    ) -> list[FileLink] | None:
        if post.kind == "system_notice":
            path, fields = SYSTEM_ATTACHMENT_LIST, _SYSTEM_FILE_FIELDS
        else:
            path, fields = COURSE_ATTACHMENT_LIST, _COURSE_FILE_FIELDS
        seq = qna_attachment_seq(html, post.id) if post.kind == "qna" else None
        data = ajax_fields(html, path, fields, content_seq=seq)
        if not data or not data["CONTENT_SEQ"]:
            return None
        if post.course_id is not None and data.get("ky") != post.course_id:
            raise ReadOnlyViolation("현재 강좌와 첨부 목록의 강좌가 일치하지 않습니다.")
        response = await self._request("POST", path, data=data)
        links = parse_file_links(response.text)
        if not verify_download_target:
            return links
        # The scoped file list issues a download CONTENT_SEQ distinct from its lookup key.
        verified = []
        for link in links:
            params = parse_qs(urlsplit(link.href).query, keep_blank_values=True)
            content_keys = params.get("CONTENT_SEQ", [])
            if params.get("FILE_SEQ") != [link.attachment.id] or len(content_keys) != 1 or not is_item_id(content_keys[0]):
                continue
            if any(key in params and params[key] != [data.get(key)] for key in ("ky", "ud", "pf_st_flag")):
                continue
            verified.append(link)
        return verified

    async def get_post(
        self, kind: PostKind, post_id: str, course_id: str | None = None,
        *, page: int = 1, board_id: str | None = None,
    ) -> Post:
        post, links = await self._post_with_links(kind, post_id, course_id, page, board_id)
        return replace(post, attachments=tuple(link.attachment for link in links) if links is not None else None)

    async def get_assignment_attachment_file(
        self, course_id: str, assignment_id: str, attachment_id: str, *, for_analysis: bool = False,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id) or not (
            is_item_id(assignment_id) and is_item_id(attachment_id)
        ):
            raise AttachmentReadError("invalid_attachment_id", "강좌·과제·첨부 ID를 확인해 주세요.")
        try:
            _, links = await self._post_with_links(
                "assignment", assignment_id, course_id, 1, None, verify_download_target=True,
            )
        except ValueError as exc:
            raise AttachmentReadError("attachment_source_not_found", "선택한 강좌의 과제를 확인하지 못했어요.") from exc
        link = next((item for item in links or [] if item.attachment.id == attachment_id), None)
        if link is None:
            raise AttachmentReadError("attachment_not_found", "현재 과제에서 확인한 첨부를 선택해 주세요.")

        async with self._attachment_response(link.href) as response:
            mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            disposition = response.headers.get("content-disposition", "").partition(";")[0].strip().lower()
            encoding = response.headers.get("content-encoding", "identity").strip().lower()
            if response.status_code != 200 or encoding not in ("", "identity"):
                raise AttachmentReadError("attachment_download_failed", "e-Class에서 첨부 원본을 받지 못했어요.")
            if mime in ("text/html", "application/xhtml+xml") and disposition not in ("attachment", "inline"):
                raise AttachmentReadError("attachment_download_failed", "e-Class에서 첨부 대신 웹페이지를 반환했어요.")
            content = await _read_assignment_attachment_response(response)

        if for_analysis and content.startswith(b"%PDF-"):
            try:
                _open_pdf(content)
            except AttachmentReadError:
                raise
            except _PDF_PARSE_ERRORS:
                # Let the AI provider try PDFs that the local parser cannot inspect.
                pass

        name = link.attachment.name.replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
        if name in ("", ".", ".."):
            name = "attachment"
        if not mime or mime == "application/octet-stream":
            mime = guess_type(name)[0] or "application/octet-stream"
        return {
            "status": "ok", "course_id": course_id, "assignment_id": assignment_id,
            "attachment_id": attachment_id, "name": name, "mime": mime,
            "size_bytes": len(content), "base64": b64encode(content).decode("ascii"),
        }

    async def get_syllabus(self, course_id: str) -> Syllabus:
        course = await self._open_course(course_id)
        home = await self._request("GET", COURSE_HOME)
        data = ajax_fields(home.text, SYLLABUS_POP, _SYLLABUS_FIELDS)
        if not data or data["KJKEY"] != course_id:
            raise RuntimeError("이 강좌의 강의계획서 조회 정보를 찾을 수 없습니다.")
        popup = await self._request("POST", SYLLABUS_POP, data=data)
        data = ajax_fields(popup.text, SYLLABUS_VIEW, _SYLLABUS_FIELDS)
        if not data or data["KJKEY"] != course_id:
            raise RuntimeError("이 강좌의 강의계획서 본문 주소를 확인할 수 없습니다.")
        view = await self._request("POST", SYLLABUS_VIEW, data=data)
        return parse_syllabus(view.text, course_id, course.name)

    async def _course_file_links(self, course_id: str | None) -> list[FileLink]:
        await self._open_course(course_id)
        response = await self._request("POST", COURSE_FILES, data={"SCH_VALUE": "", **_ENCODING})
        return parse_file_links(response.text)

    async def list_course_files(self, course_id: str) -> list[Attachment]:
        return [link.attachment for link in await self._course_file_links(course_id)]

    async def _course_pdf_links(self, course_id: str) -> list[FileLink]:
        if not course_id:
            raise AttachmentReadError("missing_course_id", "PDF가 있는 강좌의 course_id를 지정해 주세요.")
        try:
            links = await self._course_file_links(course_id)
        except ValueError as exc:
            raise AttachmentReadError("attachment_source_not_found", "수강 목록에서 확인한 강좌 ID를 지정해 주세요.") from exc
        return [link for link in links if link.attachment.name.casefold().endswith(".pdf")]

    async def _read_course_pdf_files(
        self, links: list[FileLink], read: Callable[[FileLink], Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        slots = asyncio.Semaphore(_COURSE_PDF_CONCURRENCY)

        async def read_one(link: FileLink) -> dict[str, Any]:
            async with slots:
                try:
                    result = await read(link)
                except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                    result = {**attachment_failure(exc), "status": "error"}
                return {**result, "id": link.attachment.id, "name": link.attachment.name}

        # The caller holds the course session lock until every download settles.
        return await asyncio.gather(*(read_one(link) for link in links))

    async def read_course_pdfs(self, course_id: str, *, start_file: int = 1, max_files: int = 16) -> dict[str, Any]:
        if start_file < 1 or not 1 <= max_files <= _MAX_COURSE_PDF_FILES:
            raise AttachmentReadError("invalid_file_range", f"start_file은 1 이상, max_files는 1~{_MAX_COURSE_PDF_FILES}여야 해요.")
        pdfs = await self._course_pdf_links(course_id)
        start = start_file - 1
        if start and start >= len(pdfs):
            raise AttachmentReadError("invalid_file_range", f"파일모음에서 확인한 PDF는 {len(pdfs)}개예요.")

        async def read_text(link: FileLink) -> dict[str, Any]:
            content = await self._download_attachment_pdf(link.href)
            return await asyncio.to_thread(_extract_course_pdf, link.attachment, content)

        files = await self._read_course_pdf_files(pdfs[start:start + max_files], read_text)
        next_file = start + len(files) + 1
        return {
            "status": "ok", "course_id": course_id, "total_files": len(pdfs), "start_file": start_file,
            "files": files, "next_file": next_file if next_file <= len(pdfs) else None,
        }

    async def get_course_pdf_originals(self, course_id: str) -> dict[str, Any]:
        pdfs = await self._course_pdf_links(course_id)
        budget = _CoursePdfBudget()

        async def read_original(link: FileLink) -> dict[str, Any]:
            budget.check(0, 0)
            content = await self._download_attachment_pdf(link.href, budget=budget)
            return {"status": "ok", "base64": b64encode(content).decode("ascii"), "size_bytes": len(content)}

        files = await self._read_course_pdf_files(pdfs, read_original)
        budget.check(0, 0)
        return {"status": "ok", "course_id": course_id, "files": files, "total_files": len(pdfs)}

    async def read_attachment(
        self, kind: AttachmentSource, attachment_id: str, course_id: str | None = None,
        *, post_id: str | None = None, page: int = 1, board_id: str | None = None,
        start_page: int = 1, max_pages: int = 10,
    ) -> AttachmentText:
        if start_page < 1 or not 1 <= max_pages <= 25:
            raise AttachmentReadError("invalid_page_range", "start_page는 1 이상, max_pages는 1~25여야 해요.")
        if kind != "system_notice" and not course_id:
            raise AttachmentReadError("missing_course_id", "첨부가 있는 강좌의 course_id를 지정해 주세요.")
        if kind != "file_collection" and not post_id:
            raise AttachmentReadError("missing_post_id", "첨부가 있는 게시물의 post_id를 지정해 주세요.")
        try:
            if kind == "file_collection":
                links = await self._course_file_links(course_id)
            else:
                _, links = await self._post_with_links(kind, post_id, course_id, page, board_id)
        except ValueError as exc:
            raise AttachmentReadError(
                "attachment_source_not_found", "강좌나 게시물을 확인하지 못했어요. 조회한 목록의 출처 정보를 사용해 주세요.",
            ) from exc
        link = next((item for item in links or [] if item.attachment.id == attachment_id), None)
        if link is None:
            raise AttachmentReadError("attachment_not_found", "해당 게시물 또는 파일모음에서 확인한 첨부 ID를 지정해 주세요.")
        if not link.attachment.name.casefold().endswith(".pdf"):
            raise AttachmentReadError("unsupported_file_type", "현재 내용 추출은 PDF 첨부만 지원해요.")
        content = await self._download_attachment_pdf(link.href)
        return await asyncio.to_thread(_extract_pdf, link.attachment, content, start_page, max_pages)

    async def _download_attachment_pdf(self, href: str, *, budget: _CoursePdfBudget | None = None) -> bytes:
        try:
            return await self._download_pdf(href, budget=budget)
        except httpx.HTTPError as exc:
            raise AttachmentReadError("attachment_download_failed", "e-Class에서 첨부를 내려받지 못했어요.") from exc

    async def _download_pdf(self, href: str, *, budget: _CoursePdfBudget | None = None) -> bytes:
        async with self._attachment_response(href) as response:
            mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
            if mime not in ("application/pdf", "application/octet-stream"):
                raise AttachmentReadError("attachment_download_failed", "e-Class에서 PDF 응답을 받지 못했어요.")
            return await _read_pdf_response(response, budget)

    @asynccontextmanager
    async def _attachment_response(self, href: str) -> AsyncIterator[httpx.Response]:
        if self._http is None:
            raise RuntimeError("SeoultechLMSClient는 'async with' 문 안에서 사용해야 합니다.")
        target = _validated_url("GET", href, paths=ATTACHMENT_DOWNLOAD_PATHS)
        expected = parse_qs(urlsplit(target).query)
        for redirect_count in range(2):
            async with self._http.stream(
                "GET", target, headers={"Accept-Encoding": "identity"}, follow_redirects=False,
            ) as response:
                if response.status_code in (401, 403):
                    raise AuthenticationRequired("LMS 로그인 세션을 확인해 주세요.")
                if response.status_code in _REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if redirect_count or not location:
                        raise ReadOnlyViolation("확인된 첨부 다운로드 이동만 허용합니다.")
                    redirect = urljoin(target, location)
                    if _is_login_url(redirect):
                        raise AuthenticationRequired("LMS 로그인 세션을 확인해 주세요.")
                    target = _validated_url("GET", redirect, paths=ATTACHMENT_REDIRECT_PATHS)
                    params = parse_qs(urlsplit(target).query)
                    # The LMS replaces FILE_SEQ with an opaque token for the final download.
                    file_tokens = params.get("FILE_SEQ", [])
                    if len(file_tokens) != 1 or not is_item_id(file_tokens[0]):
                        raise ReadOnlyViolation("첨부 다운로드 식별자를 확인할 수 없습니다.")
                    for key in ("CONTENT_SEQ", "ky", "ud", "pf_st_flag"):
                        if key in expected and params.get(key) != expected[key]:
                            raise ReadOnlyViolation("첨부 ID 또는 강좌가 바뀐 다운로드 이동을 차단했습니다.")
                    continue
                if response.is_error:
                    raise AttachmentReadError("attachment_download_failed", f"첨부를 내려받지 못했어요 (HTTP {response.status_code}).")
                yield response
                return
        raise ReadOnlyViolation("확인된 첨부 다운로드 이동만 허용합니다.")


async def _read_assignment_attachment_response(response: httpx.Response) -> bytes:
    content = bytearray()
    declared = response.headers.get("content-length", "")
    if declared.isdecimal() and int(declared) > _MAX_ASSIGNMENT_ATTACHMENT_BYTES:
        raise AttachmentReadError("file_too_large", "32 MiB를 넘는 첨부 원본은 받을 수 없어요.")
    async for chunk in response.aiter_bytes(64 * 1024):
        if len(content) + len(chunk) > _MAX_ASSIGNMENT_ATTACHMENT_BYTES:
            raise AttachmentReadError("file_too_large", "32 MiB를 넘는 첨부 원본은 받을 수 없어요.")
        content.extend(chunk)
    return bytes(content)


async def _read_pdf_response(response: httpx.Response, budget: _CoursePdfBudget | None) -> bytes:
    content = bytearray()

    def check_size(size: int) -> None:
        if budget is not None:
            budget.check(size, size - len(content))
        elif size > _MAX_PDF_BYTES:
            raise AttachmentReadError("file_too_large", "12 MiB가 넘는 첨부는 읽을 수 없어요.")

    declared = response.headers.get("content-length", "")
    if declared.isdecimal():
        check_size(int(declared))
    complete = False
    try:
        async for chunk in response.aiter_bytes(64 * 1024):
            check_size(len(content) + len(chunk))
            content.extend(chunk)
            if budget is not None:
                budget.used += len(chunk)
        if not content.startswith(b"%PDF-"):
            raise AttachmentReadError("pdf_unreadable", "e-Class 응답에서 PDF 원본을 확인하지 못했어요.")
        complete = True
        return bytes(content)
    finally:
        if budget is not None and not complete:
            budget.used -= len(content)


class _UnencryptedPdfReader(PdfReader):
    def read(self, stream) -> None:
        super().read(stream)
        # Check the trailer before PdfReader tries to initialize decryption.
        if self.is_encrypted:
            raise AttachmentReadError("pdf_encrypted", "암호화된 PDF라 열 수 없어요.")


def _open_pdf(content: bytes) -> PdfReader:
    return _UnencryptedPdfReader(BytesIO(content))


def _extract_pdf(
    attachment: Attachment, content: bytes, start_page: int, max_pages: int,
) -> AttachmentText:
    try:
        reader = _open_pdf(content)
        total_pages = len(reader.pages)
        if start_page > total_pages:
            raise AttachmentReadError("invalid_page_range", f"PDF의 전체 페이지 수는 {total_pages}쪽이에요.")
        remaining = _MAX_PDF_CHARS
        pages = []
        truncated = False
        for index in range(start_page - 1, min(total_pages, start_page - 1 + max_pages)):
            text = (reader.pages[index].extract_text() or "").strip()
            if len(text) > remaining:
                if not pages:
                    pages.append(text[:remaining])
                    truncated = True
                break
            pages.append(text)
            remaining -= len(text)
    except AttachmentReadError:
        raise
    except _PDF_PARSE_ERRORS as exc:
        raise AttachmentReadError("pdf_unreadable", "이 PDF에서 텍스트를 읽을 수 없어요.") from exc
    next_page = start_page + len(pages)
    return AttachmentText(
        attachment.id, attachment.name, total_pages, start_page, pages,
        next_page if next_page <= total_pages else None, truncated,
    )


def _extract_course_pdf(attachment: Attachment, content: bytes) -> dict[str, Any]:
    try:
        reader = _open_pdf(content)
        total_pages = len(reader.pages)
    except AttachmentReadError:
        raise
    except _PDF_PARSE_ERRORS as exc:
        raise AttachmentReadError("pdf_unreadable", "이 PDF에서 텍스트를 읽을 수 없어요.") from exc

    page_limit = min(total_pages, _MAX_COURSE_PDF_PAGES)
    # Divide the character budget across the document so early pages cannot crowd out later pages.
    page_chars = min(_MAX_COURSE_PDF_PAGE_CHARS, _MAX_COURSE_PDF_CHARS // max(1, page_limit))
    pages: list[str] = []
    unreadable_pages: list[int] = []
    shortened_pages: list[int] = []
    for index in range(page_limit):
        try:
            text = (reader.pages[index].extract_text() or "").strip()
        except _PDF_PARSE_ERRORS:
            unreadable_pages.append(index + 1)
            pages.append("")
            continue
        if len(text) > page_chars:
            shortened_pages.append(index + 1)
        pages.append(text[:page_chars])

    truncated = page_limit < total_pages or bool(shortened_pages)
    read_pages = len(pages) - len(unreadable_pages)
    text_pages = sum(bool(page) for page in pages)
    if unreadable_pages and read_pages == 0:
        raise AttachmentReadError("pdf_unreadable", "이 PDF의 페이지를 읽을 수 없어요.")
    status = "ok"
    if truncated or unreadable_pages:
        status = "partial"
    elif not text_pages:
        status = "no_text"
    return {
        "id": attachment.id, "name": attachment.name, "status": status, "pages": pages,
        "total_pages": total_pages, "read_pages": read_pages, "text_pages": text_pages,
        "truncated": truncated, "unreadable_pages": unreadable_pages, "shortened_pages": sorted(shortened_pages),
    }
