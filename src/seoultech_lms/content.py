from __future__ import annotations

import re
from html import unescape
from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup, Tag

from .endpoints import ATTACHMENT_DOWNLOAD_PATHS, BASE_URL, BOARD_FORM
from .models import Attachment, DiscussionComment, DiscussionOpinion, LearningActivity, Post, Syllabus
from .parser import parse_notice_datetime

PostKind = Literal["assignment", "course_notice", "system_notice", "material", "open_board", "qna", "discussion"]
AttachmentSource = Literal[
    "assignment", "course_notice", "system_notice", "material", "open_board", "qna", "discussion", "file_collection",
]

_ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_ACTIVITY_PREFIX = {
    "assignment": "class_menu_report_",
    "material": "class_menu_lecture_material_",
    "discussion": "class_menu_discuss_",
}
ACTIVITY_TYPES = {
    "report": "assignment",
    "lecture_material": "material",
    "discuss": "discussion",
    "lecture_weeks": "lecture",
    "test": "quiz",
    "survey": "survey",
}
ACTIVITY_COUNT_KEYS = (*ACTIVITY_TYPES.values(), "other_activity")
ACTIVITY_ID = re.compile(r"class_menu_(?P<type>[a-z_]+)_(?P<id>[A-Za-z0-9-]+)")
_LIST_SELECTORS = {
    "course_notice": ".board_list_wrap",
    "system_notice": ".board_list_wrap",
    "open_board": ".board_list_wrap",
    "qna": ".qna_list_wrap",
}
_VIEW_CALLS = {
    "system_notice": "noticeViewPop",
    "open_board": "materialViewPop",
}
_OPINION_VIEW_CALL = re.compile(r"""^\s*viewDiscussDetailPop\s*\(\s*['"]?([0-9]+)['"]?\s*[,)]""")
_DISCUSSION_COMMENT_CALL = re.compile(
    r"""\bcmmtList\s*\(\s*['"](?P<opinion_id>[0-9]+)['"]\s*,"""
    r"""\s*['"](?P<BRD_ID>K009)['"]\s*,\s*['"](?P<CMMT_BRD_ID>KC09)['"]\s*,"""
    r"""\s*['"](?P<auth>st)['"]\s*,\s*['"](?P<topic_id>[0-9]+)['"]\s*\)"""
)


@dataclass(frozen=True)
class FileLink:
    attachment: Attachment
    href: str


def is_item_id(value: str | None) -> bool:
    return value is not None and bool(_ITEM_ID.fullmatch(value))


def _text(node: Tag | None, separator: str = " ") -> str:
    return node.get_text(separator, strip=True) if node else ""


def _local_url(href: str):
    parts = urlsplit(href)
    if parts.scheme not in ("", "https") or parts.netloc not in ("", urlsplit(BASE_URL).netloc):
        return None
    return parts


def parse_open_boards(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, str] = {}
    for a in soup.select("a[href]"):
        try:
            url = _local_url(a["href"])
        except ValueError:
            continue
        if not url or url.path != BOARD_FORM:
            continue
        group = dict(parse_qsl(url.query)).get("ARTL_GRP_ID")
        if group and is_item_id(group):
            title = _text(a)
            if group not in groups or title:
                groups[group] = title or "열린게시판"
    return [{"id": group, "title": title} for group, title in groups.items()]


def parse_board_ids(html: str) -> list[str]:
    return [board["id"] for board in parse_open_boards(html)]


def parse_post_list(
    html: str, kind: PostKind, course_id: str | None, board_id: str | None = None,
) -> list[Post]:
    return _parse_post_rows(BeautifulSoup(html, "html.parser"), kind, course_id, board_id)


def assignment_submission_status(row: Tag) -> bool | None:
    if "not_submit" in row.get("class", []):
        return False
    if row.select_one(".submit_check_outer > .submit_check") is not None:
        return True
    return None


def _parse_post_rows(
    soup: BeautifulSoup, kind: PostKind, course_id: str | None, board_id: str | None,
) -> list[Post]:
    prefix = _ACTIVITY_PREFIX.get(kind)
    selector = f'a[id^="{prefix}"]' if prefix else _LIST_SELECTORS[kind]
    posts: dict[str, Post] = {}
    for row in soup.select(selector):
        post_id = row["id"].removeprefix(prefix) if prefix else row.get("data-num")
        view_call = _VIEW_CALLS.get(kind)
        if not post_id and view_call:
            handler = str(row.get("onclick", ""))
            match = re.search(rf"\b{view_call}\(\s*['\"]?([\w-]+)", handler)
            if match:
                post_id = match.group(1)
        if not is_item_id(post_id):
            continue
        title = _text(row.select_one(".activity_title, .board_title, .qna_title")) or _text(row)
        registered = _text(row.select_one(".reg_info, .board_list_bottom"))
        posts[post_id] = Post(
            id=post_id, kind=kind, title=title, course_id=course_id, board_id=board_id,
            created_at=parse_notice_datetime(registered, course_id or "") if registered else None,
            submitted=assignment_submission_status(row) if kind == "assignment" else None,
        )
    return list(posts.values())


