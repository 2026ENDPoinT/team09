import { BrowserWindow, ipcMain, screen, session, type IpcMainEvent, type IpcMainInvokeEvent, type Rectangle } from "electron";
import { fileURLToPath, pathToFileURL } from "node:url";
import { AssistSession } from "./assist.js";
import { GptAssist } from "./gpt.js";
import { SonioxStream } from "./soniox.js";
import { chatQuestionLimit, type ChatRect, type ChatView, type Explanation, type LectureRecord, type LiveEvent, type Result } from "../../shared/live-lecture.js";
import { LectureRecording } from "./archive.js";

const preload = fileURLToPath(new URL("preload.cjs", import.meta.url));
const overlayPartition = "ast-live-lecture-overlay";
const chatPartition = "ast-live-lecture-chat";
const mainSize = { width: 556, height: 424 };
const chatSize = { width: 420, height: 560 };
const launcherHeight = 79;
const chatMargin = 18;
const mainMinimum = { width: 410, height: 300 };
const chatMinimum = { width: 310, height: 290 };
const margin = 14;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}

function fitSize(value: number, minimum: number, available: number) {
  return Math.max(1, clamp(value, minimum, available));
}

function resizeSize(value: unknown) {
  if (!value || typeof value !== "object" || !("width" in value) || !("height" in value)) return;
  const { width, height } = value;
  if (typeof width === "number" && typeof height === "number" && Number.isInteger(width) && Number.isInteger(height)) {
    return { width, height };
  }
}

function options(bounds: Rectangle, partition: string): Electron.BrowserWindowConstructorOptions {
  return {
    ...bounds, show: false, frame: false, resizable: false, maximizable: false,
    fullscreenable: false, minimizable: false, alwaysOnTop: true, hasShadow: true,
    // A macOS panel can join full-screen Spaces without changing AST's activation policy.
    ...(process.platform === "darwin" ? { type: "panel", acceptFirstMouse: true } : {}),
    backgroundColor: "#ffffff",
    webPreferences: { preload, partition, sandbox: true, contextIsolation: true, nodeIntegration: false,
      backgroundThrottling: false },
  };
}

function harden(window: BrowserWindow) {
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
}

type WindowOptions = {
  rendererPath: string;
  config: { soniox: string; openai: string; sttModel: string; model: string };
  owner: BrowserWindow;
  hidden?: boolean;
  saveRecording?: (record: LectureRecord) => Promise<void>;
  onCreate?: (windows: { primary: BrowserWindow; chat: BrowserWindow; close(): void }) => void;
};

