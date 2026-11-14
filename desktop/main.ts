import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { app, BrowserWindow, type IpcMainInvokeEvent } from "electron";
import { registerChatActions } from "./chat-controller.js";
import { loadChatApiKey } from "./chat-key.js";
import { removeLegacyChatKey } from "./chat-settings.js";
import { createLmsConnector } from "./lms-connector.js";
import { registerScreenActions } from "./screen-controller.js";
import { ScreenData } from "./screen-data.js";
import { registerAssignmentWindows } from "./assignment-windows.js";
import { accountDirectory } from "./account-data.js";
import { readLoginSettings } from "./login-settings.js";
import { registerFocusLibrary } from "./focus-library-ipc.js";
import { AstStudy } from "./ast-study.js";
import { registerStudyFontSettings } from "./study-font-settings.js";
import { createChatWorkspace } from "./chat-workspace.js";
import { registerChatWorkspace } from "./chat-workspace-ipc.js";
import { registerLiveLecture } from "./live-lecture/controller.js";

const projectRoot = app.getAppPath();
const desktopDir = dirname(fileURLToPath(import.meta.url));
const rendererPath = join(projectRoot, "dist", "index.html");
const rendererUrl = pathToFileURL(rendererPath).href;

let mainWindow: BrowserWindow | undefined;
let chat: ReturnType<typeof registerChatActions> | undefined;
let assignmentWindows: ReturnType<typeof registerAssignmentWindows> | undefined;
let screenActions: ReturnType<typeof registerScreenActions> | undefined;
let study: AstStudy | undefined;
let liveLecture: ReturnType<typeof registerLiveLecture> | undefined;
let quitting = false;
let shutdownComplete = false;

const accountRoot = join(app.getPath("userData"), "accounts");
const connector = createLmsConnector(projectRoot, join(app.getPath("userData"), "lms"), undefined, accountRoot);
const screenData = new ScreenData(connector.requestTool, (status) => {
  chat?.sessionChanged();
  assignmentWindows?.sessionChanged();
  screenActions?.sessionChanged();
  study?.sessionChanged(activeDirectory(), screenData.confirmedSessionRevision);
  liveLecture?.sessionChanged();
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("ast:prefetch-status", status);
}, {
  directory: (account) => accountDirectory(accountRoot, account),
  publicDirectory: app.getPath("userData"),
  busy: () => Boolean(chat?.busy || assignmentWindows?.busy),
});
function activeDirectory() {
  const account = screenData.account;
  return account ? accountDirectory(accountRoot, account) : undefined;
}

function verifySender(event: IpcMainInvokeEvent) {
  if (event.sender !== mainWindow?.webContents ||
      event.senderFrame !== event.sender.mainFrame ||
      event.senderFrame?.url !== rendererUrl) {
    throw new Error("허용된 AST 창에서만 요청할 수 있어요.");
  }
}

async function start() {
  const apiKey = await loadChatApiKey(projectRoot);
  if (apiKey) {
    await removeLegacyChatKey().catch(() => {
      console.warn("이전에 저장한 채팅 키를 정리하지 못했어요.");
    });
  }
  if (quitting) return;
  assignmentWindows = registerAssignmentWindows({
    rendererPath: join(projectRoot, "dist", "assignment-browser.html"), preload: join(desktopDir, "preload.cjs"),
    activeDirectory, apiKey, connector, screenData, verifyMain: verifySender,
  });
  screenActions = registerScreenActions(screenData, connector.requestTool, verifySender, (status) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("ast:astra-login-status", status);
  }, activeDirectory, assignmentWindows.openCourseNoticeLink, assignmentWindows.openCoursePage, assignmentWindows.openBrowser);
  chat = registerChatActions({
    apiKey, verifySender, getClient: connector.getClient, window: () => mainWindow,
    confirmedLmsSession: () => screenData.confirmedSessionRevision, activeDirectory,
    callTool: connector.callTool, openAssignment: assignmentWindows.open, otherChat: assignmentWindows.chat,
    openBrowser: assignmentWindows.openBrowser, openCourseNotice: assignmentWindows.openCourseNotice,
    workspace: createChatWorkspace({
      screenData, run: registerChatWorkspace(() => mainWindow, verifySender),
      openCoursePage: assignmentWindows.openCoursePage, openBrowser: assignmentWindows.openBrowser,
    }),
  });
  void screenActions.initialize(readLoginSettings);
  const studyRoot = app.isPackaged ? process.resourcesPath : projectRoot;
  study = new AstStudy({ launcher: join(studyRoot, "AST_Study", "run-study"), apiKey });
  registerFocusLibrary(verifySender, activeDirectory, () => screenData.confirmedSessionRevision, study);
  registerStudyFontSettings(verifySender, activeDirectory, () => screenData.confirmedSessionRevision);
  liveLecture = registerLiveLecture({
    projectRoot, rendererPath: join(projectRoot, "dist", "live-lecture.html"),
    apiKey, activeDirectory, sessionRevision: () => screenData.confirmedSessionRevision, verifyMain: verifySender,
  });
  createWindow();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    title: "Agent for SeoulTech",
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 540,
    backgroundColor: "#191d1d",
    ...(process.platform === "darwin" ? {
      titleBarStyle: "hidden",
      trafficLightPosition: { x: 16, y: 23 },
    } : {}),
    webPreferences: {
      preload: join(desktopDir, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event) => event.preventDefault());
  mainWindow.on("closed", () => { chat?.stop(); mainWindow = undefined; });
  void mainWindow.loadFile(rendererPath);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow && chat && !quitting) createWindow();
    if (mainWindow?.isMinimized()) mainWindow.restore();
    mainWindow?.focus();
  });
  app.on("activate", () => { if (!mainWindow && chat && !quitting) createWindow(); });
  void app.whenReady().then(start);
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    if (shutdownComplete) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    const savingLectures = liveLecture?.dispose();
    screenActions?.shutdown();
    const saving = screenData.shutdown();
    chat?.stop();
    assignmentWindows?.close();
    const closing = connector.close();
    void Promise.allSettled([closing, saving, savingLectures, study?.close()]).finally(() => {
      shutdownComplete = true;
      app.quit();
    });
  });
}
