from __future__ import annotations

import asyncio
import logging
import re
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from .assignment_summary import AssignmentSummaryCache
from .auth import (
    AuthenticationRequired, account_session_path, account_storage_root, auth_state_path,
    clear_account_sessions, last_session_account, normalize_login_id, save_account_session,
    write_auth_state_secure,
)
from .browser import DesktopLogin, start_login_browser
from .campus_briefing import get_campus_briefing as collect_campus_briefing
from .campus_file_text import extract_file_text
from .campus_files import fetch_campus_notice_file, save_campus_notice_file
from .campus_notices import CampusBoard, CampusNoticeClient
from .client import SeoultechLMSClient, attachment_failure
from .content import AttachmentSource, PostKind, is_item_id
from .department_notices import DepartmentNoticeClient
from .dorm_menu import Dorm, DormMenuPeriod, get_dorm_menu as collect_dorm_menu
from .models import CourseRoster, StudentProfile, as_jsonable


mcp = FastMCP(
    "seoultech_c4t",
    instructions=(
        "이 서버는 사용자 컴퓨터에서 'python -m seoultech_lms.mcp_server'로 실행되는 로컬 stdio MCP다. "
        "호스트 AI 클라이언트가 로컬 프로세스와 로컬 인증 상태에 접근할 수 있어야 한다. "
        "서울과학기술대학교 e-Class의 로그인한 사용자 데이터를 읽기 전용으로 조회한다. "
        "대학 홈페이지 공개 공지·첨부파일과 생활관 공개 식단은 e-Class 로그인 없이 조회한다. "
        "AST에서는 start_desktop_login으로 Chromium 또는 Chrome을 열고 confirm_desktop_login으로 세션을 저장한다. "
        "로그인 도구는 'python -m seoultech_lms.login_window'를 로컬에서 실행해 공식 LMS 로그인 페이지를 Chrome으로 열고 인증 상태만 로컬에 저장한다. "
        "과제 제출, 게시물 작성, 수정, 삭제, 파일 업로드는 지원하지 않는다."
    ),
)


# e-Class stores the active course in the login session.
_query_lock = asyncio.Lock()
_campus_query_lock = asyncio.Lock()
_desktop_login = DesktopLogin()
_active_account: str | None = None
_assignment_cache = AssignmentSummaryCache()


def _account_session_path() -> Path | None:
    root = account_storage_root()
    if root is None:
        return None
    if _active_account is None:
        raise AuthenticationRequired("ASTRA로 로그인해 계정을 확인해 주세요.")
    return account_session_path(root, _active_account)


@asynccontextmanager
async def _query_client():
    async with _query_lock, SeoultechLMSClient(
        session_path=_account_session_path(), assignment_cache=_assignment_cache,
    ) as client:
        yield client


def _confirmed_login(
    state: dict[str, Any] | None, login_id: str | None, roster: CourseRoster, message: str,
    profile: StudentProfile | None,
) -> dict[str, Any]:
    global _active_account
    result = {"status": "authenticated", "message": message}
    root = account_storage_root()
    if root is not None:
        if state is not None:
            if login_id is None:
                return {"status": "login_required", "message": "계정을 확인하지 못했어요. ASTRA 로그인 창에서 아이디를 입력해 다시 로그인해 주세요."}
            _active_account = save_account_session(root, login_id, state)
        if _active_account is None:
            return {"status": "login_required", "message": "ASTRA로 로그인해 계정을 확인해 주세요."}
        result["account_key"] = _active_account
    elif state is not None:
        write_auth_state_secure(auth_state_path(), state)
    display_name = profile.display_name if profile else roster.display_name
    if display_name:
        result["display_name"] = display_name
    if profile:
        result["student_profile"] = {"department": profile.department, "year": profile.year}
    regular = sum(course.category == "regular" for course in roster.courses)
    result["course_roster"] = {
        "regular": regular,
        "non_regular": len(roster.courses) - regular if roster.non_regular_available else None,
        "courses": [
            {"id": course.id, "name": course.name, "professor": course.professor, "category": course.category}
            for course in roster.courses
        ],
    }
    return result


def _json_list(items: list[Any]) -> list[dict[str, Any]]:
    return [as_jsonable(item) for item in items]


def _with_course_names(items: list[Any], course_names: dict[str, str]) -> list[dict[str, Any]]:
    results = _json_list(items)
    for result in results:
        result["course_name"] = course_names.get(str(result.get("course_id")))
    return results


