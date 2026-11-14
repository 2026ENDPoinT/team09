import { assignmentDeadline, assignmentDueTime, compareAssignmentDeadlines, isAssignmentVisible, type AssignmentVisibility } from "../shared/assignment-visibility.js";
import { assignmentUrl, isAssignmentId, isCourseId } from "../shared/assignment-browser.js";
import type { ChatSource } from "../shared/chat.js";
import { shiftTimetableDate, timetableWeekStart } from "../shared/timetable-week.js";

type Fields = Record<string, unknown>;
const listTools = new Set(["list_assignments", "get_pending_assignments", "get_upcoming_deadlines"]);
const deadlineAt = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
});
const deadlineDate = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric" });
const seoulDate = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short" });
const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
const dayMs = 86_400_000;
export const ASSIGNMENT_SUMMARY_TOOL = "get_assignment_summary";
const assignmentOutsideRange = "과제 표시 설정의 범위를 벗어난 과제예요. 과제 표시 설정에서 지난 과제와 표시 기간을 바꿀 수 있어요.";

function record(value: unknown): value is Fields {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function filterAssignmentTool(name: string, args: Fields, value: unknown, settings: AssignmentVisibility, now: Date,
  openAssignment = false): unknown {
  const filter = (items: unknown[], upcoming = false) => items.filter(record)
    .map((item) => item.deadline_checked === false ? { ...item, due_at: null, late_due_at: null } : item)
    .filter((item) => isAssignmentVisible(item.due_at, settings, now) &&
      (!upcoming || (assignmentDueTime(item.due_at)?.getTime() ?? -Infinity) >= now.getTime()))
    .sort((a, b) => compareAssignmentDeadlines(a.due_at, b.due_at, now)).map((item) => {
      const due = assignmentDueTime(item.due_at);
      return { ...item, deadline_label: due ? assignmentDeadline(due, now).text : "마감일 확인 필요" };
    });
  if (listTools.has(name)) {
    if (Array.isArray(value)) return filter(value, name === "get_upcoming_deadlines");
    if (record(value) && Array.isArray(value.result)) return { ...value, result: filter(value.result, name === "get_upcoming_deadlines") };
  }
  if (name === ASSIGNMENT_SUMMARY_TOOL && record(value) && Array.isArray(value.assignments)) {
    return { ...value, assignments: filter(value.assignments) };
  }
  if (name === "get_course_briefing" && record(value)) {
    return { ...value,
      ...(Array.isArray(value.pending_assignments) && { pending_assignments: filter(value.pending_assignments) }),
      ...(Array.isArray(value.completed_assignments) && { completed_assignments: filter(value.completed_assignments) }),
    };
  }
  if (name === "get_post" && args.kind === "assignment" && record(value) && (value.status == null || value.status === "ok")) {
    if (!openAssignment && !isAssignmentVisible(value.due_at, settings, now)) return { status: "error", message: assignmentOutsideRange };
    const due = assignmentDueTime(value.due_at);
    return { ...value, deadline_label: due ? assignmentDeadline(due, now).text : "마감일 확인 필요" };
  }
  return value;
}

export type PendingAssignmentPeriod = "all" | "this-week" | "next-week" | "today" | "tomorrow" | { days: number };

const reply = "(?:가|는|를|이|은|을)?(?:목록(?:을|만)?)?(?:좀|최신으로|다시)?(?:뭐(?:가|가있어(?:요)?|가있나요|있어(?:요)?|있나요|야|예요)?|몇개(?:야|예요)?|언제(?:야|예요)?|있어(?:요)?|있나요|알려(?:줘(?:요)?|주세요)|보여(?:줘(?:요)?|주세요)|정리(?:해줘(?:요)?|해주세요)|확인(?:해줘(?:요)?|해주세요)|알수있어(?:요)?)?";
const dueWords = "(?:마감(?:일|기한|일정)?|제출기한)";
const pending = `(?:남은|미제출(?:한)?|(?:아직)?(?:안한|안낸|안제출한|제출안한))과제(?:의?${dueWords})?`;
const deadline = `(?:(?:마감(?:되는|하는|할)?|제출(?:해야하는|해야할|할)|내야(?:하는|할))과제|과제의?${dueWords})`;
const periodQuestion = new RegExp(`^(?:${pending}|${deadline})${reply}$`);
const upcomingQuestion = new RegExp(`^(?:다가오는|곧)${deadline}${reply}$`);
const allPendingQuestion = new RegExp(`^(?:(?:나|내|저|제|전체)?${pending}|(?:내|제|전체)과제의?${dueWords})${reply}$`);
const calendarPeriods = { 이번주: "this-week", 다음주: "next-week", 오늘: "today", 내일: "tomorrow" } as const;

export function isAssignmentOverviewQuestion(question: string): boolean {
  if (!/과제|실습/.test(question) || /첨부|PDF|파일|본문|요구\s*사항|풀이|풀어|제출\s*(?:방법|형식)|작성\s*방법|열어|띄워|이동/i.test(question)) return false;
  return /할\s*만\s*한|할\s*수\s*있는|(?:과제|실습)(?:가|는|이|은)?\s*(?:좀\s*)?(?:뭐(?:가)?\s*(?:있|야|예요)|몇\s*(?:개|건)|있(?:어|냐|나|을까|는지))/.test(question) ||
    /(?:과제|실습)(?:를|을)?\s*(?:좀\s*)?(?:확인|조회)\s*해\s*(?:봐|줘|주세요)/.test(question);
}

export function isAssignmentStatusQuestion(question: string): boolean {
  return /과제/.test(question) && !/본문|첨부|파일|조건|요구\s*사항|풀이|제출\s*(?:방법|형식)|작성\s*방법/.test(question) &&
    /남은|미제출|안\s*(?:한|낸)|제출\s*안|마감|제출\s*기한|다가오는/.test(question);
}

export function pendingAssignmentPeriod(question: string): PendingAssignmentPeriod | undefined {
  const text = question.replace(/\s/g, "").replace(/[.!?？！。]+$/, "")
    .replace(/^(?:최신(?:으로)?|다시|새로)(?:확인해서|조회해서|확인하고|조회하고)?/, "");
  const calendar = text.match(/^(이번주|다음주|오늘|내일)(?:안에|에)?/);
  if (calendar && periodQuestion.test(text.slice(calendar[0].length))) {
    return calendarPeriods[calendar[1] as keyof typeof calendarPeriods];
  }
  const rolling = text.match(/^(?:앞으로)?([1-9]\d{0,2})일(?:안에|내(?:에)?|이내(?:에)?|동안)?/);
  if (rolling && periodQuestion.test(text.slice(rolling[0].length))) return { days: Number(rolling[1]) };
  if (upcomingQuestion.test(text)) return { days: 7 };
  if (allPendingQuestion.test(text) ||
      /^(?:나|내|저|제가)?뭐(?:가)?(?:안한|안낸|안제출한)과제(?:가)?(?:있어(?:요)?|있나요)?$/.test(text)) return "all";
}

function periodBounds(period: Exclude<PendingAssignmentPeriod, "all">, now: Date) {
  if (typeof period !== "string") {
    const start = now.getTime();
    return { label: `앞으로 ${period.days}일`, start, end: start + period.days * dayMs + 1 };
  }
  const today = seoulDate.format(now);
  const week = period === "this-week" || period === "next-week";
  const base = week ? timetableWeekStart(today) : today;
  const length = week ? 7 : 1;
  const first = shiftTimetableDate(base, period === "next-week" || period === "tomorrow" ? length : 0);
  const midnight = (day: string) => Date.parse(`${day}T00:00:00+09:00`);
  const label = { "this-week": "이번 주", "next-week": "다음 주", today: "오늘", tomorrow: "내일" }[period];
  return { label, start: midnight(first), end: midnight(shiftTimetableDate(first, length)) };
}

function markdownLabel(value: string) {
  return value.replace(/\s+/g, " ").trim().replace(/[\\`*_[\]~]/g, "\\$&");
}

type PendingAssignment = {
  id: unknown;
  course_id: unknown;
  course_name: unknown;
  title: string;
  dueAt: string | null;
  lateDueAt: string | null;
  submitted: false | null;
};

export function pendingAssignmentSummary(
  value: unknown, now: Date, settings: AssignmentVisibility, period: PendingAssignmentPeriod,
): { text: string; sources: ChatSource[] } | undefined {
  if (record(value) && value.status != null && value.status !== "ok") return;
  const rows = record(value) ? value.assignments ?? value.result : value;
  if (!Array.isArray(rows)) return;
  const partial = record(value) && Array.isArray(value.unavailable) && value.unavailable.length > 0;
  const checkedAt = record(value) && typeof value.as_of === "string" ? new Date(value.as_of) : undefined;
  const notes = [
    partial && "일부 강좌의 목록이나 과제 상세를 확인하지 못했어요.",
    checkedAt && !Number.isNaN(checkedAt.getTime()) && `e-Class 목록 확인 · ${deadlineAt.format(checkedAt)}`,
  ].filter(Boolean);
  const items = rows.filter(record).flatMap((item): PendingAssignment[] => {
    if (typeof item.title !== "string" || !item.title.trim() || item.submitted === true) return [];
    const dueAt = item.deadline_checked !== false && typeof item.due_at === "string" ? item.due_at : null;
    const lateDueAt = item.deadline_checked !== false && typeof item.late_due_at === "string" ? item.late_due_at : null;
    if (!isAssignmentVisible(dueAt, settings, now)) return [];
    return [{ id: item.id, course_id: item.course_id, course_name: item.course_name, title: item.title,
      dueAt, lateDueAt, submitted: item.submitted === false ? false : null }];
  }).sort((a, b) => compareAssignmentDeadlines(a.dueAt, b.dueAt, now));
  const bounds = period === "all" ? undefined : periodBounds(period, now);
  const unconfirmed = bounds ? items.filter(({ dueAt }) => !assignmentDueTime(dueAt)) : [];
  const inPeriod = bounds ? items.filter(({ dueAt }) => {
    const due = assignmentDueTime(dueAt)?.getTime();
    return due != null && due >= bounds.start && due < bounds.end;
  }) : items;
  const sources: ChatSource[] = [];
  const formatDeadline = (value: string | null) => {
    const due = assignmentDueTime(value);
    return due ? (dateOnly.test(value ?? "") ? deadlineDate : deadlineAt).format(due) : undefined;
  };
  const line = (item: PendingAssignment) => {
    const title = item.title.replace(/\s+/g, " ").trim();
    const due = assignmentDueTime(item.dueAt);
    const badge = due ? assignmentDeadline(due, now).text : "마감일 확인 필요";
    let name = markdownLabel(title);
    if (isAssignmentId(item.id) && isCourseId(item.course_id)) {
      const url = assignmentUrl(item.id);
      sources.push({ title, url, assignment: { assignmentId: item.id, courseId: item.course_id } });
      name = `[${name}](${url})`;
    }
    const when = formatDeadline(item.dueAt);
    const lateWhen = formatDeadline(item.lateDueAt);
    const details = [typeof item.course_name === "string" && markdownLabel(item.course_name), when && `${when} 마감`,
      lateWhen && `지각 제출 ${lateWhen}까지`,
      item.submitted == null && "제출 여부 확인 필요"].filter(Boolean).join(" · ");
    return `- **${badge}** ${name}${details ? `\n  ${details}` : ""}`;
  };
  const unknown = inPeriod.filter(({ submitted }) => submitted == null).length;
  const heading = !unknown ? `미제출 과제 ${inPeriod.length}개`
    : unknown === inPeriod.length ? `제출 여부 확인이 필요한 과제 ${unknown}개`
    : `미제출 ${inPeriod.length - unknown}개 · 제출 확인 필요 ${unknown}개`;
  const scope = bounds ? bounds.label + " " : "";
  const empty = partial || unconfirmed.length ? "확인된 미제출 과제가 없어요." : "표시할 미제출 과제가 없어요.";
  const emptyText = bounds ? `${bounds.label}에는 ${empty}` : empty;
  const sections = [
    inPeriod.length ? `### ${scope}${heading}\n\n${inPeriod.map(line).join("\n")}` : emptyText,
    unconfirmed.length && `### 마감일 확인 필요\n\n${unconfirmed.map(line).join("\n")}`,
    ...notes,
  ].filter(Boolean);
  return { text: sections.join("\n\n"), sources };
}
