from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .assignment_summary import SEOUL_TIME, AssignmentSummary, AssignmentSummaryCache, AssignmentSummaryItem
from .auth import AuthenticationRequired, auth_state_path
from .browser import start_login_browser
from .client import SeoultechLMSClient
from .content import AttachmentSource, PostKind
from .models import as_jsonable


mcp = FastMCP(
    "seoultech_c4t",
    instructions=(
        "이 서버는 사용자 컴퓨터에서 'python -m seoultech_lms.mcp_server'로 실행되는 로컬 stdio MCP다. "
        "호스트 AI 클라이언트가 로컬 프로세스와 로컬 인증 상태에 접근할 수 있어야 한다. "
        "서울과학기술대학교 e-Class의 로그인한 사용자 데이터를 읽기 전용으로 조회한다. "
        "로그인 도구는 'python -m seoultech_lms.login_window'를 로컬에서 실행해 공식 LMS 로그인 페이지를 Chrome으로 열고 인증 상태만 로컬에 저장한다. "
        "과제 제출, 게시물 작성, 수정, 삭제, 파일 업로드는 지원하지 않는다."
    ),
)


# e-Class stores the active course in the login session.
_query_lock = asyncio.Lock()
_assignment_cache = AssignmentSummaryCache()


@asynccontextmanager
async def _query_client():
    async with _query_lock:
        try:
            async with SeoultechLMSClient(assignment_cache=_assignment_cache) as client:
                yield client
        except AuthenticationRequired:
            _assignment_cache.clear()
            raise


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
async def get_student_profile(include_contact: bool = False) -> dict[str, str | int | None]:
    """로그인한 본인의 e-Class 내 정보에서 이름, 소속 학과와 학년을 읽는다. 전화번호나 이메일을 요청한 경우에만 include_contact를 true로 지정한다."""
    async with _query_client() as client:
        return await client.get_student_profile(include_contact=include_contact)


@mcp.tool()
async def list_courses() -> list[dict[str, Any]]:
    """현재 수강 중인 과목 목록을 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.get_courses())


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
    """전체 과목 또는 지정한 과목의 과제, 교수자 안내 본문, 마감일, 제출 여부를 조회한다."""
    async with _query_client() as client:
        courses = await client.get_courses()
        assignments = await client.get_assignments(course_id, include_completed=include_completed)
    return _with_course_names(assignments, {course.id: course.name for course in courses})


@mcp.tool()
async def get_assignment_summary(course_id: str | None = None, refresh_details: bool = False) -> AssignmentSummary:
    """최신 강좌 과제 목록을 대조한 뒤 미제출·제출 미확인 과제의 마감, 지각 마감, 제출 상태를 조회한다. 변경된 과제와 미확인 과제는 상세를 읽는다. unavailable이 있으면 일부 조회에 실패했으므로 결과를 전체 목록으로 설명하지 않는다. todo_checked는 홈 할일 위젯 확인 여부다. 모든 과제 마감 정보를 다시 확인해야 할 때만 refresh_details를 사용한다."""
    async with _query_client() as client:
        return await client.get_assignment_summary(course_id, refresh_details=refresh_details)


@mcp.tool()
async def get_pending_assignments(course_id: str | None = None) -> list[AssignmentSummaryItem]:
    """최신 정규 강좌 목록에서 미제출 또는 제출 미확인 과제의 마감을 반환한다. 교수자 안내는 list_assignments를 사용한다."""
    async with _query_client() as client:
        summary = await client.get_assignment_summary(course_id, include_non_regular=False)
    if summary.get("unavailable"):
        raise RuntimeError("일부 과제를 확인하지 못했어요. 확인된 과제와 실패한 범위는 get_assignment_summary에서 볼 수 있어요.")
    return [
        {**item, "due_at": _legacy_deadline(item["due_at"]), "late_due_at": _legacy_deadline(item["late_due_at"])}
        for item in summary["assignments"]
    ]


def _legacy_deadline(value: str | None) -> str | None:
    return datetime.fromisoformat(value).replace(tzinfo=None).isoformat() if value is not None else None


@mcp.tool()
async def get_upcoming_deadlines(
    days: int = 7,
    course_id: str | None = None,
) -> list[AssignmentSummaryItem]:
    """최신 목록을 확인해 현재 시각부터 지정한 일수 안에 마감되는 미제출·제출 미확인 과제를 조회한다."""
    if days < 0:
        raise ValueError("days는 0 이상이어야 합니다.")
    assignments = await get_pending_assignments(course_id)
    if any(item["due_at"] is None for item in assignments):
        raise RuntimeError("마감일을 확인하지 못한 과제가 있어요. 확인된 과제와 미확인 항목은 get_assignment_summary에서 볼 수 있어요.")
    now = datetime.now(SEOUL_TIME).replace(tzinfo=None)
    end = now + timedelta(days=days)
    return [item for item in assignments if item["due_at"] and now <= datetime.fromisoformat(item["due_at"]) <= end]


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
    """list_posts의 게시물 ID와 페이지로 본문 및 첨부 목록을 조회한다. attachments가 null이면 첨부 목록을 확인하지 못한 것이다."""
    async with _query_client() as client:
        return as_jsonable(await client.get_post(kind, post_id, course_id, page=page, board_id=board_id))


@mcp.tool()
async def get_syllabus(course_id: str) -> dict[str, Any]:
    """지정 강좌의 강의계획서 본문과 표를 조회한다."""
    async with _query_client() as client:
        return as_jsonable(await client.get_syllabus(course_id))


@mcp.tool()
async def list_course_files(course_id: str) -> list[dict[str, Any]]:
    """지정 강좌의 파일모음에서 파일명과 첨부 ID를 조회한다."""
    async with _query_client() as client:
        return _json_list(await client.list_course_files(course_id))


@mcp.tool()
async def read_attachment(
    kind: AttachmentSource, attachment_id: str, course_id: str | None = None,
    post_id: str | None = None, page: int = 1, board_id: str | None = None,
    start_page: int = 1, max_pages: int = 10,
) -> dict[str, Any]:
    """get_post 또는 list_course_files에서 확인한 PDF 첨부 ID로 페이지별 텍스트를 읽는다. 파일모음은 kind=file_collection이다. next_page가 있으면 이어 읽을 수 있다."""
    async with _query_client() as client:
        result = await client.read_attachment(
            kind, attachment_id, course_id, post_id=post_id, page=page, board_id=board_id,
            start_page=start_page, max_pages=max_pages,
        )
    return as_jsonable(result)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