@mcp.tool()
def start_login() -> dict[str, str]:
    """로그인 세션이 없거나 만료됐을 때 사용자가 직접 로그인할 Chrome 창을 연다."""
    return start_login_browser(auth_state_path())


@mcp.tool()
async def start_desktop_login() -> dict[str, str]:
    """AST 로그인 창을 열고 사용자가 직접 로그인하면 세션을 메모리에 대기시킨다."""
    global _active_account
    async with _query_lock:
        _active_account = None
        return await _desktop_login.open()


@mcp.tool()
async def get_desktop_login_status(recheck: bool = False) -> dict[str, str]:
    """열린 ASTRA 로그인 창의 감지 상태를 확인한다. 쿠키와 인증 정보는 반환하지 않는다."""
    return await _desktop_login.status(recheck=recheck)


@mcp.tool()
async def clear_desktop_login() -> dict[str, str]:
    """AST 앱에 저장한 로그인 세션을 지우고 다시 로그인할 수 있게 한다."""
    global _active_account
    root = account_storage_root()
    if root is None:
        return {"status": "error", "message": "AST 앱의 세션 저장 위치를 확인하지 못했어요."}
    async with _query_lock:
        _active_account = None
        _desktop_login.clear()
        try:
            clear_account_sessions(root)
            auth_state_path().unlink(missing_ok=True)
        except OSError:
            return {"status": "error", "message": "저장된 로그인 세션을 지우지 못했어요."}
    return {"status": "cleared", "message": "ASTRA로 로그인해 주세요."}


@mcp.tool()
async def confirm_desktop_login(use_saved: bool = True) -> dict[str, Any]:
    """공식 LMS에서 저장된 세션 또는 새 로그인 정보를 확인한다."""
    global _active_account
    try:
        async with _query_lock:
            try:
                state = _desktop_login.candidate()
            except AuthenticationRequired as exc:
                return {"status": "login_required", "message": str(exc)}
            if state is None and not use_saved:
                return {"status": "login_required", "message": "새 로그인 정보를 확인하지 못했어요. 다시 로그인해 주세요."}
            saved_account = None
            path = None
            if state is None and (root := account_storage_root()) is not None:
                saved_account = _active_account or last_session_account(root)
                _active_account = None
                if saved_account is None:
                    raise AuthenticationRequired("저장된 ASTRA 세션이 없어요.")
                path = account_session_path(root, saved_account)
            try:
                async with SeoultechLMSClient(browser_state=state, session_path=path) as client:
                    roster = await client.get_login_roster()
                    profile = await client.get_student_profile(roster.display_name)
            except AuthenticationRequired:
                if not use_saved:
                    _desktop_login.clear()
                raise
            if saved_account is not None:
                _active_account = saved_account
            result = _confirmed_login(state, _desktop_login.login_id(), roster, "e-Class 로그인을 확인했어요.", profile)
            if state is not None:
                _desktop_login.clear()
    except AuthenticationRequired:
        return {"status": "login_required", "message": "로그인이 완료되지 않았어요. 로그인 버튼으로 다시 시도해 주세요."}
    except httpx.HTTPError:
        return {"status": "error", "message": "e-Class 연결을 확인하지 못했어요. 네트워크를 확인하고 다시 눌러 주세요."}
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return {"status": "error", "message": "로컬 세션을 확인하거나 저장하지 못했어요. 로그인 버튼으로 다시 시도해 주세요."}
    return result


