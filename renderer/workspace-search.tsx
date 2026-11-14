import { useEffect, useRef, useState } from "react";
import { campusNoticeBoardLabel, campusNoticeKey, isSchoolCampusNoticeBoard, type CampusNotice, type CampusNoticeDetail } from "../shared/campus-notices.js";
import type { CourseRoster } from "../shared/lms.js";
import type { DashboardAssignment, DashboardNotice } from "./dashboard.js";
import { LetHimCookIcon } from "./lethimcook-icon.js";
import { FocusModeIcon } from "./focus-mode-icon.js";
import { normalizeNoticeQuery, noticeBodyExcerpt, useCampusNoticeIndex } from "./use-notice-search.js";

type SearchResult = { key: string; name: string; detail: string; excerpt?: string; open: () => void };

export function WorkspaceSearch({ courses, notices, assignments, onCourse, onNotice, onCampusNotice, onAssignment, onAsk, placement = "header", focusMode = false }: {
  courses: CourseRoster["courses"];
  notices: DashboardNotice[];
  assignments: DashboardAssignment[];
  onCourse: (id: string) => void;
  onNotice: (notice: DashboardNotice) => void;
  onCampusNotice: (notice: CampusNotice, detail?: CampusNoticeDetail) => void;
  onAssignment: (assignment: DashboardAssignment) => void;
  onAsk: (question: string) => void;
  placement?: "header" | "home";
  focusMode?: boolean;
}) {
  const Icon = focusMode ? FocusModeIcon : LetHimCookIcon;
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [composing, setComposing] = useState(false);

  useEffect(() => {
    if (placement !== "header") return;
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    }
    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, [placement]);

  const normalized = normalizeNoticeQuery(query);
  const active = open && !!normalized && !composing;
  const campus = useCampusNoticeIndex(open && !!normalized);
  const localResults: SearchResult[] = active ? [
    ...courses.map((course) => ({ key: `course:${course.id}`, name: course.name, detail: course.professor ?? "과목", open: () => onCourse(course.id) })),
    ...notices.map((notice) => ({ key: `notice:${notice.course_id}:${notice.id}`, name: notice.title, detail: `수업 공지 · ${notice.course_name}`,
      excerpt: noticeBodyExcerpt(notice.content, normalized), open: () => onNotice(notice) })),
    ...[...new Map(assignments.map((item) => [`assignment:${item.course_id}:${item.id}`, item])).entries()].map(([key, item]) =>
      ({ key, name: item.title, detail: `과제 자료 · ${item.course_name}`, open: () => onAssignment(item) })),
  ] : [];
  const results = localResults.filter(({ name, detail, excerpt }) => excerpt || normalizeNoticeQuery(`${name} ${detail}`).includes(normalized));

  if (active) {
    const bodyResults: SearchResult[] = [];
    for (const notice of campus.notices) {
      if (!isSchoolCampusNoticeBoard(notice.board)) continue;
      const key = campusNoticeKey(notice);
      const detail = campus.entries[key]?.detail;
      const fields = [notice.title, notice.department, detail?.title, detail?.department];
      const titleMatch = fields.some((value) => value && normalizeNoticeQuery(value).includes(normalized));
      const excerpt = titleMatch ? undefined : noticeBodyExcerpt(detail?.content, normalized) ?? noticeBodyExcerpt(notice.preview, normalized);
      if (titleMatch || excerpt) {
        (titleMatch ? results : bodyResults).push({
          key, name: notice.title, detail: `학교 공지 · ${campusNoticeBoardLabel(notice.board)}`, excerpt,
          open: () => onCampusNotice(notice, detail),
        });
      }
    }
    results.push(...bodyResults);
  }

  function select(result: SearchResult) {
    setQuery("");
    setOpen(false);
    result.open();
  }

  function ask() {
    const topic = query.trim();
    setQuery("");
    setOpen(false);
    onAsk(`“${topic}”에 대해 알려줘. 학교생활과 관련된 내용이라면 필요한 자료를 찾아 확인한 내용을 정리해줘.`);
  }

  return <div className={`ast-search ast-search--${placement}`} role="search" aria-label={placement === "header" ? "상단 통합 검색" : "홈 검색"} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={(event) => {
    if (event.key === "Escape") { setOpen(false); input.current?.focus(); }
  }}>
    <label className="ast-search-box">
      {placement === "header" && <Icon name="search" />}
      <input ref={input} type="search" value={query} maxLength={500} aria-label="과목, 공지, 자료 검색" placeholder="과목, 공지, 자료 검색"
        onFocus={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
        onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing && event.keyCode !== 229 && active && results.length) select(results[0]);
        }} />
      <kbd aria-hidden={placement === "home"}>{navigator.platform.startsWith("Mac") ? "⌘ K" : "Ctrl K"}</kbd>
    </label>
    {active && <div className="ast-search-results">
      {!!results.length && <ul>{results.map((result) => <li key={result.key}>
        <button type="button" onClick={() => select(result)}><strong>{result.name}</strong><span>{result.detail}</span>
          {result.excerpt && <span className="ast-search-excerpt">{result.excerpt}</span>}</button>
      </li>)}</ul>}
      {campus.loading ? <p role="status">공지 본문을 확인 중이에요…</p>
        : campus.partial ? <p role="status">일부 공지를 불러오지 못했어요.</p>
        : !results.length && <p role="status">검색 범위에서 결과를 찾지 못했어요.</p>}
      {!results.length && <button className="ast-search-ask" type="button" onClick={ask}>AI에게 물어보기 <span aria-hidden="true">↗</span></button>}
    </div>}
  </div>;
}
