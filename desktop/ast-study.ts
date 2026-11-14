import { spawn, type ChildProcessByStdio } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { createInterface } from "node:readline";
import type { Readable, Writable } from "node:stream";

const messages = {
  "invalid-request": "선택한 PDF를 학습 창에 전달하지 못했어요.",
  "pdf-open-failed": "학습 창에서 PDF를 열지 못했어요. 파일이 손상되었거나 암호로 보호되어 있는지 확인해 주세요.",
  cancelled: "학습 창에서 PDF 열기를 취소했어요.",
  busy: "학습 창에서 다른 PDF를 여는 중이에요. 잠시 뒤 다시 시도해 주세요.",
  closing: "학습 창을 닫는 중이에요. 잠시 뒤 다시 시도해 주세요.",
  "startup-failed": "AST 학습 창을 시작하지 못했어요. AST_Study의 실행 빌드를 확인해 주세요.",
  "shutdown-failed": "이전 학습 창의 작업을 정리하는 중이에요. 잠시 뒤 다시 시도해 주세요.",
};
const sessionChangedMessage = "로그인 상태가 바뀌었어요.";
const noAnswerMessage = "학습 창의 응답을 기다리는 시간이 초과됐어요. 잠시 뒤 다시 시도해 주세요.";
const disconnectedMessage = "AST 학습 창의 연결이 끊겼어요. PDF를 다시 열어 주세요.";

export class AstStudyError extends Error {}

type StudyPdf = { path: string; name: string };
type StudyOptions = { launcher: string; apiKey?: string };
type PendingOpen = { resolve: () => void; reject: (error: AstStudyError) => void; timer: NodeJS.Timeout };

class StudyProcess {
  private readonly child: ChildProcessByStdio<Writable, Readable, null>;
  private readonly ready: Promise<void>;
  private readonly done: Promise<void>;
  private readonly pending = new Map<number, PendingOpen>();
  private nextId = 0;
  private started = false;
  private stopped = false;
  private stopping?: Promise<void>;

  constructor(options: StudyOptions, readonly directory: string, readonly revision: number) {
    this.child = spawn(options.launcher, ["--ast-bridge", join(directory, "study")], {
      stdio: ["pipe", "pipe", "ignore"],
      env: { ...process.env, ...(options.apiKey ? { OPENAI_API_KEY: options.apiKey } : {}) },
    });
    const child = this.child;
    this.done = new Promise(resolve => child.once("close", () => {
      this.stopped = true;
      this.rejectPending(disconnectedMessage);
      resolve();
    }));
    const reader = createInterface({ input: child.stdout, crlfDelay: Infinity });
    this.ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        fail();
        child.kill();
      }, 20_000);
      const fail = () => {
        clearTimeout(timer);
        reject(new AstStudyError(messages["startup-failed"]));
      };
      child.once("error", fail);
      child.once("close", fail);
      reader.on("line", line => {
        let event: { type?: string; id?: number; code?: string };
        try {
          event = JSON.parse(line);
        } catch {
          return;
        }
        if (!event || typeof event !== "object") return;
        if (event.type === "ready") {
          clearTimeout(timer);
          this.started = true;
          resolve();
        } else if (event.type === "opened" || event.type === "error") {
          if (typeof event.id !== "number") {
            if (!this.started && event.type === "error") fail();
            return;
          }
          const pending = this.pending.get(event.id);
          if (!pending) return;
          this.pending.delete(event.id);
          clearTimeout(pending.timer);
          if (event.type === "opened") pending.resolve();
          else {
            const code = event.code;
            const message = code && Object.hasOwn(messages, code) ? messages[code as keyof typeof messages] : disconnectedMessage;
            pending.reject(new AstStudyError(message));
          }
        }
      });
    });
    void this.ready.catch(() => {});
    child.stdin.on("error", () => this.rejectPending(disconnectedMessage));
  }

  get closed() { return this.stopped; }

  async open(pdf: StudyPdf, current: () => boolean) {
    await this.ready;
    if (!current()) throw new AstStudyError(sessionChangedMessage);
    if (this.stopping || this.stopped) throw new AstStudyError(disconnectedMessage);
    const id = ++this.nextId;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new AstStudyError(noAnswerMessage));
      }, 60_000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, command: "open", ...pdf }) + "\n", error => {
        if (!error || !this.pending.delete(id)) return;
        clearTimeout(timer);
        reject(new AstStudyError(disconnectedMessage));
      });
    });
    if (!current()) throw new AstStudyError(sessionChangedMessage);
  }

  close(reason: string) {
    if (this.stopping) return this.stopping;
    if (this.stopped) return this.done;
    this.rejectPending(reason);
    // EOF gives the Java window the same save-and-close path if the command cannot be read.
    this.child.stdin.end(JSON.stringify({ id: ++this.nextId, command: "shutdown" }) + "\n");
    this.stopping = new Promise<void>(resolve => {
      const timer = setTimeout(() => {
        // Leave a ready JVM to finish saving study results and settling cancelled requests.
        if (!this.started) this.child.kill();
        this.child.unref();
        this.child.stdout.destroy();
        resolve();
      }, 90_000);
      void this.done.then(() => {
        clearTimeout(timer);
        resolve();
      });
    });
    return this.stopping;
  }

  private rejectPending(message: string) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new AstStudyError(message));
    }
    this.pending.clear();
  }
}

export class AstStudy {
  private active?: StudyProcess;
  private closing: Promise<void> = Promise.resolve();
  private closed = false;

  constructor(private readonly options: StudyOptions) {}

  async open(directory: string, revision: number, pdf: StudyPdf, current: () => boolean) {
    if (this.closed || !current()) throw new AstStudyError(sessionChangedMessage);
    await mkdir(join(directory, "study"), { recursive: true, mode: 0o700 });
    if (this.closed || !current()) throw new AstStudyError(sessionChangedMessage);
    this.sessionChanged(directory, revision);
    await this.closing;
    if (this.closed || !current()) throw new AstStudyError(sessionChangedMessage);
    if (!this.active || this.active.closed) this.active = new StudyProcess(this.options, directory, revision);
    return this.active.open(pdf, current);
  }

  sessionChanged(directory: string | undefined, revision: number | undefined) {
    const active = this.active;
    if (!active || (active.directory === directory && active.revision === revision)) return;
    this.active = undefined;
    this.closing = active.close(sessionChangedMessage);
  }

  close() {
    this.closed = true;
    const active = this.active;
    this.active = undefined;
    if (active) this.closing = active.close(messages.closing);
    return this.closing;
  }
}
