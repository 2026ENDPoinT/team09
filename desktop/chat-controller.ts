import { join } from "node:path";
import { app, ipcMain, shell, type BrowserWindow, type IpcMainInvokeEvent } from "electron";
import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { assignmentIdFromUrl, assignmentTarget, courseNoticeIdFromUrl, ECLASS_ORIGIN, isCourseId, type AssignmentDetails, type AssignmentTarget } from "../shared/assignment-browser.js";
import { campusNoticeLink, isCampusNoticeBoardPage, noticeWebLink } from "../shared/campus-notices.js";
import type { ChatCost, ChatEvent, ChatSource, ChatTranscriptTurn } from "../shared/chat.js";
import { ChatAgentError, runChatTurn, type ChatAgentDependencies } from "./chat-agent.js";
import { answerClassQuestion, classQuestion } from "./chat-class-guidance.js";
import { ChatCostLedger } from "./chat-cost.js";
import { historyTurn, trimHistory } from "./chat-history-context.js";
import { readChatSettings, saveChatSettings } from "./chat-settings.js";
import { toolProgress } from "./chat-tool-activity.js";
import { isPublicChatTool } from "./chat-tool-scope.js";
import { ChatTranscript } from "./chat-transcript.js";
import { readAssignmentSettings } from "./assignment-settings.js";
import type { ChatWorkspace } from "./chat-workspace.js";
import type { PdfInput, PdfNotesBundle } from "./assignment-pdf-notes.js";

type Context = {
  apiKey: string;
  getClient: () => Promise<Client>;
  callTool?: (name: string, args: Record<string, unknown>, options: { timeout: number; signal: AbortSignal }) => ReturnType<Client["callTool"]>;
  openAssignment?: (target: AssignmentTarget) => Promise<boolean>;
  openBrowser?: (url: URL) => boolean;
  openCourseNotice?: (courseId: string, noticeId: string, page?: number) => Promise<boolean>;
  assignment?: () => AssignmentDetails | undefined;
  assignmentAnalysis?: () => string | undefined;
  assignmentPdfNotes?: (assignment: AssignmentDetails, requirePdfNotes: boolean) => Promise<PdfNotesBundle | undefined>;
  openAssignmentPdf?: (assignment: AssignmentDetails, id: string, signal: AbortSignal) => Promise<PdfInput | undefined>;
  workspace?: ChatWorkspace;
  memoryOnly?: boolean;
  activeDirectory?: () => string | undefined;
  confirmedLmsSession: () => number | undefined;
  window: () => BrowserWindow | undefined;
};
type ActiveTurn = {
  id: string; question: string; controller: AbortController; results: string[]; cost?: ChatCost; sentAt: number; readAt?: number;
};

