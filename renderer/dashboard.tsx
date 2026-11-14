import { useCallback, useState, type ReactNode } from "react";
import { dormNames, type CourseBriefing, type CourseOverview, type CourseRoster, type CourseTimetable, type Dorm, type HomeSnapshot } from "../shared/lms.js";
import { shiftTimetableDate } from "../shared/timetable-week.js";
import { asKoreanTime, assignmentDeadline, assignmentDueTime } from "../shared/assignment-visibility.js";
import { displayTime } from "./briefing.js";
import { readCalendar } from "./timetable.js";
import { useScreenRead } from "./use-screen-read.js";
import "./lethimcook-dashboard.css";
import "./dashboard-layout.css";

export type DashboardAssignment = CourseBriefing["pending_assignments"][number];
export type DashboardNotice = CourseBriefing["recent_notices"][number];

const isoDate = new Intl.DateTimeFormat("sv-SE", { dateStyle: "short", timeZone: "Asia/Seoul" });
const localDate = new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric", weekday: "long", timeZone: "Asia/Seoul" });
const localClock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Seoul" });
const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
const meals = [["breakfast", "아침"], ["lunch", "점심"], ["dinner", "저녁"]] as const;

type ScheduledAssignment = { item: DashboardAssignment; due: Date; date: string };

function shortDate(date: string) { return date.slice(5).replace("-", "."); }

