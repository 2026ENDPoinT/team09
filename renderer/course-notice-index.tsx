import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { asKoreanTime } from "../shared/assignment-visibility.js";
import { COURSE_NOTICE_QUERY_LIMIT } from "../shared/course-classroom.js";
import type { CourseNoticeIndexSnapshot, IndexedCourseNotice } from "../shared/course-notice-index.js";
import type { CourseNotice, LmsBridgeError } from "../shared/lms.js";
import { displayTime } from "./briefing.js";
import { CourseNoticeBody } from "./course-notice.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import { NoticeFilterButton } from "./notice-filter-button.js";
import { normalizeNoticeQuery, noticeBodyExcerpt } from "./use-notice-search.js";
import "./course-notice-index.css";

const readError: LmsBridgeError = { status: "error", message: "수업 공지를 불러오지 못했어요." };
const pageSize = 40;
const shortDate = new Intl.DateTimeFormat("ko-KR", { month: "numeric", day: "numeric", timeZone: "Asia/Seoul" });
const noticeKey = ({ course_id, id }: CourseNotice) => `${course_id}:${id}`;

function useCourseNotices(visible: boolean, revision: number) {
  const [snapshot, setSnapshot] = useState<CourseNoticeIndexSnapshot>();
  const [error, setError] = useState<LmsBridgeError>();

  useEffect(() => {
    if (!visible) return;
    let canceled = false;
    let timer: number | undefined;
    let version: number | undefined;
    let loading = true;

    async function read() {
      try {
        const result = await window.ast.getCourseNoticeIndex(revision, version);
        if (canceled) return;
        if (result && "status" in result) {
          setError(result);
          if (result.status === "login_required") setSnapshot(undefined);
          loading = false;
          if (result.status === "login_required") return;
        } else {
          setError(undefined);
          if (result) {
            version = result.version;
            loading = result.loading;
            setSnapshot(result);
          }
        }
      } catch {
        if (canceled) return;
        setError(readError);
        loading = false;
      }
      timer = window.setTimeout(() => void read(), loading ? 600 : 2000);
    }

    void read();
    return () => { canceled = true; window.clearTimeout(timer); };
  }, [revision, visible]);

  return { snapshot, error: error ?? snapshot?.error, loading: !error && (snapshot?.loading ?? true) };
}

