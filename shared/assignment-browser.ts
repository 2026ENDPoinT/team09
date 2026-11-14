export const ECLASS_ORIGIN = "https://eclass.seoultech.ac.kr";
export const ACTIVITY_PATH = "/ilos/cls/st/activity/activity_form.acl";
export const REPORT_PATH = "/ilos/cls/st/report/report_view_form.acl";
export const COURSE_ENTRY_PATH = "/ilos/cls/st/co/eclass_room2.acl";
export const ECLASS_MAIN_PATH = "/ilos/main/main_form.acl";
export const COURSE_NOTICE_PATH = "/ilos/cls/st/notice/notice_list_form.acl";
export const ATTACHMENT_PREVIEW_PATH = "/ilos/co/efile_preview_check_form.acl";
export const OPEN_BOARD_PATH = "/ilos/cls/st/board/open_material_list_form.acl";
export const COURSE_PAGE_PATHS = {
  attendance: "/ilos/cls/st/attend/attendance_list_form.acl",
  groups: "/ilos/cls/st/group/group_list_form.acl",
  grades: "/ilos/cls/st/eval/eval3_result_view_form.acl",
  qna: "/ilos/cls/st/qna/qna_list_form.acl",
  files: "/ilos/cls/st/files/files_list_form.acl",
} as const;

export type CourseBrowserPage =
  | { kind: keyof typeof COURSE_PAGE_PATHS }
  | { kind: "open_board"; boardId: string }
  | { kind: "activity"; activityId: string; url: string };

export type AssignmentTarget = { assignmentId: string; courseId?: string };
export const ASSIGNMENT_FONT_SIZES = [13, 15, 17, 19, 22] as const;
export type AssignmentFontSize = (typeof ASSIGNMENT_FONT_SIZES)[number];
export const DEFAULT_ASSIGNMENT_FONT_SIZE: AssignmentFontSize = 15;

export function isAssignmentFontSize(value: unknown): value is AssignmentFontSize {
  return ASSIGNMENT_FONT_SIZES.some((size) => value === size);
}

export type AssignmentDetails = {
  courseId: string;
  assignmentId: string;
  courseName: string;
  title: string;
  dueAt: string | null;
  lateDueAt?: string | null;
  publishedAt?: string | null;
  submissionMethod?: string | null;
  submissionFormat?: string | null;
  points?: string | null;
  scoreVisibility?: string | null;
  submitted?: boolean | null;
  description: string | null;
  attachments: { id: string; name: string }[] | null;
};

export const CURRENT_ASSIGNMENT_GUIDE_FORMAT = "study-guide-v2";
export const ENCRYPTED_ASSIGNMENT_PDF_MESSAGE = "암호화된 PDF라 열 수 없어요.";

export type AssignmentAnalysisResult =
  | { status: "ready"; markdown: string; format?: "study-guide" | typeof CURRENT_ASSIGNMENT_GUIDE_FORMAT; omittedFiles?: string[]; encryptedFiles?: string[]; saved?: boolean }
  | { status: "unavailable" | "error"; message: string }
  | { status: "cancelled" };

export type AssignmentPageState = {
  openedFromNotice?: boolean;
  openedFromCourse?: boolean;
  url: string;
  initialLoad: boolean;
  loading: boolean;
  back: boolean;
  forward: boolean;
  error: string | null;
  canRetryNavigation: boolean;
  assignment: AssignmentDetails | null;
  assignmentState: "loading" | "ready" | "unavailable" | "login" | "none";
  assignmentMessage: string | null;
  analysis?:
    | (Extract<AssignmentAnalysisResult, { status: "ready" }> & { upgrade?: { status: "loading"; markdown?: string } | { status: "error"; message: string } })
    | Extract<AssignmentAnalysisResult, { status: "unavailable" | "error" }>
    | { status: "loading"; markdown?: string };
  attachmentPreview?: { id: string; name: string; inline: boolean; isPdf: boolean };
};

export type AssignmentAttachmentOpenResult =
  | { status: "opened" | "cancelled" }
  | { status: "error"; message: string };

export type AssignmentBrowserTab = { id: number; title: string; pdf?: { url: string; name: string } };
export type AssignmentBrowserState = AssignmentPageState & {
  assignmentFontSize: AssignmentFontSize;
  activeTabId: number;
  tabs: AssignmentBrowserTab[];
};

