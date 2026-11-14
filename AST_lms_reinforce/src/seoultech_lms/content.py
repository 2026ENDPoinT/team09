from __future__ import annotations

import re
from html import unescape
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup, Tag

from .endpoints import ATTACHMENT_DOWNLOAD_PATHS, BASE_URL, BOARD_FORM
from .models import Attachment, Post, Syllabus
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


def parse_board_ids(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, None] = {}
    for a in soup.select("a[href]"):
        url = _local_url(a["href"])
        if url and url.path == BOARD_FORM:
            group = dict(parse_qsl(url.query)).get("ARTL_GRP_ID")
            if group and is_item_id(group):
                groups[group] = None
    return list(groups)


def parse_post_list(
    html: str, kind: PostKind, course_id: str | None, board_id: str | None = None,
) -> list[Post]:
    soup = BeautifulSoup(html, "html.parser")
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
            submitted="not_submit" not in row.get("class", []) if kind == "assignment" else None,
        )
    return list(posts.values())


def parse_post_body(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one(".view_title .font_headline2, .view_title")) or None
    editor = soup.select_one(".editor_content")
    return title, _text(editor, "\n") if editor else None


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