export function CourseNoticeIndexScreen({ revision, visible, includeNonRegular, onSignIn }: {
  revision: number; visible: boolean; includeNonRegular: boolean; onSignIn: () => void;
}) {
  const { snapshot, error, loading } = useCourseNotices(visible, revision);
  const [refreshError, setRefreshError] = useState(false);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [courseId, setCourseId] = useState("");
  const [selectedKey, setSelectedKey] = useState<string>();
  const [reading, setReading] = useState(false);
  const [limit, setLimit] = useState(pageSize);
  const [refreshing, setRefreshing] = useState(false);
  const composing = useRef(false);
  const list = useRef<HTMLDivElement>(null);
  const selectedRow = useRef<HTMLButtonElement | null>(null);
  const readerTitle = useRef<HTMLHeadingElement>(null);
  const courses = useMemo(() => snapshot?.courses.filter((course) => includeNonRegular || course.category === "regular") ?? [],
    [snapshot?.courses, includeNonRegular]);
  const availableCourseIds = useMemo(() => new Set(courses.map(({ id }) => id)), [courses]);
  const activeCourseId = availableCourseIds.has(courseId) ? courseId : "";
  const searchable = useMemo(() => snapshot?.entries.filter(({ notice }) => availableCourseIds.has(notice.course_id)).map((entry) => ({
    entry,
    fields: [entry.notice.title, entry.notice.course_name, entry.body?.text ?? entry.notice.content ?? ""].map(normalizeNoticeQuery),
  })) ?? [], [snapshot?.entries, availableCourseIds]);
  const results = useMemo(() => searchable.filter(({ entry, fields }) =>
    (!activeCourseId || entry.notice.course_id === activeCourseId) && (!query || fields.some((field) => field.includes(query)))),
  [activeCourseId, query, searchable]);
  const selected = results.find(({ entry }) => noticeKey(entry.notice) === selectedKey)?.entry;
  const loginRequired = error?.status === "login_required";

  const resetResults = useCallback(() => {
    setLimit(pageSize);
    setSelectedKey(undefined);
    setReading(false);
    if (list.current) list.current.scrollTop = 0;
  }, []);

  useEffect(() => {
    if (courseId !== activeCourseId || (selectedKey && !selected)) {
      setCourseId(activeCourseId);
      resetResults();
    }
  }, [courseId, activeCourseId, selectedKey, selected, resetResults]);

  useEffect(() => {
    if (snapshot?.version !== undefined) setRefreshing(false);
  }, [snapshot?.version]);

  useEffect(() => {
    if (reading && selected) {
      readerTitle.current?.closest("article")?.scrollTo(0, 0);
      readerTitle.current?.focus({ preventScroll: true });
    }
  }, [reading, selected?.notice.id, selected?.notice.course_id]);

  function search(value: string) {
    setQuery(normalizeNoticeQuery(value));
    resetResults();
  }

  function filterCourse(id: string) {
    if (id === courseId) return;
    setCourseId(id);
    resetResults();
  }

  function select(entry: IndexedCourseNotice, row: HTMLButtonElement) {
    selectedRow.current = row;
    setSelectedKey(noticeKey(entry.notice));
    setReading(true);
  }

  async function refresh() {
    setRefreshError(false);
    setRefreshing(true);
    try {
      if (await window.ast.refreshCourseNoticeIndex(revision)) return;
    } catch { /* Display a retry message for both IPC and session failures. */ }
    setRefreshError(true);
    setRefreshing(false);
  }

  return <section className="course-notice-index" aria-labelledby="course-notice-index-title">
    <div className="intro">
      <h1 id="course-notice-index-title">수업 공지</h1>
      <button className="button course-notice-index-refresh" type="button" onClick={() => void refresh()}
        disabled={refreshing || loginRequired || snapshot?.courses.length === 0}>
        <LetHimCookIcon name="reset" />새로고침
      </button>
    </div>
    <div className="notice-controls course-notice-index-controls">
      <div className="notice-search" role="search" aria-label="수업 공지 검색">
        <LetHimCookIcon name="search" />
        <input type="search" value={draft} maxLength={COURSE_NOTICE_QUERY_LIMIT} aria-label="수업 공지 검색" placeholder="제목, 과목, 본문 검색"
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={(event) => {
            composing.current = false;
            setDraft(event.currentTarget.value);
            search(event.currentTarget.value);
          }}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft(value);
            if (!composing.current && !(event.nativeEvent as InputEvent).isComposing) search(value);
          }} />
      </div>
      {courses.length > 0 && <div className="notice-filter-options course-notice-index-tags" role="group" aria-label="과목 필터">
        <div className="notice-filter-all">
          <NoticeFilterButton pressed={!activeCourseId} onClick={() => filterCourse("")}>전체</NoticeFilterButton>
        </div>
        <div className="notice-filter-scroll course-notice-index-tag-scroll">
          {courses.map(({ id, name }) => <NoticeFilterButton key={id} pressed={activeCourseId === id} onClick={() => filterCourse(id)}>
            {name}
          </NoticeFilterButton>)}
        </div>
      </div>}
    </div>
    <div className="notice-scope">
      {loading && <p role="status">수업 공지 목록과 본문을 확인하고 있어요. 먼저 불러온 공지부터 검색할 수 있어요.</p>}
      {!loading && snapshot?.partial && <p role="status">일부 공지를 확인하지 못했어요. 확인한 내용은 계속 검색할 수 있어요.</p>}
      {!loading && !snapshot?.partial && snapshot?.checkedAt && <p>마지막 동기화 · <time dateTime={new Date(snapshot.checkedAt).toISOString()}>{displayTime(new Date(snapshot.checkedAt).toISOString())}</time></p>}
      {(refreshError || error) && <p className="notice-inline-error" role="status">{error?.message ?? "수업 공지를 새로고침하지 못했어요."}</p>}
      {loginRequired && <button className="button" type="button" onClick={onSignIn}>다시 로그인</button>}
    </div>
    <div className="course-notice-index-board" data-reading={Boolean(reading && selected)}>
      <section className="notice-timeline course-notice-index-list" aria-labelledby="course-notice-list-title">
        <div className="notice-timeline-header">
          <h2 id="course-notice-list-title">{query ? "검색 결과" : "공지 목록"}</h2>
          <span aria-live="polite">{results.length}건</span>
        </div>
        <div className="notice-timeline-scroll" ref={list}>
          {results.length ? <ul className="course-notice-index-rows">
            {results.slice(0, limit).map(({ entry }) => {
              const { notice, body } = entry;
              const key = noticeKey(notice);
              const date = asKoreanTime(notice.created_at);
              const excerpt = noticeBodyExcerpt(body?.text ?? notice.content, query);
              return <li key={key}>
                <button type="button" className="notice-row course-notice-index-row" aria-current={selectedKey === key || undefined}
                  onClick={(event) => select(entry, event.currentTarget)}>
                  <strong>{notice.title}</strong>
                  {excerpt && <span className="notice-result-excerpt">{excerpt}</span>}
                  <span className="course-notice-index-meta"><span title={notice.course_name}>{notice.course_name}</span>
                    {date && notice.created_at && <time dateTime={notice.created_at}>{shortDate.format(date)}</time>}
                  </span>
                </button>
              </li>;
            })}
          </ul> : <div className="empty"><p>{error ? "표시할 공지가 없어요." : loading ? "공지 목록을 불러오고 있어요." :
            query ? "검색어와 일치하는 공지가 없어요." : "확인된 수업 공지가 없어요."}</p></div>}
          {results.length > limit && <button type="button" className="button course-notice-index-more" onClick={() => setLimit((value) => value + pageSize)}>더 보기</button>}
        </div>
      </section>
      {selected ? <article className="notice-reading-pane course-notice-index-reader" aria-labelledby="course-notice-index-reader-title">
        <button className="button course-notice-index-back" type="button" onClick={() => {
          setReading(false);
          requestAnimationFrame(() => selectedRow.current?.focus());
        }}>← 목록으로</button>
        <div className="notice-reading-source"><span className="notice-reading-topic">{selected.notice.course_name}</span></div>
        <h2 id="course-notice-index-reader-title" tabIndex={-1} ref={readerTitle}>{selected.notice.title}</h2>
        {selected.notice.created_at && <div className="notice-reading-meta"><time dateTime={selected.notice.created_at}>{displayTime(selected.notice.created_at)}</time></div>}
        <div className="notice-reading-body">
          {!selected.body && <>
            {selected.notice.content && <p className="notice-content-text">{selected.notice.content}</p>}
            <p className="course-notice-index-preview-status">{loading ? "본문을 미리 불러오는 중이에요." : "전체 본문을 아직 확인하지 못했어요."}</p>
          </>}
          <CourseNoticeBody key={noticeKey(selected.notice)} notice={selected.notice} visible={visible} indexed previewHtml={selected.body?.body_html} />
        </div>
      </article> : <div className="notice-reading-empty course-notice-index-reader">읽을 공지를 선택해 주세요.</div>}
    </div>
  </section>;
}
