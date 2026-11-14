import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { BrowserWindow, ipcMain, WebContentsView, type IpcMainEvent, type IpcMainInvokeEvent, type Rectangle, type WebContents } from "electron";
import {
  assignmentIdFromUrl, assignmentTarget, assignmentUrl, ATTACHMENT_PREVIEW_PATH, courseNoticeIdFromUrl, courseNoticeUrl, COURSE_PAGE_PATHS, DEFAULT_ASSIGNMENT_FONT_SIZE, ECLASS_MAIN_PATH, ECLASS_ORIGIN, isCourseId, isCourseNoticeId, OPEN_BOARD_PATH,
  CURRENT_ASSIGNMENT_GUIDE_FORMAT,
  type AssignmentAttachmentOpenResult, type AssignmentBrowserState, type AssignmentFontSize, type AssignmentPageState, type AssignmentDetails, type AssignmentTarget, type CourseBrowserPage,
} from "../shared/assignment-browser.js";
import type { LoginResult } from "../shared/lms.js";
import { createAssignmentAttachmentPreviewStore, type AssignmentAttachmentFile, type PreparedAssignmentAttachment } from "./assignment-attachment-preview.js";
import { createAssignmentAnalysis } from "./assignment-analysis.js";
import { readAssignmentFontSize, saveAssignmentFontSize } from "./assignment-settings.js";
import { createChatSession } from "./chat-controller.js";
import { readChatSettings } from "./chat-settings.js";
import { allowedLmsRequest, AssignmentWebSession, browserAddress, type NavigationBlock } from "./assignment-web-session.js";
import type { createLmsConnector } from "./lms-connector.js";
import type { ScreenData } from "./screen-data.js";
import { createWebLoadingView } from "./web-loading-view.js";
import { verifiedAccount } from "./account-data.js";

const loginUrl = ECLASS_ORIGIN + "/ilos/main/member/login_form.acl";
const eclassHost = new URL(ECLASS_ORIGIN).hostname;
const unsupportedAddress = "AST에서 열 수 없는 주소예요. 공식 브라우저에서 확인해 주세요.";
const temporaryConnectionErrors = new Set([
  -7,   // ERR_TIMED_OUT
  -21,  // ERR_NETWORK_CHANGED
  -100, // ERR_CONNECTION_CLOSED
  -101, // ERR_CONNECTION_RESET
  -106, // ERR_INTERNET_DISCONNECTED
  -118, // ERR_CONNECTION_TIMED_OUT
  -324, // ERR_EMPTY_RESPONSE
]);
type Chat = ReturnType<typeof createChatSession>;
type AssignmentLoad = "page-first" | "verify-first" | "panel-only";
type CourseHome = { courseId: string; url: string; kind: CourseBrowserPage["kind"] | "notice" };
const coursePageTitles: Record<CourseHome["kind"], string> = {
  attendance: "출석", groups: "그룹활동", grades: "성적", qna: "질의응답", files: "파일모음",
  open_board: "열린게시판", activity: "강의 활동", notice: "수업 공지",
};

type Entry = {
  group: BrowserTabs;
  loginId?: string;
  window: BrowserWindow;
  view: WebContentsView;
  loadingView?: ReturnType<typeof createWebLoadingView>;
  title: string;
  initialTitle: string;
  initialNavigation?: Promise<void>;
  requestedUrl?: string;
  retryUrl?: string;
  home?: AssignmentTarget;
  courseHome?: CourseHome;
  course?: string;
  target?: AssignmentTarget;
  prepared?: AssignmentDetails;
  chats: Map<string, Chat>;
  activeChat?: Chat;
  attachmentRequest?: AbortController;
  attachmentPreview?: PreparedAssignmentAttachment;
  state: AssignmentPageState;
  navigation: number;
  sequence: number;
  request?: AbortController;
};

type BrowserTabs = {
  window: BrowserWindow;
  tabs: Map<number, Entry>;
  activeTabId: number;
  readyToShow: boolean;
  showRequested: boolean;
  layout?: Rectangle;
};

type PreparedAssignment = {
  owner: WebContents;
  request: number;
  entry: Entry;
  target: AssignmentTarget;
  mode: AssignmentLoad;
  cancel: () => void;
};

type Options = {
  rendererPath: string;
  preload: string;
  authPath?: string;
  activeDirectory?: () => string | undefined;
  apiKey: string;
  connector: ReturnType<typeof createLmsConnector>;
  screenData: ScreenData;
  verifyMain: (event: IpcMainInvokeEvent) => void;
  show?: boolean;
  web?: AssignmentWebSession;
  analysisFetch?: typeof fetch;
};

function sameAssignment(a: AssignmentTarget | undefined, b: AssignmentTarget): boolean {
  return a?.assignmentId === b.assignmentId && (!b.courseId || !a.courseId || a.courseId === b.courseId);
}

function isLmsLogin(url: string): boolean {
  try {
    const page = new URL(url);
    return page.origin === ECLASS_ORIGIN && (page.pathname === "/" || /\/login(?:_form)?\.acl$|\/index\.(?:acl|jsp)$/.test(page.pathname));
  } catch { return false; }
}

function samePage(a: string, b: string): boolean {
  return a.split("#", 1)[0] === b.split("#", 1)[0];
}

