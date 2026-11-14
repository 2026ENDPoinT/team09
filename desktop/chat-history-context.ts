import { isAssignmentId, isCourseId, type AssignmentDetails } from "../shared/assignment-browser.js";

type Fields = Record<string, unknown>;
type Message = { role: "user" | "assistant"; content: string };
export type DocumentReference = { name: string; title: string; args: Fields; nextPage?: number };
type SolutionOffer = Pick<AssignmentDetails, "courseId" | "assignmentId">;
export type HistoryTurn = { items: Message[]; references?: DocumentReference[]; solutionOffer?: SolutionOffer; workspaceClarification?: string };

const readKeys: Record<string, string[]> = {
  read_attachment: ["kind", "course_id", "post_id", "board_id", "attachment_id", "page"],
  read_campus_notice_file: ["board", "board_id", "notice_id", "file_id"],
  get_post: ["kind", "course_id", "post_id", "board_id", "page"],
  get_campus_notice: ["board", "board_id", "notice_id"],
  get_syllabus: ["course_id"],
};

function object(value: unknown): value is Fields {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function documentReference(name: string, args: Fields, value: unknown): DocumentReference | undefined {
  if (!Object.hasOwn(readKeys, name) || !object(value) || (value.status != null && value.status !== "ok")) return;
  const label = [value.filename, value.name, value.title, value.course_name].find((field) => typeof field === "string" && field.trim());
  if (typeof label !== "string") return;
  const keys = readKeys[name];
  const locator = Object.fromEntries(keys.flatMap((key) => {
    const field = args[key];
    const valid = key === "course_id" ? isCourseId(field)
      : typeof field === "string" && /^[\w-]{1,120}$/.test(field) ||
        key === "page" && Number.isSafeInteger(field) && Number(field) > 0;
    return valid ? [[key, field]] : [];
  }));
  const nextPage = value.next_page;
  return { name, title: label.replace(/\s+/g, " ").trim().slice(0, 160), args: locator,
    ...(typeof nextPage === "number" && Number.isSafeInteger(nextPage) && nextPage > 0 ? { nextPage } : {}) };
}

export function historyTurn(question: string, answer: string, usedTool: boolean, references: DocumentReference[] = [],
  solutionOffer?: SolutionOffer): HistoryTurn {
  return { items: [{ role: "user", content: question }, {
    role: "assistant", content: usedTool ? "이전 요청에 자료를 조회해 답변했어요." : answer.slice(0, 4000),
  }], ...(references.length ? { references: references.slice(-8) } : {}), ...(solutionOffer ? { solutionOffer } : {}) };
}

export function trimHistory(history: unknown[]): HistoryTurn[] {
  const turns = history.slice(-8).flatMap((turn): HistoryTurn[] => {
    if (!object(turn) || !Array.isArray(turn.items)) return [];
    const items = turn.items.filter(object);
    const question = items.find(({ role }) => role === "user")?.content;
    if (typeof question !== "string") return [];
    const legacyToolTurn = items.some(({ type }) => type === "function_call" || type === "function_call_output" || type === "reasoning");
    const answer = items.find(({ role }) => role === "assistant")?.content;
    const references = Array.isArray(turn.references) ? turn.references.filter(object).flatMap((ref) => {
      if (typeof ref.name !== "string" || !object(ref.args) || typeof ref.title !== "string") return [];
      return documentReference(ref.name, ref.args, { title: ref.title, next_page: ref.nextPage }) ?? [];
    }) : [];
    const offer = turn.solutionOffer;
    const solutionOffer = object(offer) && isCourseId(offer.courseId) && isAssignmentId(offer.assignmentId)
      ? { courseId: offer.courseId, assignmentId: offer.assignmentId } : undefined;
    if (legacyToolTurn || typeof answer === "string") {
      const kept = historyTurn(question, typeof answer === "string" ? answer : "", legacyToolTurn, references, solutionOffer);
      if (typeof turn.workspaceClarification === "string") kept.workspaceClarification = turn.workspaceClarification.slice(0, 8_000);
      return [kept];
    }
    return [{ items: [{ role: "user", content: question }] }];
  });
  while (turns.length > 1 && JSON.stringify(turns).length > 24_000) turns.shift();
  return turns;
}
