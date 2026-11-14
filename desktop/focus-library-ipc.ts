import { BrowserWindow, dialog, ipcMain, type IpcMainInvokeEvent } from "electron";
import { join } from "node:path";
import type { FocusLibraryResult } from "../shared/focus-library.js";
import { AstStudyError, type AstStudy } from "./ast-study.js";
import { FocusLibraryError, FocusLibraryStore } from "./focus-library.js";

export function registerFocusLibrary(
  verifySender: (event: IpcMainInvokeEvent) => void,
  activeDirectory: () => string | undefined,
  activeRevision: () => number | undefined,
  study: Pick<AstStudy, "open">,
) {
  const stores = new Map<string, FocusLibraryStore>();
  let selecting = false;

  function handle<T, Args extends unknown[]>(channel: string, failure: string,
    action: (event: IpcMainInvokeEvent, store: FocusLibraryStore, current: () => boolean,
      session: { directory: string; revision: number }, ...args: Args) => Promise<T>) {
    ipcMain.handle(channel, async (event, expected: unknown, ...args: Args): Promise<FocusLibraryResult<T>> => {
      verifySender(event);
      const directory = activeDirectory();
      const revision = activeRevision();
      if (!directory || revision === undefined || revision !== expected) {
        return { ok: false, message: "ASTRA에 로그인한 뒤 내 파일을 이용해 주세요." };
      }
      let store = stores.get(directory);
      if (!store) {
        store = new FocusLibraryStore(join(directory, "focus-library"));
        stores.set(directory, store);
      }
      const current = () => revision === activeRevision() && directory === activeDirectory();
      try {
        const value = await action(event, store, current, { directory, revision }, ...args);
        if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
        return { ok: true, value };
      } catch (error) {
        return { ok: false, message: error instanceof FocusLibraryError || error instanceof AstStudyError ? error.message : failure };
      }
    });
  }

  handle("ast:focus-library", "내 파일을 불러오지 못했어요.", (_event, store) => store.read());
  handle("ast:focus-library-edit", "파일 변경 내용을 저장하지 못했어요.", (_event, store, current, _session, edit: unknown) => store.edit(edit, current));
  handle("ast:focus-pdf-import", "PDF를 가져오지 못했어요.", async (event, store, current, _session, destination: unknown) => {
    if (selecting) throw new FocusLibraryError("열려 있는 파일 선택 창을 먼저 닫아 주세요.");
    const parent = BrowserWindow.fromWebContents(event.sender);
    if (!parent) throw new Error("Missing focus library window");
    selecting = true;
    try {
      const selection = await dialog.showOpenDialog(parent, {
        title: "학습 자료 PDF 가져오기",
        filters: [{ name: "PDF 문서", extensions: ["pdf"] }],
        properties: ["openFile"],
      });
      return selection.canceled || !selection.filePaths[0] ? null : await store.importPdf(selection.filePaths[0], destination, current);
    } finally {
      selecting = false;
    }
  });
  handle("ast:focus-pdf-open", "학습 창에서 PDF를 열지 못했어요.", async (_event, store, current, session, id: unknown) => {
    const pdf = await store.pdfDocument(id);
    if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
    await study.open(session.directory, session.revision, pdf, current);
    await store.recordPdfOpen(id, current);
    return null;
  });
}