@mcp.tool()
async def confirm_browser_login(cookies: list[dict[str, Any]], login_id: str | None = None) -> dict[str, Any]:
    """AST 내장 브라우저가 직접 로그인한 e-Class 세션을 검증하고 로컬에 저장한다."""
    if not 0 < len(cookies) <= 64 or any(
        cookie.get("domain") != "eclass.seoultech.ac.kr"
        or not isinstance(cookie.get("path"), str) or not cookie["path"].startswith("/")
        or not all(isinstance(cookie.get(key), str) and 0 < len(cookie[key]) <= 4096 for key in ("name", "value"))
        for cookie in cookies
    ):
        return {"status": "login_required", "message": "브라우저의 e-Class 로그인을 완료해 주세요."}
    state = {"cookies": cookies, "origins": []}
    try:
        async with _query_lock, SeoultechLMSClient(browser_state=state) as client:
            roster = await client.get_login_roster()
            profile = await client.get_student_profile(roster.display_name)
            result = _confirmed_login(state, normalize_login_id(login_id), roster, "e-Class 로그인을 연결했어요.", profile)
            _desktop_login.clear()
    except AuthenticationRequired:
        return {"status": "login_required", "message": "브라우저의 e-Class 로그인을 완료해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
        return {"status": "error", "message": "브라우저의 로그인 상태를 저장하지 못했어요."}
    return result


@mcp.tool()
async def get_student_profile() -> dict[str, Any]:
    """AST의 내 정보 화면에 표시할 로그인 계정의 e-Class 프로필과 연락처를 조회한다."""
    try:
        async with _query_client() as client:
            profile = await client.get_student_profile(None, include_contact=True)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "내 정보를 확인하려면 e-Class에 다시 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        profile = None
    if profile is None:
        return {"status": "error", "message": "e-Class에서 내 정보를 불러오지 못했어요. 다시 시도해 주세요."}
    return as_jsonable(profile)


@mcp.tool()
async def get_course_overview(include_attendance: bool = False) -> dict[str, Any]:
    """현재 과목별 활동·게시판·파일 목록을 조회한다. include_attendance는 정규 과목의 학생 본인 출결 요약도 조회한다."""
    try:
        async with _query_client() as client:
            overview = await client.get_course_overview(include_attendance=include_attendance)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "e-Class 세션이 없거나 만료됐어요. 로그인 후 다시 확인해 주세요."}
    except httpx.HTTPError:
        return {"status": "error", "message": "e-Class에 연결하지 못했어요. 네트워크를 확인하고 다시 조회해 주세요."}
    except (OSError, RuntimeError, ValueError):
        return {"status": "error", "message": "수강 목록을 조회하지 못했어요. 잠시 후 다시 시도해 주세요."}
    return {"status": "ok", "overview": as_jsonable(overview)}


@mcp.tool()
async def get_course_classroom(course_id: str) -> dict[str, Any]:
    """AST의 개별 강의실에서 수강 중인 강좌의 주차별 활동과 열린게시판을 조회한다."""
    if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id):
        return {"status": "error", "message": "강좌 번호를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_course_classroom(course_id)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "강의실을 보려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "주차별 활동을 불러오지 못했어요. 다시 시도해 주세요."}


@mcp.tool()
async def get_course_classroom_info(course_id: str) -> dict[str, Any]:
    """AST 강의실 제목 아래에 표시할 과목 코드, 수업 시간과 강의실을 조회한다."""
    try:
        async with _query_client() as client:
            return await client.get_course_classroom_info(course_id)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업 정보를 보려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "수업 정보를 불러오지 못했어요."}


@mcp.tool()
async def get_home_course_index(course_id: str) -> dict[str, Any]:
    """AST 홈의 과목별 활동·과제·공지 목록을 확인한다."""
    if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id):
        return {"status": "error", "message": "강좌 번호를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_home_course_index(course_id)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "e-Class 로그인을 다시 확인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "강좌 목록을 확인하지 못했어요."}


@mcp.tool()
async def get_home_course_details(course_id: str, assignment_ids: list[str], include_stats: bool = False, include_attendance: bool = True) -> dict[str, Any]:
    """AST 홈에서 바뀐 과제의 마감·제출 기록과 필요한 강좌 집계를 확인한다."""
    if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id) or len(assignment_ids) > 4 or not all(is_item_id(item) for item in assignment_ids):
        return {"status": "error", "message": "강좌 또는 과제 번호를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_home_course_details(course_id, assignment_ids, include_stats, include_attendance)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "e-Class 로그인을 다시 확인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "강좌 상세 정보를 확인하지 못했어요."}


