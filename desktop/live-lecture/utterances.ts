import type { Caption, Segment } from "../../shared/live-lecture.js";

export type SpeechToken = {
  text: string;
  is_final: boolean;
  start_ms?: number;
  end_ms?: number;
  speaker?: string;
  translation_status?: string;
};

const boundary = /^<(?:end|fin)>$/;
const punctuation = /[.!?。？！…]+["'”’)]*\s*$/u;

export class Utterances {
  private current?: Segment;
  private serial = 0;
  private nextSpeaker = 0;
  private speakers = new Map<string, number>();
  private offset = 0;
  private lastEnd = 0;

  constructor(private readonly finalize: (segment: Segment) => void) {}

  newConnection(offset: number) {
    this.flush();
    this.speakers.clear();
    this.offset = offset;
    this.lastEnd = offset;
  }

  private speaker(id: string | undefined, assign: boolean): number | null {
    if (!id) return null;
    if (assign && !this.speakers.has(id)) this.speakers.set(id, ++this.nextSpeaker);
    return this.speakers.get(id) ?? null;
  }

  flush() {
    const segment = this.current;
    this.current = undefined;
    if (segment?.text.trim()) this.finalize({ ...segment, text: segment.text.trim() });
  }

  accept(tokens: SpeechToken[]): Caption[] {
    const partial: Caption[] = [];
    for (const token of tokens) {
      if (token.translation_status === "translation" || !token.text) continue;
      if (boundary.test(token.text)) {
        if (token.is_final) this.flush();
        continue;
      }
      if (!token.is_final) {
        const speaker = this.speaker(token.speaker, false) ?? (token.speaker ? null : this.current?.speaker ?? null);
        const previous = partial.at(-1);
        if (previous && previous.speaker === speaker) previous.text += token.text;
        else partial.push({ speaker, text: token.text });
        continue;
      }
      const start = token.start_ms === undefined ? this.lastEnd : this.offset + token.start_ms;
      const end = Math.max(start, token.end_ms === undefined ? start : this.offset + token.end_ms);
      const speaker = this.speaker(token.speaker, true) ?? this.current?.speaker ?? null;
      const previous = this.current;
      if (previous && ((speaker !== null && previous.speaker !== null && previous.speaker !== speaker)
        || start - previous.endMs > 1_150 || end - previous.startMs > 14_000)) this.flush();
      if (!this.current && token.text.trim()) {
        this.current = { id: String(++this.serial), startMs: start, endMs: end, speaker, text: "" };
      }
      if (this.current) {
        this.current.text += token.text;
        this.current.endMs = Math.max(this.current.endMs, end);
        this.current.speaker ??= speaker;
        if (punctuation.test(token.text) && !/^\s*\d+\.\d/u.test(token.text)) this.flush();
      }
      this.lastEnd = Math.max(this.lastEnd, end);
    }
    const current = this.current;
    if (current?.text.trim()) {
      const first = partial[0];
      if (first && (first.speaker === current.speaker || first.speaker === null)) {
        first.text = current.text + first.text;
        first.speaker = current.speaker;
      } else partial.unshift({ speaker: current.speaker, text: current.text });
    }
    return partial.filter(({ text }) => text.trim());
  }
}
