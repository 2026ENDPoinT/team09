import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { CourseBrowserPage } from "../shared/assignment-browser.js";
import { assignmentDeadline, assignmentDueTime } from "../shared/assignment-visibility.js";
import { COURSE_NOTICE_QUERY_LIMIT, type CourseClassroomActivity, type CourseClassroomData, type CourseClassroomInfo, type CourseClassroomWeek, type CourseNoticePage } from "../shared/course-classroom.js";
import type { CourseNotice, CourseStats, LmsBridgeError } from "../shared/lms.js";
import { displayTime } from "./briefing.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import { cleanNoticeText, normalizeNoticeQuery, noticeBodyExcerpt } from "./use-notice-search.js";
import { useScreenRead, type ScreenReadState } from "./use-screen-read.js";
import "./course-classroom.css";

const destinations = [
  ["attendance", "출석"], ["groups", "그룹활동"], ["grades", "성적"],
  ["notices", "공지사항"], ["qna", "질의응답"], ["files", "파일모음"],
] as const;

const activityLabels: Record<CourseClassroomActivity["kind"], string> = {
  assignment: "과제", material: "강의자료", discussion: "토론", lecture: "영상 강의",
  quiz: "시험·퀴즈", survey: "설문", other_activity: "기타 활동",
};
const activityStatus = { submitted: "제출 완료", not_submitted: "미제출", complete: "완료", incomplete: "미완료" } as const;
const emptyNotices: CourseNotice[] = [];

export type AssignmentScroll = { id: string; onComplete: () => void; onMissing: () => void };

type CourseClassroomProps = {
  course: CourseStats["course"];
  revision: number;
  noticeMode: boolean;
  assignmentScroll?: AssignmentScroll;
  onBack: () => void;
  onShowNotices: () => void;
  onShowClassroom: () => void;
  onOpenNotice: (notice: CourseNotice) => void;
  onOpenAssignment: (activity: CourseClassroomActivity) => Promise<boolean>;
  onSignIn: () => void;
};

type NoticeRequest = (page: number, query?: string, refresh?: boolean) => Promise<CourseNoticePage | LmsBridgeError>;
type SearchState = {
  notices: CourseNotice[];
  pending: boolean;
  partial: boolean;
  error: LmsBridgeError | null;
};
type SearchRequest = { query: string; refresh: boolean };

const emptySearch = { notices: emptyNotices, pending: false, partial: false, error: null } satisfies SearchState;
const noticeReadError: LmsBridgeError = { status: "error", message: "강의 공지를 불러오지 못했어요." };

function appendNotices(previous: CourseNotice[], next: CourseNotice[]) {
  const notices = new Map(previous.map((notice) => [notice.id, notice]));
  for (const notice of next) notices.set(notice.id, notice);
  return [...notices.values()];
}

function useCourseNoticeSearch(active: boolean, search: SearchRequest | null, loadPage: NoticeRequest) {
  const [state, setState] = useState<{ search: SearchRequest; result: SearchState }>();

  useEffect(() => {
    if (!active || !search) return;
    const request = search;
    let canceled = false;

    async function scan() {
      let notices: CourseNotice[] = [];
      let partial = false;
      setState({ search: request, result: { ...emptySearch, pending: true } });

      for (let page = 1; !canceled; page++) {
        const result = await loadPage(page, request.query, request.refresh).catch(() => noticeReadError);
        if (canceled) return;
        if ("status" in result) {
          setState({ search: request, result: { notices, partial, pending: false, error: result } });
          return;
        }
        notices = appendNotices(notices, result.notices);
        partial ||= result.partial === true;
        setState({ search: request, result: { notices, partial, pending: result.has_next, error: null } });
        if (!result.has_next) return;
      }
    }

    void scan();
    return () => { canceled = true; };
  }, [active, search, loadPage]);

  return search ? state?.search === search ? state.result : { ...emptySearch, pending: true } : emptySearch;
}

