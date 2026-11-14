import { useEffect, useState, type ReactNode } from "react";
import { clock, lectureDate, type LectureRecord } from "../../shared/live-lecture.js";
import "./record-view.css";

declare global {
  interface Window {
    lectureRecord?: { read(): Promise<LectureRecord>; subscribe(listener: (record: LectureRecord) => void): () => void };
  }
}

export function LectureRecordView() {
  const [record, setRecord] = useState<LectureRecord>();
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!window.lectureRecord) { setError(true); return; }
    let updated = false;
    const unsubscribe = window.lectureRecord.subscribe((value) => { updated = true; setRecord(value); });
    void window.lectureRecord.read().then((value) => { if (!updated) setRecord(value); }, () => setError(true));
    return unsubscribe;
  }, []);
  if (!record) return <p className="record-loading" role="status">{error ? "강의록을 불러오지 못했어요." : "강의록을 불러오고 있어요."}</p>;
  const marks = new Map<string, { start: number; text: string }[]>();
  for (const suggestion of record.suggestions) {
    const entries = marks.get(suggestion.segmentId) ?? [];
    for (const start of suggestion.positions ?? []) entries.push({ start, text: suggestion.quote });
    marks.set(suggestion.segmentId, entries);
  }
  function transcript(id: string, text: string) {
    const parts: ReactNode[] = [];
    let end = 0;
    for (const mark of (marks.get(id) ?? []).sort((a, b) => a.start - b.start || b.text.length - a.text.length)) {
      if (mark.start < end || !text.startsWith(mark.text, mark.start)) continue;
      parts.push(text.slice(end, mark.start), <mark key={mark.start}>{mark.text}</mark>);
      end = mark.start + mark.text.length;
    }
    return [...parts, text.slice(end)];
  }
  return <main className="lecture-record-view">
    <header className="record-heading">
      <p><time dateTime={new Date(record.startedAt).toISOString()}>{lectureDate(record.startedAt)}</time> · 진행 {clock(record.durationMs)}</p>
      <h1>{record.title}</h1>
    </header>
    <div className="record-columns">
      <section aria-labelledby="saved-transcript">
        <h2 id="saved-transcript">강의록 <span>{record.utterances}개 발화</span></h2>
        <div className="record-scroll" tabIndex={0} aria-label="저장한 강의록">
          {!record.segments.length && <p className="record-empty">저장된 발화가 없어요.</p>}
          {record.segments.map(segment => <article key={segment.id} className="record-segment">
            <div className="record-meta"><time>{clock(segment.startMs)}</time>{segment.speaker !== null && <span>화자 {segment.speaker}</span>}</div>
            <p>{transcript(segment.id, segment.text)}</p>
          </article>)}
        </div>
      </section>
      <section aria-labelledby="saved-chat">
        <h2 id="saved-chat">강의 채팅 <span>질문 {record.messages}개</span></h2>
        <div className="record-scroll" tabIndex={0} aria-label="저장한 강의 채팅">
          {!record.chat.length && <p className="record-empty">이 강의에 저장된 질문이 없어요.</p>}
          {record.chat.map(item => <article key={item.turn} className="record-turn">
            <h3>{item.question ?? item.item.concept}</h3>
            {item.text && <p>{item.text}</p>}
            {item.state === "interrupted" && <p className="record-meta">답변이 중단됐어요.</p>}
            {item.evidence && <blockquote><time>{clock(item.evidence.startMs)}</time> {item.evidence.text}</blockquote>}
          </article>)}
        </div>
      </section>
    </div>
  </main>;
}