export type AssignmentBrowserBridge = {
  getAssignmentBrowser: () => Promise<AssignmentBrowserState>;
  onAssignmentBrowser: (listener: (state: AssignmentBrowserState) => void) => () => void;
  navigateAssignmentBrowser: (url: string) => Promise<boolean>;
  commandAssignmentBrowser: (command: "back" | "forward" | "reload" | "login" | "resume" | "retry") => Promise<void>;
  changeBrowserTab: (command: "select" | "close", id: number) => Promise<void>;
  openAssignmentAttachment: (tabId: number, courseId: string, assignmentId: string, attachmentId: string) => Promise<AssignmentAttachmentOpenResult>;
  closeAssignmentAttachment: (tabId: number, previewId: string) => Promise<void>;
  downloadAssignmentAttachment: (tabId: number, previewId: string) => Promise<boolean>;
  retryAssignmentAnalysis: (tabId: number, courseId: string, assignmentId: string) => Promise<void>;
  layoutAssignmentBrowser: (bounds: { x: number; y: number; width: number; height: number }) => void;
};

export function isCourseId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9가-힣_-]{1,80}$/.test(value);
}

export function isAssignmentId(value: unknown): value is string {
  return typeof value === "string" && /^[0-9]{1,20}$/.test(value);
}

const courseActivityModes = new Set(["report", "lecture_material", "lecture_weeks", "discuss", "test", "survey"]);

export function parseCourseBrowserPage(input: unknown): CourseBrowserPage | undefined {
  if (!input || typeof input !== "object") return;
  const { kind, boardId, activityId, url } = input as Record<string, unknown>;
  if (typeof kind === "string" && Object.hasOwn(COURSE_PAGE_PATHS, kind)) {
    return { kind: kind as keyof typeof COURSE_PAGE_PATHS };
  }
  if (kind === "open_board" && typeof boardId === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(boardId)) return { kind, boardId };
  if (kind !== "activity" || typeof activityId !== "string" || !/^[A-Za-z0-9-]{1,80}$/.test(activityId) ||
      typeof url !== "string" || url.length > 4096) return;
  try {
    const target = new URL(url, ECLASS_ORIGIN);
    if (target.origin !== ECLASS_ORIGIN || target.username || target.password || target.pathname !== ACTIVITY_PATH) return;
    const [mode, ...otherModes] = target.searchParams.getAll("m");
    const [id, ...otherIds] = target.searchParams.getAll("n");
    if (!courseActivityModes.has(mode) || otherModes.length || id !== activityId || otherIds.length) return;
    return { kind, activityId, url: target.href };
  } catch { return; }
}

export function assignmentTarget(value: unknown): AssignmentTarget | undefined {
  if (!value || typeof value !== "object") return;
  const { assignmentId, courseId } = value as Partial<AssignmentTarget>;
  if (!isAssignmentId(assignmentId) || (courseId !== undefined && !isCourseId(courseId))) return;
  return { assignmentId, courseId };
}

export function assignmentUrl(assignmentId: string): string {
  return `${ECLASS_ORIGIN}${ACTIVITY_PATH}?m=report&n=${encodeURIComponent(assignmentId)}&mf=report1`;
}

export function isCourseNoticeId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value);
}

export function courseNoticeUrl(noticeId: string): URL {
  const url = new URL(COURSE_NOTICE_PATH, ECLASS_ORIGIN);
  url.hash = `notice=${noticeId}`;
  return url;
}

export function courseNoticeIdFromUrl(url: URL): string | undefined {
  if (url.origin !== ECLASS_ORIGIN || url.pathname !== COURSE_NOTICE_PATH || !url.hash.startsWith("#notice=")) return;
  const id = url.hash.slice("#notice=".length);
  if (isCourseNoticeId(id) && url.href === courseNoticeUrl(id).href) return id;
}

export function assignmentIdFromUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    if (url.origin !== ECLASS_ORIGIN || url.username || url.password) return;
    const id = url.pathname === ACTIVITY_PATH && url.searchParams.get("m") === "report" ? url.searchParams.get("n")
      : url.pathname === REPORT_PATH ? url.searchParams.get("RT_SEQ") : null;
    if (isAssignmentId(id)) return id;
  } catch { /* Other sites and invalid addresses have no assignment context. */ }
}
