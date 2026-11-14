import { useLayoutEffect, useRef } from "react";
import type { ChatCost, ChatTranscriptTurn } from "../shared/chat.js";
import { ChatAnswer } from "./chat-answer.js";
import { DarkMonoIcon } from "./dark-mono-icon.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import { FocusModeIcon } from "./focus-mode-icon.js";

export type Turn = Omit<ChatTranscriptTurn, "state"> & {
  state: "working" | ChatTranscriptTurn["state"];
  status?: string;
  generating?: boolean;
};

const readDate = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric" });
const answerDate = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function receipt(turn: Turn, now: number) {
  if (turn.readAt === undefined) {
    if (turn.sentAt === undefined) return;
    if (turn.state === "error") return "전송 확인 실패";
    if (turn.state === "cancelled") return "전송 취소됨";
    return now - turn.sentAt < 60_000 ? "방금 보냄" : "전송됨";
  }
  const minutes = Math.max(0, Math.floor((now - turn.readAt) / 60_000));
  if (minutes === 0) return "방금 읽음";
  if (minutes >= 1440) return `읽음: ${readDate.format(turn.readAt)}`;
  const hours = Math.floor(minutes / 60);
  return `읽음: ${hours ? `${hours}시간 ` : ""}${minutes % 60}분 전`;
}

function AnswerTime({ time, now }: { time: number; now: number }) {
  const minutes = Math.max(0, Math.floor((now - time) / 60_000));
  const elapsed = minutes === 0 ? "방금 전" : minutes < 60 ? `${minutes}분 전`
    : minutes < 1440 ? `${Math.floor(minutes / 60)}시간 전` : `${Math.floor(minutes / 1440)}일 전`;
  return <time className="chat-answer-time" dateTime={new Date(time).toISOString()}>
    <span>{answerDate.format(time).replace(",", "")}</span>{" "}<span>{elapsed}</span>
  </time>;
}

function AnswerArea({ turn, onOpenSource }: { turn: Turn; onOpenSource: (url: string) => void }) {
  const area = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const lastHeight = useRef(0);
  const growth = useRef<Animation | undefined>(undefined);
  const working = turn.state === "working";
  const growing = working && Boolean(turn.answer);
  useLayoutEffect(() => {
    const outer = area.current;
    const inner = content.current;
    if (!outer || !inner) return;
    const height = inner.offsetHeight;
    const from = growth.current ? outer.offsetHeight : lastHeight.current;
    lastHeight.current = height;
    growth.current?.cancel();
    growth.current = undefined;
    if (height > from && growing && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      growth.current = outer.animate([{ height: `${from}px` }, { height: `${height}px` }], { duration: 160, easing: "ease-out" });
    }
  }, [turn.answer, growing]);
  useLayoutEffect(() => () => growth.current?.cancel(), []);

  return <div ref={area} className="chat-answer-area" data-streaming={growing || undefined} aria-live={working ? "off" : undefined}>
    <div ref={content}>
      {turn.answer && <ChatAnswer text={turn.answer} sources={turn.sources} onOpenSource={onOpenSource} />}
    </div>
  </div>;
}

function Cost({ cost }: { cost?: ChatCost }) {
  const krw = cost?.krw;
  const noCalls = cost?.calls === 0 && cost.status === "estimated" && cost.krw === 0;
  const amount = krw != null && Number.isFinite(krw) && krw >= 0
    ? krw > 0 && krw < .01 ? "0.01원 미만" : `${krw.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}원`
    : null;
  const label = noCalls ? "AI 호출 없음 · 0원"
    : cost?.status === "partial" && amount ? `확인된 예상 비용 약 ${amount} · 일부 미확인`
    : cost?.status === "estimated" && amount ? `예상 비용 약 ${amount}`
    : "비용 확인 불가";

  return <details className="chat-cost">
    <summary>{label}</summary>
    <div className="chat-cost-body">
      {cost ? <>
        <dl>
          <div><dt>이번 답변 AI 호출</dt><dd>{cost.calls.toLocaleString("ko-KR")}회</dd></div>
          <div><dt>비용 확인</dt><dd>{cost.pricedCalls.toLocaleString("ko-KR")}회{cost.unknownCalls > 0 ? ` · 미확인 ${cost.unknownCalls.toLocaleString("ko-KR")}회` : ""}</dd></div>
          <div><dt>입력 토큰</dt><dd>{cost.inputTokens.toLocaleString("ko-KR")}</dd></div>
          <div><dt>그중 캐시 입력</dt><dd>{cost.cachedInputTokens.toLocaleString("ko-KR")}</dd></div>
          <div><dt>출력 토큰</dt><dd>{cost.outputTokens.toLocaleString("ko-KR")}</dd></div>
          <div><dt>{cost.status === "partial" ? "확인된 달러 비용" : "예상 달러 비용"}</dt><dd>{cost.usd == null ? "확인 불가" : `$${cost.usd.toLocaleString("en-US", { minimumFractionDigits: 6, maximumFractionDigits: 8 })}`}</dd></div>
          <div><dt>적용 환율</dt><dd>1달러 = {cost.usdKrw.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}원</dd></div>
          <div><dt>단가 확인일</dt><dd>{cost.pricingDate}</dd></div>
        </dl>
        {cost.reason && <p>{cost.reason}</p>}
        {cost.unknownCalls > 0 && <p>확인된 사용량만 표시해요. 미확인 호출은 무료라는 뜻이 아니에요.</p>}
        <p>이번 답변의 AI 호출을 합산한 예상 비용이에요. 설정한 환율을 적용하며 세금·카드 수수료는 포함하지 않아요.</p>
      </> : <p>사용량 정보를 받지 못해 비용을 확인할 수 없어요. 무료라는 뜻은 아니에요.</p>}
    </div>
  </details>;
}

