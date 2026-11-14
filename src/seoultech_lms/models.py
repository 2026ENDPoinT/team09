from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class CourseMeeting:
    """A weekday and the period label displayed on the course card."""

    weekday: str
    periods: str


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    professor: str | None = None
    url: str | None = None
    category: Literal["regular", "non_regular"] = "regular"
    schedule_text: str | None = None
    meetings: tuple[CourseMeeting, ...] = ()
    course_code: str | None = None


@dataclass(frozen=True)
class CourseRoster:
    courses: list[Course]
    non_regular_available: bool
    display_name: str | None = None


@dataclass(frozen=True)
class StudentProfile:
    display_name: str
    department: str | None
    year: int | None
    phone: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class CourseAttendance:
    present: int
    late: int
    absent: int
    early_leave: int
    excused: int
    unconfirmed: int


@dataclass(frozen=True)
class LearningActivity:
    completed: int
    total: int


@dataclass(frozen=True)
class CourseStats:
    course: Course
    counts: dict[str, int | None]
    total_posts: int | None
    attendance: CourseAttendance | None = None
    learning_activity: LearningActivity | None = None


@dataclass(frozen=True)
class CourseOverview:
    regular: int
    non_regular: int | None
    courses: list[CourseStats]


@dataclass(frozen=True)
class Notice:
    id: str
    course_id: str
    title: str
    content: str | None = None
    created_at: datetime | None = None
    url: str | None = None


@dataclass(frozen=True)
class AssignmentMetadata:
    submission_method: str | None = None
    submission_format: str | None = None
    published_at: str | None = None
    points: str | None = None
    score_visibility: str | None = None


@dataclass(frozen=True)
class Assignment:
    id: str
    course_id: str
    title: str
    description: str | None = None
    due_at: datetime | None = None
    submitted: bool | None = None
    url: str | None = None
    submitted_at: datetime | None = None
    late_due_at: datetime | None = None
    metadata: AssignmentMetadata | None = None


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
    late_due_at: datetime | None = None
    assignment_metadata: AssignmentMetadata | None = None


@dataclass(frozen=True)
class DiscussionComment:
    id: str
    content: str
    author: str | None = None
    created_at: str | None = None
    parent_id: str | None = None


@dataclass(frozen=True)
class DiscussionOpinion:
    id: str
    course_id: str
    topic_id: str
    title: str
    preview: str | None = None
    author: str | None = None
    created_at: str | None = None
    comment_count: int | None = None
    content: str | None = None
    comments: list[DiscussionComment] | None = None


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