export function createChatSession(context: Context) {
  const { apiKey } = context;
  const hasApiKey = Boolean(apiKey);
  const settingsDirectory = () => context.activeDirectory ? context.activeDirectory() ?? null : app.getPath("userData");
  const transcriptPath = () => {
    const directory = settingsDirectory();
    return !context.memoryOnly && directory ? join(directory, "chat-history.json") : undefined;
  };
  let transcript = new ChatTranscript(transcriptPath());
  let sessionRevision = context.confirmedLmsSession();
  let history: unknown[] = [];
  let active: ActiveTurn | undefined;
  let savingSettings = false;
  let composing = false;

  function emit(event: ChatEvent) {
    const window = context.window();
    if (window && !window.isDestroyed()) window.webContents.send("ast:chat-event", event);
  }

  function finish(turn: ActiveTurn, state: ChatTranscriptTurn["state"], answer: string, sources: ChatSource[] = []) {
    if (active !== turn) return;
    active = undefined;
    const { id, question, results, cost, sentAt, readAt } = turn;
    const answeredAt = state === "done" ? Date.now() : undefined;
    const saved = transcript.append({ id, question, results, cost, state, answer, sources, sentAt, readAt, answeredAt });
    emit({ requestId: id, type: state, text: answer, sources, cost, readAt, answeredAt, storageError: !saved });
  }

  function stop(message = "답변을 중지했어요.") {
    if (!active) return;
    active.controller.abort();
    finish(active, "cancelled", message);
  }

  function sessionChanged() {
    const next = context.confirmedLmsSession();
    if (sessionRevision === next) return;
    sessionRevision = next;
    history = [];
    stop("LMS 로그인 상태가 바뀌어 답변을 중지했어요.");
    if (context.activeDirectory) transcript = new ChatTranscript(transcriptPath());
  }

  async function config() {
    return { ...await readChatSettings(settingsDirectory()), hasApiKey };
  }

  async function saveConfig(input: unknown) {
    if (active || savingSettings) throw new Error("진행 중인 작업이 끝난 뒤 설정을 저장해 주세요.");
    const directory = settingsDirectory();
    if (!directory) throw new Error("ASTRA에 로그인한 뒤 설정을 저장해 주세요.");
    savingSettings = true;
    try { return { ...await saveChatSettings(input, directory), hasApiKey }; }
    finally { savingSettings = false; }
  }

  async function send(id: unknown, question: unknown) {
    if (typeof id !== "string" || !/^[\w-]{1,80}$/.test(id) || typeof question !== "string" || !question.trim() || question.length > 8000) {
      return { ok: false, message: "질문은 8,000자 이내로 입력해 주세요." };
    }
    if (active || savingSettings) return { ok: false, message: "진행 중인 작업이 끝난 뒤 다시 보내 주세요." };
    if (!apiKey) return { ok: false, message: "프로젝트 .env에 OPENAI_API_KEY를 설정하고 앱을 다시 실행해 주세요." };
    sessionChanged();
    if (context.activeDirectory && !settingsDirectory()) return { ok: false, message: "ASTRA에 로그인한 뒤 질문해 주세요." };
    const confirmedSession = sessionRevision;
    const turn: ActiveTurn = { id, question: question.trim(), controller: new AbortController(), results: [], sentAt: Date.now() };
    active = turn;
    function markRead() {
      if (active !== turn || turn.readAt !== undefined) return;
      turn.readAt = Date.now();
      emit({ requestId: turn.id, type: "read", text: "", readAt: turn.readAt });
    }
    try {
      const directory = settingsDirectory();
      const [{ model, usdKrw }, assignmentSettings] = await Promise.all([
        readChatSettings(directory), readAssignmentSettings(directory),
      ]);
      if (active !== turn) return { ok: false, message: "요청이 취소됐어요." };
      const callTool: ChatAgentDependencies["callTool"] = async (name, args, signal) => {
        const allowed = () => isPublicChatTool(name) ||
          (confirmedSession !== undefined && context.confirmedLmsSession() === confirmedSession);
        const loginRequired = { status: "login_required", message: "내 강의실에서 로그인 확인을 마쳐 주세요." };
        if (!allowed()) return loginRequired;
        const client = await context.getClient();
        signal.throwIfAborted();
        if (!allowed()) return loginRequired;
        markRead();
        if (context.callTool) return context.callTool(name, args, { timeout: 180_000, signal });
        return client.callTool({ name, arguments: args }, undefined, { timeout: 180_000, signal });
      };
      const onProgress = (message: string) => { if (active === turn) emit({ requestId: id, type: "status", text: message }); };
      const workspace = context.workspace;
      const previous = transcript.snapshot().turns.at(-1);
      const intent = context.assignment ? undefined : classQuestion(turn.question);
      const signal = turn.controller.signal;
      const timetableTool = "get_course_timetable";
      if (intent) onProgress(toolProgress(timetableTool));
      const reply = intent ? answerClassQuestion(intent,
        (on_date) => callTool(timetableTool, { on_date, include_rooms: true }, signal), signal,
      ).then((text) => ({
        text, history: trimHistory([...history, historyTurn(turn.question, text, true)]),
        sources: [], cost: new ChatCostLedger(usdKrw).snapshot(),
      })) : runChatTurn({
        apiKey, model, question: turn.question, history, assignment: context.assignment?.(),
        assignmentAnalysis: context.assignmentAnalysis?.(), assignmentSettings, signal: turn.controller.signal, usdKrw,
        previousSources: previous?.state === "done" ? previous.sources : undefined,
        onCost: (cost) => { turn.cost = cost; },
        onProgress,
        onAccepted: markRead,
        onGenerating: () => { if (active === turn) emit({ requestId: id, type: "generating", text: "" }); },
        onAnswer: (text) => { if (active === turn) emit({ requestId: id, type: "answer", text }); },
        onResult: (message) => {
          if (active !== turn || turn.results.includes(message)) return;
          turn.results.push(message);
          emit({ requestId: id, type: "result", text: message });
        },
      }, {
        listTools: async () => (await (await context.getClient()).listTools()).tools,
        callTool,
        assignmentPdfNotes: context.assignmentPdfNotes,
        openAssignmentPdf: context.openAssignmentPdf,
        workspace: workspace && { dispatch: (name, args, signal) => {
          signal.throwIfAborted();
          if (context.confirmedLmsSession() !== confirmedSession) return Promise.resolve({ status: "error", message: "로그인 상태가 바뀌었어요." });
          markRead();
          return workspace.dispatch(name, args, signal);
        } },
      });
      void reply.then((result) => {
        if (active !== turn || turn.controller.signal.aborted) return;
        markRead();
        history = result.history;
        turn.cost = result.cost;
        finish(turn, "done", result.text, result.sources);
      }, (error: unknown) => {
        if (active !== turn) return;
        finish(turn, "error", error instanceof ChatAgentError ? error.message :
          "답변을 받지 못했어요. API 키·모델 접근 권한과 네트워크 상태를 확인한 뒤 다시 시도해 주세요.");
      });
      return { ok: true };
    } catch {
      if (active === turn) active = undefined;
      return { ok: false, message: "채팅을 시작하지 못했어요. 설정을 확인한 뒤 다시 시도해 주세요." };
    }
  }

  function cancel(id: unknown) {
    if (active?.id === id) stop();
  }

  function reset() {
    stop();
    transcript.clear();
    history = [];
  }

  async function openSource(value: unknown): Promise<boolean> {
    const url = noticeWebLink(value);
    if (!url) return false;
    const source = transcript.snapshot().turns.flatMap((turn) => turn.sources).find((item) => item.url === value);
    if (!source) return false;
    try {
      const assignmentId = assignmentIdFromUrl(url.href);
      if (assignmentId) {
        const target = assignmentTarget(source.assignment);
        return await context.openAssignment?.(target?.assignmentId === assignmentId ? target : { assignmentId }) ?? false;
      }
      const noticeId = courseNoticeIdFromUrl(url);
      const course = source.courseNotice;
      if (noticeId && course?.noticeId === noticeId && isCourseId(course.courseId)) {
        return await context.openCourseNotice?.(course.courseId, noticeId, course.page) ?? false;
      }
      if (url.origin === ECLASS_ORIGIN) return false;
      if (isCampusNoticeBoardPage(url) || campusNoticeLink(url.href) || source.noticeLink === true) {
        return context.openBrowser?.(url) ?? false;
      }
      if (url.protocol !== "https:" || !["www.seoultech.ac.kr", "housing.seoultech.ac.kr"].includes(url.hostname)) return false;
      await shell.openExternal(url.href);
      return true;
    } catch { return false; }
  }
  return { stop, sessionChanged, config, saveConfig, send, cancel, reset, openSource, snapshot: () => transcript.snapshot(),
    get busy() { return !!active || composing || savingSettings; },
    setComposing(value: boolean) { composing = value; } };
}

export function registerChatActions(context: Context & {
  verifySender: (event: IpcMainInvokeEvent) => void;
  otherChat?: (event: IpcMainInvokeEvent) => ReturnType<typeof createChatSession> | undefined;
}) {
  const main = createChatSession(context);
  function chat(event: IpcMainInvokeEvent) {
    const scoped = context.otherChat?.(event);
    if (scoped) return scoped;
    context.verifySender(event);
    return main;
  }
  ipcMain.handle("ast:chat-transcript", (event) => chat(event).snapshot());
  ipcMain.handle("ast:chat-config", (event) => chat(event).config());
  ipcMain.handle("ast:save-chat-config", (event, value) => chat(event).saveConfig(value));
  ipcMain.handle("ast:chat-send", (event, id, question) => chat(event).send(id, question));
  ipcMain.handle("ast:chat-cancel", (event, id) => chat(event).cancel(id));
  ipcMain.handle("ast:chat-reset", (event) => chat(event).reset());
  ipcMain.handle("ast:chat-source", (event, value) => chat(event).openSource(value));
  ipcMain.handle("ast:chat-composing", (event, value) => {
    context.verifySender(event);
    main.setComposing(value === true);
  });
  return main;
}
