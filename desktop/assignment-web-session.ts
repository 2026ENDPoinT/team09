import { readFile } from "node:fs/promises";
import { session, type Session } from "electron";
import { ATTACHMENT_PREVIEW_PATH, COURSE_ENTRY_PATH, COURSE_NOTICE_PATH, COURSE_PAGE_PATHS, ECLASS_ORIGIN, isCourseId, OPEN_BOARD_PATH } from "../shared/assignment-browser.js";
import type { LmsAccess } from "./lms-access.js";

const host = new URL(ECLASS_ORIGIN).hostname;
const onlinePath = "/ilos/cls/st/online/";
const learningForm = onlinePath + "online_learning_form.acl";
const learningFrame = onlinePath + "online_learning.acl";
const learningCheck = onlinePath + "online_view_check.acl";
const videoAuthCheck = "/ilos/secondauth/session_secondary_auth_check.acl";
const playerRequests = new Set([
  onlinePath + "online_view_navi.acl",
  // The official player initializes and reports its own viewing session.
  onlinePath + "online_view_hisno.acl",
  onlinePath + "online_view_at.acl",
  onlinePath + "online_view_status.acl",
  onlinePath + "online_view_time.acl",
]);
const verifiedGet = new Set([
  "/", "/ilos/index.jsp", "/ilos/index.acl", "/ilos/main/member/login_form.acl", "/ilos/main/main_form.acl",
  "/ilos/cls/st/submain/submain_form.acl", "/ilos/cls/st/activity/activity_form.acl",
  "/ilos/cls/st/report/report_view_form.acl", COURSE_NOTICE_PATH,
  "/ilos/cls/st/material/lecture_material_view_form.acl", "/ilos/cls/st/discuss/discuss_view_form.acl",
  "/ilos/cls/st/online/online_view_form.acl", "/ilos/cls/st/test/test_view_form.acl",
  ...Object.values(COURSE_PAGE_PATHS), OPEN_BOARD_PATH, "/ilos/co/efile_download.acl", "/ilos/co/file_download.acl",
  "/ilos/co/file_download_v2.acl", "//ilos/co/file_download_v2.acl",
]);
const verifiedPost = new Set([
  COURSE_ENTRY_PATH, "/ilos/lo/login.acl", "/ilos/main/member/login_notice_view.acl",
  "/ilos/main/member/notice_view_pop.acl", "/ilos/main/related_sites.acl", "/ilos/main/lectime_view_data.acl",
  // The authenticated home loads course progress and dashboard widgets separately via POST.
  "/ilos/main/main_lecture_progress_view.acl", "/ilos/co/course_unread_list.acl",
  "/ilos/main/main_todo_list.acl", "/ilos/main/main_notice_list.acl", "/ilos/main/main_lectime_list.acl",
  "/ilos/main/main_calendar_view.acl", "/ilos/main/main_calendar_data1.acl", "/ilos/main/main_calendar_data2.acl",
  "/ilos/main/main_my_notice_view_pop.acl", "/ilos/main/main_quick_menu_list.acl",
  "/ilos/co/todo_list_count.acl", "/ilos/co/notification_count.acl", "/ilos/message/received_new_message_check.acl",
  "/ilos/cls/st/notice/notice_list.acl", "/ilos/cls/st/notice/notice_view_pop.acl",
  "/ilos/cls/st/activity/activity_list.acl", "/ilos/cls/st/co/efile_list.acl", "/ilos/co/file_list3.acl",
  "/ilos/main/community/notice_list.acl", "/ilos/main/community/notice_view_pop.acl",
  "/ilos/cls/st/qna/qna_list.acl", "/ilos/cls/st/qna/qna_view_pop.acl",
  "/ilos/cls/st/board/open_material_list.acl", "/ilos/cls/st/board/open_material_view_pop.acl",
  "/ilos/main/rg/regular_view_pop.acl", "/ilos/main/rg/regular_view_plan.acl",
  "/ilos/cls/st/files/files_list.acl", "/ilos/cls/st/discuss/discuss_detail_list.acl",
  "/ilos/cls/st/discuss/discuss_detail_view_pop.acl", "/ilos/cls/st/co/cmmt_list.acl",
  "/ilos/cls/st/attend/attendance_list.acl", "/ilos/cls/st/group/group_list.acl",
  "/ilos/cls/st/eval/eval3_grade_result_chart.acl", "/ilos/cls/st/eval/eval3_result_view_detail_list.acl",
]);
const readAsset = /^(?:\/ilos\/(?:css|js|images|favicon)|\/ext\/ilos\/images).*\.(?:css|js|woff2?|ttf|png|gif|jpe?g|svg|ico|webp)$/i;
const playerAsset = /^\/ilos\/player\/(?:[\w.-]+\/)*[\w.-]+\.(?:css|js|woff2?|ttf|png|gif|jpe?g|svg|webp)$/i;
const playerMedia = /^(?:\/contents\/(?:[\w.-]+\/)+[\w.-]+\.(?:mp4|m4a|m3u8|ts|m4s)|\/ilosfiles\/contents-subtitle\/(?:[\w.-]+\/)+[\w.-]+\.vtt)$/i;
const noticeEditorImage = /^\/ilosfiles\/editor-file\/(?:[A-Za-z0-9_-]+\/)+[\p{L}\p{N}_ .()-]+\.(?:png|jpe?g|gif|webp)$/iu;
const assetTypes = new Set(["stylesheet", "script", "font", "image", "other"]);

