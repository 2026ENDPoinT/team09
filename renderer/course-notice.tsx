import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { CourseNotice, CourseNoticeDetail, LmsBridgeError } from "../shared/lms.js";

export function CourseNoticeBody({ notice, visible = true, indexed = false, previewHtml }: {
  notice: CourseNotice; visible?: boolean; indexed?: boolean; previewHtml?: string;
}) {
  const { course_id: courseId, id, page } = notice;
  const [result, setResult] = useState<CourseNoticeDetail | LmsBridgeError | null>(null);
  const [attempt, setAttempt] = useState<number | null>(null);
  const [linkError, setLinkError] = useState("");
  const detail = result && !("status" in result) ? result : undefined;
  const html = detail?.body_html ?? previewHtml;

  useEffect(() => {
    if (!visible || indexed && attempt === null) return;
    let active = true;
    void window.ast.getCourseNotice(courseId, id, attempt !== null && attempt > 0, page).then((value) => {
      if (active) setResult(value);
    }, () => {
      if (active) setResult({ status: "error", message: "수업 공지 원문을 불러오지 못했어요." });
    });
    return () => { active = false; };
  }, [courseId, id, page, visible, indexed, attempt]);

  async function openLink(url?: string) {
    setLinkError("");
    try {
      const opened = url ? await window.ast.openCourseNoticeLink(courseId, url)
        : await window.ast.openCourseNoticeOriginal(courseId, id, page);
      if (opened) return;
    } catch { /* Show the same recovery message when IPC fails. */ }
    setLinkError("링크를 열지 못했어요. e-Class 링크라면 앱의 로그인 상태를 확인해 주세요.");
  }

  function activateLink(event: MouseEvent<HTMLDivElement>) {
    if (!(event.target instanceof Element)) return;
    const source = event.target.closest(".course-notice-image-source");
    const link = event.target.closest<HTMLAnchorElement>("a[href]");
    if (!source && !link) return;
    event.preventDefault();
    void openLink(source ? undefined : link?.href);
  }

  return <>
    {html ? (
      <div className="course-notice-body" onClick={activateLink} onAuxClick={(event) => {
        if (event.button === 1) activateLink(event);
      }} dangerouslySetInnerHTML={{ __html: html }} />
    ) : html !== undefined && <p>등록된 본문이 없어요.</p>}
    {!result && (!indexed || attempt !== null) && <p role="status">{previewHtml !== undefined ? "이미지와 첨부파일을 불러오고 있어요." : "공지 본문을 불러오고 있어요."}</p>}
    {result && "status" in result && <div className="notice-feedback">
      <p className="notice-inline-error" role="status">{result.message}</p>
      <button className="button" type="button" onClick={() => {
        setResult(null);
        setAttempt((value) => (value ?? 0) + 1);
      }}>다시 시도</button>
    </div>}
    {!!detail?.attachments.length && (
      <section className="notice-resources">
        <h3>첨부파일</h3>
        <ul className="course-notice-files">{detail.attachments.map((file) => <li key={file.id}>
          <button type="button" className="course-notice-action" title="e-Class에서 공지 열기" onClick={() => void openLink()}>
            {file.name} <span aria-hidden="true">↗</span>
          </button>
        </li>)}</ul>
      </section>
    )}
    {(indexed || detail) && <div className="course-notice-body-actions">
      <button type="button" className="notice-original course-notice-action" onClick={() => void openLink()}>
        e-Class에서 공지 열기 <span aria-hidden="true">↗</span>
      </button>
      {indexed && attempt === null && <button className="button" type="button" onClick={() => setAttempt(0)}>
        {previewHtml !== undefined ? "이미지와 첨부파일 보기" : "본문 불러오기"}
      </button>}
    </div>}
    {linkError && <p role="status" className="notice-inline-error">{linkError}</p>}
  </>;
}

export function CourseNoticeDialog({ notice, onDismiss }: { notice: CourseNotice; onDismiss: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog className="notice-dialog" ref={dialog} aria-labelledby="home-notice-title" onClose={onDismiss}>
    <header className="notice-dialog-top">
      <span>수업 공지</span>
      <form method="dialog"><button type="submit" className="button">닫기</button></form>
    </header>
    <div className="notice-dialog-content">
      <h2 id="home-notice-title">{notice.title}</h2>
      <p className="notice-meta">{notice.course_name}</p>
      <div className="notice-detail-body"><CourseNoticeBody notice={notice} /></div>
    </div>
  </dialog>;
}
