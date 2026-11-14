from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bs4 import BeautifulSoup, Tag

from .campus_notices import (
    CampusNoticeClient,
    _body_resources,
    _DATE,
    _ID,
    _IMAGE_EXTENSIONS,
    _MAX_PAGES,
    _notice_identifiers,
    _pagination,
    _safe_web_url,
    _standard_article,
    _standard_list_page,
    _text,
    _id_for_asset,
)

_ARCHITECTURE_PAGE_SIZE = 10
_PAGE_SIZE = 15
_STORAGE_IMAGES = re.compile(r"/storage/[a-z0-9_-]+/(?:ckfinder/images|bbs/\d{1,12})/", re.I)
_SHORT_DATE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)")
_CARD_NUMBER = re.compile(r"^No\.\s*\d+\s*", re.I)
_EMPTY_LIST = re.compile(r"(?:등록된|조회된|검색된).{0,30}없습니다")


@dataclass(frozen=True)
class DepartmentNoticeSource:
    url: str
    board_ids: frozenset[str]
    parser: Literal["standard", "archidesign", "card"]

    def article_url(self, board_id: str, notice_id: str) -> str:
        if board_id not in self.board_ids or not _ID.fullmatch(notice_id):
            raise ValueError("해당 공지 목록에서 확인한 게시판·공지 ID를 사용해 주세요.")
        if self.parser == "archidesign":
            return f"{self.url}?bgu=view&idx={notice_id}"
        return f"{self.url}?do=commonview&bnum={board_id}&bidx={notice_id}"

    def image_url(self, value: str) -> str | None:
        absolute = _safe_web_url(value, self.url)
        if absolute is None:
            return None
        url = urlsplit(absolute)
        source = urlsplit(self.url)
        path = unquote(url.path)
        if url.scheme != "https" or url.hostname != source.hostname or url.port not in (None, 443) or url.query or url.fragment:
            return None
        if not _STORAGE_IMAGES.match(path) and not (self.parser == "archidesign" and path.startswith("/data/bbsData/")):
            return None
        if "%2f" in url.path.lower() or any(char in path for char in "%\\?#;") or any(ord(char) < 32 for char in path):
            return None
        if any(part in {"", ".", ".."} for part in path[1:].split("/")):
            return None
        if path.rsplit(".", 1)[-1].lower() not in _IMAGE_EXTENSIONS:
            return None
        return f"https://{source.hostname}{quote(path, safe='/')}"


_SOURCES = {
    source_id: DepartmentNoticeSource(data["url"], frozenset(data["board_ids"]), data["parser"])
    for source_id, data in json.loads(Path(__file__).with_name("department_notice_sources.json").read_text(encoding="utf-8")).items()
}


def _source(source_id: str) -> DepartmentNoticeSource:
    source = _SOURCES.get(source_id)
    if source is None:
        raise ValueError("지원하지 않는 단과대학·학과 공지입니다.")
    return source


def _notice_row(
    source: DepartmentNoticeSource, source_id: str, board_id: str, notice_id: str, title: str,
    date: str | None, *, pinned: bool, has_attachments: bool = False, preview: str | None = None,
) -> dict[str, Any]:
    return {
        "board": source_id,
        "board_id": board_id,
        "id": notice_id,
        "title": title,
        "department": None,
        "published_at": date,
        "pinned": pinned,
        "has_attachments": has_attachments,
        "url": source.article_url(board_id, notice_id),
        "preview": preview,
    }


