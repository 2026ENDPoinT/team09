import { useState, type ReactNode } from "react";
import { campusNoticeBoardLabel, campusNoticeBoards, type CampusNotice, type SchoolCampusNoticeBoard } from "../shared/campus-notices.js";
import type { CampusBriefing, CourseBriefing, CourseNotice, HomeSnapshot } from "../shared/lms.js";
import { asKoreanTime, assignmentDeadline, assignmentDueTime, compareAssignmentDeadlines, visibleCourseBriefing, type AssignmentVisibility } from "../shared/assignment-visibility.js";
import { NoticeDetail } from "./campus-notices.js";
import { CourseNoticeBody } from "./course-notice.js";
import { useScreenRead, type ScreenReadState } from "./use-screen-read.js";
import "./briefing.css";

const dayLabel = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "long", day: "numeric",
});
const timeLabel = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "numeric", minute: "2-digit",
});
const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
const boards = Object.keys(campusNoticeBoards) as SchoolCampusNoticeBoard[];
const getCourseBriefing = (refresh: boolean) => window.ast.getCourseBriefing(refresh);
const getCampusBriefing = (refresh: boolean) => window.ast.getCampusBriefing(refresh);

export function displayTime(value: string): string {
  const date = asKoreanTime(value);
  if (!date) return "날짜 확인 필요";
  return (dateOnly.test(value) ? dayLabel : timeLabel).format(date);
}

function Panel({ id, title, period, children }: {
  id: string; title: string; period?: string; children: ReactNode;
}) {
  return (
    <section className="briefing-panel" aria-labelledby={id}>
      <div className="briefing-panel-heading">
        <h2 id={id}>{title}</h2>
        {period && <span>{period}</span>}
      </div>
      {children}
    </section>
  );
}

function AssignmentTitle({ item }: { item: CourseBriefing["pending_assignments"][number] | CourseBriefing["completed_assignments"][number] }) {
  const [error, setError] = useState(false);
  async function open() {
    setError(false);
    try {
      if (!await window.ast.openAssignment({ assignmentId: item.id, courseId: item.course_id })) setError(true);
    } catch { setError(true); }
  }
  return <>
    <button type="button" className="briefing-item-title briefing-assignment-link" onClick={() => void open()}>
      {item.title} <span aria-hidden="true">↗</span>
    </button>
    {error && <p className="notice-inline-error" role="status">과제 창을 열지 못했어요.</p>}
  </>;
}

function CourseNoticeRow({ notice, visible }: { notice: CourseNotice; visible: boolean }) {
  const [open, setOpen] = useState(false);
  return <li>
    <details className="briefing-course-notice" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <strong className="briefing-item-title">{notice.title}</strong>
        <span className="briefing-item-meta">
          <span>{notice.course_name}</span>
          {notice.created_at && <time dateTime={notice.created_at}>{displayTime(notice.created_at)}</time>}
        </span>
      </summary>
      {open && <div className="briefing-course-notice-content"><CourseNoticeBody notice={notice} visible={visible} /></div>}
    </details>
  </li>;
}

