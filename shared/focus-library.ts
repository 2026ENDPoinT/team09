export type FocusFolder = {
  kind: "folder";
  id: string;
  parentId: string | null;
  name: string;
  updatedAt: number;
  lastOpenedAt?: number;
};

export type FocusPdf = {
  kind: "pdf";
  id: string;
  parentId: string;
  name: string;
  updatedAt: number;
  lastOpenedAt?: number;
  digest: string;
};

export type FocusLibraryItem = FocusFolder | FocusPdf;
export type FocusLibrary = { version: 1; items: FocusLibraryItem[] };

export type FocusLibraryEdit =
  | { kind: "create"; parentId: string | null; name: string }
  | { kind: "rename"; id: string; name: string }
  | { kind: "move"; id: string; parentId: string | null }
  | { kind: "move-folders"; ids: string[]; parentId: string | null }
  | { kind: "visit-folder"; id: string };

export type FocusImport = { library: FocusLibrary; folderId: string; pdfId: string };
export type FocusLibraryResult<T> = { ok: true; value: T } | { ok: false; message: string };

export type FocusLibraryBridge = {
  getFocusLibrary: (revision: number) => Promise<FocusLibraryResult<FocusLibrary>>;
  editFocusLibrary: (revision: number, edit: FocusLibraryEdit) => Promise<FocusLibraryResult<FocusLibrary>>;
  importFocusPdf: (revision: number, parentId: string | null) => Promise<FocusLibraryResult<FocusImport | null>>;
  openFocusPdf: (revision: number, id: string) => Promise<FocusLibraryResult<null>>;
};

export function focusFolderPath(items: FocusLibraryItem[], id: string | null): FocusFolder[] {
  const folders = new Map(items.flatMap(item => item.kind === "folder" ? [[item.id, item] as const] : []));
  const path: FocusFolder[] = [];
  const seen = new Set<string>();
  while (id !== null && !seen.has(id)) {
    const folder = folders.get(id);
    if (!folder) break;
    path.push(folder);
    seen.add(id);
    id = folder.parentId;
  }
  return path.reverse();
}