function Heading({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return <header className="sketch-heading"><h2>{title}</h2>{children}</header>;
}

function DeadlineCard({ assignment, primary, now, onOpen }: {
  assignment: ScheduledAssignment; primary: boolean; now: Date; onOpen: (item: DashboardAssignment) => void;
}) {
  const { item, due, date } = assignment;
  const { text, days, overdue } = assignmentDeadline(due, now);
  const countdown = text.replace("D-day", "D-DAY");
  const countdownLabel = days > 0 ? `마감까지 ${days}일 남음` : days < 0 ? `마감 후 ${-days}일 지남` : overdue ? text : "오늘 마감";
  return <button type="button" className="sketch-deadline" data-primary={primary || undefined} onClick={() => onOpen(item)}>
    <span className="sketch-deadline-countdown" data-past-today={overdue && days === 0 || undefined} aria-hidden="true">{countdown}</span>
    <span className="chat-sr-only">{countdownLabel}</span>
    <strong>{item.title}</strong>
    <span>{item.course_name}{item.submitted === null && " · 제출 확인 필요"}</span>
    <time dateTime={due.toISOString()}>{shortDate(date)}({weekdays[new Date(date + "T00:00:00Z").getUTCDay()]}) {localClock.format(due)}</time>
    {primary && <b>과제 하러 가기 →</b>}
  </button>;
}

function HomeCalendar({ today, timetable, ready, deadlines, deadlinesKnown }: {
  today: string; timetable: CourseTimetable | null; ready: boolean; deadlines: ScheduledAssignment[]; deadlinesKnown: boolean;
}) {
  const [date, setDate] = useState<string>();
  const selected = date ?? today;
  const start = selected.slice(0, 7) + "-01";
  const first = new Date(start + "T00:00:00Z");
  const next = new Date(first);
  next.setUTCMonth(next.getUTCMonth() + 1);
  const end = shiftTimetableDate(next.toISOString().slice(0, 10), -1);
  const offset = first.getUTCDay();
  const length = Number(end.slice(-2));
  const days = Math.ceil((offset + length) / 7) * 7;
  const load = useCallback((refresh: boolean) => readCalendar(start, end, "month", refresh, true), [start, end]);
  const { data, error } = useScreenRead(start, ready, load, false);
  const entries = [
    ...(data?.entries.filter((entry) => !timetable || entry.date < timetable.week_start || entry.date > timetable.week_end) ?? []),
    ...(timetable?.entries ?? []),
  ];
  const classDays = new Map<string, number>();
  const deadlineDays = new Map<string, number>();
  for (const entry of entries) classDays.set(entry.date, (classDays.get(entry.date) ?? 0) + 1);
  for (const deadline of deadlines) deadlineDays.set(deadline.date, (deadlineDays.get(deadline.date) ?? 0) + 1);
  const hasSelectedWeek = Boolean(timetable && selected >= timetable.week_start && selected <= timetable.week_end);
  const classesKnown = classDays.has(selected) || Boolean(data && !data.partial) || hasSelectedWeek;

  function moveMonth(step: number) {
    const month = new Date(first);
    month.setUTCMonth(month.getUTCMonth() + step);
    setDate(month.toISOString().slice(0, 10));
  }

  return <section className="sketch-panel sketch-calendar" aria-label="학습 달력">
    <Heading title={`${first.getUTCFullYear()}년 ${first.getUTCMonth() + 1}월`}>
      <div className="sketch-calendar-actions">
        <button type="button" aria-label="이전 달" onClick={() => moveMonth(-1)}>‹</button>
        <button type="button" onClick={() => setDate(undefined)}>오늘</button>
        <button type="button" aria-label="다음 달" onClick={() => moveMonth(1)}>›</button>
      </div>
    </Heading>
    <div className="sketch-weekdays" aria-hidden="true">{weekdays.map((day) => <span key={day}>{day}</span>)}</div>
    <div className="sketch-calendar-days">
      {Array.from({ length: days }, (_, index) => {
        const day = index - offset + 1;
        if (day < 1 || day > length) return <span key={index} aria-hidden="true" />;
        const iso = shiftTimetableDate(start, day - 1);
        const classes = classDays.get(iso) ?? 0;
        const due = deadlineDays.get(iso) ?? 0;
        return <button type="button" key={index} aria-label={`${iso}${classes ? ` 수업 ${classes}개` : ""}${due ? ` 마감 ${due}개` : ""}`}
          aria-current={iso === today ? "date" : undefined} aria-pressed={iso === selected} data-scheduled={!!(classes || due) || undefined}
          data-sunday={index % 7 === 0 || undefined} onClick={() => setDate(iso)}>
          {day}{!!(classes || due) && <span className="sketch-calendar-dot" data-due={!!due || undefined} />}
        </button>;
      })}
    </div>
    <p className="sketch-calendar-summary" aria-live="polite">
      선택한 날 {shortDate(selected)} · {classesKnown ? `수업 ${classDays.get(selected) ?? 0}개` : "수업 미확인"} · {deadlinesKnown ? `마감 ${deadlineDays.get(selected) ?? 0}개` : "마감 미확인"}
      {(data?.partial || error) && <span> · 월간 시간표 일부 미확인</span>}
    </p>
  </section>;
}

function HomeMeals({ dorm, today, clock, visible, onDormMenu, onDiningSettings }: {
  dorm: Dorm; today: string; clock: string; visible: boolean; onDormMenu: () => void; onDiningSettings: () => void;
}) {
  const [chosenMeal, setChosenMeal] = useState<(typeof meals)[number][0]>();
  const defaultMeal = clock < "09:30" ? "breakfast" : clock < "14:00" ? "lunch" : "dinner";
  const meal = chosenMeal ?? defaultMeal;
  const load = useCallback((refresh: boolean) => window.ast.getDormMenu(dorm, "today", refresh), [dorm]);
  const { data, loading, error } = useScreenRead(dorm + ":" + today, visible, load);
  const day = data?.days.find((item) => item.date === today);
  const dishes = day?.meals[meal]?.split(/[,·\n]/).map((dish) => dish.trim()).filter(Boolean) ?? [];
  const notes = day?.notes.map((note) => note.trim()).filter(Boolean) ?? [];
  const items = [...dishes, ...notes];
  return <section className="sketch-panel sketch-meals" aria-label="오늘의 식단">
    <Heading title={<>오늘의 식단 <span className="sketch-meal-dorm">{dormNames[dorm]}</span></>}>
      <button className="sketch-link" type="button" onClick={onDiningSettings}>식당 변경 <span aria-hidden="true">→</span></button>
    </Heading>
    <div className="sketch-meal-tabs" role="group" aria-label="끼니 선택">
      {meals.map(([id, label]) => <button key={id} type="button" aria-pressed={meal === id} onClick={() => setChosenMeal(id)}>{label}</button>)}
    </div>
    <div className="sketch-meal-result" aria-live="polite">
      {dishes.length === 0 && <p>{error?.message ?? (loading ? "식단을 불러오고 있어요." : "게시된 식단이 없어요.")}</p>}
      {items.length > 0 && <ul className="sketch-meal-list">
        {items.map((item, index) => <li key={index}>
          <button className="sketch-meal-item" type="button" onClick={onDormMenu}>{item}</button>
        </li>)}
      </ul>}
    </div>
  </section>;
}

type DashboardProps = {
  overview: CourseOverview | null;
  roster?: CourseRoster;
  displayName?: string;
  dorm?: Dorm;
  briefing: CourseBriefing | null;
  timetable: CourseTimetable | null;
  visible: boolean;
  hidden?: boolean;
  connected: boolean;
  briefingLoading: boolean;
  assignmentsLoading: boolean;
  timetableLoading: boolean;
  checkedAt?: number;
  changes?: HomeSnapshot["changes"];
  status?: string;
  dataError?: string;
  onConnect: () => void;
  onTimetable: () => void;
  onClassroom: () => void;
  onCourse: (id: string) => void;
  onBriefing: () => void;
  onCourseNotices: () => void;
  onDormMenu: () => void;
  onDiningSettings: () => void;
  onNotice: (notice: DashboardNotice) => void;
  onAssignment: (assignment: DashboardAssignment) => void;
  onClassroomAssignment: (assignment: DashboardAssignment) => void;
};

export function Dashboard({ overview, roster, displayName, dorm, briefing, timetable, visible, hidden, connected, briefingLoading, assignmentsLoading, timetableLoading, checkedAt, changes, status, dataError,
  onConnect, onTimetable, onClassroom, onCourse, onBriefing, onCourseNotices, onDormMenu, onDiningSettings, onNotice, onAssignment, onClassroomAssignment }: DashboardProps) {
  const now = new Date();
  const today = isoDate.format(now);
  const clock = localClock.format(now);
  const pending = briefing?.pending_assignments ?? [];
  const deadlines = pending.flatMap((item): ScheduledAssignment[] => {
    const due = assignmentDueTime(item.due_at);
    return due ? [{ item, due, date: isoDate.format(due) }] : [];
  }).sort((a, b) => a.due.getTime() - b.due.getTime());
  const upcoming = deadlines.filter(({ due }) => due >= now);
  const overdue = deadlines.filter(({ due }) => due < now).reverse();
  const undated = pending.filter(({ due_at }) => !assignmentDueTime(due_at));
  const first = upcoming[0];
  const todayClasses = timetable?.entries.filter((entry) => entry.date === today).sort((a, b) => a.start_time.localeCompare(b.start_time)) ?? [];
  const ongoing = todayClasses.find((entry) => entry.start_time <= clock && clock < entry.end_time);
  const next = todayClasses.find((entry) => clock < entry.start_time);
  const currentClass = ongoing ?? next;
  const notices = briefing?.recent_notices.slice(0, 3) ?? [];
  const courses = (overview?.courses ?? roster?.courses.map((course) => ({ course, learning_activity: null })) ?? [])
    .filter(({ course }) => course.category === "regular");
  const unavailable = Boolean(briefing?.unavailable?.length);
  const noBriefing = !connected ? "e-Class에 연결해 주세요." : briefingLoading ? "불러오는 중…" : "확인된 정보가 없어요.";
  const greeting = first ? `${first.date === today ? "오늘 마감인" : "가장 가까운 마감인"} ${first.item.title}부터 확인해 볼까요?`
    : briefing ? "오늘 수업과 최근 공지를 확인해 보세요." : "수업과 과제 일정을 한곳에서 확인해요.";

  return <section className="home-dashboard sketch-home" aria-labelledby="dashboard-title" hidden={hidden}>
    <p className="sketch-breadcrumb">내 학습 <span aria-hidden="true">/</span> 홈</p>
    {checkedAt && <p className="sketch-breadcrumb">마지막 확인 · <time dateTime={new Date(checkedAt).toISOString()}>{displayTime(new Date(checkedAt).toISOString())}</time></p>}
    {(status || dataError || unavailable || !connected) && <p className="sketch-status" role="status">
      {status ?? dataError ?? (unavailable ? "일부 강좌의 과제나 공지를 확인하지 못했어요." : "e-Class에 연결하면 학습 일정을 볼 수 있어요.")}
      {!connected && <button type="button" className="sketch-link" onClick={onConnect}>e-Class 연결</button>}
    </p>}
    <div className="sketch-columns">
      <div className="sketch-primary">
        <header className="sketch-greeting">
          <time dateTime={today}>{localDate.format(now)}</time>
          <h1 id="dashboard-title">{displayName ? `${displayName}님, 반가워요!` : "반가워요!"}</h1>
          <p>{first ? <button type="button" className="sketch-greeting-assignment" onClick={() => onClassroomAssignment(first.item)}>
            {greeting}
          </button> : greeting}</p>
        </header>
        <section className="sketch-deadlines" aria-label="가까운 마감">
          <Heading title="가까운 마감"><button type="button" className="sketch-link" onClick={onBriefing}>
            {briefing && !assignmentsLoading ? `과제 ${pending.length}개 보기 →` : "과제 보기 →"}
          </button></Heading>
          {upcoming.length ? <div className="sketch-deadline-grid">
            {upcoming.slice(0, 3).map((assignment, index) => <DeadlineCard key={`${assignment.item.course_id}:${assignment.item.id}`}
              assignment={assignment} primary={index === 0} now={now} onOpen={onClassroomAssignment} />)}
          </div> : !undated.length && <div className="sketch-panel sketch-deadline-empty"><p>{connected && assignmentsLoading ? "마감 시각을 확인하고 있어요." : briefing ? "확인된 가까운 마감이 없어요." : noBriefing}</p></div>}
          {undated.length > 0 && <div className="sketch-panel sketch-notices"><ul>{undated.slice(0, 3).map((item) =>
            <li key={`${item.course_id}:${item.id}`}><button type="button" onClick={() => onClassroomAssignment(item)}>
              <span><strong>{item.title}</strong><small>{item.course_name} · 마감 시각 미확인</small></span>
            </button></li>)}</ul></div>}
        </section>
        {overdue.length > 0 && <section className="sketch-overdue" aria-label="마감이 지난 과제">
          <Heading title="마감이 지난 과제"><button type="button" className="sketch-link" onClick={onBriefing}>지난 과제 {overdue.length}개 보기 →</button></Heading>
          <div className="sketch-deadline-grid">
            {overdue.slice(0, 3).map((assignment) => <DeadlineCard key={`${assignment.item.course_id}:${assignment.item.id}`}
              assignment={assignment} primary={false} now={now} onOpen={onAssignment} />)}
          </div>
        </section>}
        <section className="sketch-panel sketch-notices" aria-label="최근 공지">
          <Heading title="최근 공지"><button type="button" className="sketch-link" onClick={onCourseNotices}>전체 공지 →</button></Heading>
          {notices.length ? <ul>{notices.map((notice) => {
            const posted = asKoreanTime(notice.created_at);
            return <li key={`${notice.course_id}:${notice.id}`}>
              <button type="button" onClick={() => onNotice(notice)}>
                <span><strong>{notice.title}</strong><small>{notice.course_name}</small></span>
                {posted && <time dateTime={posted.toISOString()}>{shortDate(isoDate.format(posted))}</time>}
              </button>
            </li>;
          })}</ul> : <p>{briefing ? "최근 공지가 없어요." : noBriefing}</p>}
        </section>
        {!!changes?.length && <details className="sketch-panel sketch-notices">
          <summary>최근 변경 {changes.length}건</summary>
          <ul>{changes.slice(0, 8).map((item) => {
            const notice = briefing?.recent_notices.find(({ id, course_id }) => id === item.id && course_id === item.courseId);
            const assignment = pending.find(({ id, course_id }) => id === item.id && course_id === item.courseId);
            return <li key={`${item.kind}:${item.courseId}:${item.id}`}><button type="button" onClick={() => {
              if (item.kind === "notice") onNotice(notice ?? { id: item.id, course_id: item.courseId, course_name: item.courseName, title: item.title, created_at: "" });
              else onAssignment(assignment ?? { id: item.id, course_id: item.courseId, course_name: item.courseName, title: item.title, due_at: null, submitted: null });
            }}><span><strong>{item.title}</strong><small>{item.courseName} · {item.kind === "notice" ? "공지" : "과제"}</small></span></button></li>;
          })}</ul>
        </details>}
      </div>
      <div className="sketch-secondary">
        <HomeCalendar today={today} timetable={timetable} ready={Boolean(visible && connected && timetable && !briefingLoading)}
          deadlines={deadlines} deadlinesKnown={Boolean(briefing && !assignmentsLoading && !unavailable && !undated.length)} />
        {dorm && <HomeMeals dorm={dorm} today={today} clock={clock} visible={visible} onDormMenu={onDormMenu} onDiningSettings={onDiningSettings} />}
        <button type="button" className="sketch-panel sketch-next" onClick={onTimetable}>
          <strong>{ongoing ? "수업 중" : "다음 수업"}{currentClass && `  ${currentClass.start_time}`}</strong>
          <span>{currentClass ? [currentClass.course_name, currentClass.room].filter(Boolean).join(" · ")
            : timetable ? todayClasses.length ? "오늘 수업이 끝났어요." : "오늘 수업이 없어요." : timetableLoading ? "수업을 확인하고 있어요." : "시간표 보기"}</span>
        </button>
      </div>
    </div>
    <section className="sketch-panel sketch-courses" aria-label="강의실 바로가기">
      <Heading title="강의실 바로가기"><button type="button" className="sketch-link" onClick={onClassroom}>내 강의실 →</button></Heading>
      {courses.length ? <ul>{courses.map(({ course, learning_activity: activity }) => <li key={course.id}>
        <button type="button" onClick={() => onCourse(course.id)}><span><strong>{course.name}</strong>
          {(activity || course.professor) && <small>{activity ? `${activity.completed} / ${activity.total} 완료` : course.professor}</small>}</span>
          <span aria-hidden="true">↗</span>
        </button>
      </li>)}</ul> : <p>{connected ? "표시할 수강 과목이 없어요." : "e-Class 연결 후 수강 과목을 확인할 수 있어요."}</p>}
    </section>
  </section>;
}
