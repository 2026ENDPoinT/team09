import { SCREEN_FRESHNESS_MS } from "../shared/screen-freshness.js";

export type ReadLane = "lms" | "campus" | "dorm";
export type ReadOptions = {
  lane: ReadLane;
  private?: boolean;
  force?: boolean;
  background?: boolean;
  retain?: boolean;
};

type Entry = { value: unknown; expiresAt: number; private: boolean };
type Job = {
  key: string;
  private: boolean;
  lane: ReadLane;
  background: boolean;
  retain: boolean;
  invalidated: boolean;
  loader: () => Promise<unknown>;
  promise: Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
};

export class StaleReadError extends Error {
  constructor() {
    super("로그인 상태가 바뀌었어요. 새 계정의 정보를 다시 불러와 주세요.");
    this.name = "StaleReadError";
  }
}

/** Process-local read results; each remote source runs one query at a time. */
export class ReadCache {
  private readonly entries = new Map<string, Entry>();
  private readonly pending = new Map<string, Job>();
  private readonly queues: Record<ReadLane, Job[]> = { lms: [], campus: [], dorm: [] };
  private readonly running: Partial<Record<ReadLane, Job>> = {};
  private readonly ttlMs: number;
  private readonly maxEntries: number;
  private readonly now: () => number;

  constructor(options: { ttlMs?: number; maxEntries?: number; now?: () => number } = {}) {
    this.ttlMs = options.ttlMs ?? SCREEN_FRESHNESS_MS;
    this.maxEntries = options.maxEntries ?? 128;
    this.now = options.now ?? Date.now;
    if (!Number.isFinite(this.ttlMs) || this.ttlMs < 0 || !Number.isInteger(this.maxEntries) || this.maxEntries < 1) {
      throw new RangeError("캐시 보관 시간과 개수를 확인해 주세요.");
    }
  }

  read<T>(key: string, loader: () => Promise<T>, options: ReadOptions): Promise<T> {
    const scopedKey = `${options.private ? "private" : "public"}:${key}`;
    const existing = this.pending.get(scopedKey);
    if (existing) {
      // A tab opened during prefetch joins that exact request and moves it ahead
      // of queued background jobs instead of issuing a duplicate school query.
      if (!options.background) existing.background = false;
      return existing.promise as Promise<T>;
    }
    const cached = this.entries.get(scopedKey);
    if (!options.force && cached && cached.expiresAt > this.now()) {
      this.entries.delete(scopedKey);
      this.entries.set(scopedKey, cached);
      return Promise.resolve(cached.value as T);
    }
    let resolve!: (value: unknown) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<unknown>((accept, decline) => { resolve = accept; reject = decline; });
    const job: Job = {
      key: scopedKey, private: Boolean(options.private), lane: options.lane,
      background: Boolean(options.background), retain: options.retain !== false, invalidated: false,
      loader, promise, resolve, reject,
    };
    this.pending.set(scopedKey, job);
    this.queues[job.lane].push(job);
    this.pump(job.lane);
    return promise as Promise<T>;
  }

  fresh<T>(key: string, privateRead = false): T | undefined {
    const entry = this.entries.get(`${privateRead ? "private" : "public"}:${key}`);
    return entry && entry.expiresAt > this.now() ? entry.value as T : undefined;
  }

  resetPrivate(): void { this.invalidate(true); }
  resetAll(): void { this.invalidate(false); }

  private invalidate(privateOnly: boolean): void {
    for (const [key, entry] of this.entries) {
      if (!privateOnly || entry.private) this.entries.delete(key);
    }
    for (const [key, job] of this.pending) {
      if (privateOnly && !job.private) continue;
      job.invalidated = true;
      this.pending.delete(key);
      job.reject(new StaleReadError());
    }
    for (const lane of Object.keys(this.queues) as ReadLane[]) {
      this.queues[lane] = this.queues[lane].filter((job) => !job.invalidated);
    }
    // Running loaders keep their lane until settled, preventing an old account's
    // course selection from racing a new account's query in the same MCP server.
  }

  private pump(lane: ReadLane): void {
    if (this.running[lane]) return;
    const queue = this.queues[lane];
    const foreground = queue.findIndex((job) => !job.background);
    const job = queue.splice(foreground < 0 ? 0 : foreground, 1)[0];
    if (!job) return;
    this.running[lane] = job;
    void this.execute(job);
  }

  private async execute(job: Job): Promise<void> {
    try {
      // Request timeouts belong inside the loader, after queue waiting ends.
      const value = await job.loader();
      if (job.invalidated) return;
      const status = value !== null && typeof value === "object" && "status" in value ? value.status : undefined;
      if (status === "login_required") {
        this.entries.delete(job.key);
      } else if (job.retain && status !== "error") {
        this.entries.delete(job.key);
        this.entries.set(job.key, { value, expiresAt: this.now() + this.ttlMs, private: job.private });
        while (this.entries.size > this.maxEntries) this.entries.delete(this.entries.keys().next().value!);
      }
      job.resolve(value);
    } catch (error) {
      if (!job.invalidated) job.reject(error);
    } finally {
      if (this.pending.get(job.key) === job) this.pending.delete(job.key);
      if (this.running[job.lane] === job) delete this.running[job.lane];
      this.pump(job.lane);
    }
  }
}
