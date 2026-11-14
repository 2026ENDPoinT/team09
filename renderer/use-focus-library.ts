import { useCallback, useEffect, useRef, useState } from "react";
import type { FocusLibrary, FocusLibraryEdit, FocusLibraryResult } from "../shared/focus-library.js";

type LibraryState = { revision: number; library?: FocusLibrary; message: string };

export function useFocusLibrary(revision: number, visible: boolean) {
  const [state, setState] = useState<LibraryState>();
  const [working, setWorking] = useState<number>();
  const request = useRef<{ revision: number } | null>(null);
  const library = state?.revision === revision ? state.library : undefined;
  const message = state?.revision === revision ? state.message : "";
  const busy = working === revision;

  const run = useCallback(async <T,>(
    action: () => Promise<FocusLibraryResult<T>>,
    onSuccess: (value: T) => Partial<LibraryState> = () => ({}),
  ): Promise<boolean> => {
    if (request.current?.revision === revision) return false;
    const id = { revision };
    request.current = id;
    setWorking(revision);
    const save = (update: Partial<LibraryState>) => {
      setState(current => ({ revision, library: current?.revision === revision ? current.library : undefined, message: "", ...update }));
    };
    save({});
    try {
      const result = await action();
      if (request.current !== id) return false;
      if (!result.ok) {
        save({ message: result.message });
        return false;
      }
      save(onSuccess(result.value));
      return true;
    } catch {
      if (request.current === id) save({ message: "내 파일 작업을 완료하지 못했어요. 다시 시도해 주세요." });
      return false;
    } finally {
      if (request.current === id) {
        request.current = null;
        setWorking(undefined);
      }
    }
  }, [revision]);

  const reload = useCallback(() => run(() => window.ast.getFocusLibrary(revision), value => ({ library: value })), [revision, run]);
  useEffect(() => {
    if (visible && state?.revision !== revision) void reload();
  }, [visible, revision, reload, state?.revision]);

  return {
    library, message, busy, loading: !library && (busy || state?.revision !== revision), reload,
    edit: (edit: FocusLibraryEdit) => run(() => window.ast.editFocusLibrary(revision, edit), value => ({ library: value })),
    importPdf: (folderId: string | null, onImported: (folder: string) => void) => run(() => window.ast.importFocusPdf(revision, folderId), result => {
      if (!result) return {};
      onImported(result.folderId);
      return { library: result.library };
    }),
    openPdf: async (id: string) => {
      if (await run(() => window.ast.openFocusPdf(revision, id))) await reload();
    },
  };
}