export function browserAddress(value: string): URL | undefined {
  const input = value.trim();
  if (!input || input.length > 4096) return;
  try {
    const url = new URL(/^[a-z][a-z\d+.-]*:/i.test(input) && !/^[\w.-]+:\d+(?:\/|$)/.test(input) ? input : "https://" + input);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return;
    return url;
  } catch { return; }
}

export function allowedLmsRequest(url: URL, method: string, resourceType: string): boolean {
  if (url.origin !== ECLASS_ORIGIN || url.username || url.password) return false;
  if (url.pathname === learningForm) return method === "POST" && resourceType === "mainFrame" && !url.search;
  if (url.pathname === learningFrame || url.pathname === learningCheck) return method === "GET" && resourceType === "subFrame";
  if (playerRequests.has(url.pathname) || url.pathname === videoAuthCheck) {
    return method === "POST" && resourceType === "xhr" && !url.search;
  }
  if (playerAsset.test(url.pathname)) return method === "GET" && assetTypes.has(resourceType);
  if (playerMedia.test(url.pathname)) return method === "GET" && (resourceType === "media" || resourceType === "xhr");
  if (url.pathname === ATTACHMENT_PREVIEW_PATH) {
    const keys = [...url.searchParams.keys()];
    return method === "GET" && resourceType === "mainFrame" && keys.length === 1 &&
      keys[0] === "FPP" && Boolean(url.searchParams.get("FPP"));
  }
  if (method === "GET" && resourceType === "image" && !url.search && !url.hash && url.pathname.startsWith("/ilosfiles/editor-file/")) {
    try { return noticeEditorImage.test(decodeURIComponent(url.pathname)); }
    catch { return false; }
  }
  if (method === "GET") return verifiedGet.has(url.pathname) || (assetTypes.has(resourceType) && readAsset.test(url.pathname));
  return method === "POST" && !url.search && verifiedPost.has(url.pathname);
}

export type NavigationBlock = "restricted" | "course-required" | "course-unavailable";

type ViewCourse = {
  course: () => string | undefined;
  selectedCourse: (id: string) => void;
  blocked: (reason: NavigationBlock, url: string, method: string) => void;
  stop: () => void;
  loginSubmitted: (loginId?: string) => boolean;
};

type Pending = { viewId: number; release: () => void; timeout: ReturnType<typeof setTimeout> };