@mcp.tool()
async def list_courses() -> list[dict[str, Any]]:
    """현재 수강 과목과 강좌 카드에 표시된 요일·교시를 조회한다. 시각은 get_course_timetable로 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.get_courses())


@mcp.tool()
async def get_course_timetable(
    on_date: date | None = None, course_id: str | None = None, include_rooms: bool = False,
) -> dict[str, Any]:
    """해당 날짜(YYYY-MM-DD, 기본값은 한국 시간 오늘)가 속한 일~토 수업시간표를 조회한다. include_rooms로 미표시 강의실을 강의계획서에서 확인한다."""
    try:
        async with _query_client() as client:
            return await client.get_course_timetable(on_date, course_id, include_rooms=include_rooms)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업시간표를 보려면 e-Class에 로그인해 주세요."}


@mcp.tool()
async def get_course_briefing() -> dict[str, Any]:
    """남은 과제, 최근 48시간에 제출한 과제, 최근 7일간의 e-Class 과목 공지를 조회한다."""
    try:
        async with _query_client() as client:
            return await client.get_course_briefing()
    except AuthenticationRequired:
        return {"status": "login_required", "message": "과제와 과목 공지를 보려면 e-Class에 로그인해 주세요."}


@mcp.tool()
async def get_course_recent_notices(course_id: str) -> dict[str, Any]:
    """AST 강의실에 표시할 최근 공지 3개를 목록의 게시 시각 기준으로 조회한다."""
    if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id):
        return {"status": "error", "message": "강좌 번호를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_course_recent_notices(course_id)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업 공지를 보려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "최근 수업 공지를 불러오지 못했어요. 다시 시도해 주세요."}


@mcp.tool()
async def get_course_notice_page(course_id: str, page: int = 1, query: str = "") -> dict[str, Any]:
    """한 강좌의 공지 목록을 페이지별로 조회하며, 검색어가 있으면 해당 페이지의 제목과 전체 본문을 검색한다."""
    if not re.fullmatch(r"[A-Za-z0-9가-힣_-]{1,80}", course_id) or not 1 <= page <= 100 or len(query) > 160:
        return {"status": "error", "message": "강좌 번호, 공지 페이지 또는 검색어를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_course_notice_page(course_id, page, query)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업 공지를 보려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "수업 공지 목록을 불러오지 못했어요. 다시 시도해 주세요."}


@mcp.tool()
async def get_course_notice(course_id: str, notice_id: str, page: int | None = None) -> dict[str, Any]:
    """AST 수업 공지 화면에서 선택한 공지의 전체 본문과 첨부 목록을 조회한다."""
    if not is_item_id(notice_id):
        return {"status": "error", "message": "수업 공지 번호를 확인해 주세요."}
    try:
        async with _query_client() as client:
            return await client.get_course_notice(course_id, notice_id, page=page)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업 공지 원문을 보려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "수업 공지 원문을 불러오지 못했어요. 다시 시도해 주세요."}


@mcp.tool()
async def get_course_notice_bodies(course_id: str, page: int, notice_ids: list[str]) -> dict[str, Any]:
    """AST의 수업 공지 검색을 위해 같은 강좌 페이지에서 확인한 공지 본문을 최대 6건 조회한다."""
    try:
        async with _query_client() as client:
            return await client.get_course_notice_bodies(course_id, page, notice_ids)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "수업 공지를 갱신하려면 e-Class에 다시 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "일부 수업 공지 본문을 불러오지 못했어요."}


@mcp.tool()
async def get_campus_briefing() -> dict[str, Any]:
    """대학·학사·장학·대학원·취업 게시판의 최근 7일 공개 공지를 모아 조회한다."""
    async with _campus_query_lock:
        return await collect_campus_briefing()


@mcp.tool()
async def get_dorm_menu(
    dorm: Dorm = "kb", period: DormMenuPeriod = "today", on_date: date | None = None,
) -> dict[str, Any]:
    """로그인 없이 생활관 식단을 조회한다. kb=KB학사, seonglim=성림학사, surim=수림학사. today는 기준일 하루, week는 해당 월~일 주간이다. on_date(YYYY-MM-DD) 기본값은 한국 시간 오늘이다."""
    return await collect_dorm_menu(dorm, period, on_date)


@mcp.tool()
async def list_notices(
    course_id: str | None = None,
    include_content: bool = True,
) -> list[dict[str, Any]]:
    """전체 과목 또는 지정한 과목의 공지 목록, 게시일과 전체 본문을 조회한다."""
    async with _query_client() as client:
        courses = await client.get_courses()
        notices = await client.get_notices(course_id, include_content=include_content)
    return _with_course_names(notices, {course.id: course.name for course in courses})


@mcp.tool()
async def search_notices(
    query: str,
    course_id: str | None = None,
) -> list[dict[str, Any]]:
    """공지 전체 본문에서 검색하고 각 결과의 게시일도 함께 반환한다."""
    normalized_query = query.strip().casefold()
    if not normalized_query:
        raise ValueError("검색어를 입력해주세요.")
    async with _query_client() as client:
        courses = await client.get_courses()
        notices = await client.get_notices(course_id, include_content=True)
    matched = [
        notice
        for notice in notices
        if normalized_query in f"{notice.title}\n{notice.content or ''}".casefold()
    ]
    return _with_course_names(matched, {course.id: course.name for course in courses})


@mcp.tool()
async def list_assignments(
    course_id: str | None = None,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    """과제 ID, 교수자 안내, 마감일과 제출 여부를 조회한다. 과제 첨부 목록은 반환하지 않으므로 해당 ID로 get_post(kind="assignment")를 호출한다."""
    async with _query_client() as client:
        courses = await client.get_courses()
        assignments = await client.get_assignments(course_id, include_completed=include_completed)
    return _with_course_names(assignments, {course.id: course.name for course in courses})


@mcp.tool()
async def get_assignment_summary(course_id: str | None = None, refresh_details: bool = False) -> dict[str, Any]:
    """최신 강좌 목록과 할일에서 남은 과제를 확인한다. 변경된 상세만 읽고, unavailable이 있으면 그 범위는 미확인이다. refresh_details는 상세 캐시도 다시 확인한다."""
    try:
        async with _query_client() as client:
            return await client.get_assignment_summary(course_id, refresh_details=refresh_details)
    except AuthenticationRequired:
        return {"status": "login_required", "message": "e-Class 로그인 후 과제를 확인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "최신 과제 목록을 확인하지 못했어요."}


async def _checked_pending_rows(course_id: str | None) -> list[dict[str, Any]]:
    async with _query_client() as client:
        summary = await client.get_assignment_summary(course_id)
    if summary.get("unavailable"):
        raise RuntimeError("일부 과제 정보를 확인하지 못했어요. get_assignment_summary에서 확인된 목록과 미확인 범위를 보세요.")
    rows = [{**row, "description": None} for row in summary["assignments"]]
    for row in rows:
        for field in ("due_at", "late_due_at", "submitted_at"):
            if row[field]:
                row[field] = datetime.fromisoformat(row[field]).replace(tzinfo=None).isoformat()
    return rows


@mcp.tool()
async def get_pending_assignments(course_id: str | None = None) -> list[dict[str, Any]]:
    """현재 미제출이거나 제출 여부가 확인되지 않은 과제의 마감·제출 정보를 조회한다. 교수자 안내는 list_assignments 또는 get_post를 사용한다."""
    return await _checked_pending_rows(course_id)


@mcp.tool()
async def get_upcoming_deadlines(
    days: int = 7,
    course_id: str | None = None,
) -> list[dict[str, Any]]:
    """오늘부터 지정한 일수 안에 마감되는 미제출 과제를 조회한다."""
    if days < 0:
        raise ValueError("days는 0 이상이어야 합니다.")
    start = datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
    end = start + timedelta(days=days)
    return [row for row in await _checked_pending_rows(course_id)
            if row["due_at"] and start <= datetime.fromisoformat(row["due_at"]) <= end]


@mcp.tool()
async def list_posts(
    kind: PostKind, course_id: str | None = None, page: int = 1, board_id: str | None = None,
) -> list[dict[str, Any]]:
    """게시물 ID와 제목을 조회한다. 학교 전체 공지만 course_id 없이 조회한다. 열린게시판은 board_id를 생략하면 강좌 내 전체 게시판을 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.list_posts(kind, course_id, page=page, board_id=board_id))


