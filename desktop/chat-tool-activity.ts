const LABELS: Record<string, string> = {
  list_courses: "수강 과목",
  get_course_overview: "수강 현황",
  get_course_timetable: "수업 시간표",
  get_course_briefing: "과제와 최근 수업 공지",
  list_notices: "수업 공지",
  search_notices: "수업 공지 검색 결과",
  list_assignments: "과제",
  get_assignment_summary: "최신 과제 목록",
  get_pending_assignments: "남은 과제",
  get_upcoming_deadlines: "다가오는 과제 마감",
  list_posts: "강의실 게시물",
  get_post: "게시물 본문",
  list_discussion_opinions: "토론 의견",
  get_discussion_opinion: "토론 의견 본문",
  get_syllabus: "강의계획서",
  list_course_files: "강의실 파일",
  read_attachment: "첨부파일 텍스트",
  list_campus_notices: "학교 공지",
  get_campus_notice: "학교 공지 본문",
  read_campus_notice_file: "공지 첨부파일 텍스트",
  get_campus_briefing: "최근 학교 공지",
  get_dorm_menu: "기숙사 식단",
};

const LIST_TOOLS = new Set([
  "list_courses", "list_notices", "search_notices", "list_assignments", "get_pending_assignments",
  "get_upcoming_deadlines", "list_posts", "list_discussion_opinions", "list_course_files",
]);

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function shortText(value: unknown): string {
  if (typeof value !== "string") return "";
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length > 85 ? clean.slice(0, 85) + "…" : clean;
}

function hasText(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

export function toolProgress(name: string): string {
  if (name === "read_attachment" || name === "read_campus_notice_file") return "첨부파일을 읽고 있어요.";
  return `${LABELS[name]} 확인 중이에요.`;
}

export function toolResult(name: string, raw: unknown, truncated: boolean): string | undefined {
  // FastMCP wraps list responses in structuredContent.result.
  const value = object(raw) && Array.isArray(raw.result) ? raw.result : raw;
  const label = LABELS[name];
  const confirmed = (subject: string, partial = false) => `${subject} ${partial || truncated ? "일부 확인" : "확인"}`;

  if (name === "read_attachment" && object(value) && (value.status === "error" || value.status === "login_required")) {
    const message = shortText(value.message);
    return message ? `PDF 읽기 실패 · ${message}` : "PDF 읽기 실패";
  }

  if (LIST_TOOLS.has(name) && Array.isArray(value) &&
      value.every((item) => object(item) && (hasText(item.title) || hasText(item.name)))) {
    const title = value.length === 1 ? shortText(value[0].title ?? value[0].name) : "";
    return confirmed(title || `${label} ${value.length}건`);
  }
  if (!object(value) || (value.status != null && value.status !== "ok")) return;
  if (name === "get_course_overview" && object(value.overview)) return confirmed(label);
  if (name === "get_course_timetable" && Array.isArray(value.entries)) return confirmed(`${label} ${value.entries.length}건`);
  if (name === "get_dorm_menu" && Array.isArray(value.days) && value.days.length) {
    const dorm = shortText(value.dorm_name);
    return confirmed(dorm ? `${dorm} 식단` : label);
  }
  if ((name === "list_campus_notices" || name === "get_campus_briefing") && Array.isArray(value.notices)) {
    return confirmed(`${label} ${value.notices.length}건`, Array.isArray(value.unavailable) && value.unavailable.length > 0);
  }
  if (name === "get_course_briefing" && Array.isArray(value.recent_notices)) {
    return confirmed(label, Array.isArray(value.unavailable) && value.unavailable.length > 0);
  }
  if (name === "get_assignment_summary" && Array.isArray(value.assignments)) {
    return confirmed(`남은 과제 ${value.assignments.length}건`, Array.isArray(value.unavailable) && value.unavailable.length > 0);
  }
  if (name === "read_attachment" || name === "read_campus_notice_file") {
    if (!Array.isArray(value.pages)) return;
    if (!value.pages.some(hasText)) return name === "read_attachment" ? "PDF에서 추출할 수 있는 텍스트 없음" : undefined;
    return confirmed(label, value.truncated === true || value.next_page != null);
  }
  if (name === "get_post" && value.kind === "assignment" && Array.isArray(value.attachments)) {
    return confirmed(`${shortText(value.title) || "과제"} 첨부 ${value.attachments.length}건`);
  }
  if (hasText(value.content) || (name === "get_syllabus" && hasText(value.text))) {
    const title = shortText(value.title);
    return confirmed(title ? `${title} 본문` : label);
  }
}
