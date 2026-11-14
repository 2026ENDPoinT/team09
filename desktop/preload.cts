import { contextBridge, ipcRenderer } from "electron";
import type { AstraLoginStatus, LmsBridge, PrefetchStatus } from "../shared/lms.js";
import type { ChatBridge, ChatEvent } from "../shared/chat.js";
import type { AssignmentBrowserBridge, AssignmentBrowserState } from "../shared/assignment-browser.js";
import type { WorkspaceActionEvent } from "../shared/chat-workspace.js";

const chat: ChatBridge = {
  getChatConfig: () => ipcRenderer.invoke("ast:chat-config"),
  getChatTranscript: () => ipcRenderer.invoke("ast:chat-transcript"),
  saveChatConfig: (input) => ipcRenderer.invoke("ast:save-chat-config", input),
  sendChat: (id, text) => ipcRenderer.invoke("ast:chat-send", id, text),
  cancelChat: (id) => ipcRenderer.invoke("ast:chat-cancel", id),
  resetChat: () => ipcRenderer.invoke("ast:chat-reset"),
  onChatEvent: (listener) => {
    const receive = (_event: Electron.IpcRendererEvent, payload: ChatEvent) => listener(payload);
    ipcRenderer.on("ast:chat-event", receive);
    return () => { ipcRenderer.removeListener("ast:chat-event", receive); };
  },
  openChatSource: (url) => ipcRenderer.invoke("ast:chat-source", url),
};

const bridge: LmsBridge = {
  ...chat,
  openLiveLecture: () => ipcRenderer.invoke("ast:open-live-lecture"),
  getLectureHistory: (revision) => ipcRenderer.invoke("ast:live-lecture-history", revision),
  closeLectureRecords: (revision) => ipcRenderer.invoke("ast:close-lecture-records", revision),
  openLectureRecord: (revision, id) => ipcRenderer.invoke("ast:open-lecture-record", revision, id),
  onLectureHistoryChanged: (listener) => {
    const receive = () => listener();
    ipcRenderer.on("ast:lecture-history-changed", receive);
    return () => ipcRenderer.removeListener("ast:lecture-history-changed", receive);
  },
  onChatWorkspaceAction: (listener) => {
    const receive = (_event: Electron.IpcRendererEvent, payload: WorkspaceActionEvent) => listener(payload);
    ipcRenderer.on("ast:chat-workspace-action", receive);
    return () => { ipcRenderer.removeListener("ast:chat-workspace-action", receive); };
  },
  completeChatWorkspaceAction: (id, status) => ipcRenderer.invoke("ast:chat-workspace-result", id, status),
  getFocusLibrary: (revision) => ipcRenderer.invoke("ast:focus-library", revision),
  getStudyFonts: (revision) => ipcRenderer.invoke("ast:study-fonts", revision),
  saveStudyFonts: (revision, input) => ipcRenderer.invoke("ast:save-study-fonts", revision, input),
  editFocusLibrary: (revision, edit) => ipcRenderer.invoke("ast:focus-library-edit", revision, edit),
  importFocusPdf: (revision, parentId) => ipcRenderer.invoke("ast:focus-pdf-import", revision, parentId),
  openFocusPdf: (revision, id) => ipcRenderer.invoke("ast:focus-pdf-open", revision, id),
  setChatComposing: (value) => ipcRenderer.invoke("ast:chat-composing", value),
  openAssignment: (target) => ipcRenderer.invoke("ast:assignment-open", target),
  prepareAssignment: (target, request, revision) => ipcRenderer.invoke("ast:assignment-prepare", target, request, revision),
  showPreparedAssignment: (request) => ipcRenderer.invoke("ast:assignment-show-prepared", request),
  cancelPreparedAssignment: (request) => ipcRenderer.invoke("ast:assignment-cancel-prepared", request),
  openLogin: () => ipcRenderer.invoke("ast:open-login"),
  confirmLogin: () => ipcRenderer.invoke("ast:confirm-login"),
  startAstraLogin: () => ipcRenderer.invoke("ast:start-astra-login"),
  getAstraLoginStatus: () => ipcRenderer.invoke("ast:astra-login-status"),
  getLoginSettings: () => ipcRenderer.invoke("ast:login-settings"),
  saveLoginSettings: (input) => ipcRenderer.invoke("ast:save-login-settings", input),
  getStudentProfile: (sessionRevision, refresh) => ipcRenderer.invoke("ast:student-profile", sessionRevision, refresh),
  getStudentPreferences: () => ipcRenderer.invoke("ast:student-preferences"),
  saveStudentPreferences: (input, sessionRevision) => ipcRenderer.invoke("ast:save-student-preferences", input, sessionRevision),
  getAssignmentSettings: () => ipcRenderer.invoke("ast:assignment-settings"),
  saveAssignmentSettings: (input, sessionRevision) => ipcRenderer.invoke("ast:save-assignment-settings", input, sessionRevision),
  getAssignmentFontSize: (sessionRevision) => ipcRenderer.invoke("ast:assignment-font-size", sessionRevision),
  saveAssignmentFontSize: (size, sessionRevision) => ipcRenderer.invoke("ast:save-assignment-font-size", size, sessionRevision),
  getCourseNoticeSettings: (sessionRevision) => ipcRenderer.invoke("ast:course-notice-settings", sessionRevision),
  saveCourseNoticeSettings: (input, sessionRevision) => ipcRenderer.invoke("ast:save-course-notice-settings", input, sessionRevision),
  onAstraLoginStatus: (listener) => {
    const receive = (_event: Electron.IpcRendererEvent, status: AstraLoginStatus) => listener(status);
    ipcRenderer.on("ast:astra-login-status", receive);
    return () => { ipcRenderer.removeListener("ast:astra-login-status", receive); };
  },
  getPrefetchStatus: () => ipcRenderer.invoke("ast:prefetch-status"),
  getHomeSnapshot: () => ipcRenderer.invoke("ast:home-snapshot"),
  refreshHome: () => ipcRenderer.invoke("ast:home-refresh"),
  onPrefetchStatus: (listener) => {
    const receive = (_event: Electron.IpcRendererEvent, status: PrefetchStatus) => listener(status);
    ipcRenderer.on("ast:prefetch-status", receive);
    return () => { ipcRenderer.removeListener("ast:prefetch-status", receive); };
  },
  getCourseOverview: (refresh) => ipcRenderer.invoke("ast:course-overview", refresh),
  getCourseTimetable: (onDate, refresh, background) => ipcRenderer.invoke("ast:course-timetable", onDate, refresh, background),
  getCourseBriefing: (refresh) => ipcRenderer.invoke("ast:course-briefing", refresh),
  getCourseClassroom: (courseId, revision, refresh) => ipcRenderer.invoke("ast:course-classroom", courseId, revision, refresh),
  getCourseClassroomInfo: (courseId, revision, refresh) => ipcRenderer.invoke("ast:course-classroom-info", courseId, revision, refresh),
  getCourseRecentNotices: (courseId, revision, refresh) => ipcRenderer.invoke("ast:course-recent-notices", courseId, revision, refresh),
  getCourseNoticePage: (courseId, page, revision, query, refresh) => ipcRenderer.invoke("ast:course-notice-page", courseId, page, revision, query, refresh),
  getCourseNoticeIndex: (revision, afterVersion) => ipcRenderer.invoke("ast:course-notice-index", revision, afterVersion),
  refreshCourseNoticeIndex: (revision) => ipcRenderer.invoke("ast:refresh-course-notice-index", revision),
  openCoursePage: (courseId, page, revision) => ipcRenderer.invoke("ast:open-course-page", courseId, page, revision),
  getCourseNotice: (courseId, noticeId, refresh, page) => ipcRenderer.invoke("ast:get-course-notice", courseId, noticeId, refresh, page),
  openCourseNoticeOriginal: (courseId, noticeId, page) => ipcRenderer.invoke("ast:open-course-notice-original", courseId, noticeId, page),
  openCourseNoticeLink: (courseId, url) => ipcRenderer.invoke("ast:open-course-notice-link", courseId, url),
  getCampusBriefing: (refresh) => ipcRenderer.invoke("ast:campus-briefing", refresh),
  getDormMenu: (dorm, period, refresh) => ipcRenderer.invoke("ast:dorm-menu", dorm, period, refresh),
  openDormMenuSource: () => ipcRenderer.invoke("ast:open-dorm-menu-source"),
  listCampusNotices: (board, startPage, refresh) => ipcRenderer.invoke("ast:list-campus-notices", board, startPage, refresh),
  getCampusNotice: (board, boardId, noticeId, background) => ipcRenderer.invoke("ast:get-campus-notice", board, boardId, noticeId, background),
  getCampusNoticeIndex: (afterRevision, scope) => ipcRenderer.invoke("ast:campus-notice-index", afterRevision, scope),
  syncCampusNoticeIndex: (force, scope) => ipcRenderer.invoke("ast:sync-campus-notice-index", force, scope),
  openCampusNoticeLink: (url, notice) => ipcRenderer.invoke("ast:open-campus-notice-link", url, notice),
};

