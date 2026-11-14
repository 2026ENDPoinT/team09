from __future__ import annotations

import os
import re
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import truststore

from .auth import ensure_private_directory, user_data_dir
from .campus_notices import ATTACHMENT_DOWNLOAD_URL, CampusNoticeClient, campus_image_url


MAX_FILE_BYTES = 32 * 1024 * 1024
_STORED_FILENAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,254}")
_FILE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,12}")


@dataclass(frozen=True)
class CampusFile:
    name: str
    content: bytes
    media_type: str
    notice_url: str


async def fetch_campus_notice_file(board: str, board_id: str, notice_id: str, file_id: str) -> CampusFile:
    async with CampusNoticeClient() as client:
        notice = await client.get_notice(board, board_id, notice_id)

    attachment = next((item for item in notice["attachments"] if item["id"] == file_id), None)
    if attachment is not None:
        fields = attachment["download_fields"]
        folder = f"/storage/www/bbs/{board_id}"
        if (
            fields.keys() != {"fpath", "fname", "ogrfname"}
            or fields["fpath"] not in (folder, f"{folder}/")
            or not _STORED_FILENAME.fullmatch(fields["fname"])
            or any(char in fields["ogrfname"] for char in "\r\n\x00/\\")
        ):
            raise ValueError("학교 공지의 첨부파일 경로를 확인할 수 없습니다.")
        method, url, name = "POST", ATTACHMENT_DOWNLOAD_URL, attachment["name"]
    else:
        image = next((item for item in notice["images"] if item["id"] == file_id), None)
        url = campus_image_url(image["url"]) if image else None
        if not url:
            raise ValueError("공지 상세에 표시된 첨부파일 또는 본문 이미지 ID를 지정해 주세요.")
        method, fields = "GET", None
        name = unquote(Path(urlsplit(url).path).name)

    async with httpx.AsyncClient(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), follow_redirects=False, timeout=25,
        headers={"Accept-Encoding": "identity"},
    ) as http:
        async with http.stream(method, url, data=fields, headers={"Referer": notice["url"]}) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                raise RuntimeError("학교 서버에서 원본 파일을 그대로 반환하지 않았습니다.")
            media_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
            if method == "GET" and not media_type.startswith("image/"):
                raise RuntimeError("학교 서버에서 본문 이미지를 반환하지 않았습니다.")
            if media_type in {"text/html", "application/xhtml+xml"} and not response.headers.get("content-disposition"):
                raise RuntimeError("학교 서버에서 파일 대신 웹페이지를 반환했습니다.")
            length = response.headers.get("content-length", "")
            if length.isdecimal() and int(length) > MAX_FILE_BYTES:
                raise ValueError("32 MiB를 넘는 파일은 원문 공지에서 받아 주세요.")
            content = bytearray()
            async for chunk in response.aiter_raw(chunk_size=64 * 1024):
                if len(content) + len(chunk) > MAX_FILE_BYTES:
                    raise ValueError("32 MiB를 넘는 파일은 원문 공지에서 받아 주세요.")
                content.extend(chunk)
            if not content:
                raise RuntimeError("학교 서버에서 빈 파일을 반환했습니다.")
    return CampusFile(name, bytes(content), media_type, notice["url"])


def save_campus_notice_file(file: CampusFile) -> str:
    directory = user_data_dir() / "campus-files"
    ensure_private_directory(directory)
    suffix = Path(file.name).suffix
    descriptor, filename = tempfile.mkstemp(
        prefix="seoultech-", suffix=suffix if _FILE_SUFFIX.fullmatch(suffix) else "", dir=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(file.content)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise
    return str(Path(filename).resolve())
