import { ipcMain, shell, type IpcMainInvokeEvent, type WebContents } from "electron";
import { campusNoticeLink, isSchoolCampusNoticeBoard, noticeWebLink } from "../shared/campus-notices.js";
import { departmentNoticeSources, type DepartmentNoticeBoard } from "../shared/seoultech-department-notices.js";
import { COURSE_NOTICE_QUERY_LIMIT } from "../shared/course-classroom.js";
import type { AstraLoginStatus } from "../shared/lms.js";
import { courseNoticeIdFromUrl, courseNoticeUrl, ECLASS_ORIGIN, isCourseId, isCourseNoticeId, parseCourseBrowserPage, type CourseBrowserPage } from "../shared/assignment-browser.js";
import { createAstraLogin } from "./astra-login.js";
import type { ScreenData, ScreenRequest } from "./screen-data.js";
import { readStudentPreferences, saveStudentPreferences } from "./student-preferences.js";
import { readAssignmentSettings, saveAssignmentSettings } from "./assignment-settings.js";
import { readCourseNoticeSettings, saveCourseNoticeSettings } from "./course-notice-settings.js";
import { readLoginSettings, saveLoginSettings } from "./login-settings.js";

function isNoticeId(value: unknown): value is string {
  return typeof value === "string" && /^\d{1,20}$/.test(value);
}