def _card_list(
    html: str, source: DepartmentNoticeSource, source_id: str, page: int,
) -> tuple[list[dict[str, Any]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    board = soup.select_one(".blog_list")
    if board is None:
        raise RuntimeError("국제대학 공지 목록을 찾지 못했습니다.")
    notices = []
    for item in board.select(":scope > .list"):
        link = item.select_one("h2 a[href]")
        ids = _notice_identifiers(link["href"], source.url, source.board_ids) if link else None
        title = _CARD_NUMBER.sub("", _text(link))
        if ids is None or not title:
            continue
        date = _DATE.search(_text(item.select_one(".date")))
        notices.append(_notice_row(
            source, source_id, *ids, title, date[0] if date else None,
            pinned=bool(link.select_one('img[alt="공지"], img[alt="notice" i]')),
            preview=_text(item.select_one(".box .text"))[:1_000] or None,
        ))
    if not notices and not _EMPTY_LIST.search(_text(board)):
        raise RuntimeError("국제대학 공지 목록의 글을 읽지 못했습니다.")
    return notices, _pagination(soup, page)


def _architecture_list(
    html: str, source: DepartmentNoticeSource, source_id: str, page: int,
) -> tuple[list[dict[str, Any]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    board = soup.select_one(".bbs-gallery-list-con .bbs-basic-gallery-con")
    if board is None:
        raise RuntimeError("건축학전공 공지 목록을 찾지 못했습니다.")
    notices = []
    for link in board.select(":scope > li > a[href]"):
        target = _safe_web_url(link["href"], source.url)
        parsed = urlsplit(target) if target else None
        if parsed is None or f"{parsed.scheme}://{parsed.hostname}{parsed.path}" != source.url:
            continue
        fields = parse_qs(parsed.query)
        ids = fields.get("idx", [])
        title = _text(link.select_one(".gal-tit"))
        if fields.get("bgu") != ["view"] or len(ids) != 1 or not _ID.fullmatch(ids[0]) or not title:
            continue
        short_date = _SHORT_DATE.search(_text(link.select_one(".gal-day")))
        published_at = None
        if short_date:
            try:
                published_at = date(2000 + int(short_date[1]), int(short_date[2]), int(short_date[3])).isoformat()
            except ValueError:
                pass
        notices.append(_notice_row(
            source, source_id, "1", ids[0], title, published_at,
            pinned=bool(link.select_one(".category")), has_attachments=bool(link.select_one(".file-icon")),
        ))
    if not notices and not _EMPTY_LIST.search(_text(board)):
        raise RuntimeError("건축학전공 공지 목록의 글을 읽지 못했습니다.")
    pager = soup.select_one(".paging")
    if pager is None:
        return notices, None
    if _text(pager.select_one(".cur")) != str(page):
        raise RuntimeError("건축학전공 홈페이지에서 요청한 공지 페이지를 반환하지 않았습니다.")
    offset = page * _ARCHITECTURE_PAGE_SIZE
    next_page = page + 1 if any(
        parse_qs(urlsplit(link["href"]).query).get("startPage") == [str(offset)]
        for link in pager.select("a[href]")
    ) else None
    return notices, next_page


def _architecture_article(
    html: str, source: DepartmentNoticeSource, source_id: str, board_id: str, notice_id: str,
) -> dict[str, Any]:
    url = source.article_url(board_id, notice_id)
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(".bbs-view-con")
    body = article.select_one(".bbs-view-content") if article else None
    title = _text(article.select_one(".bbs-view-top .bbs-tit")) if article else ""
    if article is None or body is None or not title:
        raise RuntimeError("건축학전공 공지의 본문을 찾지 못했습니다.")
    fields = {
        _text(term): _text(term.find_next_sibling("dd"))
        for term in article.select(".bbs-write-info dt")
    }
    attachments = {}
    origin = urlsplit(url).netloc
    for link in article.select(".bbs-file-list-wrap a.file-item[href]"):
        target = _safe_web_url(link["href"], url)
        parsed = urlsplit(target) if target else None
        if parsed is None or (parsed.scheme, parsed.netloc, parsed.path) != ("https", origin, "/bbs/bbs_download.php"):
            continue
        params = parse_qs(parsed.query)
        index = params.get("download", [])
        name = _text(link.select_one("dd"))
        if params.get("idx") != [notice_id] or len(index) != 1 or not _ID.fullmatch(index[0]) or not name:
            continue
        attachment_id = _id_for_asset("attachment", f"{source_id}:{notice_id}:{index[0]}")
        attachments[attachment_id] = {"id": attachment_id, "name": name}
    date = fields.get("등록일", "")
    return {
        **_notice_row(source, source_id, board_id, notice_id, title, date if _DATE.fullmatch(date) else None,
                      pinned=False, has_attachments=bool(attachments)),
        "department": fields.get("작성자") or None,
        "pinned": None,
        "attachments": list(attachments.values()),
        **_body_resources(body, url, source.image_url),
    }


class DepartmentNoticeClient(CampusNoticeClient):
    """Read only the catalogued public college and department notice boards."""

    async def list_notices(self, source_id: str, start_page: int = 1, pages: int = 1) -> dict[str, Any]:
        source = _source(source_id)
        if not 1 <= pages <= _MAX_PAGES or start_page < 1:
            raise ValueError(f"시작 페이지는 1 이상, 페이지 수는 1~{_MAX_PAGES}로 지정해 주세요.")
        notices = {}
        next_page = start_page
        for _ in range(pages):
            if source.parser == "archidesign":
                html = await self._get(source.url, {"startPage": (next_page - 1) * _ARCHITECTURE_PAGE_SIZE})
                rows, next_page = _architecture_list(html, source, source_id, next_page)
            else:
                html = await self._get(source.url, {"page": next_page, "size": _PAGE_SIZE})
                if source.parser == "card":
                    rows, next_page = _card_list(html, source, source_id, next_page)
                else:
                    rows, next_page = _standard_list_page(html, source_id, next_page, source.url, source.board_ids)
            for row in rows:
                notices.setdefault((row["board_id"], row["id"]), row)
            if next_page is None:
                break
        return {"board": source_id, "notices": list(notices.values()), "next_page": next_page}

    async def get_notice(self, source_id: str, board_id: str, notice_id: str) -> dict[str, Any]:
        source = _source(source_id)
        url = source.article_url(board_id, notice_id)
        html = await self._get(url)
        if source.parser == "archidesign":
            return _architecture_article(html, source, source_id, board_id, notice_id)
        notice = _standard_article(html, source_id, board_id, notice_id, url, source.image_url, department=True)
        notice["attachments"] = [{"id": item["id"], "name": item["name"]} for item in notice["attachments"]]
        return notice
