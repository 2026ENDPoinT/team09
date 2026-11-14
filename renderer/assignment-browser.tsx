import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { createRoot } from "react-dom/client";
import type { AssignmentBrowserBridge, AssignmentBrowserState, AssignmentDetails } from "../shared/assignment-browser.js";
import { CURRENT_ASSIGNMENT_GUIDE_FORMAT, DEFAULT_ASSIGNMENT_FONT_SIZE, ENCRYPTED_ASSIGNMENT_PDF_MESSAGE } from "../shared/assignment-browser.js";
import { asKoreanTime } from "../shared/assignment-visibility.js";
import { AssignmentFloatingChat } from "./assignment-floating-chat.js";
import { ChatAnswer } from "./chat-answer.js";
import "./styles.css";
import "./assignment-browser.css";

declare global {
  interface Window { assignmentBrowser: AssignmentBrowserBridge }
}

const timeFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short",
});

function formatDate(value?: string | null) {
  if (!value) return null;
  const date = asKoreanTime(value);
  return date ? timeFormat.format(date) : value;
}

function AssignmentSummary({ assignment, tabId, analysis }: {
  assignment: AssignmentDetails;
  tabId: number;
  analysis: AssignmentBrowserState["analysis"];
}) {
  const [pendingFile, setPendingFile] = useState<string | null>(null);
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const requestAnalysis = () => void window.assignmentBrowser.retryAssignmentAnalysis(tabId, assignment.courseId, assignment.assignmentId).catch(() => {});
  const streaming = analysis?.status === "loading" ? analysis : analysis?.status === "ready" && analysis.upgrade?.status === "loading"
    ? analysis.upgrade : undefined;
  const ready = analysis?.status === "ready" ? analysis : undefined;
  const markdown = streaming?.markdown || ready?.markdown;
  async function openAttachment(id: string) {
    setPendingFile(id);
    setFileMessage(null);
    try {
      const result = await window.assignmentBrowser.openAssignmentAttachment(tabId, assignment.courseId, assignment.assignmentId, id);
      if (result.status === "error") setFileMessage(result.message);
    } catch {
      setFileMessage("첨부파일을 열지 못했어요. 다시 시도해 주세요.");
    } finally {
      setPendingFile(null);
    }
  }

  const submission = [
    ["마감일", formatDate(assignment.dueAt) ?? "확인 필요"],
    ["지각 제출 마감", formatDate(assignment.lateDueAt)],
    ["제출 방식", assignment.submissionMethod],
    ["제출 형태", assignment.submissionFormat],
  ].filter(([, value]) => value);
  const instructorDetails = [
    ["공개일", formatDate(assignment.publishedAt)],
    ["배점", assignment.points],
    ["점수 공개", assignment.scoreVisibility],
  ].filter(([, value]) => value);
  return (
    <section className="assignment-summary" aria-labelledby="assignment-title">
      <header className="assignment-summary-header">
        <p className="eyebrow">{assignment.courseName}</p>
        <h1 id="assignment-title">{assignment.title}</h1>
        <dl className="assignment-facts assignment-submission-facts" aria-label="제출 정보">{submission.map(([label, value]) => <div key={label}>
          <dt>{label}</dt><dd>{value}</dd>
        </div>)}</dl>
        <section className="assignment-files" aria-labelledby="assignment-files-title">
          <h2 id="assignment-files-title">첨부파일{assignment.attachments?.length ? ` ${assignment.attachments.length}개` : ""}</h2>
          {assignment.attachments?.length ? <ul>{assignment.attachments.map(({ id, name }) => <li key={id}>
            <button type="button" disabled={pendingFile !== null} onClick={() => void openAttachment(id)}>
              <span>{name}</span><span aria-hidden="true">↗</span>
            </button>
          </li>)}</ul> : <p>{assignment.attachments ? "첨부파일이 없어요." : "첨부 목록을 확인하지 못했어요."}</p>}
          {(pendingFile || fileMessage) && <p role="status">{pendingFile ? "첨부파일을 불러오고 있어요." : fileMessage}</p>}
        </section>
        {(instructorDetails.length > 0 || assignment.description) && (
          <details className="assignment-instructor">
            <summary>교수자 안내 원문</summary>
            {instructorDetails.length > 0 && <dl className="assignment-facts">
              {instructorDetails.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>}
            {assignment.description && <p className="assignment-instructor-note">{assignment.description}</p>}
          </details>
        )}
      </header>
      <section className="assignment-info-card assignment-analysis" aria-labelledby="assignment-analysis-title">
        <h2 id="assignment-analysis-title">AI 과제 해설</h2>
        {ready && ready.format !== CURRENT_ASSIGNMENT_GUIDE_FORMAT && !streaming && (
          <div className="assignment-study-upgrade">
            <button className="button" type="button" onClick={requestAnalysis}>
              학습 가이드로 업데이트
            </button>
            {ready.upgrade?.status === "error" && <p role="status">{ready.upgrade.message}</p>}
          </div>
        )}
        {markdown && <div className="assignment-analysis-markdown" aria-busy={Boolean(streaming)}><ChatAnswer text={markdown} /></div>}
        {streaming && (ready || streaming.markdown) ? <p className="assignment-analysis-message" role="status">학습 가이드를 작성하고 있어요.</p>
          : !ready && <p className="assignment-analysis-message" role="status">
          {analysis?.status === "error" || analysis?.status === "unavailable" ? analysis.message : "교수자 안내와 PDF 첨부를 확인하고 있어요."}
        </p>}
        {!streaming && !!ready?.encryptedFiles?.length && <p className="assignment-analysis-message" role="status">
          {ENCRYPTED_ASSIGNMENT_PDF_MESSAGE} ({ready.encryptedFiles.join(", ")})
        </p>}
        {!streaming && !!ready?.omittedFiles?.length && <p className="assignment-analysis-message">분석에 포함되지 않은 첨부 · {ready.omittedFiles.join(", ")}</p>}
        {!streaming && ready?.saved === false && <p className="assignment-analysis-message">이 해설을 기기에 저장하지 못했어요.</p>}
        {analysis?.status === "error" && <button className="button" type="button"
          onClick={requestAnalysis}>다시 시도</button>}
      </section>
    </section>
  );
}

function AssignmentToolbar({ state }: { state: AssignmentBrowserState | null }) {
  const [draft, setDraft] = useState<string | null>(null);
  const preview = useRef<HTMLButtonElement>(null);
  const bridge = window.assignmentBrowser;
  const url = state?.url ?? "";

  return (
    <nav className="assignment-toolbar" aria-label="브라우저 탐색">
      <button type="button" className="button assignment-navigation-button" aria-label="뒤로" disabled={!state?.back} onClick={() => void bridge.commandAssignmentBrowser("back")}>←</button>
      <button type="button" className="button assignment-navigation-button" aria-label="앞으로" disabled={!state?.forward} onClick={() => void bridge.commandAssignmentBrowser("forward")}>→</button>
      <button type="button" className="button assignment-navigation-button" aria-label="새로고침" onClick={() => void bridge.commandAssignmentBrowser("reload")}>↻</button>
      {draft === null ? (
        <button ref={preview} type="button" className="button assignment-address-preview" title={url}
          aria-label={url ? `웹 주소 편집 ${url}` : "웹 주소 입력"} disabled={!state || state.initialLoad}
          onClick={() => setDraft(url)}>{url || "웹 주소 입력"}</button>
      ) : (
        <form className="assignment-address-editor" onSubmit={async (event) => {
          event.preventDefault();
          if (draft.trim() && await bridge.navigateAssignmentBrowser(draft)) {
            setDraft((current) => current === draft ? null : current);
          }
        }} onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setDraft(null);
        }} onKeyDown={(event) => {
          if (event.key !== "Escape" || event.nativeEvent.isComposing) return;
          event.preventDefault();
          setDraft(null);
          requestAnimationFrame(() => preview.current?.focus());
        }}>
          <input aria-label="웹 주소" placeholder="웹 주소 입력" value={draft} autoFocus autoComplete="off" spellCheck={false}
            onFocus={(event) => event.currentTarget.select()} onChange={(event) => setDraft(event.target.value)} />
          <button className="button" type="submit" disabled={!draft.trim()}>이동</button>
        </form>
      )}
    </nav>
  );
}

