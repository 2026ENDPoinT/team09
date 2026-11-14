import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

export class AccountScreenCache {
  private values: Record<string, unknown> = Object.create(null);
  private pending: Promise<void> = Promise.resolve();
  private dirty = false;
  readonly ready: Promise<void>;

  constructor(private readonly directory: string) {
    this.ready = readFile(join(directory, "screen-cache.json"), "utf8").then((raw) => {
      const parsed = JSON.parse(raw);
      if (parsed?.version === 1 && parsed.values && typeof parsed.values === "object") {
        Object.assign(this.values, parsed.values);
      }
    }).catch(() => {});
  }

  get<T>(key: string): T | undefined { return this.values[key] as T | undefined; }

  set(key: string, value: unknown) {
    if (JSON.stringify(this.values[key]) === JSON.stringify(value)) return;
    this.values[key] = structuredClone(value);
    if (this.dirty) return;
    this.dirty = true;
    // Preserve all loaded screens. Atomic writes keep the previous snapshot readable after interruption.
    this.pending = this.pending.then(async () => {
      this.dirty = false;
      const target = join(this.directory, "screen-cache.json");
      const temporary = target + "." + randomUUID() + ".tmp";
      await mkdir(this.directory, { recursive: true, mode: 0o700 });
      try {
        await writeFile(temporary, JSON.stringify({ version: 1, values: this.values }), { mode: 0o600, flag: "wx" });
        await rename(temporary, target);
      } finally { await rm(temporary, { force: true }).catch(() => {}); }
    }).catch(() => {});
  }

  flush() { return this.pending; }
}