if (location.pathname.endsWith("/assignment-browser.html")) {
  const browser: AssignmentBrowserBridge = {
    getAssignmentBrowser: () => ipcRenderer.invoke("ast:assignment-browser-get"),
    navigateAssignmentBrowser: (url) => ipcRenderer.invoke("ast:assignment-browser-navigate", url),
    commandAssignmentBrowser: (command) => ipcRenderer.invoke("ast:assignment-browser-command", command),
    changeBrowserTab: (command, id) => ipcRenderer.invoke("ast:assignment-browser-tab", command, id),
    openAssignmentAttachment: (tabId, courseId, assignmentId, attachmentId) =>
      ipcRenderer.invoke("ast:assignment-attachment-open", tabId, courseId, assignmentId, attachmentId),
    closeAssignmentAttachment: (tabId, previewId) => ipcRenderer.invoke("ast:assignment-attachment-close", tabId, previewId),
    downloadAssignmentAttachment: (tabId, previewId) => ipcRenderer.invoke("ast:assignment-attachment-download", tabId, previewId),
    retryAssignmentAnalysis: (tabId, courseId, assignmentId) => ipcRenderer.invoke("ast:assignment-analysis-retry", tabId, courseId, assignmentId),
    layoutAssignmentBrowser: (bounds) => ipcRenderer.send("ast:assignment-browser-layout", bounds),
    onAssignmentBrowser: (listener) => {
      const receive = (_event: Electron.IpcRendererEvent, state: AssignmentBrowserState) => listener(state);
      ipcRenderer.on("ast:assignment-browser-state", receive);
      return () => { ipcRenderer.removeListener("ast:assignment-browser-state", receive); };
    },
  };
  contextBridge.exposeInMainWorld("ast", chat);
  contextBridge.exposeInMainWorld("assignmentBrowser", browser);
} else {
  contextBridge.exposeInMainWorld("ast", bridge);
}