def is_empty_listing(soup: BeautifulSoup) -> bool:
    return any(
        re.search(r"(?:조회할|등록된|검색된|표시할|첨부된).{0,40}없습니다", _text(node))
        for node in soup.select(".list_error_msg, .error_message, .empty_content")
    )


def parse_course_activities(html: str) -> tuple[dict[str, int], LearningActivity | None]:
    """Count weekly entries and summarize assignments with a verified submission status."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select('a.activity[id^="class_menu_"]')
    if not rows and not (soup.select_one(".activity_week") or is_empty_listing(soup)):
        raise ValueError("강의실 활동 목록 구조를 확인할 수 없습니다.")
    counts = dict.fromkeys(ACTIVITY_COUNT_KEYS, 0)
    seen = set()
    submissions: dict[str, set[bool]] = {}
    for row in rows:
        identifier = row["id"]
        match = ACTIVITY_ID.fullmatch(identifier)
        kind = ACTIVITY_TYPES.get(match["type"], "other_activity") if match else "other_activity"
        if identifier not in seen:
            counts[kind] += 1
            seen.add(identifier)
        if kind == "assignment":
            statuses = submissions.setdefault(identifier, set())
            status = assignment_submission_status(row)
            if status is not None:
                statuses.add(status)

    known = [next(iter(status)) for status in submissions.values() if len(status) == 1]
    progress = LearningActivity(sum(known), len(known)) if known or not submissions else None
    return counts, progress


def parse_board_page(
    html: str, kind: PostKind, course_id: str, board_id: str | None, page: int, page_size: int,
) -> tuple[set[str], bool]:
    soup = BeautifulSoup(html, "html.parser")
    posts = _parse_post_rows(soup, kind, course_id, board_id)
    rows = soup.select(_LIST_SELECTORS[kind])
    if (rows and not posts) or (not rows and not is_empty_listing(soup)):
        raise ValueError("게시판 목록 구조를 확인할 수 없습니다.")

    pager = soup.select_one(".file_paging")
    if pager is None:
        return {post.id for post in posts}, len(rows) >= page_size
    active = pager.select_one(".paging_num_btn.on")
    if posts and _text(active) != str(page):
        raise ValueError("게시판 페이지 번호가 일치하지 않습니다.")
    has_next = any(
        _text(button).isdigit() and int(_text(button)) > page for button in pager.select(".paging_num_btn")
    ) or bool(pager.select_one('.paging_next_btn_box button[onclick]:not([onclick=""])'))
    return {post.id for post in posts}, has_next


def parse_post_body(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one(".view_title .font_headline2, .view_title")) or None
    editor = soup.select_one(".editor_content")
    return title, _text(editor, "\n") if editor else None


def _count_text(value: str) -> int | None:
    value = value.strip().replace(",", "")
    return int(value) if value.isdecimal() else None


def parse_discussion_opinions(html: str, course_id: str, topic_id: str) -> list[DiscussionOpinion]:
    soup = BeautifulSoup(html, "html.parser")
    total = soup.select_one("input#discuss_detail_cnt[value]")
    expected = _count_text(total["value"]) if total else None
    opinions: dict[str, DiscussionOpinion] = {}
    for row in soup.select(".discuss_list_wrap[onclick]"):
        match = _OPINION_VIEW_CALL.match(str(row["onclick"]))
        item = row.select_one(".discuss_list[data-num]")
        if not match or item is None or item["data-num"] != match[1] or not is_item_id(match[1]):
            continue
        preview = _text(row.select_one(".discuss_text"))
        if len(preview) > 240:
            preview = preview[:240] + "…"
        opinions[match[1]] = DiscussionOpinion(
            id=match[1], course_id=course_id, topic_id=topic_id,
            title=_text(row.select_one(".discuss_title")),
            preview=preview or None,
            author=_text(row.select_one(".reg_nm")) or None,
            created_at=_text(row.select_one(".discuss_reg_dt")) or None,
            comment_count=_count_text(_text(row.select_one(".idea_comment + div"))),
        )
    if expected is None or len(opinions) != expected:
        raise RuntimeError("e-Class의 토론 의견 목록을 모두 확인하지 못했습니다.")
    return list(opinions.values())


def parse_discussion_opinion(
    html: str, opinion: DiscussionOpinion,
) -> tuple[DiscussionOpinion, dict[str, str] | None]:
    soup = BeautifulSoup(html, "html.parser")
    editor = soup.select_one(".discuss_detail_content .editor_content")
    if editor is None:
        raise RuntimeError("e-Class의 토론 의견 본문을 확인하지 못했습니다.")
    comment_count = _count_text(_text(soup.find(id=f"cmmt_cnt{opinion.id}")))
    detail = replace(
        opinion,
        title=_text(soup.select_one(".discuss_detail_content_wrap .title")) or opinion.title,
        content=_text(editor, "\n"),
        comment_count=opinion.comment_count if comment_count is None else comment_count,
    )
    if soup.find("button", id=f"cmmt_btn{opinion.id}") is None:
        return detail, None
    # Accept only the student discussion board and the exact topic and opinion shown by the LMS.
    for script in soup.select("script:not([src])"):
        for match in _DISCUSSION_COMMENT_CALL.finditer(script.get_text()):
            if (match["opinion_id"], match["topic_id"]) == (opinion.id, opinion.topic_id):
                return detail, {
                    "KJKEY": opinion.course_id,
                    "MENU_SEQ": opinion.id,
                    "MENU_SEQ2": opinion.topic_id,
                    "BRD_ID": match["BRD_ID"],
                    "CMMT_BRD_ID": match["CMMT_BRD_ID"],
                    "auth": match["auth"],
                    "encoding": "utf-8",
                }
    return detail, None


def parse_discussion_comments(html: str) -> list[DiscussionComment]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".comment_container")
    if container is None:
        raise RuntimeError("e-Class의 토론 댓글 목록을 확인하지 못했습니다.")
    comments: list[DiscussionComment] = []
    for row in container.select('.comment_list[id^="comment_"]'):
        body = row.select_one(":scope > .comment_body_wrap > .comment_body")
        view = body.select_one(".comment_view") if body else None
        comment_id = row["id"].removeprefix("comment_")
        if view is None or not is_item_id(comment_id):
            continue
        for metadata in view.select(".comment_update_info"):
            metadata.decompose()
        parent = row.find_parent(class_="comment_reply_list_wrap")
        parent_id = str(parent.get("id", "")).removeprefix("comment_reply_list_wrap_") if parent else None
        comments.append(DiscussionComment(
            id=comment_id,
            content=_text(view, "\n"),
            author=_text(body.select_one(".comment_reg_user_nm")) or None,
            created_at=_text(body.select_one(".comment_reg_dt")) or None,
            parent_id=parent_id if is_item_id(parent_id) else None,
        ))
    return comments


def ajax_fields(
    html: str, path: str, fields: frozenset[str], *, content_seq: str | None = None,
) -> dict[str, str] | None:
    """Extract a known read form without executing the page's scripts."""
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(
        rf"""\burl\s*:\s*["']{re.escape(path)}["']\s*,\s*type\s*:\s*["']POST["']\s*,\s*data\s*:\s*\{{([^{{}}]*)\}}""",
        re.I,
    )
    for script in soup.select("script:not([src])"):
        for match in pattern.finditer(script.get_text()):
            raw = match.group(1)
            values = {
                key: value for key, _, value in re.findall(r"""(\w+)\s*:\s*(["'])(.*?)\2""", raw)
                if key in fields
            }
            if content_seq and re.search(r"\bCONTENT_SEQ\s*:\s*en_artl_num\b", raw):
                values["CONTENT_SEQ"] = content_seq
            if values.keys() == fields and values.get("encoding") == "utf-8":
                return values
    return None