function AttachmentBar({ tabId, preview, showExplanation, onToggleExplanation }: {
  tabId: number;
  preview: NonNullable<AssignmentBrowserState["attachmentPreview"]>;
  showExplanation: boolean;
  onToggleExplanation?: () => void;
}) {
  const [saveError, setSaveError] = useState(false);
  const bridge = window.assignmentBrowser;
  async function download() {
    setSaveError(false);
    try { await bridge.downloadAssignmentAttachment(tabId, preview.id); }
    catch { setSaveError(true); }
  }
  return <div className="assignment-attachment-bar">
    <button type="button" className="button" onClick={() => void bridge.closeAssignmentAttachment(tabId, preview.id)}>← 과제로 돌아가기</button>
    <strong title={preview.name}>{preview.name}</strong>
    {saveError && <span role="status">파일을 저장하지 못했어요.</span>}
    {onToggleExplanation && <button type="button" className="button" aria-expanded={showExplanation} aria-controls="assignment-explanation"
      onClick={onToggleExplanation}>{showExplanation ? "PDF만 보기" : "해설 함께 보기"}</button>}
    <button type="button" className="button" onClick={() => void download()}>원본 다운로드</button>
  </div>;
}

function AssignmentBrowser() {
  const [state, setState] = useState<AssignmentBrowserState | null>(null);
  const [split, setSplit] = useState(25);
  const [previewSplit, setPreviewSplit] = useState(62);
  const [sideBySidePdfId, setSideBySidePdfId] = useState<string>();
  const [dragging, setDragging] = useState(false);
  const shell = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const bridge = window.assignmentBrowser;
  const opening = !state || state.initialLoad;
  const showAssignmentPanel = !(state?.openedFromNotice || state?.openedFromCourse) || state.assignmentState !== "none";
  const preview = state?.attachmentPreview;
  const previewing = Boolean(preview);
  const activePdf = preview?.isPdf === true;
  const pdfFillsWindow = preview?.isPdf === true && sideBySidePdfId !== preview.id;
  const showSplit = showAssignmentPanel && !pdfFillsWindow;
  const currentSplit = previewing ? previewSplit : split;
  const updateSplit = previewing ? setPreviewSplit : setSplit;
  const assignment = state?.assignment;
  const assignmentKey = state && assignment ? `${state.activeTabId}:${assignment.courseId}:${assignment.assignmentId}` : undefined;
  const tabList = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let received = false;
    const unsubscribe = bridge.onAssignmentBrowser((next) => { received = true; setState(next); });
    void bridge.getAssignmentBrowser().then((next) => { if (!received) setState(next); });
    return unsubscribe;
  }, [bridge]);

  useEffect(() => {
    tabList.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [state?.activeTabId]);

  useEffect(() => {
    const element = page.current;
    if (!element) return;
    const layout = () => {
      const bounds = element.getBoundingClientRect();
      bridge.layoutAssignmentBrowser({ x: bounds.x, y: bounds.y, width: dragging ? 0 : bounds.width, height: bounds.height });
    };
    const observer = new ResizeObserver(layout);
    observer.observe(element);
    layout();
    return () => observer.disconnect();
  }, [bridge, dragging]);

  function drag(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId) || !shell.current) return;
    const { left, width } = shell.current.getBoundingClientRect();
    updateSplit(Math.max(18, Math.min(70, (event.clientX - left) / width * 100)));
  }

  return (
    <div className="assignment-workspace" ref={shell} style={{ gridTemplateColumns: showSplit
      ? `minmax(0, ${currentSplit}fr) 7px minmax(0, ${100 - currentSplit}fr)` : "minmax(0, 1fr)" }}>
      <nav className="assignment-tabs" aria-label="열린 브라우저 탭" ref={tabList}>
        {state?.tabs.map(({ id, title }) => <div key={id} className="assignment-tab" data-active={id === state.activeTabId || undefined}>
          <button type="button" className="assignment-tab-select" title={title} aria-current={id === state.activeTabId ? "page" : undefined}
            onClick={() => void bridge.changeBrowserTab("select", id)}>{title}</button>
          <button type="button" className="assignment-tab-close" aria-label={`${title} 탭 닫기`}
            onClick={() => void bridge.changeBrowserTab("close", id)}>×</button>
        </div>)}
      </nav>
      <section className="assignment-browser" aria-label="브라우저">
        <AssignmentToolbar key={state?.activeTabId} state={state} />
        {(state?.error || (state?.loading && !state.initialLoad)) && (
          <div className="assignment-browser-status">
            <p role="status">{state.error ?? "페이지를 불러오고 있어요."}</p>
            {state.canRetryNavigation && (
              <button className="button" type="button" onClick={() => void bridge.commandAssignmentBrowser("retry")}>다시 시도</button>
            )}
          </div>
        )}
        {state && preview && <AttachmentBar key={preview.id} tabId={state.activeTabId} preview={preview}
          showExplanation={showSplit} onToggleExplanation={preview.isPdf && showAssignmentPanel
            ? () => setSideBySidePdfId(pdfFillsWindow ? preview.id : undefined) : undefined} />}
        <div className="assignment-web-page" ref={page} aria-busy={opening || state?.loading} data-resizing={dragging || undefined}>
          {state?.attachmentPreview?.inline === false && <p className="assignment-attachment-unavailable">원본을 다운로드해 이 파일을 열 수 있어요.</p>}
          {state?.tabs.map(({ id, pdf }) => pdf && <iframe key={pdf.url} className="assignment-pdf-frame"
            title={pdf.name} src={pdf.url} hidden={id !== state.activeTabId} />)}
        </div>
      </section>
      {showSplit && <div className="assignment-divider" role="separator" aria-label="브라우저 너비" aria-orientation="vertical" aria-valuenow={Math.round(currentSplit)} aria-valuemin={18} aria-valuemax={70} tabIndex={0}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
        }} onPointerMove={drag} onLostPointerCapture={() => setDragging(false)} onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          updateSplit((value) => Math.max(18, Math.min(70, value + (event.key === "ArrowLeft" ? -2 : 2))));
        }} />}
      {showAssignmentPanel && <main id="assignment-explanation" className="assignment-side" aria-label="과제 해설" hidden={pdfFillsWindow}
        style={{
          "--assignment-font-size": `${state?.assignmentFontSize ?? DEFAULT_ASSIGNMENT_FONT_SIZE}px`,
        } as CSSProperties}>
        {state && assignment ? (
          <>
            <div className="assignment-explanation-scroll" key={assignmentKey}>
              <AssignmentSummary assignment={assignment} tabId={state.activeTabId} analysis={state.analysis} />
            </div>
          </>
        ) : (
          <section className="assignment-context-empty">
            <h2>과제 해설</h2>
            <p role="status">{state?.assignmentMessage ?? (state?.assignmentState === "none" ? "e-Class 과제 페이지를 열면 여기에 과제 정보가 표시돼요." : "과제 원문을 확인하고 있어요.")}</p>
            {(state?.assignmentState === "login" || state?.assignmentState === "unavailable") && <button className="button button--primary" onClick={() => void bridge.commandAssignmentBrowser("login")}>e-Class 로그인</button>}
            {(state?.assignmentState === "login" || state?.assignmentState === "unavailable") && <button className="button" onClick={() => void bridge.commandAssignmentBrowser("resume")}>
              {state.assignmentState === "unavailable" && !state.error && state.url ? "과제 정보 다시 불러오기" : "과제 다시 열기"}
            </button>}
          </section>
        )}
      </main>}
      {assignment && <div className="assignment-chat-region" data-across-window={activePdf || undefined}
        style={{ "--assignment-spotlight-left": previewing ? "50%" : `${(50 - currentSplit) / (100 - currentSplit) * 100}%` } as CSSProperties}>
        <AssignmentFloatingChat key={assignmentKey} />
      </div>}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<AssignmentBrowser />);