@mcp.tool()
async def get_post(
    kind: PostKind, post_id: str, course_id: str | None = None, page: int = 1, board_id: str | None = None,
) -> dict[str, Any]:
    """게시물 본문과 해당 게시물의 첨부 목록을 조회한다. 과제는 kind="assignment"와 list_assignments 또는 get_pending_assignments에서 확인한 course_id·과제 id(post_id)를 지정한다. 그 밖의 게시물은 list_posts에서 확인한 ID와 페이지를 사용한다. attachments가 null이면 첨부 목록을 확인하지 못한 것이다."""
    async with _query_client() as client:
        return as_jsonable(await client.get_post(kind, post_id, course_id, page=page, board_id=board_id))


@mcp.tool()
async def get_assignment_workspace(assignment_id: str, course_id: str | None = None) -> dict[str, Any]:
    """AST 과제 창에서 확인한 과제의 교수자 원문, 공개·마감일, 제출 방식, 배점과 첨부 목록을 읽는다."""
    if not is_item_id(assignment_id):
        return {"status": "error", "message": "과제 ID를 확인해 주세요."}
    try:
        async with _query_client() as client:
            courses = await client.get_courses()
            if course_id is None:
                matches = []
                for course in courses:
                    if any(post.id == assignment_id for post in await client.list_posts("assignment", course.id)):
                        matches.append(course)
            else:
                matches = [course for course in courses if course.id == course_id]
            if len(matches) != 1:
                return {"status": "error", "message": "과제의 수강 강좌를 확인하지 못했어요."}
            course = matches[0]
            post = await client.get_post("assignment", assignment_id, course.id)
            metadata = post.assignment_metadata
            return {"status": "ok", "assignment": {
                "courseId": course.id, "courseName": course.name, "assignmentId": post.id,
                "title": post.title, "dueAt": post.due_at.isoformat() if post.due_at else None,
                "lateDueAt": post.late_due_at.isoformat() if post.late_due_at else None, "submitted": post.submitted,
                "description": post.content, "attachments": as_jsonable(post)["attachments"],
                "submissionMethod": metadata.submission_method if metadata else None,
                "submissionFormat": metadata.submission_format if metadata else None,
                "publishedAt": metadata.published_at if metadata else None,
                "points": metadata.points if metadata else None,
                "scoreVisibility": metadata.score_visibility if metadata else None,
            }}
    except AuthenticationRequired:
        return {"status": "login_required", "message": "과제를 열려면 e-Class에 로그인해 주세요."}
    except (OSError, httpx.HTTPError, RuntimeError, ValueError):
        return {"status": "error", "message": "선택한 강좌에서 과제 상세를 확인하지 못했어요."}