function CourseTabs({ noticeMode, children }: { noticeMode: boolean; children: ReactNode }) {
  const strip = useRef<HTMLElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [scrollable, setScrollable] = useState({ previous: false, next: false });

  const measure = useCallback(() => {
    const box = viewport.current;
    if (!box || !strip.current || !content.current) return;
    const overflow = content.current.scrollWidth > strip.current.clientWidth;
    const previous = overflow && box.scrollLeft > 1;
    const next = overflow && box.scrollLeft + box.clientWidth < box.scrollWidth - 1;
    setScrollable((current) => current.previous === previous && current.next === next ? current : { previous, next });
  }, []);

  useEffect(() => {
    const observer = new ResizeObserver(measure);
    for (const element of [strip.current, viewport.current, content.current]) {
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [measure]);

  useEffect(() => {
    const box = viewport.current;
    const current = box?.querySelector("[aria-current=page]");
    if (!box || !current) return;
    const target = current.getBoundingClientRect();
    const visible = box.getBoundingClientRect();
    const padding = 6;
    if (target.left < visible.left + padding) box.scrollLeft += target.left - visible.left - padding;
    else if (target.right > visible.right - padding) box.scrollLeft += target.right - visible.right + padding;
  }, [noticeMode]);

  function scroll(direction: -1 | 1) {
    const box = viewport.current;
    if (!box) return;
    const buttons = content.current?.querySelectorAll("button");
    if (!buttons?.length) return;
    const visible = box.getBoundingClientRect();
    const steps = [...buttons].map((button) => button.getBoundingClientRect());
    const next = direction === 1 ? steps.find(({ right }) => right > visible.right - 5)
      : steps.reverse().find(({ left }) => left < visible.left + 5);
    if (!next) return;
    const left = direction === 1 ? next.right - visible.right + 6 : next.left - visible.left - 6;
    box.scrollBy({ left, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }

  return <nav ref={strip} className="course-room-tab-strip" aria-label="과목 메뉴">
    <div className="course-room-tabs" ref={viewport} onScroll={measure}>
      <div className="course-room-tabs-content" ref={content}>{children}</div>
    </div>
    {(scrollable.previous || scrollable.next) && <div className="course-room-tab-scroll">
      <button type="button" aria-label="이전 과목 메뉴 보기" disabled={!scrollable.previous} onClick={() => scroll(-1)}>‹</button>
      <button type="button" aria-label="다음 과목 메뉴 보기" disabled={!scrollable.next} onClick={() => scroll(1)}>›</button>
    </div>}
  </nav>;
}

function ReadError({ error, onRetry, onSignIn }: { error: LmsBridgeError; onRetry: () => void; onSignIn: () => void }) {
  const expired = error.status === "login_required";
  return <div className="course-room-feedback">
    <p className="notice-inline-error" role="status">{error.message}</p>
    <button type="button" className="button" onClick={expired ? onSignIn : onRetry}>{expired ? "다시 로그인" : "다시 시도"}</button>
  </div>;
}

function CourseNoticeRows({ notices, query, onOpen }: { notices: CourseNotice[]; query?: string; onOpen: (notice: CourseNotice) => void }) {
  const normalized = query ? normalizeNoticeQuery(query) : "";
  return <ul className="course-room-notice-list">
    {notices.map((notice) => {
      const excerpt = noticeBodyExcerpt(notice.content, normalized);
      return <li key={notice.id}>
        <button type="button" className="notice-row course-room-notice-row" onClick={() => onOpen(notice)}>
          <span>
            <strong className="notice-row-heading">{notice.title}</strong>
            {notice.created_at && <time className="notice-meta" dateTime={notice.created_at}>{displayTime(notice.created_at)}</time>}
            {excerpt && <span className="notice-result-excerpt">{excerpt}</span>}
          </span>
          <span className="notice-chevron" aria-hidden="true">›</span>
        </button>
      </li>;
    })}
  </ul>;
}

function NoticeSearch({ draft, setDraft, onSearch }: { draft: string; setDraft: (value: string) => void; onSearch: (query: string) => void }) {
  const composing = useRef(false);
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (composing.current) return;
    const query = cleanNoticeText(draft);
    if (query) onSearch(query);
  }
  return <form className="course-room-search" role="search" aria-label="강의 공지 검색" onSubmit={submit}>
    <label className="course-room-search-field">
      <LetHimCookIcon name="search" />
      <input type="search" aria-label="공지 제목 및 본문 검색" placeholder="제목 및 본문 검색" value={draft} maxLength={COURSE_NOTICE_QUERY_LIMIT}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }} />
    </label>
    <button type="submit" className="button button--primary" disabled={!draft.trim()}>검색</button>
  </form>;
}

function AllNotices({ page, onPrevious, onNext, hasNext, partial, notices, loading, error, onOpen, onRetry, onSignIn }: {
  page: number; onPrevious: () => void; onNext: () => void; hasNext: boolean; notices: CourseNotice[]; loading: boolean;
  partial: boolean; error: LmsBridgeError | null; onOpen: (notice: CourseNotice) => void; onRetry: () => void; onSignIn: () => void;
}) {
  return <>
    {notices.length > 0 && <CourseNoticeRows notices={notices} onOpen={onOpen} />}
    {error && <ReadError error={error} onRetry={onRetry} onSignIn={onSignIn} />}
    {!error && loading && notices.length === 0 && <p className="course-room-empty" role="status">공지 목록을 불러오고 있어요.</p>}
    {!error && !loading && notices.length === 0 && <p className="course-room-empty">등록된 공지가 없어요.</p>}
    {!error && partial && <p className="course-room-empty notice-inline-error" role="status">일부 공지를 확인하지 못했어요.</p>}
    {(page > 1 || hasNext) && <nav className="course-room-pagination" aria-label="공지 페이지">
      <button type="button" className="button" disabled={page === 1 || loading} onClick={onPrevious}>이전</button>
      <span aria-live="polite">{page}페이지</span>
      <button type="button" className="button" disabled={!hasNext || loading} onClick={onNext}>다음</button>
    </nav>}
  </>;
}

function SearchNotices({ search, state, onClear, onOpen, onRetry, onSignIn }: {
  search: SearchRequest; state: SearchState; onClear: () => void; onOpen: (notice: CourseNotice) => void; onRetry: () => void; onSignIn: () => void;
}) {
  const { notices, pending, partial, error } = state;
  return <>
    <div className="course-room-search-status">
      <p role="status">{pending ? `공지 본문을 확인 중이에요 · 찾은 공지 ${notices.length}개` : `‘${search.query}’ 검색 결과 ${notices.length}개`}</p>
      <button type="button" className="course-room-link" onClick={onClear}>검색 초기화</button>
    </div>
    {notices.length > 0 && <CourseNoticeRows notices={notices} query={search.query} onOpen={onOpen} />}
    {error && <ReadError error={error} onRetry={onRetry} onSignIn={onSignIn} />}
    {!error && !pending && partial && <p className="course-room-empty notice-inline-error" role="status">일부 공지 본문을 확인하지 못했어요.</p>}
    {!error && !pending && !partial && notices.length === 0 && <p className="course-room-empty">제목이나 본문에서 일치하는 공지를 찾지 못했어요.</p>}
  </>;
}

function ActivityRow({ activity, now, onOpen }: { activity: CourseClassroomActivity; now: Date; onOpen: () => Promise<boolean> }) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState(false);
  const { kind, status, title, details, due_at } = activity;
  const due = assignmentDueTime(due_at);
  const deadline = due && assignmentDeadline(due, now);
  const hasDueText = details?.includes("마감");
  const hasCountdown = details && /\bD(?:[+−-]\d+|[- ]?day)\b/i.test(details);
  const isAssignment = kind === "assignment";
  const canOpen = isAssignment || !!activity.url;

  async function open() {
    setError(false);
    setOpening(true);
    try { setError(!await onOpen()); }
    catch { setError(true); }
    finally { setOpening(false); }
  }

  const Row = canOpen ? "button" : "div";
  return <li className="course-room-activity" data-kind={kind} data-activity-id={activity.id}>
    <Row className="course-room-activity-row" {...(canOpen ? {
      type: "button" as const, disabled: opening, onClick: () => void open(),
      "aria-label": isAssignment ? `${title} 과제 하러 가기` : `${title} 열기`,
    } : {})}>
      <span className="course-room-activity-content">
        <span className="course-room-activity-heading">
          <span className="course-room-activity-kind">{activityLabels[kind]}</span>
          <strong>{title}</strong>
        </span>
        {(details || due) && <span className="course-room-activity-meta">
          {details && <span>{details}</span>}
          {due && due_at && !hasDueText && <span>마감 <time dateTime={due_at}>{displayTime(due_at)}</time></span>}
          {deadline && !hasCountdown && <strong>{deadline.text}</strong>}
        </span>}
      </span>
      {(status || canOpen) && <span className="course-room-activity-actions">
        {status && <span className="course-room-activity-status" data-status={status}>
          {(status === "complete" || status === "submitted") && <span aria-hidden="true">✓ </span>}{activityStatus[status]}
        </span>}
        {canOpen && <span className="course-room-activity-link" aria-hidden="true">{isAssignment && "과제 하러 가기 "}↗</span>}
      </span>}
    </Row>
    {error && <p className="notice-inline-error course-room-activity-error" role="status">e-Class에서 {isAssignment ? "과제를" : "활동을"} 열지 못했어요.</p>}
  </li>;
}

