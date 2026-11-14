import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { BrowserWindow, ipcMain, type IpcMainInvokeEvent } from "electron";
import type { LectureHistoryResult, LectureRecord, Result } from "../../shared/live-lecture.js";
import { loadRuntimeEnv } from "../chat-key.js";
import { readChatSettings } from "../chat-settings.js";
import { LectureArchive, validLectureId } from "./archive.js";
import { openLiveLecture } from "./windows.js";

type Options = {
  projectRoot: string;
  rendererPath: string;
  apiKey: string;
  activeDirectory: () => string | undefined;
  sessionRevision: () => number | undefined;
  verifyMain: (event: IpcMainInvokeEvent) => void;
  hidden?: boolean;
};

export function registerLiveLecture({ projectRoot, rendererPath, apiKey, activeDirectory, sessionRevision, verifyMain, hidden }: Options) {
  const channel = "ast:open-live-lecture";
  const historyChannel = "ast:live-lecture-history";
  const detailChannel = "ast:open-lecture-record";
  const readChannel = "ast:lecture-record";
  const details = new Map<string, { window: BrowserWindow; record: LectureRecord }>();
  const pendingWrites = new Map<string, Promise<void>>();
  let windows: Awaited<ReturnType<typeof openLiveLecture>> | undefined;
  let opening: Promise<Result> | undefined;
  let revision = 0;
  let accountRevision = sessionRevision();
  let disposed = false;

  function save(directory: string, record: LectureRecord, owner: BrowserWindow) {
    const path = join(directory, record.id);
    const write = (pendingWrites.get(path) ?? Promise.resolve()).catch(() => {}).then(() => new LectureArchive(directory).save(record));
    pendingWrites.set(path, write);
    void write.then(() => {
      if (archiveDirectory() !== directory) return;
      if (!owner.isDestroyed()) owner.webContents.send("ast:lecture-history-changed");
      const detail = details.get(record.id);
      if (detail && !detail.window.isDestroyed()) {
        detail.record = record;
        detail.window.webContents.send("ast:lecture-record-changed", record);
      }
    }).finally(() => { if (pendingWrites.get(path) === write) pendingWrites.delete(path); }).catch(() => {});
    return write;
  }

  function archiveDirectory() {
    const directory = activeDirectory();
    return directory ? join(directory, "live-lectures") : undefined;
  }

  async function open(owner: BrowserWindow, requestRevision: number): Promise<Result> {
    try {
      const directory = archiveDirectory();
      const [env, { model }] = await Promise.all([
        loadRuntimeEnv(projectRoot),
        readChatSettings(activeDirectory() ?? null),
      ]);
      if (requestRevision !== revision || owner.isDestroyed()) return { ok: false, message: "강의 해설 열기를 취소했어요." };
      const current = await openLiveLecture({
        owner, hidden, rendererPath,
        saveRecording: directory ? (record) => save(directory, record, owner) : undefined,
        config: {
          openai: apiKey, model,
          soniox: env.SONIOX_API_KEY?.trim() ?? "", sttModel: env.SONIOX_MODEL?.trim() || "stt-rt-v6",
        },
        onCreate: (created) => { windows = created; },
      });
      if (requestRevision !== revision || current.primary.isDestroyed()) {
        current.close();
        return { ok: false, message: "강의 해설 열기를 취소했어요." };
      }
      return { ok: true };
    } catch {
      return { ok: false, message: "강의 해설 창을 열지 못했어요. 다시 시도해 주세요." };
    }
  }

  ipcMain.handle(channel, (event): Promise<Result> | Result => {
    verifyMain(event);
    if (disposed) return { ok: false, message: "AST를 종료하고 있어요." };
    if (opening) return opening;
    if (windows && !windows.primary.isDestroyed()) {
      if (!hidden) windows.primary.showInactive();
      return { ok: true };
    }
    const owner = BrowserWindow.fromWebContents(event.sender);
    if (!owner) return { ok: false, message: "AST 창을 찾지 못했어요." };
    opening = open(owner, revision).finally(() => { opening = undefined; });
    return opening;
  });

  function historyDirectory(expected: unknown) {
    const directory = archiveDirectory();
    return !disposed && directory && typeof expected === "number" && expected === sessionRevision() ? directory : undefined;
  }

  ipcMain.handle(historyChannel, async (event, expected: unknown): Promise<LectureHistoryResult> => {
    verifyMain(event);
    const directory = historyDirectory(expected);
    if (!directory) return { ok: false, message: "ASTRA에 로그인한 뒤 강의록을 열어 주세요." };
    const currentRevision = revision;
    try {
      await Promise.allSettled([...pendingWrites].filter(([path]) => dirname(path) === directory).map(([, write]) => write));
      const records = await new LectureArchive(directory).list();
      if (revision === currentRevision && directory === historyDirectory(expected)) return { ok: true, records };
      return { ok: false, message: "로그인 상태가 바뀌었어요." };
    } catch { return { ok: false, message: "저장한 강의록 목록을 불러오지 못했어요." }; }
  });

  ipcMain.handle(detailChannel, async (event, expected: unknown, id: unknown): Promise<Result> => {
    verifyMain(event);
    const directory = historyDirectory(expected);
    if (!directory || !validLectureId(id)) return { ok: false, message: "열 수 있는 강의록이 없어요." };
    const owner = BrowserWindow.fromWebContents(event.sender);
    if (!owner) return { ok: false, message: "AST 창을 찾지 못했어요." };
    const currentRevision = revision;
    let window: BrowserWindow | undefined;
    try {
      await pendingWrites.get(join(directory, id));
      const record = await new LectureArchive(directory).read(id);
      if (owner.isDestroyed() || revision !== currentRevision || directory !== historyDirectory(expected)) {
        return { ok: false, message: "강의록 열기를 취소했어요." };
      }
      const existing = details.get(id);
      if (existing) {
        if (!hidden) existing.window.focus();
        return { ok: true };
      }
      window = new BrowserWindow({
        show: false, width: 1060, height: 720, minWidth: 540, minHeight: 370,
        backgroundColor: "#201923", title: "강의록 · AST",
        webPreferences: { preload: fileURLToPath(new URL("preload.cjs", import.meta.url)),
          sandbox: true, contextIsolation: true, nodeIntegration: false, partition: "ast-lecture-history" },
      });
      const detail = window;
      detail.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      detail.webContents.on("will-navigate", (navigation) => navigation.preventDefault());
      detail.webContents.session.setPermissionCheckHandler(() => false);
      detail.webContents.session.setPermissionRequestHandler((_contents, _permission, respond) => respond(false));
      details.set(id, { window: detail, record });
      const close = () => { if (!detail.isDestroyed()) detail.destroy(); };
      owner.once("closed", close);
      detail.once("closed", () => { details.delete(id); owner.off("closed", close); });
      await detail.loadFile(rendererPath, { hash: `record/${id}` });
      if (!hidden && !detail.isDestroyed()) detail.show();
      return { ok: true };
    } catch {
      if (window && !window.isDestroyed()) window.destroy();
      return { ok: false, message: "강의록 상세를 불러오지 못했어요." };
    }
  });

  ipcMain.handle(readChannel, (event): LectureRecord => {
    const detail = [...details.values()].find(({ window }) => window.webContents === event.sender);
    if (!detail || event.senderFrame !== event.sender.mainFrame
      || event.senderFrame?.url !== `${pathToFileURL(rendererPath).href}#record/${detail.record.id}`) {
      throw new Error("강의록 상세 창에서만 기록을 읽을 수 있어요.");
    }
    return detail.record;
  });

  function close() {
    revision++;
    windows?.close();
    windows = undefined;
    for (const { window } of details.values()) window.destroy();
  }

  return {
    sessionChanged() {
      const next = sessionRevision();
      if (next === accountRevision) return;
      accountRevision = next;
      close();
    },
    async dispose() {
      disposed = true;
      for (const name of [channel, historyChannel, detailChannel, readChannel]) ipcMain.removeHandler(name);
      close();
      await Promise.allSettled(pendingWrites.values());
    },
  };
}