@mcp.tool()
async def get_assignment_attachment_file(
    course_id: str, assignment_id: str, attachment_id: str, for_analysis: bool = False,
) -> CallToolResult:
    """과제 첨부 원본을 최대 32 MiB까지 내려받는다. 분석용 요청에서는 암호화된 PDF를 거부한다."""
    try:
        async with _query_client() as client:
            result = await client.get_assignment_attachment_file(course_id, assignment_id, attachment_id, for_analysis=for_analysis)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        result = attachment_failure(exc)
    return CallToolResult(content=[], structuredContent=result)


@mcp.tool()
async def list_discussion_opinions(course_id: str, topic_id: str) -> list[dict[str, Any]]:
    """list_posts(kind="discussion")의 주제 ID로 수강생 의견의 제목, 미리보기, 작성자 표시명 및 댓글 수를 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.list_discussion_opinions(course_id, topic_id))


@mcp.tool()
async def get_discussion_opinion(course_id: str, topic_id: str, opinion_id: str) -> dict[str, Any]:
    """list_discussion_opinions의 의견 ID로 전체 본문과 댓글을 조회한다. comments가 null이면 댓글 조회 정보를 확인하지 못한 것이다. 열람으로 조회수가 올라갈 수 있다."""
    async with _query_client() as client:
        return as_jsonable(await client.get_discussion_opinion(course_id, topic_id, opinion_id))


@mcp.tool()
async def get_syllabus(course_id: str) -> dict[str, Any]:
    """지정 강좌의 강의계획서 본문과 표를 조회한다."""
    async with _query_client() as client:
        return as_jsonable(await client.get_syllabus(course_id))


@mcp.tool()
async def list_course_files(course_id: str) -> list[dict[str, Any]]:
    """지정 강좌의 파일모음에서 파일명과 첨부 ID를 조회한다. 특정 과제의 첨부 목록은 get_post(kind="assignment")로 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.list_course_files(course_id))


@mcp.tool()
async def read_course_pdfs(course_id: str, start_file: int = 1, max_files: int = 16) -> dict[str, Any]:
    """강좌 파일모음 PDF의 텍스트를 최대 16개 파일씩 읽는다. pages는 1쪽부터 순서대로 반환하며 next_file이 있으면 이어 읽는다. no_text, partial, error는 전체 텍스트를 확인하지 못한 경우다."""
    try:
        async with _query_client() as client:
            return await client.read_course_pdfs(course_id, start_file=start_file, max_files=max_files)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        return attachment_failure(exc)


@mcp.tool()
async def get_course_pdf_originals(course_id: str) -> CallToolResult:
    """현재 수강 강좌의 파일모음에서 PDF 원본을 내려받는다. AST가 원본을 한 번에 분석할 때 사용하며 파일 합계는 50 MB 이하다."""
    try:
        async with _query_client() as client:
            result = await client.get_course_pdf_originals(course_id)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        result = attachment_failure(exc)
    # Keep the original bytes in one structured result rather than copying them into a text block too.
    return CallToolResult(content=[], structuredContent=result)