export class AssignmentWebSession {
  readonly session: Session;
  private readonly views = new Map<number, ViewCourse>();
  private readonly requests = new Map<number, Pending>();
  private readonly queued = new Map<number, number>();

  constructor(private readonly access: LmsAccess, partition = "ast-assignment-web") {
    this.session = session.fromPartition(partition);
    this.session.setPermissionRequestHandler((_contents, _permission, done) => done(false));
    this.session.setPermissionCheckHandler(() => false);
    const filter = { urls: ["*://eclass.seoultech.ac.kr/*"] };
    this.session.webRequest.onCompleted(filter, ({ id }) => this.release(id));
    this.session.webRequest.onErrorOccurred(filter, ({ id }) => this.release(id));
    this.session.webRequest.onBeforeRedirect(filter, ({ id }) => this.release(id));
    this.session.webRequest.onBeforeRequest(filter, (details, done) => {
      const url = new URL(details.url);
      const view = this.views.get(details.webContentsId ?? -1);
      const mainFrame = details.resourceType === "mainFrame";
      const block = (reason: NavigationBlock) => {
        if (mainFrame) view?.blocked(reason, details.url, details.method);
        done({ cancel: true });
      };
      if (!allowedLmsRequest(url, details.method, details.resourceType) ||
          (details.method === "POST" && details.initiatorOrigin && details.initiatorOrigin !== ECLASS_ORIGIN)) {
        block("restricted");
        return;
      }
      if (url.pathname === learningForm) {
        const body = details.uploadData?.map(({ bytes }) => bytes?.toString("utf8") ?? "").join("") ?? "";
        const [course, ...otherCourses] = new URLSearchParams(body).getAll("_KJKEY");
        if (!isCourseId(course) || otherCourses.length || course !== view?.course()) {
          block("course-required");
          return;
        }
      }
      if ((url.pathname === learningFrame || url.pathname === learningCheck || playerRequests.has(url.pathname) || playerMedia.test(url.pathname)) &&
          (!view || details.webContents?.getURL() !== ECLASS_ORIGIN + learningForm)) {
        block("restricted");
        return;
      }
      if (view && (mainFrame || details.resourceType === "subFrame") && details.method === "POST" && url.pathname === "/ilos/lo/login.acl") {
        const body = details.uploadData?.map(({ bytes }) => bytes?.toString("utf8") ?? "").join("") ?? "";
        const ids = new URLSearchParams(body).getAll("usr_id");
        if (!view.loginSubmitted(ids.length === 1 ? ids[0] : undefined)) {
          block("restricted");
          return;
        }
      }
      if (!view || (!url.pathname.startsWith("/ilos/cls/st/") && url.pathname !== ATTACHMENT_PREVIEW_PATH)) {
        done({});
        return;
      }
      const courseEntry = url.pathname === COURSE_ENTRY_PATH;
      const requestedCourse = courseEntry
        ? new URLSearchParams(details.uploadData?.map(({ bytes }) => bytes?.toString("utf8") ?? "").join("") ?? "").get("KJKEY")
        : view.course();
      if (!isCourseId(requestedCourse)) {
        block("course-required");
        return;
      }
      const viewId = details.webContentsId!;
      this.queued.set(details.id, viewId);
      void this.prepare(details.id, viewId, requestedCourse, courseEntry, mainFrame).then((ok) => {
        if (ok) done({});
        else block("course-unavailable");
      });
    });
  }

  add(viewId: number, context: ViewCourse) {
    this.views.set(viewId, context);
  }

  remove(viewId: number) {
    this.views.delete(viewId);
    for (const [id, queuedView] of this.queued) if (queuedView === viewId) this.queued.delete(id);
    for (const [id, request] of this.requests) if (request.viewId === viewId) this.release(id);
  }

  private release(id: number) {
    this.queued.delete(id);
    const request = this.requests.get(id);
    if (!request) return;
    this.requests.delete(id);
    clearTimeout(request.timeout);
    request.release();
  }

