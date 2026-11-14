from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    professor: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Notice:
    id: str
    course_id: str
    title: str
    content: str | None = None
    created_at: datetime | None = None
    url: str | None = None


@dataclass(frozen=True)
class Assignment:
    id: str
    course_id: str
    title: str
    description: str | None = None
    due_at: datetime | None = None
    submitted: bool | None = None
    url: str | None = None
    late_due_at: datetime | None = None


@dataclass(frozen=True)
class Material:
    id: str
    course_id: str
    title: str
    created_at: datetime | None = None
    url: str | None = None


def as_jsonable(value: Any) -> dict[str, Any]:
    result = asdict(value)
    return {key: item.isoformat() if isinstance(item, datetime) else item for key, item in result.items()}


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str


@dataclass(frozen=True)
class Post:
    id: str
    kind: str
    title: str
    course_id: str | None = None
    content: str | None = None
    attachments: tuple[Attachment, ...] | None = None
    board_id: str | None = None
    created_at: datetime | None = None
    due_at: datetime | None = None
    submitted: bool | None = None


@dataclass(frozen=True)
class Syllabus:
    course_id: str
    title: str
    text: str
    tables: list[list[list[str]]]


@dataclass(frozen=True)
class AttachmentText:
    id: str
    name: str
    total_pages: int
    start_page: int
    pages: list[str]
    next_page: int | None
    truncated: bool
