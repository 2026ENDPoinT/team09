import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { focusFolderPath, type FocusLibrary, type FocusLibraryEdit, type FocusLibraryItem } from "../shared/focus-library.js";
import micIcon from "./assets/focus-home/mic.svg?no-inline";
import lectureArrowIcon from "./assets/focus-home/lecture-arrow.svg?no-inline";
import explainIcon from "./assets/focus-home/explain.svg?no-inline";
import explainArrowIcon from "./assets/focus-home/explain-arrow.svg?no-inline";
import practiceIcon from "./assets/focus-home/practice.svg?no-inline";
import practiceArrowIcon from "./assets/focus-home/practice-arrow.svg?no-inline";
import pdfIcon from "./assets/focus-home/pdf.svg?no-inline";
import plusIcon from "./assets/focus-home/plus.svg?no-inline";
import searchIcon from "./assets/focus-home/search.svg?no-inline";
import folderIcon from "./assets/focus-home/folder.svg?no-inline";
import gridIcon from "./assets/focus-home/grid.svg?no-inline";
import listIcon from "./assets/focus-home/list.svg?no-inline";
import moreIcon from "./assets/focus-home/more.svg?no-inline";
import folderPlumIcon from "./assets/focus-home/folder-plum.svg?no-inline";
import folderBlueIcon from "./assets/focus-home/folder-blue.svg?no-inline";
import folderSlateIcon from "./assets/focus-home/folder-slate.svg?no-inline";
import folderLeafIcon from "./assets/focus-home/folder-leaf.svg?no-inline";
import folderGoldIcon from "./assets/focus-home/folder-gold.svg?no-inline";
import "./focus-workspace.css";

const destinations = [["home", "홈"], ["files", "내 파일"], ["lectures", "강의록"], ["timetable", "시간표 및 캘린더"]] as const;
export type FocusScreen = (typeof destinations)[number][0];
type StudyTask = "lecture" | "explain" | "practice";
export type PdfStudyGuide = Exclude<StudyTask, "lecture">;

const studyTasks = {
  lecture: { label: "실시간 강의 보조", question: "현재 강의를 듣고 계신가요?", description: "실시간으로 이해가 안 되는 부분을 질문하며, 배경지식도 해설받을 수 있어요.", icon: micIcon, arrow: lectureArrowIcon, action: "실시간 강의 보조 진행하기" },
  explain: { label: "PDF 해설", question: "강의자료 해설이 필요하신가요?", description: "PDF를 조각별로 분석하며 강의 해설, 개념 정리, N제 생성까지 지원해요.", icon: explainIcon, arrow: explainArrowIcon, action: "PDF 가져와 해설 보기" },
  practice: { label: "N제 제작", question: "기출문제가 없어 연습이 필요한가요?", description: "강의자료를 바탕으로 시험 대비 문제를 준비해요.", icon: practiceIcon, arrow: practiceArrowIcon, action: "PDF 가져와 N제 만들기" },
} as const;

const pdfStudyGuides = {
  explain: {
    title: "PDF로 강의 해설 보기",
    features: [
      ["강의 해설", "강의자료의 흐름을 따라가며 해설을 읽어요."],
      ["개념 정리와 N제", "핵심 내용을 개념별로 살펴보고, 강의자료에 맞는 N제를 만들어 연습할 수 있어요."],
      ["AI 멘토", "PDF와 연결된 멘토에게 막히는 부분을 바로 질문할 수 있어요."],
    ],
  },
  practice: {
    title: "PDF로 N제 만들기",
    features: [
      ["개념 완성 N제", "핵심 정의와 조건부터 짚으며 개념을 익혀요."],
      ["이해 확인 N제", "개념을 이해해야 풀 수 있는 적용 문제로 실력을 확인해요."],
      ["실전 N제", "실전 기출처럼 여러 개념과 조건을 엮은 가장 어려운 문제에 도전해요."],
      ["암기 확인 N제", "놓치기 쉬운 용어와 세부 내용까지 기억하는지 확인해요."],
    ],
  },
} as const;