export function ChatTurn({ turn, clock, newTurn, onOpenSource, onRetry, retryDisabled, darkMono = false, letHimCook = false, focusMode = false }: {
  turn: Turn;
  clock: number;
  newTurn?: boolean;
  onOpenSource: (url: string) => void;
  onRetry: (question: string) => void;
  retryDisabled: boolean;
  darkMono?: boolean;
  letHimCook?: boolean;
  focusMode?: boolean;
}) {
  const compact = darkMono || letHimCook;
  const Icon = focusMode ? FocusModeIcon : letHimCook ? LetHimCookIcon : DarkMonoIcon;
  const label = receipt(turn, clock);
  const working = turn.state === "working";
  const retry = (turn.state === "error" || turn.state === "cancelled") && (
    <button type="button" className="chat-retry chat-text-button" disabled={retryDisabled} onClick={() => onRetry(turn.question)}>
      다시 시도
    </button>
  );
  return (
    <div className="chat-turn" data-new-turn={newTurn || undefined}>
      <div className="chat-user-message"><span className="chat-sr-only">나: </span>{turn.question}</div>
      {label && <time className="chat-receipt" dateTime={new Date((turn.readAt ?? turn.sentAt)!).toISOString()}>{label}</time>}
      {turn.sentAt !== undefined && turn.readAt === undefined && !working && <div className="chat-send-error">
        <p>{turn.answer}</p>{retry}
      </div>}
      {(turn.readAt !== undefined || turn.sentAt === undefined) && <div className="chat-assistant-message">
        {compact && <span className="chat-sr-only">AST</span>}
        <div className="chat-assistant-header">
          {compact ? !working && <div className="chat-reply-avatar"><Icon name="reply" /></div>
            : <span className="chat-answer-name">✦ AST</span>}
          {turn.results.length > 0 && (
            <ul className="chat-results" aria-label="조회 결과">
              {turn.results.map((result) => <li key={result}>{result}</li>)}
            </ul>
          )}
        </div>
        {working && <p className="chat-working" data-generating={turn.generating || undefined}>
          {compact ? <span className="chat-loading-orbs" aria-hidden="true">
            <Icon name="loadingBack" /><Icon name="loadingFront" />
          </span> : <span className="chat-working-dot" />}
          <span><strong className="chat-working-label">생각 중이에요.</strong>
            {!turn.generating && turn.status && <span className="chat-working-detail">{turn.status}</span>}</span>
        </p>}
        <AnswerArea turn={turn} onOpenSource={onOpenSource} />
        {turn.sources.length > 0 && (
          <details className="chat-sources">
            <summary>확인한 자료 {turn.sources.length}개</summary>
            <ul>
              {turn.sources.map(({ title, url }, index) => <li key={`${url ?? title}:${index}`}>
                {url ? <button type="button" onClick={() => onOpenSource(url)} title={title}>
                  {compact && <Icon name="source" />}<span>{title}</span>
                  {compact ? <Icon name="external" /> : <span aria-hidden="true">↗</span>}
                </button> : <span className="chat-source-title">{compact && <Icon name="source" />}{title}</span>}
              </li>)}
            </ul>
          </details>
        )}
        {turn.state !== "working" && <Cost cost={turn.cost} />}
        {retry}
        {turn.state === "done" && turn.answeredAt !== undefined && <AnswerTime time={turn.answeredAt} now={clock} />}
      </div>}
    </div>
  );
}
