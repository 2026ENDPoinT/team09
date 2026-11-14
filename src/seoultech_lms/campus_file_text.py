from __future__ import annotations

import re
from io import BytesIO
from pathlib import PurePath
from typing import Any
from xml.parsers import expat
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile
from zlib import error as ZlibError

from .client import _extract_pdf
from .models import Attachment

_MAX_FILE_BYTES = 12 * 1024 * 1024
_MAX_XML_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 4096
_CHUNK_CHARS = 8_000
_MAX_TEXT_CHUNKS = 3
_TEXT_FORMATS = frozenset({"txt", "csv", "tsv", "md"})
_WORD_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
_HWPX_NAMESPACES = ("http://www.hancom.co.kr/hwpml/2011/paragraph",)
_HWPX_SECTION = re.compile(r"Contents/section([0-9]{1,6})\.xml")


def extract_file_text(
    filename: str, content: bytes, *, start_page: int = 1, max_pages: int = 10,
) -> dict[str, Any]:
    """Read bounded text from a previously downloaded file using 1-based pagination."""
    if start_page < 1 or not 1 <= max_pages <= 25:
        raise ValueError("start_page는 1 이상, max_pages는 1~25여야 합니다.")
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("12 MiB가 넘는 첨부에서는 텍스트를 추출할 수 없습니다.")

    file_format = PurePath(filename).suffix.removeprefix(".").lower()
    metadata = {
        "filename": filename, "format": file_format, "size_bytes": len(content),
        "start_page": start_page,
    }
    if file_format == "pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("PDF 원본을 확인할 수 없습니다.")
        try:
            pdf = _extract_pdf(Attachment("", filename), content, start_page, max_pages)
        except (KeyError, OSError, OverflowError, TypeError, NotImplementedError, ZlibError) as exc:
            raise ValueError("이 PDF에서 텍스트를 읽을 수 없습니다.") from exc
        return {
            **metadata, "status": "ok", "unit": "page", "total_pages": pdf.total_pages,
            "pages": pdf.pages, "next_page": pdf.next_page, "truncated": pdf.truncated,
        }
    if file_format in _TEXT_FORMATS:
        text = _decode_text(content)
    elif file_format in ("docx", "hwpx"):
        text = _read_office_body(file_format, content)
    else:
        return {
            **metadata, "status": "unsupported", "unit": None, "total_pages": None,
            "pages": [], "next_page": None, "truncated": False,
        }

    total_pages = max(1, (len(text) + _CHUNK_CHARS - 1) // _CHUNK_CHARS)
    if start_page > total_pages:
        raise ValueError(f"이 첨부의 텍스트는 {total_pages}개 구간입니다.")
    last_page = min(total_pages, start_page - 1 + min(max_pages, _MAX_TEXT_CHUNKS))
    pages = [text[index * _CHUNK_CHARS:(index + 1) * _CHUNK_CHARS] for index in range(start_page - 1, last_page)]
    return {
        **metadata, "status": "ok", "unit": "chunk", "total_pages": total_pages, "pages": pages,
        "next_page": last_page + 1 if last_page < total_pages else None, "truncated": False,
    }


def _decode_text(content: bytes) -> str:
    try:
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = content.decode("utf-16")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp949")
    except UnicodeDecodeError as exc:
        raise ValueError("첨부의 텍스트 인코딩을 확인할 수 없습니다.") from exc
    if "\x00" in text:
        raise ValueError("첨부에서 일반 텍스트를 확인할 수 없습니다.")
    return text


def _read_office_body(file_format: str, content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ARCHIVE_MEMBERS:
                raise ValueError("압축 문서에 너무 많은 항목이 있습니다.")
            if file_format == "docx":
                sections = [entry for entry in entries if entry.filename == "word/document.xml"]
                if len(sections) != 1:
                    raise ValueError("Word 문서 본문을 확인할 수 없습니다.")
                namespaces = _WORD_NAMESPACES
            else:
                numbered = [
                    (int(match[1]), entry)
                    for entry in entries if (match := _HWPX_SECTION.fullmatch(entry.filename))
                ]
                if not numbered or len({index for index, _ in numbered}) != len(numbered):
                    raise ValueError("한글 문서 본문을 확인할 수 없습니다.")
                sections = [entry for _, entry in sorted(numbered, key=lambda pair: pair[0])]
                namespaces = _HWPX_NAMESPACES

            if sum(section.file_size for section in sections) > _MAX_XML_BYTES:
                raise ValueError("압축 해제한 문서 본문이 8 MiB를 넘습니다.")
            parts = []
            remaining = _MAX_XML_BYTES
            for section in sections:
                if section.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
                    raise ValueError("문서 본문에 지원하지 않는 압축 방식이 사용되었습니다.")
                with archive.open(section) as member:
                    data = member.read(remaining + 1)
                if len(data) > remaining:
                    raise ValueError("압축 해제한 문서 본문이 8 MiB를 넘습니다.")
                remaining -= len(data)
                parts.append(_read_xml_text(data, namespaces))
            return "\n".join(part for part in parts if part)
    except (BadZipFile, EOFError, LookupError, OSError, RuntimeError, expat.ExpatError, ZlibError) as exc:
        raise ValueError("손상되었거나 보호된 문서에서 텍스트를 읽을 수 없습니다.") from exc


def _read_xml_text(data: bytes, namespaces: tuple[str, ...]) -> str:
    parser = expat.ParserCreate(namespace_separator="|")
    parser.buffer_text = True
    text_elements = {f"{namespace}|t" for namespace in namespaces}
    paragraphs = {f"{namespace}|p" for namespace in namespaces}
    breaks = {
        f"{namespace}|{tag}": replacement
        for namespace in namespaces
        for tag, replacement in (("tab", "\t"), ("br", "\n"), ("cr", "\n"), ("lineBreak", "\n"))
    }
    parts: list[str] = []
    text_depth = 0

    def start_element(name: str, _attrs: dict[str, str]) -> None:
        nonlocal text_depth
        if name in text_elements:
            text_depth += 1
        elif name in breaks:
            parts.append(breaks[name])

    def end_element(name: str) -> None:
        nonlocal text_depth
        if name in text_elements:
            text_depth -= 1
        elif name in paragraphs:
            parts.append("\n")

    def characters(value: str) -> None:
        if text_depth:
            parts.append(value)

    def reject_doctype(*_args: object) -> None:
        raise ValueError("DTD가 포함된 문서 본문은 읽을 수 없습니다.")

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.Parse(data, True)
    return "".join(parts).strip()
