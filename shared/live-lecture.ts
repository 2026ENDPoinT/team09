export type Segment = { id: string; startMs: number; endMs: number; speaker: number | null; text: string };
export type Caption = { speaker: number | null; text: string };
export type Suggestion = {
  id: string;
  segmentId: string;
  quote: string;
  positions?: number[];
  concept: string;
  followUps: string[];
  startMs: number;
};
export type Explanation = {
  turn: number;
  item: Suggestion;
  evidence?: Segment;
  question?: string;
  followUp?: string;
  text: string;
  state: "loading" | "ready" | "error";
};
export type ChatRect = { left: number; top: number; width: number; height: number };
export type ChatView = { open: boolean; revision: number; spotlight: ChatRect; orb: ChatRect; panel: ChatRect };
export const chatQuestionLimit = 2000;
export type Phase = "idle" | "connecting" | "listening" | "reconnecting" | "pausing" | "paused" | "stopping" | "ended" | "error";
export type LiveState = {
  phase: Phase;
  segments: Segment[];
  captions: Caption[];
  suggestions: Suggestion[];
  startedAt: number | null;
  elapsedMs: number;
  message: string;
  aiMessage: string;
  reviewStatus: "waiting" | "checking" | "checked";
  gaps: number;
  demo: boolean;
};
export type LiveEvent =
  | { type: "state"; state: LiveState }
  | { type: "captions"; captions: Caption[] }
  | { type: "chat-view"; view: ChatView }
  | { type: "explanation"; explanation: Explanation | null };
export type Result = { ok: true } | { ok: false; message: string };
export type LectureChatEntry = Omit<Explanation, "state"> & { state: Explanation["state"] | "interrupted" };
export type LectureRecordSummary = {
  id: string; title: string; startedAt: number; endedAt: number; durationMs: number; utterances: number; messages: number;
};
export type LectureRecord = LectureRecordSummary & { segments: Segment[]; suggestions: Suggestion[]; chat: LectureChatEntry[] };
export type LectureHistoryResult = { ok: true; records: LectureRecordSummary[] } | { ok: false; message: string };
export type LiveBridge = {
  config(): Promise<{ soniox: boolean; openai: boolean }>;
  state(): Promise<LiveState>;
  start(): Promise<Result>;
  resume(): Promise<Result>;
  demo(): Promise<Result>;
  audio(data: ArrayBuffer): void;
  pause(): Promise<void>;
  stop(): Promise<void>;
  explain(id: string, followUp?: string): Promise<void>;
  explainRecent(): Promise<void>;
  explainUtterance(segmentId: string): Promise<void>;
  explanation(): Promise<Explanation | null>;
  ask(question: string): Promise<void>;
  chatView(): Promise<ChatView>;
  setChatOpen(open: boolean): Promise<void>;
  finishChatClose(revision: number): Promise<void>;
  captureChatPointer(capture: boolean): Promise<void>;
  resize(width: number, height: number): Promise<void>;
  close(): Promise<void>;
  subscribe(listener: (event: LiveEvent) => void): () => void;
};

export function clock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return [Math.floor(seconds / 60), seconds % 60].map((part) => String(part).padStart(2, "0")).join(":");
}

const lectureDateFormat = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" });

export function lectureDate(timestamp: number): string {
  return lectureDateFormat.format(timestamp);
}

export function hasSpeechContent(text: string) {
  return /[\p{L}\p{N}][\s\S]*[\p{L}\p{N}]/u.test(text);
}

export function conceptKey(text: string) {
  return text.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

export function conceptQuestion(concept: string) {
  const normalized = concept.normalize("NFC");
  const syllable = normalized.charCodeAt(normalized.length - 1);
  if (syllable >= 0xac00 && syllable <= 0xd7a3) {
    return concept + ((syllable - 0xac00) % 28 === 0 ? "란" : "이란") + " 무엇일까요?";
  }
  return concept + "의 뜻은 무엇일까요?";
}