export function FocusNavigation({ screen, onOpen }: { screen: FocusScreen; onOpen: (screen: FocusScreen) => void }) {
  return <nav className="focus-navigation" aria-label="집중 모드 메뉴">
    <p>집중 모드</p>
    {destinations.map(([id, name]) => <button key={id} type="button" aria-current={screen === id ? "page" : undefined} onClick={() => onOpen(id)}>{name}</button>)}
  </nav>;
}

function FocusDialog({ title, children, onDismiss }: {
  title: string; children: ReactNode; onDismiss: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);
  return <dialog className="focus-dialog" ref={dialog} aria-labelledby={titleId} onClose={onDismiss}>
    <header><h2 id={titleId}>{title}</h2><form method="dialog"><button type="submit" aria-label="닫기">×</button></form></header>
    {children}
  </dialog>;
}

export function FocusHome({ name, onGuide, library }: {
  name?: string; onGuide: (guide: PdfStudyGuide) => void; library: ReactNode;
}) {
  const [openingLecture, setOpeningLecture] = useState(false);
  const [lectureError, setLectureError] = useState("");

  async function startLecture() {
    setOpeningLecture(true);
    setLectureError("");
    try {
      const result = await window.ast.openLiveLecture();
      if (!result.ok) setLectureError(result.message);
    } catch { setLectureError("강의 해설 창을 열지 못했어요. 다시 시도해 주세요."); }
    finally { setOpeningLecture(false); }
  }
  return <section className="focus-home" aria-labelledby="focus-home-title">
    <header className="focus-home-intro">
      <p>{name ? `${name}님 안녕하세요!` : "안녕하세요!"}</p>
      <h1 id="focus-home-title">학습을 시작할까요?</h1>
    </header>
    <div className="focus-study-list">
      {(Object.keys(studyTasks) as StudyTask[]).map(id => {
        const item = studyTasks[id];
        return <article className="focus-study" key={id} data-task={id}>
          <div className="focus-study-info">
            <span className="focus-study-icon"><img src={item.icon} alt="" /></span>
            <div><p className="focus-study-label">{item.label}</p><h2>{item.question}</h2><p>{item.description}</p></div>
          </div>
          <button type="button" disabled={id === "lecture" && openingLecture}
            onClick={() => { if (id === "lecture") void startLecture(); else onGuide(id); }}>{item.action}<img src={item.arrow} alt="" /></button>
        </article>;
      })}
    </div>
    {lectureError && <p className="focus-lecture-error" role="alert">{lectureError}</p>}
    {library}
  </section>;
}

function FocusStudyGuide({ kind, onDismiss }: { kind: PdfStudyGuide; onDismiss: () => void }) {
  const { title, features } = pdfStudyGuides[kind];
  return <FocusDialog title={title} onDismiss={onDismiss}>
    <div className="focus-study-guide">
      <p>여기서 <strong>PDF 가져오기</strong>로 강의자료를 추가하고 목록에서 PDF를 누르면 AST 학습 프로그램이 자동으로 열려요.</p>
      {kind === "practice" && <p>학습창의 <strong>N제 출제</strong>에서 공부 목적에 맞는 문제집을 골라 만들어요.</p>}
      <dl>
        {features.map(([name, description]) => <div key={name}>
          <dt>{name}</dt>
          <dd>{description}</dd>
        </div>)}
      </dl>
    </div>
    <form method="dialog" className="focus-dialog-actions">
      <button type="submit" className="focus-primary">확인</button>
    </form>
  </FocusDialog>;
}

type EditDialog =
  | { kind: "create" }
  | { kind: "rename"; item: FocusLibraryItem }
  | { kind: "move"; item: FocusLibraryItem }
  | { kind: "move-folders"; ids: string[] };