function CoursePanels({ data, visible, now, assignmentsLoading }: { data: CourseBriefing; visible: boolean; now: Date; assignmentsLoading?: boolean }) {
  const pending = [...data.pending_assignments].sort((first, second) => compareAssignmentDeadlines(first.due_at, second.due_at, now));
  return (
    <div className="briefing-course-panels">
      {!!data.unavailable?.length && (
        <p className="briefing-note briefing-note--attention" role="status">
          일부 강좌의 과제나 공지 정보를 확인하지 못했어요.
        </p>
      )}
      <div className="briefing-assignment-grid">
        <Panel id="briefing-pending-title" title="미제출 과제">
          {pending.length === 0 ? <p className="briefing-note">{assignmentsLoading ? "과제를 불러오고 있어요." : "확인된 미제출 과제가 없어요."}</p> : (
            <ul className="briefing-list">
              {pending.map((item) => {
                const due = assignmentDueTime(item.due_at);
                const badge = due ? assignmentDeadline(due, now) : null;
                return (
                  <li className="briefing-row" key={item.course_id + ":" + item.id}>
                    <div>
                      <AssignmentTitle item={item} />
                      <span className="briefing-item-meta">
                        <span>{item.course_name}</span>
                        {item.due_at && due
                          ? <time dateTime={item.due_at}>{badge?.overdue ? "기한 지남 · " : "마감 "}{displayTime(item.due_at)}</time>
                          : <span>마감일 확인 필요</span>}
                        {item.submitted === null && <span>제출 여부 확인 필요</span>}
                      </span>
                    </div>
                    {badge && <span className={"tag briefing-due" + (badge.overdue ? " briefing-due--overdue" : "")}>{badge.text}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
        <Panel id="briefing-completed-title" title="제출한 과제" period="최근 2일">
          {data.completed_assignments.length === 0 ? <p className="briefing-note">{assignmentsLoading ? "제출 내역을 확인하고 있어요." : "최근 2일간 확인된 제출이 없어요."}</p> : (
            <ul className="briefing-list">
              {data.completed_assignments.map((item) => (
                <li className="briefing-row" key={item.course_id + ":" + item.id}>
                  <div>
                    <AssignmentTitle item={item} />
                    <span className="briefing-item-meta">
                      <span>{item.course_name}</span>
                      <time dateTime={item.submitted_at}>제출 {displayTime(item.submitted_at)}</time>
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <Panel id="briefing-course-notices-title" title="수업 공지" period="최근 7일">
        {data.recent_notices.length === 0 ? <p className="briefing-note">최근 7일간 확인된 수업 공지가 없어요.</p> : (
          <ul className="briefing-list">
            {data.recent_notices.map((notice) => <CourseNoticeRow key={notice.course_id + ":" + notice.id} notice={notice} visible={visible} />)}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function CampusNoticeRows({ notices, onSelect, showBoard }: {
  notices: CampusNotice[]; onSelect: (notice: CampusNotice) => void; showBoard?: boolean;
}) {
  return (
    <ul className="briefing-list">
      {notices.map((notice) => (
        <li key={notice.board + ":" + notice.board_id + ":" + notice.id}>
          <button className="notice-row briefing-campus-row" type="button" onClick={() => onSelect(notice)}>
            <span>
              <span className="briefing-item-title">
                {notice.pinned && <span className="tag briefing-pinned">고정</span>}
                <strong>{notice.title}</strong>
              </span>
              <span className="briefing-item-meta">
                {showBoard && <span>{campusNoticeBoardLabel(notice.board)}</span>}
                {notice.published_at && <time dateTime={notice.published_at}>{displayTime(notice.published_at)}</time>}
                {notice.department && <span>{notice.department}</span>}
                {notice.has_attachments && <span>첨부파일</span>}
              </span>
              {notice.preview && <span className="briefing-campus-preview">{notice.preview}</span>}
            </span>
            <span className="notice-chevron" aria-hidden="true">›</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function CampusPanel({ state, onOpenCampusNotices }: {
  state: ScreenReadState<CampusBriefing>; onOpenCampusNotices: () => void;
}) {
  const [board, setBoard] = useState<SchoolCampusNoticeBoard | "all">("all");
  const [selection, setSelection] = useState<CampusNotice | null>(null);
  const notices = (state.data?.notices ?? [])
    .filter((item) => board === "all" || item.board === board)
    .sort((first, second) => (second.published_at ?? "").localeCompare(first.published_at ?? ""));

  return (
    <section className="briefing-panel" aria-labelledby="briefing-campus-title" aria-busy={state.loading}>
      <div className="briefing-panel-heading">
        <h2 id="briefing-campus-title">학교 공지</h2>
        <button type="button" className="button" onClick={onOpenCampusNotices}>학교 공지 전체 보기</button>
      </div>
      {state.data && (
        <div className="notice-boards briefing-campus-filters" role="group" aria-label="학교 공지 분류">
          <button type="button" className="button" aria-pressed={board === "all"} onClick={() => setBoard("all")}>전체</button>
          {boards.map((source) => (
            <button key={source} type="button" className="button" aria-pressed={board === source} onClick={() => setBoard(source)}>
              {campusNoticeBoards[source]}
            </button>
          ))}
        </div>
      )}
      {!!state.data?.unavailable?.length && (
        <p className="briefing-note briefing-note--attention" role="status">
          일부 게시판을 불러오지 못했어요. {state.data.unavailable.map(campusNoticeBoardLabel).join(", ")}
        </p>
      )}
      {state.data && state.error && (
        <p className="briefing-note briefing-note--attention" role="status">{state.error.message} 이전 공지를 표시하고 있어요.</p>
      )}
      {notices.length === 0 ? (
        <p className={"briefing-note" + (state.error ? " briefing-note--attention" : "")} role="status">
          {(state.data ? null : state.error?.message) ?? (state.loading && !state.data ? "학교 공지를 불러오고 있어요." : "표시할 학교 공지가 없어요.")}
        </p>
      ) : board === "all" ? (
        <div className="briefing-campus-groups">
          {boards.map((source) => {
            const group = notices.filter((notice) => notice.board === source);
            if (!group.length) return null;
            const id = "briefing-campus-group-" + source;
            return (
              <section key={source} className="briefing-campus-group" aria-labelledby={id}>
                <div className="briefing-campus-group-heading">
                  <h3 id={id}>{campusNoticeBoards[source]}</h3>
                  <span>{group.length}건</span>
                </div>
                <CampusNoticeRows notices={group} onSelect={setSelection} />
              </section>
            );
          })}
        </div>
      ) : (
        <CampusNoticeRows notices={notices} onSelect={setSelection} showBoard />
      )}
      {selection && <NoticeDetail notice={selection} onDismiss={() => setSelection(null)} />}
    </section>
  );
}

export function Briefing({ onSignIn, onOpenCampusNotices, visible, assignmentSettings, now, home }: {
  onSignIn: () => void; onOpenCampusNotices: () => void; visible: boolean; assignmentSettings: AssignmentVisibility; now: Date;
  home?: HomeSnapshot | null;
}) {
  const legacy = useScreenRead("course", visible && !home, getCourseBriefing, false);
  const course = home ? { ...legacy, data: home.briefing, error: home.error ?? null, loading: home.assignmentsLoading || !home.briefing && !home.error,
    refresh: () => void window.ast.refreshHome() } : legacy;
  const visibleCourse = visibleCourseBriefing(course.data, assignmentSettings, now);
  const campus = useScreenRead("campus", visible, getCampusBriefing);
  const loading = course.loading || campus.loading;
  const asOf = course.data?.as_of ?? campus.data?.as_of;

  return (
    <section className="briefing" aria-labelledby="briefing-title">
      <div className="intro">
        <div>
          <h1 id="briefing-title">브리핑</h1>
          <p className="subtitle">과제 마감과 최근 공지를 한곳에서 확인해요.</p>
        </div>
        <div className="briefing-refresh">
          {asOf && <span className="timestamp">{displayTime(asOf)} 기준</span>}
          <button className="button" type="button" onClick={() => { course.refresh(); campus.refresh(); }} disabled={loading}>
            {loading ? "불러오는 중…" : "새로고침"}
          </button>
        </div>
      </div>
      <div className="briefing-sections">
        <div aria-label="과제 및 수업 공지" aria-busy={course.loading}>
          {course.data && course.error && (
            <p className="briefing-note briefing-note--attention" role="status">{course.error.message} 이전 과제와 공지를 표시하고 있어요.</p>
          )}
          {visibleCourse ? <CoursePanels data={visibleCourse} visible={visible} now={now} assignmentsLoading={home?.assignmentsLoading} /> : (
            <section className="briefing-panel" aria-labelledby="briefing-course-state-title">
              <div className="briefing-panel-heading"><h2 id="briefing-course-state-title">과제 및 수업 공지</h2></div>
              <div className="briefing-note briefing-note--action">
                <p role="status">{course.error?.message ?? "과제와 수업 공지를 불러오고 있어요."}</p>
                {course.error?.status === "login_required" && (
                  <button className="button button--primary" type="button" onClick={onSignIn}>e-Class 연결하기</button>
                )}
              </div>
            </section>
          )}
        </div>
        <CampusPanel state={campus} onOpenCampusNotices={onOpenCampusNotices} />
      </div>
    </section>
  );
}
