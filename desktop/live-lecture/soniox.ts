import { Utterances, type SpeechToken } from "./utterances.js";
import type { Caption, Segment } from "../../shared/live-lecture.js";

type Events = {
  ready(): void;
  reconnect(attempt: number): void;
  gap(): void;
  captions(value: Caption[]): void;
  final(segment: Segment): void;
  ended(error?: string): void;
};

const endpoint = "wss://stt-rt.soniox.com/transcribe-websocket";
const audioMs = (bytes: number) => bytes / 32;
const maxBacklogBytes = 32_000;
const maxPendingBytes = maxBacklogBytes * 2;
const connectMs = 8_000;

type ProviderMessage = {
  tokens?: SpeechToken[];
  final_audio_proc_ms?: number;
  finished?: boolean;
  error_code?: number;
  error_type?: string;
};

function failure(code: number) {
  if (code === 401 || code === 403) return "Soniox API 키 또는 모델 접근 권한을 확인해 주세요.";
  if (code === 402 || code === 429) return "Soniox 잔액이나 사용 한도를 확인해 주세요.";
  return "Soniox 전사를 이어갈 수 없어요. 연결 상태와 모델 설정을 확인해 주세요.";
}

export class SonioxStream {
  private socket?: WebSocket;
  private pending: Array<{ data: ArrayBuffer; offset: number }> = [];
  private pendingBytes = 0;
  private capturedBytes = 0;
  private attempts = 0;
  private keepalive?: ReturnType<typeof setInterval>;
  private closed = false;
  private stopping = false;
  private sent = false;
  private sentMs = 0;
  private finalizedMs = 0;
  private gap = false;
  private connectionTimer?: ReturnType<typeof setTimeout>;
  private retryTimer?: ReturnType<typeof setTimeout>;
  private drainTimer?: ReturnType<typeof setTimeout>;
  private utterances: Utterances;

  constructor(
    private readonly key: string,
    private readonly model: string,
    private readonly events: Events,
    private readonly connect: (url: string, protocols: string[]) => WebSocket = (url, protocols) => new WebSocket(url, protocols),
  ) {
    this.utterances = new Utterances(events.final);
  }

  start() {
    if (this.closed || this.socket || this.retryTimer) return;
    let socket: WebSocket;
    try {
      socket = this.connect(endpoint, ["soniox-api-key", this.key]);
    } catch {
      this.finish(failure(401));
      return;
    }
    this.socket = socket;
    this.sent = false;
    this.sentMs = 0;
    this.finalizedMs = 0;
    this.connectionTimer = setTimeout(() => this.lost(socket, 503), connectMs);
    socket.addEventListener("open", () => {
      if (this.socket !== socket || this.closed) return;
      clearTimeout(this.connectionTimer);
      socket.send(JSON.stringify({
        model: this.model,
        audio_format: "pcm_s16le", sample_rate: 16_000, num_channels: 1,
        language_hints: ["ko", "en"],
        enable_speaker_diarization: true,
        enable_endpoint_detection: true,
      }));
      for (const { data, offset } of this.pending) {
        if (this.socket !== socket) break;
        this.send(data, offset);
      }
      this.pending = [];
      this.pendingBytes = 0;
      this.gap = false;
      if (this.socket !== socket) return;
      this.keepalive = setInterval(() => {
        if (!this.stopping && socket.readyState === WebSocket.OPEN) socket.send('{"type":"keepalive"}');
      }, 8_000);
      this.events.ready();
    });
    socket.addEventListener("message", ({ data }) => {
      if (this.socket !== socket || this.closed || typeof data !== "string") return;
      let value: ProviderMessage;
      try { value = JSON.parse(data); } catch { return; }
      if (!value || typeof value !== "object") return;
      if (typeof value.error_code === "number") {
        this.lost(socket, value.error_code, value.error_type);
        return;
      }
      if (typeof value.final_audio_proc_ms === "number") this.finalizedMs = Math.max(this.finalizedMs, value.final_audio_proc_ms);
      if (Array.isArray(value.tokens)) {
        if (value.tokens.some((token) => token?.is_final && token.text !== "<end>")) this.attempts = 0;
        const tokens = value.tokens.filter((token) => token && typeof token.text === "string");
        this.events.captions(this.utterances.accept(tokens));
      }
      if (value.finished) this.finish();
    });
    socket.addEventListener("close", () => this.lost(socket, 503));
    socket.addEventListener("error", () => this.lost(socket, 503));
  }

  private markGap() {
    if (this.gap) return;
    this.gap = true;
    this.events.gap();
  }

  private send(data: ArrayBuffer, offset: number) {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (socket.bufferedAmount > maxBacklogBytes * 2) {
      this.markGap();
      this.lost(socket, 503);
      return;
    }
    if (!this.sent) {
      this.utterances.newConnection(offset);
      this.sent = true;
    }
    socket.send(data);
    this.sentMs += audioMs(data.byteLength);
  }

  push(data: ArrayBuffer) {
    if (this.closed || this.stopping) return;
    const offset = audioMs(this.capturedBytes);
    this.capturedBytes += data.byteLength;
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send(data, offset);
      return;
    }
    this.pending.push({ data, offset });
    this.pendingBytes += data.byteLength;
    while (this.pendingBytes > maxPendingBytes) {
      this.pendingBytes -= this.pending.shift()!.data.byteLength;
      this.markGap();
    }
  }

  private lost(socket: WebSocket, code: number, type?: string) {
    if (socket !== this.socket || this.closed) return;
    this.socket = undefined;
    clearTimeout(this.connectionTimer);
    clearInterval(this.keepalive);
    socket.close();
    this.utterances.flush();
    this.events.captions([]);
    if (this.sentMs - this.finalizedMs > 160) this.markGap();
    if (this.stopping) { this.finish("전사가 끊겨 마지막 자막 일부를 받지 못했어요."); return; }
    if ((code < 500 && code !== 429 && type !== "max_duration_reached") || this.attempts >= 3) {
      this.finish(failure(code));
      return;
    }
    const attempt = ++this.attempts;
    this.events.reconnect(attempt);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      this.start();
    }, 500 * 2 ** (attempt - 1));
  }

  stop() {
    if (this.closed || this.stopping) return;
    this.stopping = true;
    if (this.socket?.readyState !== WebSocket.OPEN || !this.sent) {
      if (this.pendingBytes > 0) this.markGap();
      this.finish();
      return;
    }
    this.drainTimer = setTimeout(() => {
      this.markGap();
      this.finish("마지막 자막을 모두 받지 못했어요.");
    }, 4_000);
    this.socket.send("");
  }

  dispose(flush = false) {
    if (flush && !this.closed) this.utterances.flush();
    this.finish(undefined, false);
  }

  private finish(error?: string, notify = true) {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.connectionTimer);
    clearInterval(this.keepalive);
    clearTimeout(this.retryTimer);
    clearTimeout(this.drainTimer);
    this.socket?.close();
    this.socket = undefined;
    this.pending = [];
    if (notify) {
      this.utterances.flush();
      this.events.captions([]);
      this.events.ended(error);
    }
  }
}
