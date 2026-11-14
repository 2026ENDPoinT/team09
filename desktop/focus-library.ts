import { createHash, randomUUID } from "node:crypto";
import { constants, createWriteStream } from "node:fs";
import { mkdir, open, readFile, rename, rm, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { focusFolderPath, type FocusFolder, type FocusImport, type FocusLibrary, type FocusLibraryItem, type FocusPdf } from "../shared/focus-library.js";

const pdfLimit = 100 * 1024 * 1024;
const idPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;

export class FocusLibraryError extends Error {}

function isId(value: unknown): value is string {
  return typeof value === "string" && idPattern.test(value);
}

function nameFor(value: unknown) {
  const name = typeof value === "string" ? value.normalize("NFC").trim() : "";
  if (!name || name.length > 160 || /[\p{Cc}/\\]/u.test(name) || name === "." || name === "..") {
    throw new FocusLibraryError("이름은 특수 경로 문자 없이 1~160자로 입력해 주세요.");
  }
  return name;
}

function validateItem(value: unknown): value is FocusLibraryItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<FocusLibraryItem>;
  return isId(item.id) && (item.parentId === null || isId(item.parentId)) && typeof item.name === "string" &&
    item.name.length > 0 && item.name.length <= 160 && typeof item.updatedAt === "number" && Number.isFinite(item.updatedAt) &&
    (item.lastOpenedAt === undefined || Number.isFinite(item.lastOpenedAt)) &&
    (item.kind === "folder" || (item.kind === "pdf" && item.parentId !== null && typeof item.digest === "string" && /^[0-9a-f]{64}$/.test(item.digest)));
}

export class FocusLibraryStore {
  private writes = Promise.resolve();

  constructor(private readonly root: string) {}

