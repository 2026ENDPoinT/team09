import type { AssignmentTarget } from "./assignment-browser.js";

export type ChatSource = {
  title: string;
  url?: string;
  assignment?: AssignmentTarget;
  courseNotice?: { courseId: string; noticeId: string; page?: number };
  noticeLink?: boolean;
};

// Initial reference rate, not a live exchange quote. Editable in chat settings.
// KITA / KB reference quote, 2026-11-12 (https://www.kita.net/cmmrcInfo/ehgtGnrlzInfo/rltmEhgt.do).
export const DEFAULT_USD_KRW = 1334.4;
export const CHAT_FONT_SIZES = [14, 16, 18, 20, 22] as const;
export type ChatFontSize = (typeof CHAT_FONT_SIZES)[number];
export const DEFAULT_CHAT_FONT_SIZE: ChatFontSize = 16;

export type ChatCost = {
  status: "estimated" | "partial" | "unavailable";
  usd: number | null;
  krw: number | null;
  usdKrw: number;
  calls: number;
  pricedCalls: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  unknownCalls: number;
  pricingDate: string;
  reason?: string;
};

export type ChatPreferences = {
  model: string;
  usdKrw: number;
  fontSize: ChatFontSize;
};

export type ChatConfig = ChatPreferences & { hasApiKey: boolean };
export type ChatSettingsInput = { model: string; usdKrw?: number; fontSize?: ChatFontSize };
export type ChatActionResult = { ok: boolean; message?: string };
export type ChatTranscriptTurn = {
  id: string;
  question: string;
  answer: string;
  state: "done" | "error" | "cancelled";
  results: string[];
  sources: ChatSource[];
  cost?: ChatCost;
  sentAt?: number;
  readAt?: number;
  answeredAt?: number;
};
export type ChatTranscriptSnapshot = { turns: ChatTranscriptTurn[]; storageError: boolean };
export const CHAT_TRANSCRIPT_LIMIT = 100;
export type ChatEvent = {
  requestId: string;
  type: "read" | "status" | "generating" | "answer" | "result" | "done" | "error" | "cancelled";
  text: string;
  sources?: ChatSource[];
  cost?: ChatCost;
  storageError?: boolean;
  readAt?: number;
  answeredAt?: number;
};

export type ChatBridge = {
  setChatComposing?: (value: boolean) => Promise<void>;
  getChatConfig: () => Promise<ChatConfig>;
  getChatTranscript: () => Promise<ChatTranscriptSnapshot>;
  saveChatConfig: (input: ChatSettingsInput) => Promise<ChatConfig>;
  sendChat: (requestId: string, text: string) => Promise<ChatActionResult>;
  cancelChat: (requestId: string) => Promise<void>;
  resetChat: () => Promise<void>;
  onChatEvent: (listener: (event: ChatEvent) => void) => () => void;
  openChatSource: (url: string) => Promise<boolean>;
};
