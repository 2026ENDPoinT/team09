import { useState, type FormEvent } from "react";
import { CHAT_FONT_SIZES, DEFAULT_CHAT_FONT_SIZE, type ChatConfig } from "../shared/chat.js";

export function ChatSettings({ config, onSaved, onClose }: {
  config: ChatConfig;
  onSaved: (config: ChatConfig) => void;
  onClose?: () => void;
}) {
  const [model, setModel] = useState(config.model);
  const [usdKrw, setUsdKrw] = useState(String(config.usdKrw));
  const [fontSize, setFontSize] = useState(config.fontSize ?? DEFAULT_CHAT_FONT_SIZE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const rate = Number(usdKrw);
    if (!Number.isFinite(rate) || rate <= 0 || rate > 100_000) {
      setError("환산 환율은 0보다 크고 100,000 이하인 숫자로 입력해 주세요.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const saved = await window.ast.saveChatConfig({ model: model.trim(), usdKrw: rate, fontSize });
      onSaved(saved);
    } catch {
      setError("설정을 저장하지 못했어요. 입력 내용을 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat-settings" aria-label="AI 대화 설정">
      {onClose && <div className="chat-settings-heading">
        <h3>대화 설정</h3>
        <button className="chat-icon-button" type="button" onClick={onClose} disabled={busy} aria-label="설정 닫기">×</button>
      </div>}
      <p className="chat-key-status">OpenAI API 키 · {config.hasApiKey ? "설정됨" : "미설정"}</p>
      <p className="chat-setting-help">
        프로젝트의 <code>.env</code>에 <code>OPENAI_API_KEY</code>를 설정하고 앱을 다시 실행해 주세요.
        채팅과 과제 해설은 필요한 학교 자료를 OpenAI로 보내며 API 요금이 발생해요. 과제 해설은 처음 열 때 PDF 첨부와 교수자 안내를 함께 분석해요.
      </p>
      <form onSubmit={(event) => void save(event)}>
        <label htmlFor="chat-font-size">채팅 글자 크기</label>
        <select id="chat-font-size" value={fontSize} disabled={busy} onChange={(event) => {
          const size = CHAT_FONT_SIZES.find((choice) => String(choice) === event.target.value);
          if (size !== undefined) setFontSize(size);
        }}>
          {CHAT_FONT_SIZES.map((size) => <option key={size} value={size}>{size}px{size === DEFAULT_CHAT_FONT_SIZE && " (기본)"}</option>)}
        </select>
        <label htmlFor="chat-model">모델</label>
        <input id="chat-model" value={model} onChange={(event) => setModel(event.target.value)} maxLength={100} required spellCheck={false} />
        <label htmlFor="chat-usd-krw">환산 환율 (1달러당 원)</label>
        <input id="chat-usd-krw" type="number" min="0.0001" max="100000" step="any" value={usdKrw} onChange={(event) => setUsdKrw(event.target.value)} required aria-describedby="chat-rate-help" />
        <p id="chat-rate-help" className="chat-setting-help">변경한 고정 환율은 다음 답변의 원화 예상 비용부터 적용해요.</p>
        {error && <p className="chat-error" role="alert">{error}</p>}
        <div className="chat-settings-actions">
          <button className="chat-primary-button" type="submit" disabled={busy || !model.trim()}>{busy ? "저장 중…" : "저장"}</button>
        </div>
      </form>
    </section>
  );
}