const homeFolderArt = [
  { tone: "plum", source: folderPlumIcon }, { tone: "blue", source: folderBlueIcon },
  { tone: "slate", source: folderSlateIcon }, { tone: "leaf", source: folderLeafIcon },
  { tone: "gold", source: folderGoldIcon },
];
const fileDate = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeZone: "Asia/Seoul" });
const folderTones = ["plum", "sand", "blue", "leaf", "rose"];

function FolderArt({ tone }: { tone: string }) {
  return <span className="focus-folder-art" data-tone={tone} aria-hidden="true">
    <span className="focus-folder-back" /><span className="focus-folder-paper" /><span className="focus-folder-front" />
  </span>;
}

export function FocusFiles({ embedded = false, library, folderId, busy, loading, message, guide, onOpenFolder, onImport, onEdit, onOpenPdf, onReload }: {
  embedded?: boolean;
  library?: FocusLibrary;
  folderId: string | null;
  busy: boolean;
  loading: boolean;
  message: string;
  guide?: { kind: PdfStudyGuide; dismiss: () => void };
  onOpenFolder: (id: string | null) => void;
  onImport: () => void;
  onEdit: (edit: FocusLibraryEdit) => Promise<boolean>;
  onOpenPdf: (id: string) => void;
  onReload: () => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"recent" | "name">("recent");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [dialog, setDialog] = useState<EditDialog | null>(null);
  const [selection, setSelection] = useState<Set<string> | null>(null);
  const importButton = useRef<HTMLButtonElement>(null);
  const Heading = embedded ? "h2" : "h1";
  const items = library?.items ?? [];
  const path = focusFolderPath(items, folderId);
  const term = query.trim().toLocaleLowerCase();
  const recency = (item: FocusLibraryItem) => (embedded ? item.lastOpenedAt : undefined) ?? item.updatedAt;
  const matches = items.filter(item => item.parentId === folderId && item.name.toLocaleLowerCase().includes(term)).sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
    if (sort === "name") return a.name.localeCompare(b.name, "ko");
    return recency(b) - recency(a) || a.name.localeCompare(b.name, "ko");
  });

  function openFolder(id: string | null) {
    setQuery("");
    setSelection(null);
    onOpenFolder(id);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dialog || busy) return;
    const fields = new FormData(event.currentTarget);
    const name = String(fields.get("name") ?? "");
    const destination = String(fields.get("destination") ?? "") || null;
    const change: FocusLibraryEdit = dialog.kind === "create" ? { kind: "create", parentId: folderId, name }
      : dialog.kind === "rename" ? { kind: "rename", id: dialog.item.id, name }
        : dialog.kind === "move" ? { kind: "move", id: dialog.item.id, parentId: destination }
          : { kind: "move-folders", ids: dialog.ids, parentId: destination };
    if (await onEdit(change)) {
      setDialog(null);
      setSelection(null);
    }
  }

  const moving = dialog?.kind === "move" || dialog?.kind === "move-folders";
  const movingIds = dialog?.kind === "move-folders" ? dialog.ids : dialog?.kind === "move" ? [dialog.item.id] : [];
  const selectionAvailable = matches.some(item => item.kind === "folder");
  const selectedIds = matches.filter(item => item.kind === "folder" && selection?.has(item.id)).map(item => item.id);

  return <section className="focus-files" data-embedded={embedded || undefined} aria-labelledby="focus-files-title">
    <header className="focus-files-heading">
      <div>
        <Heading id="focus-files-title">{embedded ? "내 학습 자료" : "내 파일"}</Heading>
        <p>{embedded ? "PDF와 폴더를 열어 학습을 이어가요." : "PDF와 관련 학습 자료를 문서별 폴더에 모아둬요."}</p>
      </div>
      <div className="focus-file-actions">
        {!embedded && <button type="button" disabled={busy || !library} onClick={() => setDialog({ kind: "create" })}>새 폴더</button>}
        <button ref={importButton} type="button" className={embedded ? undefined : "focus-primary"} disabled={busy || !library} onClick={onImport}>
          {embedded && <img src={pdfIcon} alt="" />}PDF 가져오기
        </button>
        {embedded && <button type="button" className="focus-primary" disabled={busy || !library} onClick={() => setDialog({ kind: "create" })}>
          <img src={plusIcon} alt="" />새로 만들기
        </button>}
      </div>
    </header>
    <div className="focus-file-toolbar">
      <label className="focus-file-search">
        {embedded && <img src={searchIcon} alt="" />}
        <input type="search" aria-label="현재 폴더 검색" placeholder={embedded ? "자료 이름으로 검색해 보세요" : "현재 폴더에서 이름 검색"} value={query}
          onChange={event => { setQuery(event.target.value); setSelection(null); }} />
      </label>
      <div role="group" aria-label="파일 정렬">
        <button type="button" aria-pressed={sort === "recent"} onClick={() => setSort("recent")}>{embedded ? "최근 열람" : "최근 수정"}</button>
        <button type="button" aria-pressed={sort === "name"} onClick={() => setSort("name")}>이름순</button>
      </div>
      {embedded && <button type="button" disabled={busy || (!selectionAvailable && selection === null)} aria-pressed={selection !== null}
        onClick={() => setSelection(current => current ? null : new Set())}>{selection ? "선택 취소" : "일괄 선택"}</button>}
    </div>
    <div className="focus-file-location">
      <nav className="focus-file-path" aria-label="폴더 경로">
        {embedded && <strong>내 문서</strong>}
        <button type="button" aria-current={!folderId ? "location" : undefined} onClick={() => openFolder(null)}>
          {embedded && <img src={folderIcon} alt="" />}{embedded ? "홈 화면" : "내 파일"}
        </button>
        {path.map(folder => <span key={folder.id}><span aria-hidden="true">›</span><button type="button" aria-current={folder.id === folderId ? "location" : undefined} onClick={() => openFolder(folder.id)}>{folder.name}</button></span>)}
      </nav>
      <div className="focus-file-view" role="group" aria-label="보기 방식">
        <span>{matches.length}개{embedded && " 항목"}</span>
        <div className="focus-file-view-buttons">
          <button type="button" aria-label="격자" aria-pressed={view === "grid"} onClick={() => setView("grid")}>{embedded ? <img src={gridIcon} alt="" /> : "격자"}</button>
          <button type="button" aria-label="목록" aria-pressed={view === "list"} onClick={() => setView("list")}>{embedded ? <img src={listIcon} alt="" /> : "목록"}</button>
        </div>
      </div>
    </div>
    {selection && <div className="focus-bulk-actions">
      <span role="status">폴더 {selectedIds.length}개 선택</span>
      <button type="button" disabled={busy || !selectedIds.length} onClick={() => setDialog({ kind: "move-folders", ids: selectedIds })}>선택한 폴더 이동</button>
    </div>}
    {message && !dialog && <p className="focus-feedback" role="status">{message}</p>}
    {loading ? <p className="focus-file-empty" role="status">내 파일을 불러오고 있어요.</p>
      : !library ? <div className="focus-file-empty"><button type="button" onClick={onReload}>다시 불러오기</button></div>
        : !matches.length ? <div className="focus-file-empty">
          {!term && (embedded ? <img src={folderPlumIcon} alt="" /> : <FolderArt tone="plum" />)}
          <p>{term ? "이 이름으로 찾은 파일이나 폴더가 없어요." : folderId ? "이 폴더가 비어 있어요." : "아직 저장한 학습 자료가 없어요."}</p>
          {!term && <button type="button" disabled={busy} onClick={onImport}>PDF 가져오기</button>}
        </div> : <ul className="focus-file-shelf" data-view={view} aria-label="현재 폴더의 항목">
          {matches.map(item => {
            const children = items.filter(child => child.parentId === item.id);
            const folders = children.filter(child => child.kind === "folder").length;
            const pdfs = children.length - folders;
            const toneIndex = parseInt(item.id[0], 16);
            const tone = folderTones[toneIndex % folderTones.length];
            const art = homeFolderArt[toneIndex % homeFolderArt.length];
            const preview = item.kind === "folder"
              ? embedded ? <img src={art.source} alt="" /> : <FolderArt tone={tone} />
              : <span className="focus-pdf-art" aria-hidden="true">PDF</span>;
            const selecting = selection !== null && item.kind === "folder";
            const selected = selection?.has(item.id) ?? false;
            return <li className="focus-file-item" key={item.id} data-selected={selected || undefined}>
              <button type="button" className="focus-file-open" disabled={busy || (selection !== null && item.kind === "pdf")}
                aria-pressed={selecting ? selected : undefined} onClick={() => {
                  if (selection && item.kind === "folder") {
                    setSelection(current => {
                      if (!current) return current;
                      const next = new Set(current);
                      if (next.has(item.id)) next.delete(item.id);
                      else next.add(item.id);
                      return next;
                    });
                  } else if (item.kind === "folder") openFolder(item.id);
                  else onOpenPdf(item.id);
                }}>
                {embedded ? <span className="focus-file-thumb" data-tone={art.tone}>{preview}</span> : preview}
                <span className="focus-file-name">{item.name}</span>
                <span className="focus-file-meta">{item.kind === "folder" ? `폴더${folders ? ` · 하위 폴더 ${folders}개` : ""} · PDF ${pdfs}개` : "PDF 문서"}</span>
                <time className="focus-file-date" dateTime={new Date(item.updatedAt).toISOString()}>{fileDate.format(item.updatedAt)} 수정</time>
              </button>
              {selection === null && <details className="focus-file-menu">
                <summary aria-label={`${item.name} 메뉴`}>{embedded ? <img src={moreIcon} alt="" /> : "···"}</summary>
                <div>
                  <button type="button" disabled={busy} onClick={event => { event.currentTarget.closest("details")!.open = false; setDialog({ kind: "rename", item }); }}>이름 변경</button>
                  {item.kind === "folder" && <button type="button" disabled={busy} onClick={event => { event.currentTarget.closest("details")!.open = false; setDialog({ kind: "move", item }); }}>폴더 이동</button>}
                </div>
              </details>}
            </li>;
          })}
        </ul>}
    {guide && <FocusStudyGuide kind={guide.kind} onDismiss={() => {
      guide.dismiss();
      importButton.current?.focus();
    }} />}
    {dialog && <FocusDialog title={dialog.kind === "create" ? "새 폴더" : dialog.kind === "rename" ? "이름 변경" : "폴더 이동"} onDismiss={() => setDialog(null)}>
      <form className="focus-file-form" onSubmit={event => void submit(event)}>
        {moving ? <label>이동할 위치
          <select name="destination" defaultValue={dialog.kind === "move" ? dialog.item.parentId ?? "" : folderId ?? ""} autoFocus>
            <option value="">내 파일</option>
            {items.filter(item => item.kind === "folder" && !focusFolderPath(items, item.id).some(folder => movingIds.includes(folder.id))).map(item =>
              <option key={item.id} value={item.id}>{focusFolderPath(items, item.id).map(folder => folder.name).join(" / ")}</option>)}
          </select>
        </label> : <label>이름<input name="name" required maxLength={160} defaultValue={dialog.kind === "rename" ? dialog.item.name : ""} autoFocus /></label>}
        {message && <p className="focus-feedback" role="status">{message}</p>}
        <div className="focus-dialog-actions"><button type="submit" className="focus-primary" disabled={busy}>{moving ? "이동" : "저장"}</button></div>
      </form>
    </FocusDialog>}
  </section>;
}