def qna_attachment_seq(html: str, post_id: str) -> str | None:
    # The detail page passes its encoded article key to its fileList helper.
    match = re.search(rf"""\bfileList\(\s*["']([\w-]+)["']\s*,\s*["']?{re.escape(post_id)}\b""", unescape(html))
    return match.group(1) if match else None


def parse_file_links(html: str) -> list[FileLink]:
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, FileLink] = {}
    for anchor in soup.select(".attach_list a[href]"):
        href = anchor["href"]
        url = _local_url(href)
        if not url or url.path not in ATTACHMENT_DOWNLOAD_PATHS or url.fragment:
            continue
        params = dict(parse_qsl(url.query))
        file_id = params.get("FILE_SEQ")
        if not is_item_id(file_id) or not is_item_id(params.get("CONTENT_SEQ")):
            continue
        if "icon_download" in anchor.get("class", []):
            continue
        name = _text(anchor)
        if name:
            links[file_id] = FileLink(Attachment(file_id, name), href)
    return list(links.values())


def parse_syllabus(html: str, course_id: str, title: str) -> Syllabus:
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for table in soup.select("table"):
        rows = [
            [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            for row in table.find_all("tr")
            if row.find_parent("table") is table
        ]
        if rows:
            tables.append(rows)
    text = soup.get_text("\n", strip=True)
    if not tables or not text:
        raise RuntimeError("강의계획서 내용을 확인할 수 없습니다.")
    return Syllabus(course_id, title, text, tables)