@mcp.tool()
async def read_attachment(
    kind: AttachmentSource, attachment_id: str, course_id: str | None = None,
    post_id: str | None = None, page: int = 1, board_id: str | None = None,
    start_page: int = 1, max_pages: int = 10,
) -> dict[str, Any]:
    """get_post 또는 list_course_files에서 확인한 PDF 첨부 ID로 페이지별 텍스트를 읽는다. list_course_files에서 찾은 PDF는 kind="file_collection"과 course_id·attachment_id를 지정한다. 과제 자체에 달린 PDF는 kind="assignment"와 course_id·post_id·attachment_id를 지정한다. next_page가 있으면 이어 읽고, 실패하면 status와 code를 확인한다."""
    try:
        async with _query_client() as client:
            result = await client.read_attachment(
                kind, attachment_id, course_id, post_id=post_id, page=page, board_id=board_id,
                start_page=start_page, max_pages=max_pages,
            )
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        return attachment_failure(exc)
    return as_jsonable(result)


@mcp.tool()
async def list_campus_notices(board: CampusBoard, start_page: int = 1, pages: int = 3) -> dict[str, Any]:
    """공개 대학·학사·장학·대학원·취업 공지 목록을 읽는다. 이어 읽으려면 next_page를 start_page로 사용한다."""
    async with _campus_query_lock, CampusNoticeClient() as client:
        return await client.list_notices(board, start_page=start_page, pages=pages)


@mcp.tool()
async def get_campus_notice(board: CampusBoard, board_id: str, notice_id: str) -> dict[str, Any]:
    """목록에서 확인한 board_id와 글 id로 공개 공지의 본문, 원문 URL, 첨부파일·본문 이미지 ID를 읽는다."""
    async with _campus_query_lock, CampusNoticeClient() as client:
        notice = await client.get_notice(board, board_id, notice_id)
    return {
        **notice,
        "attachments": [
            {key: value for key, value in attachment.items() if key != "download_fields"}
            for attachment in notice["attachments"]
        ],
    }


@mcp.tool()
async def list_department_notices(source_id: str, start_page: int = 1, pages: int = 1) -> dict[str, Any]:
    """앱에서 지정한 공식 단과대학·학과의 공개 공지 목록을 읽는다. 이어 읽으려면 next_page를 사용한다."""
    async with _campus_query_lock, DepartmentNoticeClient() as client:
        return await client.list_notices(source_id, start_page, pages)


@mcp.tool()
async def get_department_notice(source_id: str, board_id: str, notice_id: str) -> dict[str, Any]:
    """공식 단과대학·학과 공지 목록에서 확인한 게시판 및 글 ID로 본문과 자료 정보를 읽는다."""
    async with _campus_query_lock, DepartmentNoticeClient() as client:
        return await client.get_notice(source_id, board_id, notice_id)


@mcp.tool()
async def read_campus_notice_file(
    board: CampusBoard, board_id: str, notice_id: str, file_id: str,
    start_page: int = 1, max_pages: int = 10,
) -> dict[str, Any]:
    """공지 상세의 파일 ID로 지원 문서의 텍스트를 읽는다. next_page가 있으면 이어 읽고, unsupported면 원본을 받는다."""
    async with _campus_query_lock:
        file = await fetch_campus_notice_file(board, board_id, notice_id, file_id)
    result = await asyncio.to_thread(
        extract_file_text, file.name, file.content, start_page=start_page, max_pages=max_pages,
    )
    return {**result, "notice_url": file.notice_url}


@mcp.tool()
async def download_campus_notice_file(
    board: CampusBoard, board_id: str, notice_id: str, file_id: str,
) -> dict[str, Any]:
    """공지 상세의 첨부파일 또는 본문 이미지 ID로 원본을 로컬에 저장하고 절대 경로를 반환한다. 최대 32 MiB."""
    async with _campus_query_lock:
        file = await fetch_campus_notice_file(board, board_id, notice_id, file_id)
    path = await asyncio.to_thread(save_campus_notice_file, file)
    return {
        "filename": file.name, "path": path, "size_bytes": len(file.content),
        "media_type": file.media_type, "notice_url": file.notice_url,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