export function registerAssignmentWindows(options: Options) {
  const { connector, screenData } = options;
  const web = options.web ?? new AssignmentWebSession(connector.access);
  const attachments = createAssignmentAttachmentPreviewStore();
  const analysis = createAssignmentAnalysis({
    apiKey: options.apiKey, connector, activeDirectory: options.activeDirectory,
    activeRevision: () => screenData.confirmedSessionRevision,
    readModel: async (directory) => (await readChatSettings(directory ?? null)).model,
    fetch: options.analysisFetch,
  });
  const rendererUrl = pathToFileURL(options.rendererPath).href;
  const loadingPath = join(dirname(options.rendererPath), "web-loading", "index.html");
  const windows = new Map<number, BrowserTabs>();
  const courseByAssignment = new Map<string, string>();
  let sessionRevision = screenData.confirmedSessionRevision;
  let windowAccount = screenData.account?.key;
  let importedRevision: number | undefined;
  let importing: Promise<void> | undefined;
  let confirming: Promise<void> | undefined;
  let loginWindow: Entry | undefined;
  let preparedAssignment: PreparedAssignment | undefined;
  let shuttingDown = false;
  let assignmentFontSize = DEFAULT_ASSIGNMENT_FONT_SIZE;
  let fontSizeRead: Promise<void>;
  let fontSizeWrite: Promise<unknown> = Promise.resolve();
  loadFontSize();

  function sender(event: IpcMainInvokeEvent | IpcMainEvent): Entry | undefined {
    const group = windows.get(event.sender.id);
    if (group && event.senderFrame === event.sender.mainFrame && event.senderFrame?.url === rendererUrl) return group.tabs.get(group.activeTabId);
  }

  function requireSender(event: IpcMainInvokeEvent): Entry {
    const entry = sender(event);
    if (!entry) throw new Error("과제 브라우저 창에서만 사용할 수 있어요.");
    return entry;
  }

  function entries() { return [...windows.values()].flatMap((group) => [...group.tabs.values()]); }

  function browserState(group: BrowserTabs): AssignmentBrowserState {
    return {
      ...group.tabs.get(group.activeTabId)!.state,
      assignmentFontSize,
      activeTabId: group.activeTabId,
      tabs: [...group.tabs].map(([id, { title, attachmentPreview, state }]) => ({
        id, title,
        pdf: attachmentPreview?.kind === "pdf" && state.attachmentPreview
          ? { url: attachmentPreview.url, name: state.attachmentPreview.name } : undefined,
      })),
    };
  }

  function publish(group: BrowserTabs) {
    const active = group.tabs.get(group.activeTabId);
    if (!active || group.window.isDestroyed()) return;
    group.window.setTitle(active.title + " · AST");
    group.window.webContents.send("ast:assignment-browser-state", browserState(group));
  }

  function publishFontSize(size: AssignmentFontSize) {
    if (size === assignmentFontSize || shuttingDown) return;
    assignmentFontSize = size;
    for (const group of windows.values()) publish(group);
  }

  function loadFontSize() {
    const revision = screenData.confirmedSessionRevision;
    const directory = options.activeDirectory?.();
    fontSizeRead = revision === undefined || (options.activeDirectory && !directory) ? Promise.resolve() :
      fontSizeWrite.then(() => readAssignmentFontSize(directory)).then((size) => {
        if (revision === screenData.confirmedSessionRevision) publishFontSize(size);
      });
  }

  function requireFontSizeSession(expected: unknown) {
    const revision = screenData.confirmedSessionRevision;
    const directory = options.activeDirectory?.();
    if (shuttingDown || revision === undefined || expected !== revision || (options.activeDirectory && !directory)) {
      throw new Error("ASTRA에 다시 로그인한 뒤 글자 크기를 설정해 주세요.");
    }
    return directory;
  }

  function update(entry: Entry, changes: Partial<AssignmentPageState> = {}) {
    if (entry.window.isDestroyed() || entry.view.webContents.isDestroyed()) return;
    const contents = entry.view.webContents;
    entry.state = { ...entry.state, back: contents.navigationHistory.canGoBack(), forward: contents.navigationHistory.canGoForward(), ...changes };
    publish(entry.group);
  }

  function clearContext(entry: Entry, assignmentState: AssignmentPageState["assignmentState"], assignmentMessage: string | null = null) {
    closeAttachment(entry);
    entry.activeChat?.stop();
    entry.activeChat = undefined;
    update(entry, { assignment: null, assignmentState, assignmentMessage, analysis: undefined });
  }

  async function analyzeAssignment(entry: Entry, requested = false) {
    const { assignment, analysis: previous } = entry.state;
    const { group, window } = entry;
    if (!assignment || !group.readyToShow || !group.showRequested || group.tabs.get(group.activeTabId) !== entry) return;
    const legacy = previous?.status === "ready" && previous.format !== CURRENT_ASSIGNMENT_GUIDE_FORMAT ? previous : undefined;
    if (previous && (!requested || (previous.status !== "error" && (!legacy || legacy.upgrade?.status === "loading")))) return;

    let pending: NonNullable<AssignmentPageState["analysis"]> = legacy
      ? { ...legacy, upgrade: { status: "loading" } } : { status: "loading" };
    const current = () => !window.isDestroyed() && entry.state.analysis === pending && entry.state.assignment === assignment;
    update(entry, { analysis: pending });
    const result = await analysis.analyze(assignment, Boolean(legacy), false, (markdown) => {
      if (!current()) return;
      pending = legacy ? { ...legacy, upgrade: { status: "loading", markdown } } : { status: "loading", markdown };
      update(entry, { analysis: pending });
    }).catch(() => (
      { status: "error", message: "과제 해설을 만들지 못했어요. 다시 시도해 주세요." } as const
    ));
    if (!current()) return;
    if (legacy && result.status !== "ready") {
      update(entry, { analysis: {
        ...legacy,
        upgrade: result.status === "cancelled" ? undefined : { status: "error", message: result.message },
      } });
      return;
    }
    if (result.status === "ready") {
      const { pdfNotes: _notes, fingerprint: _fingerprint, ...guide } = result;
      update(entry, { analysis: guide });
    } else {
      update(entry, { analysis: result.status === "cancelled" ? undefined : result });
    }
  }

  function showAssignment(entry: Entry, assignment: AssignmentDetails) {
    const key = assignment.courseId + ":" + assignment.assignmentId;
    let chat = entry.chats.get(key);
    if (!chat) {
      chat = createChatSession({
        apiKey: options.apiKey, memoryOnly: true, activeDirectory: options.activeDirectory, assignment: () => entry.state.assignment ?? undefined, getClient: connector.getClient,
        assignmentAnalysis: () => entry.state.analysis?.status === "ready" ? entry.state.analysis.markdown : undefined,
        assignmentPdfNotes: async (assignment, requirePdfNotes) => {
          if (!requirePdfNotes && entry.state.analysis?.status !== "ready") return;
          const result = await analysis.analyze(assignment, false, requirePdfNotes);
          return result.status === "ready" ? result.pdfNotes : undefined;
        },
        openAssignmentPdf: analysis.openPdf,
        callTool: connector.callTool, confirmedLmsSession: () => screenData.confirmedSessionRevision,
        openAssignment: open, openBrowser, openCourseNotice,
        window: () => entry.window,
      });
      entry.chats.set(key, chat);
    }
    if (entry.activeChat !== chat) entry.activeChat?.stop();
    entry.activeChat = chat;
    entry.title = assignment.title;
    update(entry, { assignment, assignmentState: "ready", assignmentMessage: null,
      analysis: entry.state.assignment === assignment ? entry.state.analysis : undefined });
    void analyzeAssignment(entry);
  }

  async function ensureCookies(revision: number) {
    if (importedRevision === revision) return;
    if (importing) await importing;
    if (importedRevision === revision) return;
    const directory = options.activeDirectory?.();
    const path = directory ? join(directory, "lms", "auth_state.json") : options.authPath;
    if (!path || screenData.confirmedSessionRevision !== revision) throw new Error("Missing verified account");
    const work = web.importLogin(path).then(() => { importedRevision = revision; });
    importing = work;
    try { await work; }
    finally { if (importing === work) importing = undefined; }
  }

  function beginPageLoad(entry: Entry, changes: Partial<AssignmentPageState> = {}) {
    if (!entry.state.initialLoad || !entry.loadingView) {
      entry.loadingView?.dispose();
      const overlay = createWebLoadingView(entry.window, loadingPath,
        entry.group.tabs.get(entry.group.activeTabId) === entry, () => {
          if (entry.loadingView === overlay) entry.loadingView = undefined;
        });
      entry.loadingView = overlay;
      fit(entry);
    }
    update(entry, { ...changes, initialLoad: true });
  }

  function revealPage(entry: Entry) {
    if (!entry.state.initialLoad) return;
    entry.initialNavigation = undefined;
    update(entry, { initialLoad: false });
    if (entry.group.showRequested && entry.group.tabs.get(entry.group.activeTabId) === entry) entry.loadingView?.reveal();
    else entry.loadingView?.dispose();
  }

  function onLoadFailure(entry: Entry, url: string, error: string, retryUrl?: string) {
    entry.requestedUrl = undefined;
    entry.retryUrl = retryUrl;
    update(entry, { url, loading: false, error, canRetryNavigation: !!retryUrl });
    if (entry.state.assignmentState === "loading") clearContext(entry, "unavailable", "과제 페이지를 열지 못했어요.");
    revealPage(entry);
  }

  function onNavigationBlocked(entry: Entry, reason: NavigationBlock, url: string, method: string) {
    // A queued request may finish after the user has already navigated elsewhere.
    if (!entry.state.loading || !samePage(entry.state.url, url)) return;
    if (reason === "restricted") {
      onLoadFailure(entry, url, "이 e-Class 경로는 AST에서 열 수 없어요. 공식 브라우저에서 직접 확인해 주세요.");
    } else if (reason === "course-required") {
      const message = screenData.confirmedSessionRevision === undefined
        ? "e-Class 로그인 확인을 마친 뒤 다시 열어 주세요."
        : "AST 메인 창에서 해당 강좌의 공지나 과제를 다시 열어 주세요.";
      onLoadFailure(entry, url, message);
    } else {
      onLoadFailure(entry, url, "e-Class 강좌를 연결하지 못했어요. 로그인 상태를 확인한 뒤 다시 시도해 주세요.",
        method === "GET" ? url : undefined);
    }
  }

  function loadUrl(entry: Entry, url: string) {
    const contents = entry.view.webContents;
    if (contents.isDestroyed()) return;
    entry.view.setVisible(entry.group.tabs.get(entry.group.activeTabId) === entry);
    entry.requestedUrl = url;
    entry.retryUrl = undefined;
    entry.initialNavigation = undefined;
    ++entry.navigation;
    const changes = { url, loading: true, error: null, canRetryNavigation: false };
    const currentUrl = contents.getURL();
    const sameDocument = currentUrl !== url && samePage(currentUrl, url);
    if (sameDocument) update(entry, changes);
    else beginPageLoad(entry, changes);
    const navigation = contents.loadURL(url);
    if (!sameDocument && entry.state.initialLoad) entry.initialNavigation = navigation;
    void navigation.catch(() => {
      // A canceled initial request can reject without a terminal did-fail-load event.
      if (entry.initialNavigation === navigation && !contents.isDestroyed() && !contents.isLoadingMainFrame()) {
        onLoadFailure(entry, url, "페이지를 열지 못했어요. 주소나 연결을 확인해 주세요.");
      }
    });
  }

  function needsLogin(entry: Entry, message: string) {
    clearContext(entry, "login", message);
    if (!entry.view.webContents.getURL() || entry.view.webContents.getURL() === "about:blank") loadUrl(entry, loginUrl);
  }

  async function loadAssignment(entry: Entry, target: AssignmentTarget, mode: AssignmentLoad) {
    if (entry.window.isDestroyed()) return;
    const id = ++entry.sequence;
    entry.request?.abort();
    const controller = new AbortController();
    entry.request = controller;
    entry.target = target;
    entry.prepared = undefined;
    const revision = screenData.confirmedSessionRevision;
    if (revision === undefined) {
      needsLogin(entry, "내 강의실에서 로그인 확인을 마치거나 이 창에서 e-Class에 로그인해 주세요.");
      return;
    }
    clearContext(entry, "loading");
    const current = () => !entry.window.isDestroyed() && id === entry.sequence && screenData.confirmedSessionRevision === revision;
    try {
      await ensureCookies(revision);
    } catch {
      if (current()) needsLogin(entry, "브라우저에 연결할 로그인 세션을 확인하지 못했어요.");
      return;
    }
    if (!current()) return;
    if (mode === "page-first" && target.courseId) {
      entry.course = target.courseId;
      loadUrl(entry, assignmentUrl(target.assignmentId));
      // The completed page starts the panel lookup. Both use the same course-selection lock.
      return;
    }
    const result = await connector.requestTool<
      { status: "ok"; assignment: AssignmentDetails } | { status: "login_required"; message: string }
    >("get_assignment_workspace", { assignment_id: target.assignmentId, ...(target.courseId ? { course_id: target.courseId } : {}) },
      65_000, "과제 원문을 불러오지 못했어요.", controller.signal);
    if (!current()) return;
    if (result.status === "login_required") {
      needsLogin(entry, result.message);
      return;
    }
    if (result.status !== "ok" || result.assignment.assignmentId !== target.assignmentId ||
        (target.courseId && result.assignment.courseId !== target.courseId)) {
      clearContext(entry, "unavailable", result.status === "ok" ? "현재 과제의 원문을 확인하지 못했어요." : result.message);
      if (!entry.state.loading) revealPage(entry);
      return;
    }
    const assignment = result.assignment;
    entry.course = assignment.courseId;
    courseByAssignment.set(assignment.assignmentId, assignment.courseId);
    entry.target = { courseId: assignment.courseId, assignmentId: assignment.assignmentId };
    entry.prepared = assignment;
    if (mode === "verify-first") loadUrl(entry, assignmentUrl(assignment.assignmentId));
    else if (entry.state.assignmentState === "loading" && !entry.state.error &&
        assignmentIdFromUrl(entry.view.webContents.getURL()) === assignment.assignmentId) showAssignment(entry, assignment);
  }

  async function connectBrowserLogin(entry: Entry) {
    if (confirming || shuttingDown) return confirming;
    const loginId = entry.loginId;
    entry.loginId = undefined;
    if (options.activeDirectory && !loginId) {
      update(entry, { assignmentMessage: "AST 메인 창에서 ASTRA로 다시 로그인해 주세요." });
      return;
    }
    const work = (async () => {
      const cookies = await web.loginCookies();
      if (!cookies.length) return;
      screenData.invalidateSession();
      const revision = screenData.status.sessionRevision;
      const result = await screenData.authenticate(() => connector.requestTool<LoginResult>(
        "confirm_browser_login", { cookies, ...(loginId ? { login_id: loginId } : {}) }, 35_000, "브라우저 로그인을 확인하지 못했어요."));
      if (screenData.status.sessionRevision !== revision || shuttingDown) return;
      const account = verifiedAccount(result);
      if (result.status === "authenticated" && (!options.activeDirectory || account)) {
        // A change of account must import the freshly verified cookies before opening a new view.
        importedRevision = !account || account.key === windowAccount ? revision + 1 : undefined;
        screenData.warm(account, result.course_roster, result.student_profile);
      } else {
        for (const entry of entries()) if (entry.state.assignmentState === "login") {
          update(entry, { assignmentMessage: result.status === "authenticated"
            ? "계정을 확인하지 못했어요. AST 메인 창에서 다시 로그인해 주세요." : result.message });
        }
      }
    })().catch(() => {
      for (const entry of entries()) if (entry.state.assignmentState === "login") {
        update(entry, { assignmentMessage: "브라우저 로그인 연결을 다시 시도해 주세요." });
      }
    });
    confirming = work;
    try { await work; }
    finally {
      if (confirming === work) confirming = undefined;
      if (loginWindow === entry) loginWindow = undefined;
    }
  }

  function onLoaded(entry: Entry, url: string) {
    if (entry.window.isDestroyed()) return;
    update(entry, { url, loading: false });
    if (isLmsLogin(url)) {
      if (entry.courseHome && !entry.target) {
        clearContext(entry, "none");
        update(entry, { error: "e-Class 로그인이 만료됐어요. AST 메인 창에서 다시 로그인한 뒤 페이지를 열어 주세요." });
        return;
      }
      clearContext(entry, "login", "e-Class에서 로그인하면 과제를 이어서 열어요.");
      return;
    }
    if (url.split(/[?#]/, 1)[0] === ECLASS_ORIGIN + ECLASS_MAIN_PATH && entry.state.assignmentState === "login") {
      void connectBrowserLogin(entry);
      return;
    }
    const assignmentId = assignmentIdFromUrl(url);
    if (!assignmentId) {
      ++entry.sequence;
      entry.prepared = undefined;
      if (entry.courseHome) {
        entry.target = undefined;
        entry.title = entry.initialTitle;
      }
      clearContext(entry, "none");
      return;
    }
    if (entry.prepared?.assignmentId === assignmentId && entry.prepared.courseId === entry.course) {
      showAssignment(entry, entry.prepared);
      return;
    }
    void loadAssignment(entry, { assignmentId, courseId: entry.course }, "panel-only");
  }

  async function openNativeNotice(entry: Entry, url: string) {
    const contents = entry.view.webContents;
    if (contents.isDestroyed()) return;
    const noticeId = entry.courseHome?.kind === "notice" && entry.courseHome.url === url
      ? courseNoticeIdFromUrl(new URL(url)) : undefined;
    if (!noticeId) { revealPage(entry); return; }
    beginPageLoad(entry, { error: null, canRetryNavigation: false });
    const sequence = entry.sequence;
    // The official list opens each notice through a POST-backed dialog.
    const opened = await contents.executeJavaScript(`(() => {
      if (typeof noticeViewPop !== "function") return false;
      noticeViewPop(${JSON.stringify(noticeId)});
      return Boolean(document.querySelector("#notice_view_pop .editor_content")?.getClientRects().length);
    })()`).catch(() => false);
    if (contents.isDestroyed() || sequence !== entry.sequence || contents.getURL() !== url) return;
    if (!opened) {
      onLoadFailure(entry, url, "e-Class에서 공지를 열지 못했어요. 다시 시도해 주세요.", url);
      return;
    }
    entry.retryUrl = undefined;
    update(entry, { error: null, canRetryNavigation: false });
    revealPage(entry);
  }

  function fit(entry: Entry) {
    if (!entry.group.layout || entry.window.isDestroyed() || entry.view.webContents.isDestroyed()) return;
    const [width, height] = entry.window.getContentSize();
    const { x, y, width: requestedWidth, height: requestedHeight } = entry.group.layout;
    const bounds = {
      x: Math.min(width, x), y: Math.min(height, y),
      width: Math.max(0, Math.min(requestedWidth, width - x)),
      height: Math.max(0, Math.min(requestedHeight, height - y)),
    };
    entry.view.setBounds(bounds);
    entry.attachmentPreview?.view?.setBounds(bounds);
    entry.loadingView?.fit(bounds);
  }

  function setTabVisible(entry: Entry, visible: boolean) {
    entry.attachmentPreview?.view?.setVisible(visible);
    const canShowPage = screenData.confirmedSessionRevision !== undefined || isLmsLogin(entry.state.url) ||
      browserAddress(entry.state.url)?.origin !== ECLASS_ORIGIN;
    if (!entry.view.webContents.isDestroyed()) entry.view.setVisible(visible && !entry.attachmentPreview && canShowPage);
  }

  function discardAttachment(entry: Entry, preview: PreparedAssignmentAttachment) {
    if (preview.view && !entry.window.isDestroyed()) entry.window.contentView.removeChildView(preview.view);
    preview.dispose();
  }

  function closeAttachment(entry: Entry) {
    entry.attachmentRequest?.abort();
    entry.attachmentRequest = undefined;
    const preview = entry.attachmentPreview;
    if (!preview) return;
    entry.attachmentPreview = undefined;
    entry.state = { ...entry.state, attachmentPreview: undefined };
    discardAttachment(entry, preview);
    if (!entry.window.isDestroyed()) setTabVisible(entry, entry.group.tabs.get(entry.group.activeTabId) === entry);
  }

  async function openAttachment(entry: Entry, tabId: unknown, courseId: unknown, assignmentId: unknown, attachmentId: unknown): Promise<AssignmentAttachmentOpenResult> {
    const { group, window, state } = entry;
    const assignment = state.assignment;
    if (tabId !== group.activeTabId || !assignment || assignment.courseId !== courseId || assignment.assignmentId !== assignmentId) {
      return { status: "cancelled" };
    }
    const revision = screenData.confirmedSessionRevision;
    const file = assignment.attachments?.find(({ id }) => id === attachmentId);
    const target = assignmentTarget({ courseId, assignmentId });
    if (!file || !target || revision === undefined || state.loading) {
      return { status: "error", message: "현재 과제의 첨부파일을 확인하지 못했어요." };
    }
    entry.attachmentRequest?.abort();
    const request = new AbortController();
    entry.attachmentRequest = request;
    const current = () => !request.signal.aborted && !window.isDestroyed() && group.activeTabId === tabId &&
      screenData.confirmedSessionRevision === revision && entry.state.assignment === assignment &&
      entry.attachmentRequest === request;
    const failed = { status: "error", message: "첨부파일을 열지 못했어요. 다시 시도해 주세요." } as const;
    let preview: PreparedAssignmentAttachment | undefined;
    const discardPending = () => {
      if (preview) discardAttachment(entry, preview);
      preview = undefined;
    };
    request.signal.addEventListener("abort", discardPending, { once: true });
    try {
      const result = await connector.requestTool<AssignmentAttachmentFile>(
        "get_assignment_attachment_file", { course_id: courseId, assignment_id: assignmentId, attachment_id: file.id },
        90_000, failed.message, request.signal, current);
      if (!current()) return { status: "cancelled" };
      if (result.status !== "ok") return { status: "error", message: result.message };
      if (result.course_id !== courseId || result.assignment_id !== assignmentId || result.attachment_id !== file.id) return failed;
      preview = attachments.prepare({ ...result, name: file.name });
      if (!preview) return failed;
      if (preview.view) {
        preview.view.setVisible(false);
        window.contentView.addChildView(preview.view);
        preview.view.setBounds(entry.view.getBounds());
      }
      await preview.open();
      if (!current() || !preview) return { status: "cancelled" };
      if (entry.attachmentPreview) discardAttachment(entry, entry.attachmentPreview);
      entry.attachmentPreview = preview;
      preview = undefined;
      update(entry, { attachmentPreview: {
        id: entry.attachmentPreview.id,
        name: file.name,
        inline: entry.attachmentPreview.kind !== "download",
        isPdf: entry.attachmentPreview.kind === "pdf",
      } });
      setTabVisible(entry, true);
      return { status: "opened" };
    } catch {
      return current() ? failed : { status: "cancelled" };
    } finally {
      request.signal.removeEventListener("abort", discardPending);
      discardPending();
      if (entry.attachmentRequest === request) entry.attachmentRequest = undefined;
    }
  }

  function create(destination?: { target: AssignmentTarget } | { courseHome: CourseHome }, showRequested = true): Entry {
    const courseHome = destination && "courseHome" in destination ? destination.courseHome : undefined;
    const target = destination && "target" in destination ? destination.target : undefined;
    const title = courseHome ? `e-Class ${coursePageTitles[courseHome.kind]}` : target ? "과제 브라우저" : "브라우저";
    const window = new BrowserWindow({
      title: title + " · AST",
      width: courseHome ? 1120 : 1340, height: 850, minWidth: 820, minHeight: 500, show: false,
      backgroundColor: "#f5f7fb",
      webPreferences: {
        preload: options.preload, session: attachments.getSession(), plugins: true,
        sandbox: true, contextIsolation: true, nodeIntegration: false,
      },
    });
    const view = new WebContentsView({
      webPreferences: { session: web.session, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true,
        backgroundThrottling: showRequested },
    });
    const group: BrowserTabs = { window, tabs: new Map(), activeTabId: view.webContents.id, readyToShow: false, showRequested };
    const shellId = window.webContents.id;
    windows.set(shellId, group);
    const entry = attachTab(group, view, title, target?.courseId ?? courseHome?.courseId, destination && { target, courseHome });
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.once("ready-to-show", () => {
      group.readyToShow = true;
      if (group.showRequested && options.show !== false) window.show();
      const active = group.tabs.get(group.activeTabId);
      if (active) void analyzeAssignment(active);
    });
    window.on("resize", () => {
      const active = group.tabs.get(group.activeTabId);
      if (active) fit(active);
    });
    window.on("closed", () => {
      windows.delete(shellId);
      for (const tab of [...group.tabs.values()]) removeTab(tab);
    });
    void window.loadFile(options.rendererPath);
    return entry;
  }

  function selectTab(entry: Entry, focusPage = false) {
    const { group, window } = entry;
    if (window.isDestroyed() || entry.view.webContents.isDestroyed()) return;
    const previous = group.tabs.get(group.activeTabId);
    if (previous && previous !== entry) {
      previous.attachmentRequest?.abort();
      previous.activeChat?.stop();
      setTabVisible(previous, false);
      previous.loadingView?.setVisible(false);
    }
    group.activeTabId = entry.view.webContents.id;
    fit(entry);
    setTabVisible(entry, true);
    entry.loadingView?.setVisible(true);
    publish(group);
    void analyzeAssignment(entry);
    if (focusPage) entry.view.webContents.focus();
  }

  function removeTab(entry: Entry) {
    const { group, view, window } = entry;
    const ids = [...group.tabs.keys()];
    const index = ids.findIndex((id) => group.tabs.get(id) === entry);
    if (index === -1) return;
    const id = ids[index];
    group.tabs.delete(id);
    if (loginWindow === entry) loginWindow = undefined;
    ++entry.sequence;
    entry.request?.abort();
    closeAttachment(entry);
    for (const chat of entry.chats.values()) chat.stop();
    entry.chats.clear();
    entry.loadingView?.dispose();
    web.remove(id);
    if (window.isDestroyed()) {
      if (!view.webContents.isDestroyed()) view.webContents.close();
      return;
    }
    window.contentView.removeChildView(view);
    if (!view.webContents.isDestroyed()) view.webContents.close();
    const next = group.tabs.get(ids[index + 1] ?? ids[index - 1]);
    if (group.tabs.size === 0) window.destroy();
    else if (id === group.activeTabId && next) selectTab(next);
    else publish(group);
  }

  function attachTab(group: BrowserTabs, view: WebContentsView, title: string, course: string | undefined,
    root?: { target?: AssignmentTarget; courseHome?: CourseHome }): Entry {
    const { window } = group;
    const { target, courseHome } = root ?? {};
    window.contentView.addChildView(view);
    const entry: Entry = {
      group, window, view, title, initialTitle: title, home: target, courseHome, target, course, navigation: 0, sequence: 0, chats: new Map(),
      state: { openedFromNotice: courseHome?.kind === "notice", openedFromCourse: !target,
        url: "", initialLoad: false, loading: false, back: false, forward: false, error: null, canRetryNavigation: false,
        assignment: null, assignmentState: target ? "loading" : "none", assignmentMessage: null },
    };
    const contents = view.webContents;
    const viewId = contents.id;
    let waitingForPage = false;
    group.tabs.set(viewId, entry);
    view.setVisible(viewId === group.activeTabId);
    if (root) beginPageLoad(entry);
    web.add(viewId, {
      loginSubmitted: (loginId) => {
        if (options.activeDirectory && loginWindow !== entry) {
          update(entry, { assignmentMessage: "이 창에서 다시 로그인 버튼을 눌러 주세요." });
          return false;
        }
        entry.loginId = loginId;
        return true;
      },
      course: () => screenData.confirmedSessionRevision === undefined ? undefined : entry.course,
      selectedCourse: (course) => { entry.course = course; entry.prepared = undefined; clearContext(entry, "none"); },
      blocked: (reason, url, method) => onNavigationBlocked(entry, reason, url, method),
      stop: () => { if (!contents.isDestroyed()) contents.stop(); },
    });
    contents.once("destroyed", () => removeTab(entry));
    contents.setWindowOpenHandler(({ url, disposition, postBody }) => {
      const destination = browserAddress(url);
      const method = postBody ? "POST" : "GET";
      const permitted = destination && (destination.hostname === eclassHost
        ? allowedLmsRequest(destination, method, "mainFrame")
        : method === "GET");
      if (!destination || !permitted || group.tabs.size >= 20) {
        update(entry, { error: group.tabs.size >= 20 ? "탭을 닫은 뒤 새 링크를 열어 주세요." : unsupportedAddress, canRetryNavigation: false });
        return { action: "deny" };
      }
      return {
        action: "allow",
        outlivesOpener: true,
        overrideBrowserWindowOptions: {
          webPreferences: { session: web.session, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, webviewTag: false },
        },
        createWindow: (options) => {
          // Adopt Chromium's guest to keep the original referrer, method and history.
          const guest = (options as typeof options & { webContents: WebContents }).webContents;
          const preview = destination.origin === ECLASS_ORIGIN && destination.pathname === ATTACHMENT_PREVIEW_PATH;
          const id = assignmentIdFromUrl(destination.href);
          const course = (id && courseByAssignment.get(id)) || entry.course;
          const tab = attachTab(group, new WebContentsView({ webContents: guest }), preview ? "첨부 미리보기" : destination.hostname, course);
          beginPageLoad(tab, { url: destination.href, loading: true });
          if (disposition !== "background-tab") selectTab(tab, true);
          return guest;
        },
      };
    });
    contents.on("page-title-updated", (_event, pageTitle) => {
      if (!entry.state.assignment) {
        entry.title = pageTitle.trim().slice(0, 140) || entry.initialTitle;
        publish(group);
      }
    });
    contents.on("will-navigate", (event) => {
      const destination = browserAddress(event.url);
      if (!destination) {
        event.preventDefault();
        update(entry, { error: unsupportedAddress, canRetryNavigation: false });
        return;
      }
      const id = assignmentIdFromUrl(destination.href);
      const knownCourse = id && courseByAssignment.get(id);
      if (knownCourse) entry.course = knownCourse;
    });
    contents.on("will-redirect", (event) => {
      if (!browserAddress(event.url)) {
        event.preventDefault();
        if (event.isMainFrame) onLoadFailure(entry, entry.state.url, unsupportedAddress);
      } else if (event.isMainFrame) {
        update(entry, { url: event.url });
      }
    });
    contents.on("will-frame-navigate", (event) => {
      if (!/^https?:\/\//i.test(event.url) && event.url !== "about:blank") {
        event.preventDefault();
        if (event.isMainFrame) update(entry, { error: unsupportedAddress, canRetryNavigation: false });
      }
    });
    contents.on("did-start-navigation", (event) => {
      if (!event.isMainFrame || event.isSameDocument || !browserAddress(event.url)) return;
      ++entry.navigation;
      waitingForPage = true;
      const id = assignmentIdFromUrl(event.url);
      if (!id || id !== entry.prepared?.assignmentId || entry.prepared.courseId !== entry.course) {
        ++entry.sequence;
        entry.request?.abort();
        entry.prepared = undefined;
      }
      if (entry.state.assignmentState !== "login") clearContext(entry, id ? "loading" : "none");
      if (entry.requestedUrl !== event.url) {
        entry.requestedUrl = undefined;
        entry.initialNavigation = undefined;
      }
      entry.retryUrl = undefined;
      beginPageLoad(entry, { url: event.url, loading: true, error: null, canRetryNavigation: false });
    });
    contents.on("did-finish-load", () => {
      const url = contents.getURL();
      // Chromium can finish loading an error document after a different navigation has started.
      if (!samePage(entry.state.url, url) || (entry.state.error && !entry.state.loading)) return;
      waitingForPage = false;
      entry.requestedUrl = undefined;
      entry.initialNavigation = undefined;
      onLoaded(entry, url);
      void openNativeNotice(entry, url);
    });
    contents.on("did-navigate-in-page", (_event, url, isMainFrame) => {
      if (!isMainFrame) return;
      const addressOnly = entry.requestedUrl === url && !contents.isLoadingMainFrame();
      if (addressOnly) {
        entry.requestedUrl = undefined;
        waitingForPage = contents.isLoading();
      }
      if (samePage(entry.state.url, url)) update(entry, { url, ...(addressOnly ? { loading: false } : {}) });
      else onLoaded(entry, url);
      if (waitingForPage && entry.state.initialLoad) return;
      if (entry.courseHome?.kind === "notice" && entry.courseHome.url === url && courseNoticeIdFromUrl(new URL(url))) {
        void openNativeNotice(entry, url);
      } else if (addressOnly) {
        revealPage(entry);
      }
    });
    contents.on("did-stop-loading", () => {
      if (!contents.isLoadingMainFrame()) update(entry, { loading: false });
      if (!waitingForPage || !entry.state.initialLoad) return;
      const navigation = entry.navigation;
      // Downloads and empty responses can stop the load without a finish or failure event.
      setImmediate(() => {
        if (window.isDestroyed() || contents.isDestroyed() || navigation !== entry.navigation ||
            !waitingForPage || !entry.state.initialLoad || entry.initialNavigation || contents.isLoading()) return;
        waitingForPage = false;
        entry.requestedUrl = undefined;
        const currentUrl = contents.getURL();
        if (currentUrl && currentUrl !== "about:blank") onLoaded(entry, currentUrl);
        else update(entry, { url: "", loading: false });
        revealPage(entry);
      });
    });
    contents.on("did-fail-load", (_event, code, _description, url, mainFrame) => {
      if (!mainFrame || code === -3) return;
      if (!samePage(entry.state.url, url) || (entry.state.error && !entry.state.loading)) return;
      const retryUrl = temporaryConnectionErrors.has(code) ? entry.requestedUrl : undefined;
      const message = retryUrl
        ? "연결이 끊겨 페이지를 열지 못했어요. 네트워크를 확인한 뒤 다시 시도해 주세요."
        : "페이지를 열지 못했어요. 주소나 연결을 확인해 주세요.";
      onLoadFailure(entry, url, message, retryUrl);
    });
    contents.on("render-process-gone", () => {
      if (entry.state.initialLoad || entry.state.loading) {
        onLoadFailure(entry, entry.state.url, "페이지를 열지 못했어요. 창을 닫고 다시 열어 주세요.");
      }
    });
    return entry;
  }

  function resolveAssignment(target: AssignmentTarget) {
    const knownCourse = courseByAssignment.get(target.assignmentId);
    const normalized = { assignmentId: target.assignmentId, courseId: target.courseId ?? knownCourse };
    const roster = screenData.roster;
    const verifiedCourse = normalized.courseId && (!knownCourse || knownCourse === normalized.courseId) &&
      (!roster || roster.courses.some(({ id }) => id === normalized.courseId));
    const mode: AssignmentLoad = verifiedCourse ? "page-first" : "verify-first";
    const openTabs = entries();
    const found = openTabs.find((entry) => sameAssignment(entry.target, normalized)) ??
      openTabs.find((entry) => sameAssignment(entry.home, normalized));
    return { target: normalized, mode, found };
  }

  function needsAssignmentLoad(entry: Entry, target: AssignmentTarget) {
    return !sameAssignment(entry.target, target) ||
      (assignmentIdFromUrl(entry.state.url) !== target.assignmentId && entry.state.assignmentState === "none");
  }

  function showAssignmentTab(entry: Entry, target: AssignmentTarget, mode: AssignmentLoad) {
    const { group, window, view } = entry;
    if (!group.showRequested) {
      group.showRequested = true;
      view.webContents.backgroundThrottling = true;
    }
    selectTab(entry);
    if (window.isMinimized()) window.restore();
    if (group.readyToShow && options.show !== false) { window.show(); window.focus(); }
    if (needsAssignmentLoad(entry, target)) void loadAssignment(entry, target, mode);
  }

  async function open(requested: AssignmentTarget): Promise<boolean> {
    if (shuttingDown) return false;
    const { target, mode, found } = resolveAssignment(requested);
    if (found) {
      showAssignmentTab(found, target, mode);
      return true;
    }
    const entry = create({ target });
    void loadAssignment(entry, target, mode);
    return true;
  }

  function clearPreparedAssignment(discard: boolean) {
    const prepared = preparedAssignment;
    if (!prepared) return;
    preparedAssignment = undefined;
    const { owner, entry, cancel } = prepared;
    owner.removeListener("destroyed", cancel);
    owner.removeListener("render-process-gone", cancel);
    if (discard && !entry.group.showRequested && !entry.window.isDestroyed()) entry.window.destroy();
    return prepared;
  }

  async function openScopedCoursePage(courseId: string, url: URL, kind: CourseHome["kind"], signal?: AbortSignal): Promise<boolean> {
    const revision = screenData.confirmedSessionRevision;
    if (shuttingDown || revision === undefined || !isCourseId(courseId) || !allowedLmsRequest(url, "GET", "mainFrame")) return false;
    try { await ensureCookies(revision); }
    catch { return false; }
    if (shuttingDown || signal?.aborted || screenData.confirmedSessionRevision !== revision) return false;

    const found = entries().find(({ courseHome }) => courseHome?.courseId === courseId && courseHome.url === url.href);
    if (found) {
      if (found.window.isMinimized()) found.window.restore();
      if (options.show !== false) { found.window.show(); found.window.focus(); }
      selectTab(found);
      if (found.state.url !== url.href || found.course !== courseId) {
        found.course = courseId;
        found.target = undefined;
        await navigate(found, url.href);
      } else if (!found.state.loading && !found.state.initialLoad) {
        if (courseNoticeIdFromUrl(url) && found.view.webContents.getURL() === url.href) void openNativeNotice(found, url.href);
        else if (found.state.error) await navigate(found, url.href);
      }
      return true;
    }
    const entry = create({ courseHome: { courseId, url: url.href, kind } });
    await navigate(entry, url.href);
    return true;
  }

  function openCourseNoticeLink(courseId: string, url: URL, page?: number): Promise<boolean> {
    const noticeId = courseNoticeIdFromUrl(url);
    return noticeId ? openCourseNotice(courseId, noticeId, page) : openScopedCoursePage(courseId, url, "notice");
  }

  async function openCourseNotice(courseId: string, noticeId: string, page?: number): Promise<boolean> {
    const revision = screenData.confirmedSessionRevision;
    if (shuttingDown || revision === undefined || !isCourseId(courseId) || !isCourseNoticeId(noticeId)) return false;
    const roster = screenData.roster;
    if (roster && !roster.courses.some(({ id }) => id === courseId)) return false;
    if (!screenData.hasIndexedCourseNotice(courseId, noticeId)) {
      const notice = await screenData.courseNotice(courseId, noticeId, {}, page);
      if ("status" in notice || revision !== screenData.confirmedSessionRevision) return false;
    }
    return openScopedCoursePage(courseId, courseNoticeUrl(noticeId), "notice");
  }

  async function openCoursePage(courseId: string, page: CourseBrowserPage, signal?: AbortSignal): Promise<boolean> {
    if (shuttingDown || signal?.aborted || screenData.confirmedSessionRevision === undefined || !isCourseId(courseId)) return false;
    const roster = screenData.roster;
    if (roster && !roster.courses.some(({ id }) => id === courseId)) return false;
    if (page.kind === "activity") {
      const id = assignmentIdFromUrl(page.url);
      if (id) return open({ courseId, assignmentId: id });
      return openScopedCoursePage(courseId, new URL(page.url), page.kind);
    }
    if (page.kind === "open_board") {
      const url = new URL(OPEN_BOARD_PATH, ECLASS_ORIGIN);
      url.searchParams.set("ARTL_GRP_ID", page.boardId);
      return openScopedCoursePage(courseId, url, page.kind);
    }
    return openScopedCoursePage(courseId, new URL(COURSE_PAGE_PATHS[page.kind], ECLASS_ORIGIN), page.kind, signal);
  }

  function openBrowser(url?: URL): boolean {
    if (shuttingDown || (url && (url.hostname === eclassHost || !browserAddress(url.href)))) return false;
    const entry = create();
    if (url) loadUrl(entry, url.href);
    return true;
  }

  async function navigate(entry: Entry, value: unknown): Promise<boolean> {
    const address = typeof value === "string" ? browserAddress(value) : undefined;
    if (!address) {
      entry.retryUrl = undefined;
      update(entry, { error: "http 또는 https 웹 주소를 입력해 주세요.", canRetryNavigation: false });
      return false;
    }
    const assignmentId = assignmentIdFromUrl(address.href);
    if (assignmentId) {
      const knownCourse = courseByAssignment.get(assignmentId);
      void loadAssignment(entry, { assignmentId, courseId: knownCourse ?? entry.course }, knownCourse ? "page-first" : "verify-first");
    } else {
      ++entry.sequence;
      entry.request?.abort();
      entry.prepared = undefined;
      loadUrl(entry, address.href);
    }
    return true;
  }

  function sessionChanged() {
    const revision = screenData.confirmedSessionRevision;
    if (revision === sessionRevision) return;
    sessionRevision = revision;
    assignmentFontSize = DEFAULT_ASSIGNMENT_FONT_SIZE;
    loadFontSize();
    analysis.sessionChanged();
    clearPreparedAssignment(true);
    courseByAssignment.clear();
    for (const entry of entries()) {
      if (entry.courseHome && !entry.window.isDestroyed()) entry.window.destroy();
      else if (!entry.home) removeTab(entry);
    }
    const nextAccount = screenData.account?.key;
    if (nextAccount && windowAccount && nextAccount !== windowAccount) {
      for (const { window } of windows.values()) window.destroy();
    }
    if (nextAccount) windowAccount = nextAccount;
    for (const entry of entries()) {
      ++entry.sequence;
      entry.request?.abort();
      closeAttachment(entry);
      entry.prepared = undefined;
      for (const chat of entry.chats.values()) chat.sessionChanged();
      // Assignment evidence belongs to the previous verified login.
      entry.chats.clear();
      if (revision === undefined && entry.target) {
        if (!isLmsLogin(entry.state.url)) {
          entry.view.setVisible(false);
          if (!entry.state.loading) revealPage(entry);
        }
        clearContext(entry, "login", "e-Class 로그인을 다시 확인해 주세요.");
      } else if (revision !== undefined && entry.target && entry.state.assignmentState === "login") {
        void loadAssignment(entry, entry.target, "verify-first");
      }
    }
  }

  ipcMain.handle("ast:assignment-font-size", async (event, expected: unknown) => {
    options.verifyMain(event);
    requireFontSizeSession(expected);
    await Promise.all([fontSizeRead, fontSizeWrite]);
    requireFontSizeSession(expected);
    return assignmentFontSize;
  });
  ipcMain.handle("ast:save-assignment-font-size", (event, size: unknown, expected: unknown) => {
    options.verifyMain(event);
    requireFontSizeSession(expected);
    const saved = Promise.all([fontSizeRead, fontSizeWrite]).then(async () => {
      const directory = requireFontSizeSession(expected);
      const fontSize = await saveAssignmentFontSize(size, directory);
      requireFontSizeSession(expected);
      publishFontSize(fontSize);
      return fontSize;
    });
    fontSizeWrite = saved.catch(() => {});
    return saved;
  });
  ipcMain.handle("ast:assignment-open", (event, value: unknown) => {
    if (!sender(event)) options.verifyMain(event);
    const target = assignmentTarget(value);
    return target ? open(target) : false;
  });
  ipcMain.handle("ast:assignment-prepare", (event, value: unknown, request: unknown, revision: unknown) => {
    options.verifyMain(event);
    const requested = assignmentTarget(value);
    if (shuttingDown || !requested?.courseId || typeof request !== "number" || !Number.isSafeInteger(request) ||
        typeof revision !== "number" || revision !== screenData.confirmedSessionRevision) return false;
    clearPreparedAssignment(true);
    const { target, mode, found } = resolveAssignment(requested);
    const existing = found && !needsAssignmentLoad(found, target) ? found : undefined;
    const entry = existing ?? create({ target }, false);
    const owner = event.sender;
    const cancel = () => { clearPreparedAssignment(true); };
    preparedAssignment = { owner, request, entry, target, mode, cancel };
    owner.once("destroyed", cancel);
    owner.once("render-process-gone", cancel);
    if (!existing) void loadAssignment(entry, target, mode);
    return true;
  });
  ipcMain.handle("ast:assignment-show-prepared", (event, request: unknown) => {
    options.verifyMain(event);
    if (shuttingDown || !preparedAssignment || preparedAssignment.owner !== event.sender || preparedAssignment.request !== request) return false;
    const { entry, target, mode } = clearPreparedAssignment(false)!;
    if (entry.window.isDestroyed() || entry.view.webContents.isDestroyed()) return open(target);
    showAssignmentTab(entry, target, mode);
    return true;
  });
  ipcMain.handle("ast:assignment-cancel-prepared", (event, request: unknown) => {
    options.verifyMain(event);
    if (preparedAssignment?.owner === event.sender && preparedAssignment.request === request) clearPreparedAssignment(true);
  });
  ipcMain.handle("ast:assignment-browser-get", async (event) => {
    await fontSizeRead;
    return browserState(requireSender(event).group);
  });
  ipcMain.handle("ast:assignment-browser-tab", (event, command: unknown, id: unknown) => {
    const { group } = requireSender(event);
    const tab = typeof id === "number" ? group.tabs.get(id) : undefined;
    if (!tab) return;
    if (command === "select") selectTab(tab);
    else if (command === "close") removeTab(tab);
  });
  ipcMain.handle("ast:assignment-browser-navigate", (event, value: unknown) => navigate(requireSender(event), value));
  ipcMain.handle("ast:assignment-attachment-open", (event, tabId: unknown, courseId: unknown, assignmentId: unknown, attachmentId: unknown) =>
    openAttachment(requireSender(event), tabId, courseId, assignmentId, attachmentId));
  ipcMain.handle("ast:assignment-analysis-retry", (event, tabId: unknown, courseId: unknown, assignmentId: unknown) => {
    const entry = requireSender(event);
    const assignment = entry.state.assignment;
    if (tabId === entry.group.activeTabId && assignment?.courseId === courseId && assignment?.assignmentId === assignmentId) {
      return analyzeAssignment(entry, true);
    }
  });
  ipcMain.handle("ast:assignment-attachment-close", (event, tabId: unknown, previewId: unknown) => {
    const entry = requireSender(event);
    if (tabId !== entry.group.activeTabId || !entry.attachmentPreview || entry.attachmentPreview.id !== previewId) return;
    closeAttachment(entry);
    update(entry);
  });
  ipcMain.handle("ast:assignment-attachment-download", (event, tabId: unknown, previewId: unknown) => {
    const entry = requireSender(event);
    const preview = entry.attachmentPreview;
    const revision = screenData.confirmedSessionRevision;
    if (!preview || preview.id !== previewId || revision === undefined) return false;
    return preview.download(entry.window, () => !entry.window.isDestroyed() && tabId === entry.group.activeTabId &&
      entry.attachmentPreview === preview && screenData.confirmedSessionRevision === revision);
  });
  ipcMain.handle("ast:assignment-browser-command", async (event, command: unknown) => {
    const entry = requireSender(event);
    const contents = entry.view.webContents;
    if (command === "login") {
      if (confirming) return;
      loginWindow = undefined;
      screenData.invalidateSession();
      const revision = screenData.status.sessionRevision;
      clearContext(entry, "login", "e-Class에서 로그인하면 과제를 이어서 열어요.");
      if (options.activeDirectory) {
        try { await web.clearLoginCookies(); }
        catch {
          update(entry, { assignmentMessage: "로그인 창을 초기화하지 못했어요. 다시 시도해 주세요." });
          return;
        }
      }
      if (entry.window.isDestroyed() || screenData.status.sessionRevision !== revision) return;
      entry.loginId = undefined;
      loginWindow = entry;
      loadUrl(entry, loginUrl);
    } else if (command === "resume" && entry.target) {
      const pageOpen = !entry.state.error && !entry.state.loading &&
        assignmentIdFromUrl(contents.getURL()) === entry.target.assignmentId;
      await loadAssignment(entry, entry.target, pageOpen && entry.state.assignmentState === "unavailable" ? "panel-only" : "verify-first");
    } else if (command === "retry" && entry.state.canRetryNavigation && entry.retryUrl) {
      if (entry.courseHome?.url === entry.retryUrl && contents.getURL() === entry.retryUrl &&
          courseNoticeIdFromUrl(new URL(entry.retryUrl))) {
        await openNativeNotice(entry, entry.retryUrl);
        return;
      }
      const assignmentId = assignmentIdFromUrl(entry.retryUrl);
      if (assignmentId && entry.prepared?.assignmentId !== assignmentId) await navigate(entry, entry.retryUrl);
      else loadUrl(entry, entry.retryUrl);
    } else if (command === "reload") {
      if (!contents.getURL() && entry.target) await loadAssignment(entry, entry.target, "verify-first");
      else contents.reload();
    } else if (command === "back" || command === "forward") {
      const history = contents.navigationHistory;
      const offset = command === "back" ? -1 : 1;
      if (!history.canGoToOffset(offset)) return;
      const index = history.getActiveIndex() + offset;
      const id = assignmentIdFromUrl(history.getEntryAtIndex(index)?.url ?? "");
      const course = id && courseByAssignment.get(id);
      if (course) entry.course = course;
      history.goToIndex(index);
    }
  });
  ipcMain.on("ast:assignment-browser-layout", (event, value: unknown) => {
    const entry = sender(event);
    if (!entry || !value || typeof value !== "object") return;
    const { x, y, width, height } = value as Rectangle;
    if (![x, y, width, height].every((part) => Number.isFinite(part) && part >= 0 && part <= 20_000)) return;
    entry.group.layout = { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
    fit(entry);
  });

  return {
    open, openBrowser, openCourseNotice, openCourseNoticeLink, openCoursePage, sessionChanged,
    get busy() {
      return entries().some(({ window, chats }) => !window.isDestroyed() &&
        (window.isFocused() || [...chats.values()].some((chat) => chat.busy)));
    },
    chat: (event: IpcMainInvokeEvent) => sender(event)?.activeChat,
    close() {
      shuttingDown = true;
      analysis.sessionChanged();
      clearPreparedAssignment(true);
      for (const { window } of windows.values()) if (!window.isDestroyed()) window.destroy();
    },
  };
}
