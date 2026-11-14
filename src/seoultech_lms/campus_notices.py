from __future__ import annotations

import hashlib
import re
import ssl
from typing import Any, Callable, Literal, Self
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

import httpx
import truststore
from bs4 import BeautifulSoup, Tag

CampusBoard = Literal["notice", "matters", "janghak", "graduate", "job"]

_ORIGIN = "https://www.seoultech.ac.kr"
_BOARD_IDS = {
    "notice": frozenset({"4691"}),
    "matters": frozenset({"6112", "57139"}),
    "janghak": frozenset({"5233", "57138"}),
    "graduate": frozenset({"56589"}),
    "job": frozenset({"57925", "57926"}),
}
_PAGE_SIZE = 15
_MAX_PAGES = 5
_ID = re.compile(r"[0-9]{1,12}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PAGER = re.compile(r"javascript:\s*dcPaging\(\s*([0-9]+)\s*\)\s*;?", re.I)
_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "avif"})
ATTACHMENT_DOWNLOAD_URL = f"{_ORIGIN}/hcm/bbs/bbs_download.jsp"
_DOWNLOAD_CALL = re.compile(
    r"""(?:javascript:\s*)?downloadfile\(\s*(?P<path_quote>['"])(?P<path>/storage/[a-z0-9_-]+/bbs/[0-9]+/?)"""
    r"""(?P=path_quote)\s*,\s*(?P<file_quote>['"])(?P<file>[A-Za-z0-9][A-Za-z0-9_.-]{0,254})"""
    r"""(?P=file_quote)\s*,\s*(?P<name_quote>['"])(?P<name>.*?)(?P=name_quote)\s*\)\s*;?\s*""",
    re.I | re.S,
)


def _board_url(board: CampusBoard) -> str:
    if board not in _BOARD_IDS:
        raise ValueError("지원하지 않는 학교 공지 게시판입니다.")
    return f"{_ORIGIN}/service/info/{board}"


def _notice_url(board: CampusBoard, board_id: str, notice_id: str) -> str:
    source = _board_url(board)
    if board_id not in _BOARD_IDS[board] or not _ID.fullmatch(notice_id):
        raise ValueError("해당 게시판 목록에서 확인한 게시판·공지 ID를 사용해 주세요.")
    return f"{source}?do=commonview&bnum={board_id}&bidx={notice_id}"


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node is not None else ""


def _safe_web_url(value: str, source: str) -> str | None:
    if not value or any(ord(character) < 32 for character in value) or "\\" in value:
        return None
    try:
        absolute = urljoin(source, value)
        url = urlsplit(absolute)
        if url.scheme not in ("http", "https") or not url.hostname or url.username is not None or url.password is not None:
            return None
        if url.port not in (None, 80 if url.scheme == "http" else 443):
            return None
    except ValueError:
        return None
    return absolute


def campus_image_url(value: str) -> str | None:
    """Accept only raster files under the university site's public image directory."""
    absolute = _safe_web_url(value, _ORIGIN)
    if absolute is None:
        return None
    url = urlsplit(absolute)
    path = unquote(url.path)
    if url.scheme != "https" or url.hostname != "www.seoultech.ac.kr":
        return None
    if not path.startswith("/storage/www/ckfinder/images/"):
        return None
    if any(char in path for char in ("%", "\\", "?", "#", ";")) or any(ord(char) < 32 for char in path):
        return None
    if any(part in {"", ".", ".."} for part in path[1:].split("/")):
        return None
    if "." not in path or path.rsplit(".", 1)[-1].lower() not in _IMAGE_EXTENSIONS:
        return None
    return _ORIGIN + quote(path, safe="/")


def _id_for_asset(kind: str, value: str) -> str:
    return f"{kind}-{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _list_page(
    html: str, board: CampusBoard, page: int,
) -> tuple[list[dict[str, Any]], int | None]:
    source = _board_url(board)
    return _standard_list_page(html, board, page, source, _BOARD_IDS[board], campus=True)


