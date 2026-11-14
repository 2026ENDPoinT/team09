import { randomUUID } from "node:crypto";
import { readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { CHAT_TRANSCRIPT_LIMIT, type ChatCost, type ChatTranscriptSnapshot, type ChatTranscriptTurn } from "../shared/chat.js";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validCost(value: unknown): value is ChatCost {
  if (!record(value)) return false;
  const number = (item: unknown) => typeof item === "number" && Number.isFinite(item);
  return (value.status === "estimated" || value.status === "partial" || value.status === "unavailable") &&
    (value.usd === null || number(value.usd)) && (value.krw === null || number(value.krw)) &&
    ["usdKrw", "calls", "pricedCalls", "inputTokens", "cachedInputTokens", "outputTokens", "unknownCalls"]
      .every((key) => number(value[key])) &&
    typeof value.pricingDate === "string" && (value.reason === undefined || typeof value.reason === "string");
}

function validTurn(value: unknown): value is ChatTranscriptTurn {
  return record(value) && typeof value.id === "string" && typeof value.question === "string" &&
    typeof value.answer === "string" && (value.state === "done" || value.state === "error" || value.state === "cancelled") &&
    Array.isArray(value.results) && value.results.every((result) => typeof result === "string") &&
    Array.isArray(value.sources) && value.sources.every((source) =>
      record(source) && typeof source.title === "string" && (source.url === undefined || typeof source.url === "string")) &&
    (value.cost === undefined || validCost(value.cost)) &&
    [value.sentAt, value.readAt, value.answeredAt].every((time) => time === undefined ||
      typeof time === "number" && Number.isFinite(time) && time >= 0 && time <= 8.64e15);
}

export class ChatTranscript {
  private turns: ChatTranscriptTurn[] = [];
  private storageError = false;
  private unreadable = false;

  constructor(private readonly path?: string) {
    if (!path) return;
    try {
      const stored: unknown = JSON.parse(readFileSync(path, "utf8"));
      if (!record(stored) || stored.version !== 1 || !Array.isArray(stored.turns) || !stored.turns.every(validTurn)) {
        throw new Error("Invalid chat transcript");
      }
      this.turns = stored.turns.slice(-CHAT_TRANSCRIPT_LIMIT);
    } catch (error) {
      if (!record(error) || error.code !== "ENOENT") {
        this.storageError = true;
        this.unreadable = true;
      }
    }
  }

  snapshot(): ChatTranscriptSnapshot {
    return { turns: this.turns, storageError: this.storageError };
  }

  append(turn: ChatTranscriptTurn): boolean {
    this.turns = [...this.turns, turn].slice(-CHAT_TRANSCRIPT_LIMIT);
    if (!this.path) return true;
    if (this.unreadable) return false;

    // Finish the atomic write before announcing completion or closing the window.
    const temporary = this.path + "." + randomUUID() + ".tmp";
    try {
      writeFileSync(temporary, JSON.stringify({ version: 1, turns: this.turns }), { mode: 0o600, flag: "wx" });
      renameSync(temporary, this.path);
      this.storageError = false;
    } catch {
      this.storageError = true;
    } finally {
      try { rmSync(temporary, { force: true }); } catch { /* A failed cleanup must not hide the answer. */ }
    }
    return !this.storageError;
  }

  clear() {
    if (this.path) rmSync(this.path, { force: true });
    this.turns = [];
    this.storageError = false;
    this.unreadable = false;
  }
}