export async function openLiveLecture({ rendererPath, config, owner, hidden = false, saveRecording, onCreate }: WindowOptions) {
  const rendererUrl = pathToFileURL(rendererPath).href;
  function trusted(event: IpcMainEvent | IpcMainInvokeEvent, window: BrowserWindow, hash = "") {
    return !window.isDestroyed() && event.sender === window.webContents
      && event.senderFrame === event.sender.mainFrame && event.senderFrame?.url === rendererUrl + hash;
  }
  const display = screen.getDisplayMatching(owner.getBounds()).workArea;
  const width = fitSize(mainSize.width, mainMinimum.width, display.width - 2 * margin);
  const height = fitSize(mainSize.height, mainMinimum.height, display.height - 2 * margin);
  const primary = new BrowserWindow(options({
    x: display.x + display.width - width - margin, y: display.y + margin, width, height,
  }, overlayPartition));
  harden(primary);
  if (process.platform === "linux") primary.setVisibleOnAllWorkspaces(true);
  const chat = new BrowserWindow({
    ...options({ x: display.x, y: display.y + display.height - launcherHeight, width: display.width, height: launcherHeight }, chatPartition),
    transparent: true, backgroundColor: "#00000000", hasShadow: false, skipTaskbar: true,
  });
  harden(chat);
  if (process.platform === "linux") chat.setVisibleOnAllWorkspaces(true);
  let preferredChatSize = chatSize;
  let chatOpen = false;
  let chatExpanded = false;
  let chatRevision = 0;
  let chatCloseTimer: ReturnType<typeof setTimeout> | undefined;
  let chatCapturing = false;
  let ignoresMouse = false;
  let closing = false;
  let stream: SonioxStream | undefined;
  let streamNumber = 0;
  let recording: LectureRecording | undefined;
  let chatRecording: LectureRecording | undefined;
  let transition: "pause" | "stop" | undefined;

  const capture = session.fromPartition(overlayPartition);
  const chatSession = session.fromPartition(chatPartition);
  chatSession.setPermissionCheckHandler(() => false);
  chatSession.setPermissionRequestHandler((_contents, _permission, respond) => respond(false));
  capture.setPermissionCheckHandler((contents, permission, _origin, request) =>
    contents === primary.webContents && permission === "media" && request.isMainFrame && request.mediaType === "audio"
    && request.requestingUrl === rendererUrl);
  capture.setPermissionRequestHandler((contents, permission, respond, request) => {
    const media = request as Electron.MediaAccessPermissionRequest;
    respond(contents === primary.webContents && permission === "media" && media.isMainFrame && media.requestingUrl === rendererUrl
      && media.mediaTypes?.length === 1 && media.mediaTypes[0] === "audio");
  });

  function send(window: BrowserWindow | undefined, event: LiveEvent) {
    if (window && !window.isDestroyed()) window.webContents.send("ast:live-lecture:event", event);
  }

  function chatLayout() {
    const area = screen.getDisplayMatching(primary.getBounds()).workArea;
    const width = fitSize(preferredChatSize.width, chatMinimum.width, area.width - 2 * chatMargin);
    const height = fitSize(preferredChatSize.height, chatMinimum.height, area.height - launcherHeight - chatMargin);
    const layerHeight = chatExpanded ? height + launcherHeight + chatMargin : launcherHeight;
    const bounds = { x: area.x, y: area.y + area.height - layerHeight, width: area.width, height: layerHeight };
    const spotlightWidth = Math.min(480, Math.max(100, area.width - 2 * (chatMargin + 60)));
    const view: ChatView = {
      open: chatOpen, revision: chatRevision,
      spotlight: { left: Math.round((area.width - spotlightWidth) / 2), top: layerHeight - chatMargin - 51, width: spotlightWidth, height: 51 },
      orb: { left: area.width - chatMargin - 51, top: layerHeight - chatMargin - 51, width: 51, height: 51 },
      panel: { left: area.width - chatMargin - width, top: layerHeight - launcherHeight - height, width, height },
    };
    return { bounds, view };
  }

  let layout = chatLayout();

  function updateChatPointer() {
    if (hidden || closing || chat.isDestroyed()) return;
    const { x, y } = screen.getCursorScreenPoint();
    const { bounds, view } = layout;
    const left = x - bounds.x;
    const top = y - bounds.y;
    const inside = (rect: ChatRect) => left >= rect.left && left < rect.left + rect.width
      && top >= rect.top && top < rect.top + rect.height;
    const ignore = !chatCapturing && !inside(view.orb) && !inside(chatOpen ? view.panel : view.spotlight);
    if (ignore !== ignoresMouse) {
      chat.setIgnoreMouseEvents(ignore);
      ignoresMouse = ignore;
    }
  }

  function positionChat() {
    if (closing || chat.isDestroyed()) return;
    const next = chatLayout();
    if (JSON.stringify(next) === JSON.stringify(layout)) return;
    layout = next;
    const { bounds, view } = layout;
    chat.setBounds(bounds);
    updateChatPointer();
    send(chat, { type: "chat-view", view });
    send(primary, { type: "chat-view", view });
  }

  function finishChatClose(revision: number) {
    if (chatOpen || revision !== chatRevision || !chatExpanded) return;
    clearTimeout(chatCloseTimer);
    chatExpanded = false;
    positionChat();
  }

  function setChatOpen(open: boolean) {
    if (chatOpen === open) return;
    clearTimeout(chatCloseTimer);
    chatOpen = open;
    chatExpanded = true;
    chatCapturing = false;
    const revision = ++chatRevision;
    positionChat();
    if (open && !hidden && chat.isVisible()) chat.moveTop();
    if (!open) chatCloseTimer = setTimeout(() => finishChatClose(revision), 700);
  }

  function showExplanation(explanation: Explanation | null) {
    if (explanation) {
      if (explanation.turn !== shownTurn) chatRecording = recording;
      chatRecording?.updateChat(explanation);
      if (chatRecording && (explanation.turn !== shownTurn || explanation.state !== "loading")) saveEnded(chatRecording);
    }
    if (closing || primary.isDestroyed()) return;
    if (explanation && explanation.turn !== shownTurn) setChatOpen(true);
    shownTurn = explanation?.turn;
    send(primary, { type: "explanation", explanation });
    send(chat, { type: "explanation", explanation });
  }

  let shownTurn: number | undefined;
  const assistant = new AssistSession(new GptAssist(config.openai, config.model), {
    state: (state) => send(primary, { type: "state", state }),
    captions: (captions) => send(primary, { type: "captions", captions }),
    explanation: showExplanation,
    archiveSegment: (segment) => { recording?.segments.push(segment); },
    archiveSuggestions: (suggestions) => {
      if (!recording) return;
      recording.suggestions.push(...suggestions);
      saveEnded(recording);
    },
    demoEnded: () => endCapture(),
  });

  primary.on("move", positionChat);
  screen.on("display-metrics-changed", positionChat);
  screen.on("display-added", positionChat);
  screen.on("display-removed", positionChat);
  const pointerTimer = hidden ? undefined : setInterval(updateChatPointer, 30);
  const channels: string[] = [];

  function handle(name: string, allowed: "primary" | "chat" | "both", action: (value: unknown, window: BrowserWindow) => unknown) {
    const channel = "ast:live-lecture:" + name;
    channels.push(channel);
    ipcMain.handle(channel, (event, value: unknown) => {
      if (allowed !== "chat" && trusted(event, primary)) return action(value, primary);
      if (allowed !== "primary" && trusted(event, chat, "#chat")) return action(value, chat);
      throw new Error("라이브 해설 창에서만 실행할 수 있어요.");
    });
  }

  function saveEnded(record: LectureRecording) {
    if (!record.ended || !saveRecording) return;
    void saveRecording(record.snapshot(record.ended.at, record.ended.duration)).catch(() => {
      if (!closing) assistant.update({ message: "강의록을 저장하지 못했어요. 저장 공간을 확인해 주세요." });
    });
  }

  function sealRecording(endedAt = Date.now()) {
    if (!recording || recording.ended) return;
    const { startedAt, elapsedMs } = assistant.current;
    recording.ended = { at: endedAt, duration: elapsedMs + (startedAt === null ? 0 : endedAt - startedAt) };
    saveEnded(recording);
  }

  function captureEnded(message?: string) {
    stream = undefined;
    const paused = transition === "pause";
    transition = undefined;
    if (paused) assistant.phase("paused", message);
    else {
      assistant.phase(message ? "error" : "ended", message);
      sealRecording();
    }
  }

  function connect() {
    const offset = Math.max(assistant.current.elapsedMs, assistant.current.segments.at(-1)?.endMs ?? 0);
    const prefix = `${++streamNumber}-`;
    stream = new SonioxStream(config.soniox, config.sttModel, {
      ready: () => { if (!transition) assistant.phase("listening"); },
      reconnect: (attempt) => assistant.phase("reconnecting", `Soniox에 다시 연결 중이에요 · ${attempt}/3`),
      gap: () => assistant.update({ gaps: assistant.current.gaps + 1 }),
      captions: (captions) => assistant.setCaptions(captions),
      final: (segment) => assistant.add({ ...segment, id: prefix + segment.id, startMs: offset + segment.startMs, endMs: offset + segment.endMs }),
      ended: captureEnded,
    });
    stream.start();
  }

  function begin(demo: boolean): Result {
    const { phase } = assistant.current;
    if (!["idle", "ended", "error"].includes(phase)) {
      return { ok: false, message: "현재 강의가 끝난 뒤 다시 시작해 주세요." };
    }
    if (!demo && (!config.soniox || !config.openai)) return { ok: false, message: "AST의 .env에 Soniox와 OpenAI 키를 설정해 주세요." };
    if (!demo && !saveRecording) return { ok: false, message: "ASTRA에 로그인한 뒤 강의 해설을 시작해 주세요." };
    recording = demo ? undefined : new LectureRecording();
    assistant.begin(demo);
    if (!demo) connect();
    return { ok: true };
  }

  function endCapture() {
    if (["idle", "ended", "error", "stopping", "pausing"].includes(assistant.current.phase)) return;
    transition = "stop";
    assistant.phase("stopping");
    if (stream) stream.stop();
    else captureEnded();
  }

  handle("config", "primary", () => ({ soniox: !!config.soniox, openai: !!config.openai }));
  handle("state", "primary", () => assistant.current);
  handle("start", "primary", () => begin(false));
  handle("resume", "primary", (): Result => {
    if (assistant.current.phase !== "paused") return { ok: false, message: "일시 중지한 강의가 없어요." };
    assistant.resume();
    if (!assistant.current.demo) connect();
    return { ok: true };
  });
  handle("demo", "primary", () => begin(true));
  handle("pause", "primary", () => {
    if (!["connecting", "listening", "reconnecting"].includes(assistant.current.phase)) return;
    transition = "pause";
    assistant.phase("pausing");
    if (stream) stream.stop();
    else captureEnded();
  });
  handle("stop", "primary", endCapture);
  handle("explain", "both", (value) => {
    if (!value || typeof value !== "object") return;
    const { id, followUp } = value as { id?: unknown; followUp?: unknown };
    if (typeof id !== "string" || id.length >= 120) return;
    if (followUp === undefined || (typeof followUp === "string" && followUp.length <= 100)) {
      if (assistant.explain(id, followUp) === true) setChatOpen(true);
    }
  });
  handle("explain-recent", "primary", () => { if (assistant.explainRecent() === true) setChatOpen(true); });
  handle("explain-utterance", "primary", (id) => {
    if (typeof id === "string" && id.length < 120 && assistant.explainUtterance(id) === true) setChatOpen(true);
  });
  handle("explanation", "both", () => assistant.detail);
  handle("ask", "chat", (value) => {
    if (typeof value === "string" && value.length <= chatQuestionLimit && value.trim()) void assistant.ask(value.trim());
  });
  handle("chat-view", "chat", () => layout.view);
  handle("chat-open", "chat", (value) => { if (typeof value === "boolean") setChatOpen(value); });
  handle("chat-close-finished", "chat", (value) => { if (typeof value === "number") finishChatClose(value); });
  handle("chat-capture-pointer", "chat", (value) => {
    chatCapturing = value === true && chatOpen;
    updateChatPointer();
  });
  handle("resize", "both", (value, window) => {
    const size = resizeSize(value);
    if (!size) return;
    const main = primary.getBounds();
    const area = screen.getDisplayMatching(main).workArea;
    if (window === chat) {
      if (!chatOpen) return;
      preferredChatSize = {
        width: fitSize(size.width, chatMinimum.width, area.width - 2 * chatMargin),
        height: fitSize(size.height, chatMinimum.height, area.height - launcherHeight - chatMargin),
      };
      positionChat();
      return;
    }
    const width = fitSize(size.width, mainMinimum.width, area.width);
    const height = fitSize(size.height, mainMinimum.height, area.height - Math.max(0, main.y - area.y));
    const x = clamp(main.x + main.width - width, area.x, area.x + area.width - width);
    const y = clamp(main.y, area.y, area.y + area.height - height);
    primary.setBounds({ x, y, width, height });
  });
  handle("close", "primary", () => primary.close());

  const receiveAudio = (event: IpcMainEvent, value: unknown) => {
    if (!trusted(event, primary) || !(value instanceof ArrayBuffer) || value.byteLength < 2
      || value.byteLength > 8_000 || value.byteLength % 2 !== 0) return;
    stream?.push(value);
  };
  ipcMain.on("ast:live-lecture:audio", receiveAudio);

  function close() { if (!primary.isDestroyed()) primary.destroy(); }
  owner.once("closed", close);
  chat.once("closed", close);
  primary.once("closed", () => {
    const endedAt = Date.now();
    closing = true;
    owner.off("closed", close);
    chat.off("closed", close);
    stream?.dispose(true);
    sealRecording(endedAt);
    assistant.dispose();
    clearInterval(pointerTimer);
    clearTimeout(chatCloseTimer);
    screen.off("display-metrics-changed", positionChat);
    screen.off("display-added", positionChat);
    screen.off("display-removed", positionChat);
    capture.setPermissionCheckHandler(() => false);
    capture.setPermissionRequestHandler((_contents, _permission, respond) => respond(false));
    if (!chat.isDestroyed()) chat.destroy();
    ipcMain.removeListener("ast:live-lecture:audio", receiveAudio);
    for (const channel of channels) ipcMain.removeHandler(channel);
  });
  if (!hidden) {
    primary.once("ready-to-show", () => primary.showInactive());
    chat.once("ready-to-show", () => {
      updateChatPointer();
      chat.showInactive();
    });
  }
  try {
    const windows = { primary, chat, close };
    onCreate?.(windows);
    await Promise.all([primary.loadFile(rendererPath), chat.loadFile(rendererPath, { hash: "chat" })]);
    if (closing) throw new Error("강의 해설 창을 열기 전에 닫혔어요.");
    return windows;
  } catch (error) {
    close();
    throw error;
  }
}