def _pagination(soup: BeautifulSoup, page: int) -> int | None:
    pager = soup.select_one(".dc-paging")
    if pager is None:
        return None
    if _text(pager.select_one(".on")) != str(page):
        raise RuntimeError("학교 홈페이지에서 요청한 공지 페이지를 반환하지 않았습니다.")
    if any(int(match[1]) > page for link in pager.select("a[href]") if (match := _PAGER.fullmatch(link["href"]))):
        return page + 1
    return None


def _notice_identifiers(link: str, source: str, board_ids: frozenset[str], *, campus: bool = False) -> tuple[str, str] | None:
    target = _safe_web_url(link, source)
    if target is None:
        return None
    parsed = urlsplit(target)
    if f"{parsed.scheme}://{parsed.hostname}{parsed.path.rstrip('/')}" != source:
        return None
    fields = parse_qs(parsed.query)
    action = fields.get("do", [])
    if action != ["commonview"] and (campus or action != ["view"]):
        return None
    board_id = fields.get("bnum", [])
    notice_id = fields.get("bidx", [])
    if len(board_id) != 1 or board_id[0] not in board_ids or len(notice_id) != 1 or not _ID.fullmatch(notice_id[0]):
        return None
    return board_id[0], notice_id[0]


def _standard_list_page(
    html: str, board: str, page: int, source: str, board_ids: frozenset[str], *, campus: bool = False,
) -> tuple[list[dict[str, Any]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tbl_list" if campus else "table.tbl_list, table.board")
    if table is None:
        raise RuntimeError("학교 공지 목록의 표를 찾지 못했습니다.")
    next_page = _pagination(soup, page)

    notices = []
    rows = table.select(":scope > tbody > tr, :scope > tr")
    for row in rows:
        cells = row.find_all("td", recursive=False)
        link = row.select_one('a[href*="bidx="][href*="do=commonview"]' if campus else 'a[href*="bidx="][href*="do="]')
        if len(cells) < 5 or link is None:
            continue
        ids = _notice_identifiers(link["href"], source, board_ids, campus=campus)
        if ids is None:
            continue
        board_id, notice_id = ids
        featured = cells[0].get("colspan") == "2"
        featured_parts = cells[0].find_all("div", recursive=False) if featured else []
        title = _text(featured_parts[0]) if featured_parts else _text(link)
        if not title:
            continue
        date = _text(cells[-2])
        notices.append({
            "board": board,
            "board_id": board_id,
            "id": notice_id,
            "title": title,
            "department": _text(cells[-3]) or None,
            "published_at": date if _DATE.fullmatch(date) else None,
            "pinned": featured or bool(cells[0].select_one('img[alt="공지"], img[alt="notice" i]')),
            "has_attachments": bool(cells[-4].select_one("img, a")),
            "url": f"{source}?do=commonview&bnum={board_id}&bidx={notice_id}",
            "preview": _text(featured_parts[1]) if len(featured_parts) > 1 else None,
        })
    if not notices and rows and not re.search(r"(?:등록된|조회된|검색된).{0,30}없습니다", _text(table)):
        raise RuntimeError("학교 공지 목록의 글을 읽지 못했습니다.")
    return notices, next_page


def _attachment_metadata(table: Tag, board_id: str, *, department: bool = False) -> list[dict[str, Any]]:
    attachments: dict[str, dict[str, Any]] = {}
    folder = f"/storage/www/bbs/{board_id}"
    for link in table.select(":scope > tbody > tr > td:not(.cont) .list_attach a[href], "
                             ":scope > tr > td:not(.cont) .list_attach a[href]"):
        match = _DOWNLOAD_CALL.fullmatch(link["href"].strip())
        if not match:
            continue
        stored_folder = match["path"].rstrip("/")
        if (department and not stored_folder.endswith(f"/bbs/{board_id}")) or (not department and stored_folder != folder):
            continue
        display_name = _text(link) or match["name"]
        if not display_name or len(display_name) > 512 or any(c in display_name for c in "/\\"):
            continue
        if any(ord(c) < 32 or ord(c) == 127 for c in display_name):
            continue
        attachment_id = _id_for_asset("attachment", f"{stored_folder}/{match['file']}")
        attachments.setdefault(attachment_id, {
            "id": attachment_id,
            "name": display_name,
            "download_fields": {"fpath": match["path"], "fname": match["file"], "ogrfname": display_name},
        })
    return list(attachments.values())


def _body_text(body: Tag) -> str:
    for br in body.select("br"):
        br.replace_with("\n")
    for cell in body.select("td, th"):
        cell.append(" ")
    for block in body.select("p, div, li, tr, h1, h2, h3, h4, h5, h6"):
        block.insert_before("\n")
        block.append("\n")
    lines = (" ".join(line.split()) for line in body.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def _article(html: str, board: CampusBoard, board_id: str, notice_id: str) -> dict[str, Any]:
    source = _notice_url(board, board_id, notice_id)
    return _standard_article(html, board, board_id, notice_id, source, campus_image_url)


def _standard_article(
    html: str, board: str, board_id: str, notice_id: str, source: str,
    image_url: Callable[[str], str | None], *, department: bool = False,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tbl_view")
    body = table.select_one(":scope > tbody > tr > td.cont, :scope > tr > td.cont") if table is not None else None
    if body is None:
        raise RuntimeError("학교 공지의 본문을 찾지 못했습니다.")
    fields = {
        _text(th): _text(th.find_next_sibling("td"))
        for th in table.select(":scope > tbody > tr > th, :scope > tr > th")
    }
    title = fields.get("제목") or fields.get("Title")
    if not title:
        raise RuntimeError("학교 공지의 제목을 찾지 못했습니다.")
    date = fields.get("날짜") or fields.get("등록일") or fields.get("Date") or ""
    return {
        "board": board,
        "board_id": board_id,
        "id": notice_id,
        "title": title,
        "department": fields.get("작성자") or fields.get("Writer") or None,
        "published_at": date if _DATE.fullmatch(date) else None,
        "pinned": None,
        "has_attachments": bool(fields.get("첨부파일") or fields.get("Files")),
        "url": source,
        "preview": None,
        "attachments": _attachment_metadata(table, board_id, department=department),
        **_body_resources(body, source, image_url),
    }


def _body_resources(body: Tag, source: str, image_url: Callable[[str], str | None]) -> dict[str, Any]:
    for node in reversed(body.select("script, style, template, [hidden], [aria-hidden=true]")):
        node.decompose()
    images = {}
    for image in body.select("img[src], img[data-src]"):
        url = image_url(image.get("data-src") or image.get("src") or "")
        if url is not None:
            images[url] = {"id": _id_for_asset("image", url), "url": url, "alt": image.get("alt", "")}
    links = {}
    for anchor in body.select("a[href]"):
        url = _safe_web_url(anchor["href"].strip(), source)
        if url is not None:
            links[url] = {"url": url, "text": _text(anchor)}
    return {"content": _body_text(body), "images": list(images.values()), "links": list(links.values())}


class CampusNoticeClient:
    """Read public notices without using any e-Class session."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._http = httpx.AsyncClient(
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            follow_redirects=False,
            timeout=15,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _get(self, url: str, params: dict[str, int] | None = None) -> str:
        if self._http is None:
            raise RuntimeError("CampusNoticeClient는 async with 블록에서 사용해 주세요.")
        response = await self._http.get(url, params=params)
        response.raise_for_status()
        return response.text

    async def list_notices(
        self, board: CampusBoard, start_page: int = 1, pages: int = 3,
    ) -> dict[str, Any]:
        source = _board_url(board)
        if not 1 <= pages <= _MAX_PAGES or start_page < 1:
            raise ValueError(f"시작 페이지는 1 이상, 페이지 수는 1~{_MAX_PAGES}로 지정해 주세요.")
        notices = {}
        next_page = start_page
        for _ in range(pages):
            html = await self._get(source, {"page": next_page, "size": _PAGE_SIZE})
            rows, next_page = _list_page(html, board, next_page)
            for row in rows:
                notices.setdefault((row["board_id"], row["id"]), row)
            if next_page is None:
                break
        return {"board": board, "notices": list(notices.values()), "next_page": next_page}

    async def get_notice(
        self, board: CampusBoard, board_id: str, notice_id: str,
    ) -> dict[str, Any]:
        html = await self._get(_notice_url(board, board_id, notice_id))
        return _article(html, board, board_id, notice_id)
