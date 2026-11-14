import { randomUUID } from "node:crypto";
import { mkdir, readdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Explanation, LectureChatEntry, LectureRecord, LectureRecordSummary, Segment, Suggestion } from "../../shared/live-lecture.js";

const recordId = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u;

export function validLectureId(id: unknown): id is string {
  return typeof id === "string" && recordId.test(id);
}

export class LectureRecording {
  readonly id = randomUUID();
  readonly startedAt = Date.now();
  readonly segments: Segment[] = [];
  readonly suggestions: Suggestion[] = [];
  private readonly chat = new Map<number, LectureChatEntry>();
  private lastTurn?: number;
  ended?: { at: number; duration: number };

  updateChat(entry: Explanation) {
    const last = this.lastTurn === undefined ? undefined : this.chat.get(this.lastTurn);
    if (last?.state === "loading" && last.turn !== entry.turn) this.chat.set(last.turn, { ...last, state: "interrupted" });
    this.chat.set(entry.turn, entry);
    this.lastTurn = entry.turn;
  }

  snapshot(endedAt: number, durationMs: number): LectureRecord {
    const first = this.segments[0]?.text.replace(/\s+/gu, " ").trim();
    const title = first ? Array.from(first).slice(0, 46).join("") + (Array.from(first).length > 46 ? "…" : "") : "강의 해설";
    const chat = [...this.chat.values()].map((entry): LectureChatEntry => entry.state === "loading" ? { ...entry, state: "interrupted" } : entry);
    return { id: this.id, title, startedAt: this.startedAt, endedAt, durationMs,
      utterances: this.segments.length, messages: chat.length, segments: [...this.segments], suggestions: [...this.suggestions], chat };
  }
}

export class LectureArchive {
  constructor(private readonly directory: string) {}

  async save(record: LectureRecord) {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const path = join(this.directory, `${record.id}.json`);
    const temporary = `${path}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, JSON.stringify(record), { flag: "wx", mode: 0o600 });
      await rename(temporary, path);
    } finally { await rm(temporary, { force: true }).catch(() => {}); }
  }

  async read(id: string): Promise<LectureRecord> {
    if (!validLectureId(id)) throw new Error("Invalid lecture ID");
    const value: LectureRecord = JSON.parse(await readFile(join(this.directory, `${id}.json`), "utf8"));
    if (value?.id !== id || typeof value.title !== "string" || !Number.isFinite(value.startedAt) || !Number.isFinite(value.endedAt)
      || !Number.isFinite(value.durationMs) || !Array.isArray(value.segments) || !Array.isArray(value.suggestions) || !Array.isArray(value.chat)) {
      throw new Error("Invalid lecture record");
    }
    return value;
  }

  async list(): Promise<LectureRecordSummary[]> {
    const entries = await readdir(this.directory).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return [];
      throw error;
    });
    const records: LectureRecordSummary[] = [];
    for (const entry of entries) {
      if (!entry.endsWith(".json") || !validLectureId(entry.slice(0, -5))) continue;
      try {
        const { segments: _segments, suggestions: _suggestions, chat: _chat, ...summary } = await this.read(entry.slice(0, -5));
        records.push(summary);
      } catch { /* A damaged recording should not hide the remaining records. */ }
    }
    return records.sort((a, b) => b.startedAt - a.startedAt);
  }
}