function Week({ week, now, onOpen }: { week: CourseClassroomWeek; now: Date; onOpen: (activity: CourseClassroomActivity) => Promise<boolean> }) {
  const [expanded, setExpanded] = useState(true);
  return <details className="course-room-week" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary onClick={(event) => { event.currentTarget.parentElement?.setAttribute("data-animate", ""); }}>
      <span><strong>{week.number == null ? "기타 활동" : `${week.number}주차`}</strong>{week.date_label && <span>{week.date_label}</span>}</span>
      <span className="course-room-week-chevron" aria-hidden="true" />
    </summary>
    {week.activities.length > 0 ? <ul className="course-room-activities">
      {week.activities.map((activity) => <ActivityRow key={`${activity.kind}:${activity.id}`} activity={activity} now={now} onOpen={() => onOpen(activity)} />)}
    </ul> : <p className="course-room-empty">등록된 활동이 없어요.</p>}
  </details>;
}

function ClassroomInfo({ data, loading }: ScreenReadState<CourseClassroomInfo>) {
  return <div className="course-room-info" aria-busy={loading && !data}>
    <table className="course-room-meetings" aria-label="요일별 수업 시간과 강의실">
      <thead><tr><th scope="col">수업 시간</th><th scope="col">강의실</th></tr></thead>
      <tbody>
        {data?.meetings.length ? data.meetings.map((meeting) => {
          const time = "start_time" in meeting
            ? <span className="course-room-clock"><time dateTime={meeting.start_time}>{meeting.start_time}</time>–<time dateTime={meeting.end_time}>{meeting.end_time}</time></span>
            : <span>{meeting.periods}{meeting.periods.includes("교시") ? "" : "교시"}</span>;
          const key = "start_time" in meeting ? `${meeting.start_time}:${meeting.end_time}` : meeting.periods;
          return <tr key={`${meeting.weekday}:${key}:${meeting.room ?? ""}`}>
            <td><span className="course-room-meeting-time"><strong>{meeting.weekday}요일</strong>{" "}{time}</span></td>
            <td>{meeting.room ?? <span className="course-room-info-muted">미확인</span>}</td>
          </tr>;
        }) : <tr><td colSpan={2} className="course-room-info-muted">{loading ? "불러오는 중…" : "수업 시간과 강의실 미확인"}</td></tr>}
      </tbody>
    </table>
    <dl className="course-room-info-code">
      <dt>과목 코드</dt>
      <dd>{data?.course_code ? <span className="course-room-code">{data.course_code}</span> : <span className="course-room-info-muted">{loading ? "—" : "미확인"}</span>}</dd>
    </dl>
  </div>;
}

