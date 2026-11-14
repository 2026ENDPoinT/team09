"""Endpoints verified in the authenticated SeoulTech e-Class web application."""
from __future__ import annotations

from urllib.parse import urljoin

BASE_URL = "https://eclass.seoultech.ac.kr"


def absolute(path: str) -> str:
    return urljoin(f"{BASE_URL}/", path)


# Strictly read-only allowlist. No submission, post creation, update, or delete
# endpoint belongs in this module.
MAIN_FORM = "/ilos/main/main_form.acl"
HOME_TODO_LIST = "/ilos/main/main_todo_list.acl"
MY_INFO = "/ilos/mp/myinfo_pop_form.acl"
ENTER_COURSE = "/ilos/cls/st/co/eclass_room2.acl"
COURSE_HOME = "/ilos/cls/st/submain/submain_form.acl"
NOTICE_FORM = "/ilos/cls/st/notice/notice_list_form.acl"
NOTICE_LIST = "/ilos/cls/st/notice/notice_list.acl"
NOTICE_VIEW = "/ilos/cls/st/notice/notice_view_pop.acl"
ACTIVITY_FORM = "/ilos/cls/st/activity/activity_form.acl"
ACTIVITY_LIST = "/ilos/cls/st/activity/activity_list.acl"
REPORT_VIEW = "/ilos/cls/st/report/report_view_form.acl"

ALLOWED_GET_PATHS = frozenset({MAIN_FORM, COURSE_HOME, NOTICE_FORM, ACTIVITY_FORM, REPORT_VIEW})
ALLOWED_POST_PATHS = frozenset({ENTER_COURSE, NOTICE_LIST, NOTICE_VIEW, ACTIVITY_LIST, MY_INFO})

SYSTEM_NOTICE_LIST = "/ilos/main/community/notice_list.acl"
SYSTEM_NOTICE_VIEW = "/ilos/main/community/notice_view_pop.acl"
MATERIAL_VIEW = "/ilos/cls/st/material/lecture_material_view_form.acl"
DISCUSSION_VIEW = "/ilos/cls/st/discuss/discuss_view_form.acl"
QNA_LIST = "/ilos/cls/st/qna/qna_list.acl"
QNA_VIEW = "/ilos/cls/st/qna/qna_view_pop.acl"
BOARD_FORM = "/ilos/cls/st/board/open_material_list_form.acl"
BOARD_LIST = "/ilos/cls/st/board/open_material_list.acl"
BOARD_VIEW = "/ilos/cls/st/board/open_material_view_pop.acl"
SYLLABUS_POP = "/ilos/main/rg/regular_view_pop.acl"
SYLLABUS_VIEW = "/ilos/main/rg/regular_view_plan.acl"
COURSE_FILES = "/ilos/cls/st/files/files_list.acl"
COURSE_ATTACHMENT_LIST = "/ilos/cls/st/co/efile_list.acl"
SYSTEM_ATTACHMENT_LIST = "/ilos/co/file_list3.acl"

# These routes are allowed only during the bounded file download flow.
ATTACHMENT_DOWNLOAD_PATHS = frozenset({"/ilos/co/efile_download.acl", "/ilos/co/file_download.acl"})
ATTACHMENT_REDIRECT_PATHS = frozenset({"/ilos/co/file_download_v2.acl", "//ilos/co/file_download_v2.acl"})

ALLOWED_GET_PATHS |= {MATERIAL_VIEW, DISCUSSION_VIEW}
ALLOWED_POST_PATHS |= {
    HOME_TODO_LIST,
    SYSTEM_NOTICE_LIST, SYSTEM_NOTICE_VIEW, QNA_LIST, QNA_VIEW, BOARD_LIST, BOARD_VIEW,
    SYLLABUS_POP, SYLLABUS_VIEW, COURSE_FILES, COURSE_ATTACHMENT_LIST, SYSTEM_ATTACHMENT_LIST,
}
