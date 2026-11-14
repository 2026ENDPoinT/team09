import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { extname } from "node:path";
import { dialog, session, WebContentsView, type BrowserWindow, type Session } from "electron";

export type AssignmentAttachmentFile = {
  status: "ok";
  course_id: string;
  assignment_id: string;
  attachment_id: string;
  name: string;
  mime: string;
  size_bytes: number;
  base64: string;
};

type Preview = { mime: string; bytes: Buffer<ArrayBuffer> };
export type PreparedAssignmentAttachment = {
  id: string;
  open(): Promise<void>;
  download(window: BrowserWindow, current: () => boolean): Promise<boolean>;
  dispose(): void;
} & (
  | { kind: "pdf"; url: string; view?: undefined }
  | { kind: "preview"; view: WebContentsView }
  | { kind: "download"; view?: undefined }
);

const origin = "https://assignment-attachment.invalid";
const maxBytes = 32 * 1024 * 1024;
const maxTextBytes = 256 * 1024;
const textExtensions = new Set([
  ".txt", ".md", ".csv", ".tsv", ".log", ".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".java", ".kt", ".py",
  ".js", ".ts", ".jsx", ".tsx", ".json", ".xml", ".html", ".htm", ".css", ".sql", ".sh", ".swift", ".go", ".rs", ".rb",
  ".yaml", ".yml", ".ini", ".asm", ".s",
]);

function decodeFile(file: AssignmentAttachmentFile): Buffer<ArrayBuffer> | undefined {
  const { base64, size_bytes: size } = file;
  if (typeof file.name !== "string" || typeof file.mime !== "string" || typeof base64 !== "string" ||
      !Number.isSafeInteger(size) || size < 0 || size > maxBytes || base64.length !== Math.ceil(size / 3) * 4 ||
      /[^A-Za-z0-9+/=]/.test(base64)) return;
  const padding = (3 - size % 3) % 3;
  if (base64.indexOf("=") !== (padding ? base64.length - padding : -1) || !base64.endsWith("=".repeat(padding))) return;
  const bytes = Buffer.from(base64, "base64");
  if (bytes.length === size) return bytes;
}

function previewFile(file: AssignmentAttachmentFile, bytes: Buffer<ArrayBuffer>): Preview | undefined {
  const header = bytes.toString("latin1", 0, 12);
  if (header.startsWith("%PDF-")) return { mime: "application/pdf", bytes };
  if (header.startsWith("\x89PNG\r\n\x1a\n")) return { mime: "image/png", bytes };
  if (header.startsWith("\xff\xd8\xff")) return { mime: "image/jpeg", bytes };
  if (header.startsWith("GIF87a") || header.startsWith("GIF89a")) return { mime: "image/gif", bytes };
  if (header.startsWith("RIFF") && header.endsWith("WEBP")) return { mime: "image/webp", bytes };
  if (bytes.length >= 26 && header.startsWith("BM") && bytes.readUInt32LE(2) === bytes.length) return { mime: "image/bmp", bytes };

  if (file.mime.toLowerCase().startsWith("text/") || textExtensions.has(extname(file.name).toLowerCase())) {
    const sample = bytes.subarray(0, maxTextBytes);
    const truncated = sample.length < bytes.length;
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(sample, { stream: truncated });
    } catch {
      text = new TextDecoder("euc-kr").decode(sample, { stream: truncated });
    }
    if (truncated) text += "\n\n미리보기는 파일의 앞부분만 보여줘요.";
    return { mime: "text/plain; charset=utf-8", bytes: Buffer.from(text, "utf-8") };
  }
}

function downloadName(name: string): string {
  const basename = name.split(/[/\\]/).at(-1)?.replace(/[\u0000-\u001f\u007f]/g, "").trim() ?? "";
  return basename && basename !== "." && basename !== ".." ? basename.slice(0, 180) : "attachment";
}

export function createAssignmentAttachmentPreviewStore() {
  let isolated: Session | undefined;
  const responses = new Map<string, () => Response>();

  function getSession() {
    if (isolated) return isolated;
    isolated = session.fromPartition("ast-assignment-preview-" + randomUUID(), { cache: false });
    isolated.setPermissionRequestHandler((_contents, _permission, respond) => respond(false));
    isolated.setPermissionCheckHandler(() => false);
    isolated.protocol.handle("https", (request) => {
      const respond = request.method === "GET" ? responses.get(request.url) : undefined;
      return respond ? respond() : new Response(null, { status: 404 });
    });
    isolated.protocol.handle("http", () => new Response(null, { status: 404 }));
    return isolated;
  }

  function prepare(file: AssignmentAttachmentFile): PreparedAssignmentAttachment | undefined {
    const bytes = decodeFile(file);
    if (!bytes) return;
    const preview = previewFile(file, bytes);
    const isPdf = preview?.mime === "application/pdf";
    const id = randomUUID();
    const previewUrl = `${origin}/preview/${id}`;
    const responseHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
    const view = preview && !isPdf ? new WebContentsView({ webPreferences: {
      session: getSession(), sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true,
    } }) : undefined;
    const contents = view?.webContents;
    let disposed = false;
    let saving = false;

    if (preview) {
      responses.set(previewUrl, () => new Response(preview.bytes, { headers: {
        ...responseHeaders, "Content-Type": preview.mime, "Content-Length": String(preview.bytes.length),
        // Chromium renders PDF in its own privileged viewer. Other previews are inert documents.
        ...(!isPdf && { "Content-Security-Policy": "default-src 'none'" }),
      } }));
      contents?.setWindowOpenHandler(() => ({ action: "deny" }));
      contents?.on("will-navigate", (event) => event.preventDefault());
      contents?.on("will-redirect", (event) => event.preventDefault());
      contents?.once("destroyed", dispose);
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      responses.delete(previewUrl);
      if (contents && !contents.isDestroyed()) contents.close();
    }

    const actions = {
      id,
      async open() {
        if (!disposed && contents && !contents.isDestroyed()) await contents.loadURL(previewUrl);
      },
      async download(window: BrowserWindow, current: () => boolean) {
        if (disposed || saving || !current()) return false;
        saving = true;
        try {
          const { canceled, filePath } = await dialog.showSaveDialog(window, { defaultPath: downloadName(file.name) });
          if (canceled || !filePath || disposed || !current()) return false;
          await writeFile(filePath, bytes, { mode: 0o600 });
          return true;
        } finally {
          saving = false;
        }
      },
      dispose,
    };
    if (isPdf) return { kind: "pdf", url: previewUrl, ...actions };
    return view ? { kind: "preview", view, ...actions } : { kind: "download", ...actions };
  }

  return { prepare, getSession };
}
