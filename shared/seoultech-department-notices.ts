import sourceData from "../src/seoultech_lms/department_notice_sources.json" with { type: "json" };
import { departments } from "./seoultech-departments.js";

export type DepartmentNoticeBoard = `college:${string}` | `department:${string}`;

export type DepartmentNoticeSource = {
  id: DepartmentNoticeBoard;
  label: string;
  listUrl: string;
  parser: "standard" | "archidesign" | "card";
  boardIds: readonly string[];
};

const configuredSources: Readonly<Partial<Record<DepartmentNoticeBoard, {
  url: string;
  parser: string;
  board_ids: string[];
}>>> = sourceData;

function noticeSource(id: DepartmentNoticeBoard, name: string): DepartmentNoticeSource | undefined {
  const source = configuredSources[id];
  if (!source) return;
  const { parser, url } = source;
  if (parser !== "standard" && parser !== "archidesign" && parser !== "card") return;
  return { id, label: `${name} 공지사항`, listUrl: url, parser, boardIds: source.board_ids };
}

export const collegeNoticeSources: Readonly<Partial<Record<string, DepartmentNoticeSource>>> = {
  공과대학: noticeSource("college:engineering", "공과대학"),
  정보통신대학: noticeSource("college:information", "정통대"),
  에너지바이오대학: noticeSource("college:energy-bio", "에너지바이오대학"),
  조형대학: noticeSource("college:art-design", "조형대학"),
  인문사회대학: noticeSource("college:humanities", "인문사회대학"),
  기술경영융합대학: noticeSource("college:business", "기술경영융합대학"),
  미래융합대학: noticeSource("college:future", "미래융합대학"),
  창의융합대학: noticeSource("college:convergence", "창의융합대학"),
  교양대학: noticeSource("college:liberal", "교양대학"),
  국제대학: noticeSource("college:international", "국제대학"),
};

export const departmentNoticeSourceCatalog: Readonly<Partial<Record<string, DepartmentNoticeSource>>> =
  Object.fromEntries(departments.flatMap(({ id, name }) => {
    const source = noticeSource(`department:${id}`, name);
    return source ? [[id, source]] : [];
  }));

const sourcesById = new Map(
  [...Object.values(collegeNoticeSources), ...Object.values(departmentNoticeSourceCatalog)]
    .flatMap((source) => source ? [[source.id, source] as const] : []),
);

export function departmentNoticeSource(board: unknown): DepartmentNoticeSource | undefined {
  if (typeof board !== "string") return;
  return sourcesById.get(board as DepartmentNoticeBoard);
}

export function departmentNoticeSources(departmentId: string | null | undefined): {
  college?: DepartmentNoticeSource;
  department?: DepartmentNoticeSource;
} {
  const selected = departments.find(({ id }) => id === departmentId);
  if (!selected) return {};
  return { college: collegeNoticeSources[selected.college], department: departmentNoticeSourceCatalog[selected.id] };
}