function isPage(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

export function registerScreenActions(
  screenData: ScreenData,
  requestTool: ScreenRequest,
  verifySender: (event: IpcMainInvokeEvent) => void,
  notifyLogin?: (status: AstraLoginStatus) => void,
  activeDirectory?: () => string | undefined,
  openCourseNotice?: (courseId: string, url: URL, page?: number) => Promise<boolean>,
  openCoursePage?: (courseId: string, page: CourseBrowserPage) => Promise<boolean>,
  openBrowser?: (url: URL) => boolean,
) {
  let loginSender: WebContents | undefined;
  const login = createAstraLogin(screenData, requestTool, (status) => {
    if (notifyLogin) notifyLogin(status);
    else if (loginSender && !loginSender.isDestroyed()) loginSender.send("ast:astra-login-status", status);
  }, !!activeDirectory);
  function checkLoginSender(event: IpcMainInvokeEvent) {
    verifySender(event);
    loginSender = event.sender;
  }
  async function currentStudentPreferences() {
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory?.();
    if (revision === undefined || (activeDirectory && !directory)) return null;
    const preferences = await readStudentPreferences(directory);
    return revision === screenData.confirmedSessionRevision ? preferences : null;
  }
  async function currentDepartmentBoards(): Promise<DepartmentNoticeBoard[]> {
    const preferences = await currentStudentPreferences();
    const { college, department } = departmentNoticeSources(preferences?.departmentId);
    return [college?.id, department?.id].filter((id): id is DepartmentNoticeBoard => id !== undefined);
  }
  ipcMain.handle("ast:start-astra-login", (event) => {
    checkLoginSender(event);
    return login.start();
  });
  ipcMain.handle("ast:astra-login-status", (event) => {
    checkLoginSender(event);
    return login.snapshot();
  });
  ipcMain.handle("ast:login-settings", (event) => {
    verifySender(event);
    return readLoginSettings();
  });
  ipcMain.handle("ast:save-login-settings", (event, input: unknown) => {
    verifySender(event);
    return saveLoginSettings(input);
  });
  ipcMain.handle("ast:student-profile", (event, sessionRevision: unknown, refresh: unknown) => {
    verifySender(event);
    return screenData.readStudentProfile(sessionRevision, refresh === true);
  });
  ipcMain.handle("ast:student-preferences", async (event) => {
    verifySender(event);
    return currentStudentPreferences();
  });
  ipcMain.handle("ast:save-student-preferences", async (event, input: unknown, expected: unknown) => {
    verifySender(event);
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory?.();
    if (revision === undefined || expected !== revision || (activeDirectory && !directory)) return null;
    const saved = await saveStudentPreferences(input, directory);
    if (revision !== screenData.confirmedSessionRevision) return null;
    if (saved) screenData.clearDepartmentNoticeSelection();
    return saved;
  });
  ipcMain.handle("ast:assignment-settings", async (event) => {
    verifySender(event);
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory ? activeDirectory() ?? null : undefined;
    const settings = await readAssignmentSettings(directory);
    if (revision !== screenData.confirmedSessionRevision) return readAssignmentSettings(null);
    return settings;
  });
  ipcMain.handle("ast:save-assignment-settings", async (event, input: unknown, expected: unknown) => {
    verifySender(event);
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory?.();
    if (revision === undefined || expected !== revision || (activeDirectory && !directory)) {
      throw new Error("ASTRA에 다시 로그인한 뒤 설정을 저장해 주세요.");
    }
    const settings = await saveAssignmentSettings(input, directory);
    if (revision !== screenData.confirmedSessionRevision) throw new Error("로그인 상태가 바뀌었어요.");
    return settings;
  });
  ipcMain.handle("ast:course-notice-settings", async (event, expected: unknown) => {
    verifySender(event);
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory?.();
    if (revision === undefined || expected !== revision || (activeDirectory && !directory)) {
      return { status: "login_required", message: "로그인 상태를 확인해 주세요." };
    }
    const settings = await readCourseNoticeSettings(directory);
    if (revision !== screenData.confirmedSessionRevision) return { status: "login_required", message: "로그인 상태가 바뀌었어요." };
    return settings;
  });
  ipcMain.handle("ast:save-course-notice-settings", async (event, input: unknown, expected: unknown) => {
    verifySender(event);
    const revision = screenData.confirmedSessionRevision;
    const directory = activeDirectory?.();
    if (revision === undefined || expected !== revision || (activeDirectory && !directory)) {
      throw new Error("ASTRA에 다시 로그인한 뒤 설정을 저장해 주세요.");
    }
    const settings = await saveCourseNoticeSettings(input, directory);
    if (revision !== screenData.confirmedSessionRevision) throw new Error("로그인 상태가 바뀌었어요.");
    return settings;
  });
  ipcMain.handle("ast:open-login", (event) => {
    checkLoginSender(event);
    return login.openLegacy();
  });
  ipcMain.handle("ast:confirm-login", async (event) => {
    checkLoginSender(event);
    const { status, message } = await login.confirmLegacy();
    return { status, message };
  });
  ipcMain.handle("ast:course-overview", (event, refresh: unknown) => {
    verifySender(event);
    return screenData.overview({ force: refresh === true });
  });
  ipcMain.handle("ast:prefetch-status", (event) => {
    verifySender(event);
    return screenData.status;
  });
  ipcMain.handle("ast:home-snapshot", (event) => {
    verifySender(event);
    return screenData.homeSnapshot();
  });
  ipcMain.handle("ast:home-refresh", (event) => {
    verifySender(event);
    return screenData.refreshHome();
  });

  ipcMain.handle("ast:course-timetable", (event, onDate: unknown, refresh: unknown, background: unknown) => {
    verifySender(event);
    if (onDate !== undefined && (typeof onDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(onDate))) {
      return { status: "error", message: "올바른 날짜를 선택해 주세요." };
    }
    return screenData.timetable(onDate as string | undefined, { force: refresh === true, background: background === true });
  });

  ipcMain.handle("ast:course-briefing", (event, refresh: unknown) => {
    verifySender(event);
    return screenData.courseBriefing({ force: refresh === true });
  });

  ipcMain.handle("ast:course-classroom", (event, courseId: unknown, revision: unknown, refresh: unknown) => {
    verifySender(event);
    if (!isCourseId(courseId) || typeof revision !== "number") {
      return { status: "error", message: "수강 과목을 다시 선택해 주세요." };
    }
    return screenData.courseClassroom(courseId, revision, refresh === true);
  });

  ipcMain.handle("ast:course-classroom-info", (event, courseId: unknown, revision: unknown, refresh: unknown) => {
    verifySender(event);
    if (!isCourseId(courseId) || typeof revision !== "number") {
      return { status: "error", message: "수강 과목을 다시 선택해 주세요." };
    }
    return screenData.courseClassroomInfo(courseId, revision, refresh === true);
  });

  ipcMain.handle("ast:course-recent-notices", (event, courseId: unknown, revision: unknown, refresh: unknown) => {
    verifySender(event);
    if (!isCourseId(courseId) || typeof revision !== "number") {
      return { status: "error", message: "수강 과목을 다시 선택해 주세요." };
    }
    return screenData.courseRecentNotices(courseId, revision, refresh === true);
  });

  ipcMain.handle("ast:course-notice-page", (event, courseId: unknown, page: unknown, revision: unknown, query: unknown, refresh: unknown) => {
    verifySender(event);
    if (!isCourseId(courseId) || !isPage(page) || typeof revision !== "number" ||
        (query !== undefined && (typeof query !== "string" || query.length > COURSE_NOTICE_QUERY_LIMIT))) {
      return { status: "error", message: "공지 페이지나 검색어를 확인해 주세요." };
    }
    return screenData.courseNoticePage(courseId, page, revision, query?.trim() ?? "", refresh === true);
  });

  ipcMain.handle("ast:course-notice-index", (event, revision: unknown, afterVersion: unknown) => {
    verifySender(event);
    if (typeof revision !== "number") return { status: "error", message: "로그인 상태를 확인해 주세요." };
    return screenData.courseNoticeIndex(revision, typeof afterVersion === "number" && Number.isSafeInteger(afterVersion) ? afterVersion : undefined);
  });

  ipcMain.handle("ast:refresh-course-notice-index", (event, revision: unknown) => {
    verifySender(event);
    return typeof revision === "number" && screenData.refreshCourseNoticeIndex(revision);
  });

  ipcMain.handle("ast:open-course-page", async (event, courseId: unknown, input: unknown, revision: unknown) => {
    verifySender(event);
    const page = parseCourseBrowserPage(input);
    if (!openCoursePage || !page || !isCourseId(courseId) || typeof revision !== "number" ||
        revision !== screenData.confirmedSessionRevision) return false;
    try {
      if (page.kind === "open_board" || page.kind === "activity") {
        const course = await screenData.courseClassroom(courseId, revision, false);
        if ("status" in course || revision !== screenData.confirmedSessionRevision) return false;
        const belongsToCourse = page.kind === "open_board" ? course.open_boards.some((board) => board.id === page.boardId)
          : course.weeks.some(({ activities }) => activities.some((item) =>
            item.id === page.activityId && item.url && new URL(item.url).href === page.url));
        if (!belongsToCourse) return false;
      }
      return await openCoursePage(courseId, page);
    } catch {
      return false;
    }
  });

  ipcMain.handle("ast:get-course-notice", (event, courseId: unknown, noticeId: unknown, refresh: unknown, page: unknown) => {
    verifySender(event);
    if (!isCourseId(courseId) || !isCourseNoticeId(noticeId) ||
        (page !== undefined && !isPage(page))) {
      return { status: "error", message: "수업 공지 번호를 확인해 주세요." };
    }
    if (screenData.confirmedSessionRevision === undefined) {
      return { status: "login_required", message: "수업 공지 원문을 보려면 e-Class에 로그인해 주세요." };
    }
    return screenData.courseNotice(courseId, noticeId, { force: refresh === true }, page);
  });

  async function openCourseNoticeOriginal(courseId: unknown, noticeId: unknown, page?: unknown) {
    if (!openCourseNotice || screenData.confirmedSessionRevision === undefined || !isCourseId(courseId) || !isCourseNoticeId(noticeId) ||
        (page !== undefined && !isPage(page))) return false;
    try {
      return await openCourseNotice(courseId, courseNoticeUrl(noticeId), page);
    } catch {
      return false;
    }
  }

  ipcMain.handle("ast:open-course-notice-original", (event, courseId: unknown, noticeId: unknown, page: unknown) => {
    verifySender(event);
    return openCourseNoticeOriginal(courseId, noticeId, page);
  });

  ipcMain.handle("ast:open-course-notice-link", async (event, courseId: unknown, value: unknown) => {
    verifySender(event);
    const url = noticeWebLink(value);
    if (!isCourseId(courseId) || !url || screenData.confirmedSessionRevision === undefined) return false;
    try {
      if (url.hostname === new URL(ECLASS_ORIGIN).hostname) {
        const noticeId = courseNoticeIdFromUrl(url);
        if (noticeId) return openCourseNoticeOriginal(courseId, noticeId);
        return await openCourseNotice?.(courseId, url) ?? false;
      }
      return openBrowser?.(url) ?? false;
    } catch {
      return false;
    }
  });

  ipcMain.handle("ast:campus-briefing", (event, refresh: unknown) => {
    verifySender(event);
    return screenData.campusBriefing({ force: refresh === true });
  });

  ipcMain.handle("ast:dorm-menu", (event, dorm: unknown, period: unknown, refresh: unknown) => {
    verifySender(event);
    if ((dorm !== "kb" && dorm !== "seonglim" && dorm !== "surim") || (period !== "today" && period !== "week")) {
      return { status: "error", message: "학사와 식단 기간을 다시 선택해 주세요." };
    }
    return screenData.dorm(dorm, period, { force: refresh === true });
  });

  ipcMain.handle("ast:open-dorm-menu-source", async (event) => {
    verifySender(event);
    try {
      await shell.openExternal("https://housing.seoultech.ac.kr/livng/dining");
      return true;
    } catch {
      return false;
    }
  });

  ipcMain.handle("ast:list-campus-notices", async (event, board: unknown, startPage: unknown, refresh: unknown) => {
    verifySender(event);
    if (!isPage(startPage)) {
      throw new Error("공지 게시판이나 페이지 번호가 올바르지 않아요.");
    }
    const selected = isSchoolCampusNoticeBoard(board) ? board : (await currentDepartmentBoards()).find((id) => id === board);
    if (!selected) throw new Error("공지 게시판이 올바르지 않아요.");
    return screenData.campusList(selected, startPage, { force: refresh === true });
  });

  ipcMain.handle("ast:get-campus-notice", async (event, board: unknown, boardId: unknown, noticeId: unknown, background: unknown) => {
    verifySender(event);
    if (!isNoticeId(boardId) || !isNoticeId(noticeId)) {
      throw new Error("공지 게시판이나 글 번호가 올바르지 않아요.");
    }
    const selected = isSchoolCampusNoticeBoard(board) ? board : (await currentDepartmentBoards()).find((id) => id === board);
    if (!selected) throw new Error("공지 게시판이 올바르지 않아요.");
    return screenData.campusDetail(selected, boardId, noticeId, { background: background === true });
  });

  ipcMain.handle("ast:campus-notice-index", async (event, afterRevision: unknown, scope: unknown) => {
    verifySender(event);
    const boards = scope === "department" ? await currentDepartmentBoards() : undefined;
    return screenData.campusNoticeIndex(typeof afterRevision === "number" && Number.isSafeInteger(afterRevision) ? afterRevision : undefined, boards);
  });

  ipcMain.handle("ast:sync-campus-notice-index", async (event, force: unknown, scope: unknown) => {
    verifySender(event);
    const boards = scope === "department" ? await currentDepartmentBoards() : undefined;
    screenData.syncCampusNoticeIndex(force === true, boards);
  });

  ipcMain.handle("ast:open-campus-notice-link", async (event, value: unknown, notice: unknown) => {
    verifySender(event);
    try {
      const original = campusNoticeLink(value);
      if (original) return openBrowser?.(original) ?? false;
      const url = noticeWebLink(value);
      if (!url || !openBrowser || !notice || typeof notice !== "object") return false;
      const { board, board_id, id } = notice as Record<string, unknown>;
      if (!isNoticeId(board_id) || !isNoticeId(id)) return false;
      const revision = screenData.confirmedSessionRevision;
      const selected = isSchoolCampusNoticeBoard(board) ? board : (await currentDepartmentBoards()).find((item) => item === board);
      if (!selected) return false;
      const detail = await screenData.campusDetail(selected, board_id, id);
      if ("status" in detail || (!isSchoolCampusNoticeBoard(selected) && revision !== screenData.confirmedSessionRevision) ||
          !detail.links?.some((link) => noticeWebLink(link.url)?.href === url.href)) return false;
      return openBrowser(url);
    } catch {
      return false;
    }
  });
  return login;
}