  async read(): Promise<FocusLibrary> {
    let raw: string;
    try {
      raw = await readFile(join(this.root, "catalog.json"), "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { version: 1, items: [] };
      throw error;
    }
    const data = JSON.parse(raw) as Partial<FocusLibrary> | null;
    if (data?.version !== 1 || !Array.isArray(data.items) || !data.items.every(validateItem)) throw new Error("Invalid focus library catalog");
    return { version: 1, items: data.items };
  }

  edit(input: unknown, current: () => boolean): Promise<FocusLibrary> {
    return this.queue(async () => {
      if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
      const library = await this.read();
      const { items } = library;
      if (!input || typeof input !== "object") throw new FocusLibraryError("파일 작업을 확인해 주세요.");
      const edit = input as Record<string, unknown>;
      if (edit.kind === "create") {
        const parentId = this.parent(items, edit.parentId);
        const name = nameFor(edit.name);
        this.unique(items, parentId, name);
        items.push({ kind: "folder", id: randomUUID(), parentId, name, updatedAt: Date.now() });
      } else if (edit.kind === "move-folders") {
        if (!Array.isArray(edit.ids) || !edit.ids.length || !edit.ids.every(isId)) {
          throw new FocusLibraryError("이동할 폴더를 선택해 주세요.");
        }
        this.moveFolders(items, edit.ids, edit.parentId);
      } else if (edit.kind === "visit-folder") {
        const folder = items.find(item => item.id === edit.id && item.kind === "folder");
        if (!folder) throw new FocusLibraryError("선택한 폴더를 찾을 수 없어요.");
        folder.lastOpenedAt = Date.now();
      } else {
        const item = items.find(entry => entry.id === edit.id);
        if (!item) throw new FocusLibraryError("선택한 항목을 찾을 수 없어요.");
        if (edit.kind === "rename") {
          const name = nameFor(edit.name);
          this.unique(items, item.parentId, name, item.id);
          item.name = name;
        } else if (edit.kind === "move" && item.kind === "folder") {
          this.moveFolders(items, [item.id], edit.parentId);
        } else throw new FocusLibraryError("이 항목에 사용할 수 없는 작업이에요.");
        item.updatedAt = Date.now();
      }
      await this.save(library, current);
      return library;
    });
  }

  importPdf(path: string, destination: unknown, current: () => boolean): Promise<FocusImport> {
    return this.queue(async () => {
      if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
      const library = await this.read();
      const parentId = this.parent(library.items, destination);
      const folderId = randomUUID();
      const folderPath = join(this.root, "documents", folderId);
      const source = join(folderPath, "source.pdf");
      const origin = await open(path, constants.O_RDONLY | constants.O_NONBLOCK);
      let saved = false;
      try {
        const info = await origin.stat();
        const header = Buffer.alloc(1024);
        if (!info.isFile() || info.size > pdfLimit) throw new FocusLibraryError("100MB 이하의 PDF 파일을 선택해 주세요.");
        const { bytesRead } = await origin.read(header, 0, header.length, 0);
        if (!header.subarray(0, bytesRead).includes("%PDF-")) {
          throw new FocusLibraryError("올바른 PDF 파일을 선택해 주세요.");
        }
        await mkdir(folderPath, { recursive: true, mode: 0o700 });
        const hash = createHash("sha256");
        let total = 0;
        const check = new Transform({ transform(chunk: Buffer, _encoding, callback) {
          total += chunk.length;
          if (total > pdfLimit) { callback(new FocusLibraryError("100MB 이하의 PDF 파일을 선택해 주세요.")); return; }
          if (!current()) { callback(new FocusLibraryError("로그인 상태가 바뀌었어요.")); return; }
          hash.update(chunk);
          callback(null, chunk);
        } });
        await pipeline(origin.createReadStream({ start: 0, autoClose: false }), check, createWriteStream(source, { flags: "wx", mode: 0o600 }));
        const digest = hash.digest("hex");
        if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
        const existing = library.items.find((item): item is FocusPdf => item.kind === "pdf" && item.digest === digest);
        if (existing) return { library, folderId: existing.parentId, pdfId: existing.id };
        const filename = basename(path).normalize("NFC").replace(/[\p{Cc}\\]/gu, "_");
        const stem = filename.replace(/\.pdf$/i, "").trim().slice(0, 140);
        const baseName = stem && stem !== "." && stem !== ".." ? stem : "학습 자료";
        let name = baseName;
        for (let suffix = 2; this.nameTaken(library.items, parentId, name); suffix++) name = `${baseName} (${suffix})`;
        const updatedAt = Date.now();
        const folder: FocusFolder = { kind: "folder", id: folderId, parentId, name, updatedAt };
        const pdf: FocusPdf = { kind: "pdf", id: randomUUID(), parentId: folderId, name: `${baseName}.pdf`, updatedAt, digest };
        library.items.push(folder, pdf);
        await this.save(library, current);
        saved = true;
        return { library, folderId, pdfId: pdf.id };
      } finally {
        await origin.close().catch(() => {});
        if (!saved) await rm(folderPath, { recursive: true, force: true }).catch(() => {});
      }
    });
  }

  async pdfPath(id: unknown) {
    return (await this.pdfDocument(id)).path;
  }

  async pdfDocument(id: unknown) {
    if (!isId(id)) throw new FocusLibraryError("PDF를 찾을 수 없어요.");
    const pdf = (await this.read()).items.find(item => item.kind === "pdf" && item.id === id);
    if (!pdf || pdf.kind !== "pdf") throw new FocusLibraryError("PDF를 찾을 수 없어요.");
    return { path: join(this.root, "documents", pdf.parentId, "source.pdf"), name: pdf.name };
  }

  recordPdfOpen(id: unknown, current: () => boolean): Promise<FocusLibrary> {
    return this.queue(async () => {
      const library = await this.read();
      const pdf = library.items.find(item => item.id === id && item.kind === "pdf");
      if (pdf?.kind !== "pdf") throw new FocusLibraryError("PDF를 찾을 수 없어요.");
      const openedAt = Date.now();
      pdf.lastOpenedAt = openedAt;
      for (const folder of focusFolderPath(library.items, pdf.parentId)) folder.lastOpenedAt = openedAt;
      await this.save(library, current);
      return library;
    });
  }

  private moveFolders(items: FocusLibraryItem[], ids: string[], destination: unknown) {
    const parentId = this.parent(items, destination);
    const folderIds = new Set(ids);
    const folders = items.filter(item => item.kind === "folder" && folderIds.has(item.id));
    if (folders.length !== folderIds.size) throw new FocusLibraryError("선택한 폴더를 찾을 수 없어요.");
    if (focusFolderPath(items, parentId).some(folder => folderIds.has(folder.id))) {
      throw new FocusLibraryError("이 폴더나 그 안의 하위 폴더로는 이동할 수 없어요.");
    }
    for (const folder of folders) {
      this.unique(items, parentId, folder.name, folder.id);
      folder.parentId = parentId;
      folder.updatedAt = Date.now();
    }
  }

  private parent(items: FocusLibraryItem[], value: unknown) {
    if (value === null) return null;
    if (!isId(value) || !items.some(item => item.kind === "folder" && item.id === value)) {
      throw new FocusLibraryError("저장할 폴더를 찾을 수 없어요.");
    }
    return value;
  }

  private nameTaken(items: FocusLibraryItem[], parentId: string | null, name: string, except?: string) {
    return items.some(item => item.parentId === parentId && item.id !== except && item.name.toLowerCase() === name.toLowerCase());
  }

  private unique(items: FocusLibraryItem[], parentId: string | null, name: string, except?: string) {
    if (this.nameTaken(items, parentId, name, except)) throw new FocusLibraryError("같은 이름의 항목이 이미 있어요.");
  }

  private queue<T>(task: () => Promise<T>): Promise<T> {
    const operation = this.writes.then(task);
    this.writes = operation.then(() => {}, () => {});
    return operation;
  }

  private async save(library: FocusLibrary, current: () => boolean) {
    await mkdir(this.root, { recursive: true, mode: 0o700 });
    const temporary = join(this.root, `catalog-${randomUUID()}.tmp`);
    try {
      await writeFile(temporary, JSON.stringify(library) + "\n", { flag: "wx", mode: 0o600 });
      if (!current()) throw new FocusLibraryError("로그인 상태가 바뀌었어요.");
      await rename(temporary, join(this.root, "catalog.json"));
    } finally {
      await rm(temporary, { force: true }).catch(() => {});
    }
  }
}