  private async prepare(id: number, viewId: number, course: string, nativeEntry: boolean, forceSelect: boolean): Promise<boolean> {
    const release = await this.access.acquire();
    const view = this.views.get(viewId);
    if (!view || this.queued.get(id) !== viewId || (!nativeEntry && view.course() !== course)) {
      this.queued.delete(id);
      release();
      return false;
    }
    try {
      if (nativeEntry) {
        this.access.browserCourse = undefined;
        view.selectedCourse(course);
      } else if (forceSelect || this.access.browserCourse !== course) {
        this.access.browserCourse = undefined;
        const response = await this.session.fetch(ECLASS_ORIGIN + COURSE_ENTRY_PATH, {
          method: "POST", credentials: "include", redirect: "error", signal: AbortSignal.timeout(12_000),
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ KJKEY: course, returnData: "json", returnURI: "/ilos/cls/st/submain/submain_form.acl", encoding: "utf-8" }).toString(),
        });
        const result = response.ok ? await response.json() as { isError?: boolean } : undefined;
        if (result?.isError !== false) { this.queued.delete(id); release(); return false; }
        this.access.browserCourse = course;
      }
      if (!this.views.has(viewId) || this.queued.get(id) !== viewId || view.course() !== course) {
        this.queued.delete(id);
        release();
        return false;
      }
      this.queued.delete(id);
      const timeout = setTimeout(() => {
        view.stop();
        this.access.browserCourse = undefined;
        this.release(id);
      }, 30_000);
      this.requests.set(id, { viewId, release, timeout });
      return true;
    } catch {
      this.queued.delete(id);
      release();
      return false;
    }
  }

  async importLogin(path: string) {
    const stored = JSON.parse(await readFile(path, "utf8")) as { cookies?: unknown };
    if (!Array.isArray(stored.cookies)) throw new Error("Missing browser cookies");
    const incoming = stored.cookies.filter((cookie) => cookie &&
      typeof cookie.domain === "string" && cookie.domain.replace(/^\./, "") === host &&
      typeof cookie.name === "string" && typeof cookie.value === "string" &&
      typeof cookie.path === "string" && cookie.path.startsWith("/") &&
      (!cookie.expires || cookie.expires < 0 || cookie.expires > Date.now() / 1000));
    if (!incoming.length) throw new Error("No current browser cookies");
    const release = await this.access.acquire();
    this.access.browserCourse = undefined;
    try {
      for (const cookie of await this.session.cookies.get({ domain: host })) {
        if (cookie.domain?.replace(/^\./, "") === host) await this.session.cookies.remove(ECLASS_ORIGIN + (cookie.path ?? "/"), cookie.name);
      }
      for (const cookie of incoming) {
        const sameSite = cookie.sameSite === "Strict" || cookie.sameSite === "strict" ? "strict"
          : cookie.sameSite === "None" || cookie.sameSite === "no_restriction" ? "no_restriction" : "lax";
        await this.session.cookies.set({
          url: ECLASS_ORIGIN + cookie.path, name: cookie.name, value: cookie.value, path: cookie.path,
          secure: true, httpOnly: Boolean(cookie.httpOnly), sameSite,
          ...(typeof cookie.expires === "number" && cookie.expires > 0 ? { expirationDate: cookie.expires } : {}),
        });
      }
    } finally { release(); }
  }

  async loginCookies() {
    return (await this.session.cookies.get({ domain: host })).filter((cookie) => cookie.domain?.replace(/^\./, "") === host)
      .map(({ name, value, path, secure, httpOnly, expirationDate, sameSite }) => ({
        name, value, domain: host, path: path ?? "/", secure, httpOnly, expires: expirationDate ?? -1, sameSite,
      }));
  }

  async clearLoginCookies() {
    const release = await this.access.acquire();
    try {
      this.access.browserCourse = undefined;
      for (const cookie of await this.loginCookies()) {
        await this.session.cookies.remove(ECLASS_ORIGIN + cookie.path, cookie.name);
      }
    } finally { release(); }
  }
}