export function CourseClassroom({ course, revision, noticeMode, assignmentScroll, onBack, onShowNotices, onShowClassroom, onOpenNotice, onOpenAssignment, onSignIn }: CourseClassroomProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const weeks = useRef<HTMLElement>(null);
  const scrolledAssignment = useRef<AssignmentScroll | undefined>(undefined);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState<SearchRequest | null>(null);
  const [noticePage, setNoticePage] = useState(1);
  const [opening, setOpening] = useState(false);
  const [navigationError, setNavigationError] = useState("");
  const cacheKey = `${revision}:${course.id}`;
  const loadClassroom = useCallback((refresh: boolean) => window.ast.getCourseClassroom(course.id, revision, refresh), [course.id, revision]);
  const loadInfo = useCallback((refresh: boolean) => window.ast.getCourseClassroomInfo(course.id, revision, refresh), [course.id, revision]);
  const loadRecent = useCallback((refresh: boolean) => window.ast.getCourseRecentNotices(course.id, revision, refresh), [course.id, revision]);
  const loadNotices = useCallback<NoticeRequest>((page, query, refresh) => window.ast.getCourseNoticePage(course.id, page, revision, query, refresh), [course.id, revision]);
  const loadFirstPage = useCallback((refresh: boolean) => loadNotices(1, undefined, refresh), [loadNotices]);
  const loadArchivePage = useCallback((refresh: boolean) => loadNotices(noticePage, undefined, refresh), [loadNotices, noticePage]);
  const classroom = useScreenRead<CourseClassroomData>(cacheKey, true, loadClassroom, !noticeMode);
  const recentNotices = useScreenRead(cacheKey, !noticeMode, loadRecent);
  const info = useScreenRead(cacheKey, !noticeMode, loadInfo);
  const firstPage = useScreenRead<CourseNoticePage>(cacheKey, noticeMode && !search && noticePage === 1, loadFirstPage);
  const archive = useScreenRead<CourseNoticePage>(`${cacheKey}:${noticePage}`, noticeMode && !search && noticePage > 1, loadArchivePage);
  const searchResults = useCourseNoticeSearch(noticeMode, search, loadNotices);
  const noticeList = noticePage === 1 ? firstPage : archive;
  const latest = recentNotices.data?.notices.slice(0, 3) ?? emptyNotices;
  const openBoards = classroom.data?.open_boards ?? [];
  const now = new Date();

  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [noticeMode, course.id]);

  useLayoutEffect(() => {
    if (noticeMode || !assignmentScroll || scrolledAssignment.current === assignmentScroll ||
        (!classroom.data && !classroom.error)) return;
    const row = weeks.current?.querySelector<HTMLButtonElement>(
      `[data-kind="assignment"][data-activity-id="${CSS.escape(assignmentScroll.id)}"] > button`,
    );
    const pane = weeks.current?.closest<HTMLElement>(".ast-main");
    if (!row || !pane) {
      assignmentScroll.onMissing();
      return;
    }
    const week = row.closest("details");
    if (week) {
      // Measure the full row before scrolling to an assignment from the home screen.
      week.removeAttribute("data-animate");
      week.open = true;
    }

    const centeredTop = () => {
      const bounds = row.getBoundingClientRect();
      const top = pane.scrollTop + bounds.top - pane.getBoundingClientRect().top + (bounds.height - pane.clientHeight) / 2;
      return Math.max(0, Math.min(top, pane.scrollHeight - pane.clientHeight));
    };

    let frame = 0;
    const finish = () => {
      // Notices above the activity can finish loading during the scroll.
      pane.scrollTo({ top: centeredTop(), behavior: "instant" });
      row.focus({ preventScroll: true });
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(() => {
          scrolledAssignment.current = assignmentScroll;
          assignmentScroll.onComplete();
        });
      });
    };

    const top = centeredTop();
    if (Math.abs(top - pane.scrollTop) < 1 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish();
    } else {
      pane.addEventListener("scrollend", finish, { once: true });
      pane.scrollTo({ top, behavior: "smooth" });
    }
    return () => {
      pane.removeEventListener("scrollend", finish);
      cancelAnimationFrame(frame);
    };
  }, [assignmentScroll, classroom.data, classroom.error, noticeMode]);

  async function openSection(page: CourseBrowserPage, label: string) {
    setNavigationError("");
    setOpening(true);
    try {
      if (await window.ast.openCoursePage(course.id, page, revision)) return;
    } catch { /* Show the same recovery message if IPC fails. */ }
    finally { setOpening(false); }
    setNavigationError(`${label} 창을 열지 못했어요. 다시 시도해 주세요.`);
  }

  function openActivity(item: CourseClassroomActivity) {
    if (item.kind === "assignment") return onOpenAssignment(item);
    if (!item.url) return Promise.resolve(false);
    return window.ast.openCoursePage(course.id, { kind: "activity", activityId: item.id, url: item.url }, revision);
  }

  function openAllNotices() {
    setDraft("");
    setSearch(null);
    setNoticePage(1);
    if (!noticeMode) onShowNotices();
  }

  function startSearch(query: string) {
    setSearch({ query, refresh: false });
    if (!noticeMode) onShowNotices();
  }

  return <section className="course-room" aria-labelledby="course-room-title">
    <header className="course-room-header">
      <button type="button" className="course-room-link" onClick={noticeMode ? onShowClassroom : onBack}>
        <span aria-hidden="true">←</span> {noticeMode ? "강의실로 돌아가기" : "내 강의실"}
      </button>
      <div className="course-room-heading" data-classroom={!noticeMode || undefined}>
        <div className="course-room-identity">
          <h1 id="course-room-title" ref={heading} tabIndex={-1}>{noticeMode ? "전체 공지" : course.name}</h1>
          <p className="course-room-subtitle">{noticeMode ? course.name : course.professor || (course.category === "regular" ? "정규과목" : "비정규과목")}</p>
        </div>
        {!noticeMode && <ClassroomInfo {...info} />}
      </div>
    </header>

    <CourseTabs noticeMode={noticeMode}>
      <button type="button" aria-current={noticeMode ? undefined : "page"} onClick={noticeMode ? onShowClassroom : undefined}>강의실</button>
      {destinations.map(([kind, label]) => kind === "notices"
        ? <button type="button" key={kind} aria-current={noticeMode ? "page" : undefined} onClick={noticeMode ? undefined : openAllNotices}>{label}</button>
        : <button type="button" key={kind} disabled={opening} aria-label={`${label} 새 창에서 열기`}
          onClick={() => void openSection({ kind }, label)}>{label}<span aria-hidden="true">↗</span></button>)}
      {openBoards.length > 0 ? openBoards.map(({ id, title }) => {
        const label = openBoards.length === 1 ? "열린게시판" : `열린게시판 · ${title}`;
        return <button type="button" key={id} disabled={opening} aria-label={`${label} 새 창에서 열기`} title={label}
          onClick={() => void openSection({ kind: "open_board", boardId: id }, label)}><span className="course-room-tab-label">{label}</span><span aria-hidden="true">↗</span></button>;
      }) : <button type="button" disabled title={classroom.loading ? "열린게시판을 확인하고 있어요." : "열린게시판을 확인하지 못했어요."}>열린게시판</button>}
    </CourseTabs>
    {navigationError && <p className="notice-inline-error course-room-navigation-error" role="status">{navigationError}</p>}

    {noticeMode ? <section className="course-room-card" aria-label="강의 공지 목록">
      <NoticeSearch draft={draft} setDraft={setDraft} onSearch={startSearch} />
      {search ? <SearchNotices search={search} state={searchResults} onClear={openAllNotices} onOpen={onOpenNotice}
        onRetry={() => setSearch({ query: search.query, refresh: true })} onSignIn={onSignIn} /> : <AllNotices
        page={noticePage} onPrevious={() => setNoticePage(noticePage - 1)} onNext={() => setNoticePage(noticePage + 1)}
        hasNext={!!noticeList.data?.has_next} partial={noticeList.data?.partial === true}
        notices={noticeList.data?.notices ?? emptyNotices} loading={noticeList.loading}
        error={noticeList.error} onOpen={onOpenNotice} onRetry={noticeList.refresh} onSignIn={onSignIn} />}
    </section> : (
      <section className="course-room-card" aria-labelledby="course-room-notices">
        <div className="course-room-card-heading">
          <h2 id="course-room-notices">최근 공지</h2>
          <button type="button" className="course-room-link" onClick={openAllNotices}>전체 공지 보기 <span aria-hidden="true">→</span></button>
        </div>
        <NoticeSearch draft={draft} setDraft={setDraft} onSearch={startSearch} />
        {latest.length > 0 && <CourseNoticeRows notices={latest} onOpen={onOpenNotice} />}
        {recentNotices.error && <ReadError error={recentNotices.error} onRetry={recentNotices.refresh} onSignIn={onSignIn} />}
        {!recentNotices.error && recentNotices.data?.partial && <p className="course-room-empty notice-inline-error" role="status">일부 공지를 확인하지 못했어요.</p>}
        {!recentNotices.error && !recentNotices.data?.partial && latest.length === 0 && <p className="course-room-empty" role="status">
          {recentNotices.loading ? "공지 목록을 불러오고 있어요." : "등록된 공지가 없어요."}
        </p>}
      </section>
    )}

    <section ref={weeks} className="course-room-weeks" aria-labelledby="course-room-weeks" hidden={noticeMode}>
      <div className="course-room-card-heading">
        <h2 id="course-room-weeks">주차별 활동</h2>
        <button type="button" className="button" disabled={classroom.loading} onClick={classroom.refresh}>새로고침</button>
      </div>
      {classroom.error && <ReadError error={classroom.error} onRetry={classroom.refresh} onSignIn={onSignIn} />}
      {classroom.data?.weeks.map((week, index) => <Week key={`${week.number}:${week.date_label}:${index}`} week={week} now={now} onOpen={openActivity} />)}
      {!classroom.error && !classroom.data?.weeks.length && <p className="course-room-card course-room-empty" role="status">
        {classroom.loading ? "주차별 활동을 불러오고 있어요." : "등록된 주차별 활동이 없어요."}
      </p>}
    </section>
  </section>;
}
