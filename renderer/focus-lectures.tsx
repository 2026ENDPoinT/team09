import { useEffect, useState } from "react";
import { clock, lectureDate, type LectureHistoryResult } from "../shared/live-lecture.js";

export function FocusLectures({ revision }: { revision: number }) {
  const [result, setResult] = useState<LectureHistoryResult>();
  const [opening, setOpening] = useState<string>();
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let current = true;
    let request = 0;
    const load = () => {
      const id = ++request;
      void window.ast.getLectureHistory(revision).then((value) => { if (current && id === request) setResult(value); }, () => {
        if (current && id === request) setResult({ ok: false, message: "강의록 목록을 불러오지 못했어요." });
      });
    };
    load();
    const unsubscribe = window.ast.onLectureHistoryChanged(load);
    window.addEventListener("focus", load);
    return () => { current = false; unsubscribe(); window.removeEventListener("focus", load); };
  }, [revision, refresh]);

  useEffect(() => () => {
    void window.ast.closeLectureRecords(revision).catch(() => {});
  }, [revision]);

  async function open(id: string) {
    setMessage("");
    setOpening(id);
    try {
      const selected = await window.ast.openLectureRecord(revision, id);
      if (!selected.ok) setMessage(selected.message);
    } catch { setMessage("강의록 상세를 열지 못했어요."); }
    finally { setOpening(undefined); }
  }

  return <section className="focus-lectures" aria-labelledby="focus-lectures-title">
    <header><h1 id="focus-lectures-title">강의록</h1><button type="button" className="focus-lectures-reload"
      onClick={() => setRefresh((count) => count + 1)}>새로고침</button></header>
    {!result && <p role="status">강의록을 불러오고 있어요.</p>}
    {result && !result.ok && <p className="focus-lecture-error" role="status">{result.message}</p>}
    {message && <p className="focus-lecture-error" role="alert">{message}</p>}
    {result?.ok && (result.records.length === 0 ? <p className="focus-lectures-empty">강의 해설을 종료하면 이곳에 기록이 저장돼요.</p>
      : <ul className="focus-lecture-list">{result.records.map(record => <li key={record.id}>
        <button type="button" disabled={Boolean(opening)} onClick={() => void open(record.id)}>
          <span className="focus-lecture-info"><strong>{record.title}</strong>
            <span><time dateTime={new Date(record.startedAt).toISOString()}>{lectureDate(record.startedAt)}</time> · 진행 {clock(record.durationMs)}</span>
            <span>발화 {record.utterances}개 · 질문 {record.messages}개</span>
          </span><span aria-hidden="true">↗</span>
        </button>
      </li>)}</ul>)}
  </section>;
}
