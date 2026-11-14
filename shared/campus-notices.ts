import type { CampusNoticeTag } from "./campus-notice-tags.js";
import {
  collegeNoticeSources, departmentNoticeSource, departmentNoticeSourceCatalog,
  type DepartmentNoticeBoard, type DepartmentNoticeSource,
} from "./seoultech-department-notices.js";

export const campusNoticeBoards = {
  notice: "대학공지사항",
  matters: "학사공지",
  janghak: "장학공지",
  graduate: "대학원공지",
  job: "취업공지",
} as const;

export type SchoolCampusNoticeBoard = keyof typeof campusNoticeBoards;
export type CampusNoticeBoard = SchoolCampusNoticeBoard | DepartmentNoticeBoard;
export type CampusNoticeScope = "school" | "department";

export function isSchoolCampusNoticeBoard(value: unknown): value is SchoolCampusNoticeBoard {
  return typeof value === "string" && Object.hasOwn(campusNoticeBoards, value);
}

export function campusNoticeBoardLabel(board: CampusNoticeBoard): string {
  return isSchoolCampusNoticeBoard(board) ? campusNoticeBoards[board] : departmentNoticeSource(board)?.label ?? "학과 공지";
}

export type CampusNotice = {
  board: CampusNoticeBoard;
  board_id: string;
  id: string;
  title: string;
  department: string | null;
  published_at: string | null;
  pinned: boolean;
  has_attachments: boolean;
  url: string;
  preview?: string | null;
};

export type CampusNoticePage = {
  board: CampusNoticeBoard;
  notices: CampusNotice[];
  next_page: number | null;
};

export type CampusNoticeDetail = Omit<CampusNotice, "pinned"> & {
  pinned: boolean | null;
  content: string;
  attachments: { id: string; name: string }[];
  images: { id: string; url: string; alt: string }[];
  links?: { url: string; text: string }[];
};

export type CampusNoticeError = { status: "error"; message: string };

export type CampusNoticeIndexEntry = { detail: CampusNoticeDetail; tags: CampusNoticeTag[] };

export type CampusNoticeIndexSnapshot = {
  revision: number;
  notices: CampusNotice[];
  entries: Record<string, CampusNoticeIndexEntry>;
  listedBoards: CampusNoticeBoard[];
  pages: Partial<Record<CampusNoticeBoard, { lastPage: number; nextPage: number | null; listedAt: number }>>;
  loading: boolean;
  partial: boolean;
};

export function campusNoticeKey({ board, board_id, id }: Pick<CampusNotice, "board" | "board_id" | "id">): string {
  return `${board}:${board_id}:${id}`;
}

export type CampusNoticeBridge = {
  listCampusNotices: (board: CampusNoticeBoard, startPage: number, refresh?: boolean) => Promise<CampusNoticePage | CampusNoticeError>;
  getCampusNotice: (board: CampusNoticeBoard, boardId: string, noticeId: string, background?: boolean) => Promise<CampusNoticeDetail | CampusNoticeError>;
  getCampusNoticeIndex: (afterRevision?: number, scope?: CampusNoticeScope) => Promise<CampusNoticeIndexSnapshot | null>;
  syncCampusNoticeIndex: (force?: boolean, scope?: CampusNoticeScope) => Promise<void>;
  openCampusNoticeLink: (url: string, notice?: Pick<CampusNotice, "board" | "board_id" | "id">) => Promise<boolean>;
};

export function noticeWebLink(value: unknown): URL | undefined {
  if (typeof value !== "string" || value.length > 4096 || !/^https?:\/\//i.test(value) || /[\\\x00-\x20]/.test(value)) return;
  try {
    const url = new URL(value);
    if (!url.username && !url.password && !url.port) return url;
  } catch { return; }
}

const schoolOrigin = "https://www.seoultech.ac.kr";
export function isCampusNoticeBoardPage(url: URL): boolean {
  return url.origin === schoolOrigin && isSchoolCampusNoticeBoard(/^\/service\/info\/([a-z]+)\/?$/.exec(url.pathname)?.[1]);
}
const departmentPaths = new Map<string, DepartmentNoticeSource>();
const departmentOrigins = new Set<string>();
for (const source of [...Object.values(collegeNoticeSources), ...Object.values(departmentNoticeSourceCatalog)]) {
  if (!source) continue;
  const url = new URL(source.listUrl);
  departmentPaths.set(url.origin + url.pathname, source);
  departmentOrigins.add(url.origin);
}

function isArticleQuery(query: URLSearchParams): boolean {
  return query.size === 3 && query.get("do") === "commonview" &&
    /^\d{1,20}$/.test(query.get("bnum") ?? "") && /^\d{1,20}$/.test(query.get("bidx") ?? "");
}

export function campusNoticeLink(value: unknown): URL | null {
  if (typeof value !== "string") return null;

  try {
    const url = new URL(value);
    if (url.username || url.password || url.hash) return null;

    if (isCampusNoticeBoardPage(url)) {
      return isArticleQuery(url.searchParams) ? url : null;
    }
    const source = departmentPaths.get(url.origin + url.pathname.replace(/\/$/, ""));
    if (source?.parser === "archidesign") return url.searchParams.size === 2 && url.searchParams.get("bgu") === "view" &&
      /^\d{1,20}$/.test(url.searchParams.get("idx") ?? "") ? url : null;
    if (source) return isArticleQuery(url.searchParams) && source.boardIds.includes(url.searchParams.get("bnum")!) ? url : null;

    const path = decodeURIComponent(url.pathname);
    const isImagePath = url.origin === schoolOrigin ? path.startsWith("/storage/www/ckfinder/images/") :
      departmentOrigins.has(url.origin) && (/^\/storage\/[a-z\d_-]+\/(?:ckfinder\/images|bbs\/\d+)\//i.test(path) ||
        url.hostname === "archidesign.seoultech.ac.kr" && path.startsWith("/data/bbsData/"));
    if (url.search || !isImagePath || /[%?#;\\\u0000-\u001f]/.test(path) ||
        /%2f/i.test(url.pathname) || path.slice(1).split("/").some((part) => !part || part === "." || part === "..") ||
        !/\.(?:jpe?g|png|gif|webp|bmp|tiff?|avif)$/i.test(path)) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}
