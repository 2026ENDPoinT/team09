from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from os import fstat
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
import truststore

from .assignment_summary import SEOUL_TIME, AssignmentSummary, AssignmentSummaryCache, parse_summary_index, summary_item
from .auth import AuthenticationRequired, require_auth_state
from .content import (
    AttachmentSource,
    FileLink,
    PostKind,
    ajax_fields,
    is_item_id,
    parse_board_ids,
    parse_file_links,
    parse_post_body,
    parse_post_list,
    parse_syllabus,
    qna_attachment_seq,
)
from .endpoints import (
    ACTIVITY_LIST,
    ALLOWED_GET_PATHS,
    ALLOWED_POST_PATHS,
    ATTACHMENT_DOWNLOAD_PATHS,
    ATTACHMENT_REDIRECT_PATHS,
    BASE_URL,
    BOARD_LIST,
    BOARD_VIEW,
    COURSE_ATTACHMENT_LIST,
    COURSE_FILES,
    COURSE_HOME,
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
from .home_todo import read_home_todo
from .models import Assignment, Attachment, AttachmentText, Course, Notice, Post, Syllabus
from .parser import (
    assignment_url, enrich_assignment, enrich_notice, parse_assignment_index, parse_courses, parse_notices,
    parse_student_profile, parse_summary_courses,
)
from .service import pending_assignments


class ReadOnlyViolation(RuntimeError):
    pass


_BASE_PARTS = urlsplit(BASE_URL)
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_MAX_PDF_BYTES = 12 * 1024 * 1024
_MAX_PDF_CHARS = 24_000
_ENCODING = {"encoding": "utf-8"}
_ACTIVITY_ARGS = {"MENU_ID": "", "ARTL_NUM": "", **_ENCODING}
_ACTIVITY_KINDS = frozenset({"assignment", "material", "discussion"})
_ASSIGNMENT_READ_ERRORS = (httpx.HTTPError, OSError, RuntimeError, ValueError)
_COURSE_FILE_FIELDS = frozenset({"ud", "ky", "pf_st_flag", "CONTENT_SEQ", "encoding"})
_SYSTEM_FILE_FIELDS = frozenset({"CONTENT_SEQ", "encoding"})
_SYLLABUS_FIELDS = frozenset({
    "KJKEY", "ORG_SECT", "YEAR", "TERM", "LEDG_YEAR", "LEDG_SESSN", "LSSN_CD", "SUBJT_NO", "encoding",
})


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

    def __init__(self, project_root: Path | None = None, *, assignment_cache: AssignmentSummaryCache | None = None) -> None:
        self.project_root = project_root
        self._http: httpx.AsyncClient | None = None
        self._courses_cache: list[Course] | None = None
        self._assignment_cache = assignment_cache if assignment_cache is not None else AssignmentSummaryCache()

    def _cookies(self) -> httpx.Cookies:
        with require_auth_state(self.project_root).open(encoding="utf-8") as handle:
            state = json.load(handle)
            identity = fstat(handle.fileno())
        self._assignment_cache.bind_session((identity.st_dev, identity.st_ino, identity.st_mtime_ns))
        cookies = httpx.Cookies()
        for cookie in state.get("cookies", []):
            domain = str(cookie.get("domain", "")).lstrip(".") or "eclass.seoultech.ac.kr"
            cookies.set(cookie["name"], cookie["value"], domain=domain, path=cookie.get("path", "/"))
        return cookies

    async def __aenter__(self) -> SeoultechLMSClient:
        self._courses_cache = None
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            cookies=self._cookies(),
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
        if payload.get("isError"):
            raise RuntimeError(str(payload.get("message") or "강좌 세션 진입에 실패했습니다."))

    async def get_courses(self) -> list[Course]:
        if self._courses_cache is not None:
            return list(self._courses_cache)
        response = await self._request("GET", MAIN_FORM, headers={"Accept": "text/html"})
        courses = parse_courses(response.text)
        if not courses:
            raise AuthenticationRequired("수강 과목을 찾지 못했습니다. 로그인 세션을 갱신하거나 LMS 화면 구조 변경을 확인해주세요.")
        self._courses_cache = courses
        return list(courses)

    async def get_student_profile(self, *, include_contact: bool = False) -> dict[str, str | int | None]:
        response = await self._request(
            "POST", MY_INFO, data={"encoding": "utf-8"}, headers={"Referer": BASE_URL + MAIN_FORM},
        )
        profile = parse_student_profile(response.text, include_contact=include_contact)
        if profile is None:
            raise RuntimeError("e-Class 내 정보 화면에서 학생 정보를 확인하지 못했어요.")
        return profile

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
            response = await self._request(
                "POST",
                NOTICE_LIST,
                data={"start": "", "display": "100", "SCH_VALUE": "", "ODR": "", "encoding": "utf-8"},
            )
            notices = parse_notices(response.text, course.id)
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

    async def get_assignments(self, course_id: str | None = None, include_completed: bool = True) -> list[Assignment]:
        courses = await self.get_courses()
        selected = [course for course in courses if course.id == course_id] if course_id else courses
        if course_id and not selected:
            raise ValueError(f"수강 중인 과목 ID가 아닙니다: {course_id}")
        results: list[Assignment] = []
        for course in selected:
            await self._enter_course(course.id)
            index_response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
            for assignment in parse_assignment_index(index_response.text, course.id):
                if not include_completed and assignment.submitted is True:
                    continue
                results.append(await self._read_assignment_detail(assignment))
        return results

    async def _read_assignment_detail(self, assignment: Assignment, *, verify: bool = False) -> Assignment:
        response = await self._request(
            "GET", REPORT_VIEW, params={"RT_SEQ": assignment.id, **_ENCODING}, headers={"Accept": "text/html"},
        )
        return enrich_assignment(response.text, assignment, verify=verify)

    async def get_assignment_summary(
        self, course_id: str | None = None, *, refresh_details: bool = False, include_non_regular: bool = True,
    ) -> AssignmentSummary:
        """Check current assignment indices and reuse verified unchanged metadata."""
        home = await self._request("GET", MAIN_FORM, headers={"Accept": "text/html"})
        courses = parse_summary_courses(home.text, include_non_regular=include_non_regular)
        if courses is None:
            raise AuthenticationRequired("e-Class 로그인 메인 화면을 확인할 수 없습니다.")
        selected = [course for course in courses if course.id == course_id] if course_id else courses
        if course_id and not selected:
            raise ValueError("수강 중인 과목의 course_id를 지정해 주세요.")
        cache = self._assignment_cache
        if include_non_regular:
            cache.retain_courses({course.id for course in courses})
        todo = await read_home_todo(self._request)
        results: list[Assignment] = []
        unavailable: list[str] = []
        if course_id is None and include_non_regular:
            roster_ids = {course.id for course in courses}
            if any(hint["course_id"] not in roster_ids for hint in todo["assignments"]):
                unavailable.append("홈 할일에 표시된 일부 과제의 수강 강좌를 확인하지 못했어요.")
        for course in selected:
            hints = {hint["id"]: hint for hint in todo["assignments"] if hint["course_id"] == course.id}
            try:
                await self._enter_course(course.id)
            except AuthenticationRequired:
                raise
            except _ASSIGNMENT_READ_ERRORS:
                unavailable.append(f"{course.name} 강의실을 열지 못했어요.")
                continue
            try:
                response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
                rows = parse_summary_index(response.text, course.id)
                cache.retain_assignments(course.id, set(rows) | set(hints))
                index_checked = True
            except AuthenticationRequired:
                raise
            except _ASSIGNMENT_READ_ERRORS:
                unavailable.append(f"{course.name} 과제 목록을 확인하지 못했어요.")
                rows = {}
                index_checked = False
            incomplete_detail = False
            candidates = {item_id: row.assignment for item_id, row in rows.items()}
            for item_id, hint in hints.items():
                if item_id not in candidates:
                    candidates[item_id] = Assignment(item_id, course.id, hint["title"], url=assignment_url(item_id))
            for item_id, item in candidates.items():
                row, hint = rows.get(item_id), hints.get(item_id)
                if item.submitted is True and hint is None:
                    cache.discard(item)
                    continue
                deadline_marker = (hint["deadline_text"] or None) if hint else None
                detail = None if refresh_details or not index_checked else cache.get(item, row, deadline_marker)
                if detail is None:
                    candidate = replace(item, submitted=None) if item.submitted is True else item
                    try:
                        detail = replace(await self._read_assignment_detail(candidate, verify=True), description=None)
                    except AuthenticationRequired:
                        raise
                    except _ASSIGNMENT_READ_ERRORS:
                        incomplete_detail = True
                        detail = candidate
                        cache.discard(item)
                    else:
                        if index_checked and detail.due_at is not None and detail.submitted is not None:
                            cache.store(detail, row, deadline_marker)
                        else:
                            cache.discard(item)
                results.append(detail)
            if incomplete_detail:
                unavailable.append(f"{course.name} 일부 과제의 상세를 확인하지 못했어요.")

        names = {course.id: course.name for course in selected}
        return {
            "status": "ok",
            "as_of": datetime.now(SEOUL_TIME).isoformat(),
            "assignments": [summary_item(item, names[item.course_id]) for item in pending_assignments(results)],
            "todo_checked": todo["complete"],
            **({"unavailable": unavailable} if unavailable else {}),
        }

    async def _open_course(self, course_id: str | None) -> Course:
        course = next((course for course in await self.get_courses() if course.id == course_id), None)
        if course is None:
            raise ValueError("수강 중인 과목의 course_id를 지정해 주세요.")
        await self._enter_course(course.id)
        return course

    async def _list_posts(
        self, kind: PostKind, course_id: str | None, page: int, board_id: str | None,
        *, summary_assignment: bool = False,
    ) -> list[Post]:
        if page < 1:
            raise ValueError("page는 1 이상이어야 합니다.")
        if board_id is not None and kind != "open_board":
            raise ValueError("board_id는 열린게시판에서만 지정할 수 있습니다.")
        if kind == "system_notice":
            if course_id is not None:
                raise ValueError("학교 전체 공지는 course_id 없이 조회해 주세요.")
        elif kind == "assignment" and summary_assignment:
            # Summary also includes enrolled non-regular courses.
            home = await self._request("GET", MAIN_FORM, headers={"Accept": "text/html"})
            roster = parse_summary_courses(home.text, include_non_regular=True)
            if roster is None:
                raise AuthenticationRequired("e-Class 로그인 메인 화면을 확인할 수 없습니다.")
            if course_id is None or not any(course.id == course_id for course in roster):
                raise ValueError("수강 중인 과목의 course_id를 지정해 주세요.")
            await self._enter_course(course_id)
        else:
            await self._open_course(course_id)

        listing = {"start": str(page), "display": "20", "SCH_VALUE": "", "ODR": "", **_ENCODING}
        if kind in _ACTIVITY_KINDS:
            if page != 1:
                return []
            response = await self._request("POST", ACTIVITY_LIST, data=_ACTIVITY_ARGS)
        elif kind == "course_notice":
            response = await self._request("POST", NOTICE_LIST, data=listing)
        elif kind == "system_notice":
            response = await self._request("POST", SYSTEM_NOTICE_LIST, data={**listing, "SCH_TARGET": ""})
        elif kind == "qna":
            response = await self._request(
                "POST", QNA_LIST,
                data={**listing, "display": "8", "SCH_FAQ": "", "SCH_STATUS": ""},
            )
        elif kind == "open_board":
            home = await self._request("GET", COURSE_HOME)
            groups = parse_board_ids(home.text)
            if board_id is not None:
                if board_id not in groups:
                    raise ValueError("강좌에서 확인할 수 있는 열린게시판 ID를 지정해 주세요.")
                groups = [board_id]
            posts = []
            for group in groups:
                response = await self._request("POST", BOARD_LIST, data={**listing, "ARTL_GRP_ID": group})
                posts.extend(parse_post_list(response.text, kind, course_id, group))
            return posts
        else:
            raise ValueError("지원하지 않는 게시물 종류입니다.")
        return parse_post_list(response.text, kind, course_id)

    async def list_posts(
        self, kind: PostKind, course_id: str | None = None, *, page: int = 1, board_id: str | None = None,
    ) -> list[Post]:
        return await self._list_posts(kind, course_id, page, board_id)

    async def _post_with_links(
        self, kind: PostKind, post_id: str, course_id: str | None, page: int, board_id: str | None,
    ) -> tuple[Post, list[FileLink] | None]:
        matches = [item for item in await self._list_posts(kind, course_id, page, board_id, summary_assignment=True)
                   if item.id == post_id]
        from_todo = False
        if not matches and kind == "assignment" and course_id is not None and page == 1:
            todo = await read_home_todo(self._request)
            for hint in todo["assignments"]:
                if hint["course_id"] == course_id and hint["id"] == post_id:
                    matches.append(Post(post_id, kind, hint["title"], course_id=course_id))
                    from_todo = True
                    break
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
                           due_at=assignment.due_at, submitted=assignment.submitted)
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
        return post, await self._attachment_links(post, response.text)

    async def _attachment_links(
        self, post: Post, html: str,
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
        return parse_file_links(response.text)

    async def get_post(
        self, kind: PostKind, post_id: str, course_id: str | None = None,
        *, page: int = 1, board_id: str | None = None,
    ) -> Post:
        post, links = await self._post_with_links(kind, post_id, course_id, page, board_id)
        return replace(post, attachments=tuple(link.attachment for link in links) if links is not None else None)

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

    async def read_attachment(
        self, kind: AttachmentSource, attachment_id: str, course_id: str | None = None,
        *, post_id: str | None = None, page: int = 1, board_id: str | None = None,
        start_page: int = 1, max_pages: int = 10,
    ) -> AttachmentText:
        if start_page < 1 or not 1 <= max_pages <= 25:
            raise ValueError("start_page는 1 이상, max_pages는 1~25여야 합니다.")
        if kind == "file_collection":
            links = await self._course_file_links(course_id)
        else:
            if post_id is None:
                raise ValueError("첨부가 있는 게시물의 post_id를 지정해 주세요.")
            _, links = await self._post_with_links(kind, post_id, course_id, page, board_id)
        link = next((item for item in links or [] if item.attachment.id == attachment_id), None)
        if link is None:
            raise ValueError("해당 게시물 또는 파일모음에서 확인한 첨부 ID를 지정해 주세요.")
        if not link.attachment.name.casefold().endswith(".pdf"):
            raise ValueError("현재 내용 추출은 PDF 첨부만 지원합니다.")
        content = await self._download_pdf(link.href)
        return await asyncio.to_thread(_extract_pdf, link.attachment, content, start_page, max_pages)

    async def _download_pdf(self, href: str) -> bytes:
        if self._http is None:
            raise RuntimeError("SeoultechLMSClient는 'async with' 문 안에서 사용해야 합니다.")
        target = _validated_url("GET", href, paths=ATTACHMENT_DOWNLOAD_PATHS)
        expected = parse_qs(urlsplit(target).query)
        for redirect_count in range(2):
            async with self._http.stream("GET", target, headers={"Accept-Encoding": "identity"}) as response:
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
                    raise RuntimeError(f"첨부 다운로드에 실패했습니다 (HTTP {response.status_code}).")
                mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                if mime not in ("application/pdf", "application/octet-stream"):
                    raise RuntimeError("LMS에서 PDF 응답을 받지 못했습니다.")
                declared = response.headers.get("content-length", "")
                if declared.isdecimal() and int(declared) > _MAX_PDF_BYTES:
                    raise ValueError("12 MiB가 넘는 첨부는 읽을 수 없습니다.")
                content = bytearray()
                async for chunk in response.aiter_bytes(64 * 1024):
                    if len(content) + len(chunk) > _MAX_PDF_BYTES:
                        raise ValueError("12 MiB가 넘는 첨부는 읽을 수 없습니다.")
                    content.extend(chunk)
                if not content.startswith(b"%PDF-"):
                    raise RuntimeError("LMS 응답에서 PDF 원본을 확인할 수 없습니다.")
                return bytes(content)
        raise ReadOnlyViolation("확인된 첨부 다운로드 이동만 허용합니다.")


def _extract_pdf(
    attachment: Attachment, content: bytes, start_page: int, max_pages: int,
) -> AttachmentText:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("암호화된 PDF는 읽을 수 없습니다.")
        total_pages = len(reader.pages)
        if start_page > total_pages:
            raise ValueError(f"PDF의 전체 페이지 수는 {total_pages}쪽입니다.")
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
    except (PdfReadError, RecursionError) as exc:
        raise ValueError("이 PDF에서 텍스트를 읽을 수 없습니다.") from exc
    next_page = start_page + len(pages)
    return AttachmentText(
        attachment.id, attachment.name, total_pages, start_page, pages,
        next_page if next_page <= total_pages else None, truncated,
    )
