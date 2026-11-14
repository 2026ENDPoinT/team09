import { randomUUID } from "node:crypto";
import { ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from "electron";
import type { WorkspaceAction, WorkspaceActionStatus } from "../shared/chat-workspace.js";

const statuses = new Set<unknown>(["ok", "unavailable", "assignment_missing", "browser_failed", "cancelled"]);

export function registerChatWorkspace(
  window: () => BrowserWindow | undefined,
  verifySender: (event: IpcMainInvokeEvent) => void,
) {
  const pending = new Map<string, (status: WorkspaceActionStatus) => void>();
  ipcMain.handle("ast:chat-workspace-result", (event, id: unknown, status: unknown) => {
    verifySender(event);
    if (typeof id === "string" && statuses.has(status)) pending.get(id)?.(status as WorkspaceActionStatus);
  });

  return (action: WorkspaceAction, signal: AbortSignal): Promise<WorkspaceActionStatus> => {
    const target = window();
    if (!target || target.isDestroyed() || signal.aborted) return Promise.resolve("cancelled");
    const contents = target.webContents;
    const id = randomUUID();
    return new Promise((resolve) => {
      const finish = (status: WorkspaceActionStatus) => {
        if (!pending.delete(id)) return;
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        contents.removeListener("destroyed", abort);
        contents.removeListener("render-process-gone", abort);
        resolve(status);
      };
      const cancel = (status: WorkspaceActionStatus) => {
        finish(status);
        if (!contents.isDestroyed()) {
          try { contents.send("ast:chat-workspace-action", { id }); }
          catch { /* The renderer can close while the request is being cancelled. */ }
        }
      };
      const abort = () => cancel("cancelled");
      const timer = setTimeout(() => cancel("unavailable"), 55_000);
      pending.set(id, finish);
      signal.addEventListener("abort", abort, { once: true });
      contents.once("destroyed", abort);
      contents.once("render-process-gone", abort);
      try { contents.send("ast:chat-workspace-action", { id, action }); }
      catch { finish("unavailable"); }
    });
  };
}
