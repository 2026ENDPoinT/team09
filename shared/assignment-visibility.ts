import type { CourseBriefing } from "./lms.js";

export type AssignmentVisibility = { includeOverdue: boolean; overdueDays: number };

export const defaultAssignmentVisibility: AssignmentVisibility = { includeOverdue: false, overdueDays: 7 };

export function parseAssignmentVisibility(value: unknown): AssignmentVisibility | null {
  if (!value || typeof value !== "object") return null;
  const { includeOverdue, overdueDays } = value as Partial<AssignmentVisibility>;
  if (typeof includeOverdue !== "boolean" || typeof overdueDays !== "number" ||
      !Number.isSafeInteger(overdueDays) || overdueDays < 1) return null;
  return { includeOverdue, overdueDays };
}

const seoulDate = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short" });
const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
const explicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export function asKoreanTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const input = dateOnly.test(value) ? value + "T00:00:00+09:00"
    : explicitZone.test(value) ? value
    : value.replace(" ", "T") + "+09:00";
  const date = new Date(input);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function assignmentDueTime(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  return asKoreanTime(dateOnly.test(value) ? `${value}T23:59:59.999+09:00` : value);
}

export function assignmentDeadline(due: Date, now: Date) {
  const days = (Date.parse(seoulDate.format(due)) - Date.parse(seoulDate.format(now))) / 86_400_000;
  const overdue = due < now;
  const text = days < 0 ? `D+${-days}` : days > 0 ? `D-${days}` : overdue ? "오늘 마감 지남" : "D-day";
  return { days, overdue, text };
}

export function isAssignmentVisible(dueAt: unknown, settings: AssignmentVisibility, now: Date): boolean {
  const due = assignmentDueTime(dueAt);
  if (!due || due >= now) return true;
  return settings.includeOverdue && -assignmentDeadline(due, now).days <= settings.overdueDays;
}

export function compareAssignmentDeadlines(a: unknown, b: unknown, now: Date): number {
  const left = assignmentDueTime(a);
  const right = assignmentDueTime(b);
  if (!left || !right) return Number(!left) - Number(!right);
  if (left < now && right < now) return right.getTime() - left.getTime();
  return Number(left < now) - Number(right < now) || left.getTime() - right.getTime();
}

export function visibleCourseBriefing(briefing: CourseBriefing | null, settings: AssignmentVisibility, now: Date) {
  if (!briefing) return null;
  const visible = (item: { due_at: string | null }) => isAssignmentVisible(item.due_at, settings, now);
  return { ...briefing, pending_assignments: briefing.pending_assignments.filter(visible),
    completed_assignments: briefing.completed_assignments.filter(visible) };
}
