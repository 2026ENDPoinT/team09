import { useCallback, useState, type ReactNode } from "react";
import type { CourseBriefing, CourseTimetable, HomeSnapshot, LmsBridgeError } from "../shared/lms.js";
import { shiftTimetableDate, timetableWeekStart } from "../shared/timetable-week.js";
import { assignmentDeadline, assignmentDueTime, isAssignmentVisible, type AssignmentVisibility } from "../shared/assignment-visibility.js";
import { useScreenRead } from "./use-screen-read.js";
import type { WorkspaceMode } from "./workspace-mode.js";
import previousIcon from "./assets/timetable/previous.svg?no-inline";
import nextIcon from "./assets/timetable/next.svg?no-inline";
import refreshIcon from "./assets/timetable/refresh.svg?no-inline";
import externalIcon from "./assets/timetable/deadline-external.svg?no-inline";
import courseBlue from "./assets/timetable/course-blue.svg?no-inline";
import courseIndigo from "./assets/timetable/course-indigo.svg?no-inline";
import courseAmber from "./assets/timetable/course-amber.svg?no-inline";
import courseRose from "./assets/timetable/course-rose.svg?no-inline";
import courseGreen from "./assets/timetable/course-green.svg?no-inline";
import courseViolet from "./assets/timetable/course-violet.svg?no-inline";
import focusPreviousIcon from "./assets/timetable/focus/previous.svg?no-inline";
import focusNextIcon from "./assets/timetable/focus/next.svg?no-inline";
import focusRefreshIcon from "./assets/timetable/focus/refresh.svg?no-inline";
import focusExternalIcon from "./assets/timetable/focus/deadline-external.svg?no-inline";
import focusCourseBlue from "./assets/timetable/focus/course-blue.svg?no-inline";
import focusCourseIndigo from "./assets/timetable/focus/course-indigo.svg?no-inline";
import focusCourseAmber from "./assets/timetable/focus/course-amber.svg?no-inline";
import focusCourseRose from "./assets/timetable/focus/course-rose.svg?no-inline";
import focusCourseGreen from "./assets/timetable/focus/course-green.svg?no-inline";
import focusCourseViolet from "./assets/timetable/focus/course-violet.svg?no-inline";
import "./timetable.css";
import "./timetable-layout.css";
import "./timetable-focus.css";

const weekdays = ["월", "화", "수", "목", "금", "토", "일"];
const seoulDate = new Intl.DateTimeFormat("sv-SE", { dateStyle: "short", timeZone: "Asia/Seoul" });
const seoulClock = new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Seoul" });
const minutesPerHour = 60;
const timetableIcons = {
  normal: {
    previous: previousIcon, next: nextIcon, refresh: refreshIcon, external: externalIcon,
    courses: [courseBlue, courseIndigo, courseAmber, courseRose, courseGreen, courseViolet],
  },
  focus: {
    previous: focusPreviousIcon, next: focusNextIcon, refresh: focusRefreshIcon, external: focusExternalIcon,
    courses: [focusCourseBlue, focusCourseIndigo, focusCourseAmber, focusCourseRose, focusCourseGreen, focusCourseViolet],
  },
};
const readBriefing = (refresh: boolean) => window.ast.getCourseBriefing(refresh);

type View = "week" | "month";
type Filter = "all" | "classes" | "deadlines";
type ClassEntry = CourseTimetable["entries"][number];
type Assignment = CourseBriefing["pending_assignments"][number];
type Deadline = { assignment: Assignment; date: string; time: string; badge: string };
type TimedClass = { entry: ClassEntry; start: number; end: number };
type PlacedClass = TimedClass & { lane: number; lanes: number };
type CalendarData = { entries: ClassEntry[]; partial: boolean };

function dateFromIso(iso: string) {
  return new Date(`${iso}T00:00:00Z`);
}

function datesBetween(start: string, end: string) {
  const days: string[] = [];
  for (let date = start; date <= end; date = shiftTimetableDate(date, 1)) days.push(date);
  return days;
}

function shiftMonth(start: string, step: number) {
  const date = dateFromIso(start);
  date.setUTCMonth(date.getUTCMonth() + step);
  return date.toISOString().slice(0, 10);
}

function clockMinutes(time: string) {
  const [hour, minute] = time.split(":").map(Number);
  return hour * minutesPerHour + minute;
}

function periodLabel(start: string, end: string, view: View) {
  const [year, month, day] = start.split("-");
  if (view === "month") return `${year}년 ${Number(month)}월`;
  const [endYear, endMonth, endDay] = end.split("-");
  if (endYear !== year) return `${year}년 ${Number(month)}월 ${Number(day)}일 – ${endYear}년 ${Number(endMonth)}월 ${Number(endDay)}일`;
  return <>{Number(month)}월 {Number(day)}일 – {month === endMonth ? "" : `${Number(endMonth)}월 `}{Number(endDay)}일 <span className="timetable-period-year">{year}년</span></>;
}

function dayOfWeek(date: string) {
  return (dateFromIso(date).getUTCDay() + 6) % weekdays.length;
}

function groupByDate<T extends { date: string }>(items: T[]) {
  const days = new Map<string, T[]>();
  for (const item of items) {
    const entries = days.get(item.date) ?? [];
    entries.push(item);
    days.set(item.date, entries);
  }
  return days;
}

export async function readCalendar(start: string, end: string, view: View, refresh: boolean, background = false): Promise<CalendarData | LmsBridgeError> {
  const requests = [start];
  if (view === "month") {
    for (let day = shiftTimetableDate(timetableWeekStart(start), 7); day <= end; day = shiftTimetableDate(day, 7)) requests.push(day);
  }
  const weeks = await Promise.all(requests.map((date) => window.ast.getCourseTimetable(date, refresh, background).catch(() => ({
    status: "error", message: "시간표를 불러오지 못했어요. 다시 시도해 주세요.",
  } as const))));
  const failed = weeks.filter((week): week is LmsBridgeError => "status" in week);
  const login = failed.find((week) => week.status === "login_required");
  if (login) return login;
  const loaded = weeks.filter((week): week is CourseTimetable => !("status" in week));
  if (!loaded.length) return failed[0];
  const entries = loaded.flatMap((week) => week.entries).filter((entry) => entry.date >= start && entry.date <= end);
  return { entries, partial: failed.length > 0 };
}

function placeClasses(classes: TimedClass[]): PlacedClass[] {
  const placed: PlacedClass[] = [];
  let group: (TimedClass & { lane: number })[] = [];
  let laneEnds: number[] = [];
  let groupEnd = 0;

  function finishGroup() {
    for (const slot of group) placed.push({ ...slot, lanes: laneEnds.length });
  }

  for (const slot of classes.sort((a, b) => a.start - b.start || b.end - a.end)) {
    if (slot.start >= groupEnd) {
      finishGroup();
      group = [];
      laneEnds = [];
      groupEnd = 0;
    }
    const available = laneEnds.findIndex((end) => end <= slot.start);
    const lane = available < 0 ? laneEnds.length : available;
    laneEnds[lane] = slot.end;
    group.push({ ...slot, lane });
    groupEnd = Math.max(groupEnd, slot.end);
  }
  finishGroup();
  return placed;
}

function DayHeading({ date, today, weekday }: { date: string; today: string; weekday: string }) {
  return <h3 className="timetable-heading" data-today={date === today || undefined}>
    <span>{weekday}</span>{" "}
    <time dateTime={date} aria-current={date === today ? "date" : undefined}>{Number(date.slice(-2))}</time>
    {date === today && <span className="timetable-today-badge">오늘</span>}
  </h3>;
}

function DeadlineButton({ item, children, onOpen }: { item: Deadline; children: ReactNode; onOpen: (item: Assignment) => void }) {
  return <button type="button" className="timetable-deadline" onClick={() => onOpen(item.assignment)}
    title={`${item.assignment.title} · ${item.assignment.course_name} · ${item.time}${item.assignment.submitted === null ? " · 제출 여부 확인 필요" : ""}`}>
    {children}
  </button>;
}

function WeekCalendar({ dates, entries, deadlines, today, filter, courseColors, onOpen }: {
  dates: string[]; entries: ClassEntry[]; deadlines: Deadline[]; today: string; filter: Filter; onOpen: (item: Assignment) => void;
  courseColors: ReadonlyMap<string, number>;
}) {
  const classes = groupByDate(entries);
  const due = groupByDate(deadlines);
  const ordered = new Map(dates.map((date) => [date, placeClasses((classes.get(date) ?? []).flatMap((entry) => {
    const start = clockMinutes(entry.start_time);
    const end = clockMinutes(entry.end_time);
    return end > start ? [{ entry, start, end }] : [];
  }))]));
  let firstHour = 9;
  let lastHour = 18;
  for (const slots of ordered.values()) for (const { start, end } of slots) {
    firstHour = Math.min(firstHour, Math.floor(start / minutesPerHour));
    lastHour = Math.max(lastHour, Math.ceil(end / minutesPerHour));
  }
  const hours = lastHour - firstHour;
  const totalMinutes = hours * minutesPerHour;
  return <div className="timetable-scroll" tabIndex={0} role="region" aria-label="주간 수업 시간표와 마감">
    <div className="timetable-grid" data-filter={filter}>
      <div className="timetable-axis" aria-hidden="true">
        <div className="timetable-heading">시간</div>
        {filter !== "classes" && <div className="timetable-deadline-label">과제 마감</div>}
        {filter !== "deadlines" && <div className="timetable-hours">
          {Array.from({ length: hours }, (_, i) => <div className="timetable-hour" key={i}>{String(firstHour + i).padStart(2, "0")}:00</div>)}
        </div>}
      </div>
      {dates.map((date, index) => <section className="timetable-day" data-weekend={index >= 5 || undefined} key={date} aria-label={`${date} ${weekdays[index]}요일`}>
        <DayHeading date={date} today={today} weekday={weekdays[index]} />
        {filter !== "classes" && <div className="timetable-deadline-cell">
          {(due.get(date) ?? []).map((item) => <DeadlineButton key={`${item.assignment.course_id}:${item.assignment.id}`} item={item} onOpen={onOpen}>
            <span className="timetable-due-badge">{item.badge} · <time dateTime={item.time}>{item.time}</time></span>
            <strong>{item.assignment.title}</strong>
          </DeadlineButton>)}
        </div>}
        {filter !== "deadlines" && <ul className="timetable-slots" data-today={date === today || undefined} style={{ height: `calc(${hours} * var(--timetable-hour-height))` }}>
          {ordered.get(date)?.map(({ entry, start, end, lane, lanes }, i) => {
            const clock = `${entry.start_time}–${entry.end_time}`;
            const room = entry.room ?? "강의실 미표시";
            const roomSource = entry.room_source === "syllabus" ? "강의계획서 기준" : undefined;
            return <li key={`${entry.course_id}:${start}:${i}`} className={`timetable-class timetable-class--${courseColors.get(entry.course_id) ?? 0}`}
              data-compact={end - start <= minutesPerHour || undefined}
              style={{ top: `${(start - firstHour * minutesPerHour) / totalMinutes * 100}%`, height: `${(end - start) / totalMinutes * 100}%`,
                left: `${lane / lanes * 100}%`, width: `${100 / lanes}%` }}>
              <div className="timetable-class-content" tabIndex={0} title={[clock, entry.course_name, entry.professor, room, roomSource].filter(Boolean).join(" · ")}>
                <time dateTime={entry.start_time}>{clock}</time>
                <strong>{entry.course_name}</strong>
                <span>{room}{roomSource && <small>{roomSource}</small>}</span>
                {entry.professor && <span className="timetable-visually-hidden">{entry.professor}</span>}
              </div>
            </li>;
          })}
        </ul>}
      </section>)}
    </div>
  </div>;
}

function MonthCalendar({ start, end, today, entries, deadlines, courseMarkers, courseColors, onDay, onOpen }: {
  start: string; end: string; today: string; entries: ClassEntry[]; deadlines: Deadline[]; onDay: (date: string) => void; onOpen: (item: Assignment) => void;
  courseMarkers: readonly string[]; courseColors: ReadonlyMap<string, number>;
}) {
  const days = datesBetween(timetableWeekStart(start), shiftTimetableDate(timetableWeekStart(end), 6));
  const classes = groupByDate(entries);
  const due = groupByDate(deadlines);
  return <div className="timetable-scroll" tabIndex={0} role="region" aria-label="월간 수업과 마감 캘린더">
    <div className="timetable-month">
      <div className="timetable-month-headings">
        {weekdays.map((day, index) => <div className="timetable-month-weekday" data-weekend={index >= 5 || undefined} key={day}>{day}</div>)}
      </div>
      <div className="timetable-month-days">
        {days.map((date, index) => <section className="timetable-month-day" data-outside={date < start || date > end || undefined}
          data-weekend={index % weekdays.length >= 5 || undefined} data-today={date === today || undefined} key={date} aria-label={date}>
          <button type="button" className="timetable-month-date" aria-label={`${date} 주간 보기`} aria-current={date === today ? "date" : undefined}
            onClick={() => onDay(date)}>
            <time dateTime={date}>{Number(date.slice(-2))}</time>
            {date === today && <span className="timetable-today-badge" aria-hidden="true">오늘</span>}
          </button>
          {(classes.get(date) ?? []).map((entry, i) => <div className="timetable-month-class" key={`${entry.course_id}:${entry.start_time}:${i}`}
            title={[`${entry.start_time}—${entry.end_time}`, entry.course_name, entry.room].filter(Boolean).join(" · ")}>
            <img src={courseMarkers[courseColors.get(entry.course_id) ?? 0]} alt="" />
            <time dateTime={entry.start_time}>{entry.start_time}</time> <span>{entry.course_name}</span>
          </div>)}
          {(due.get(date) ?? []).map((item) => <DeadlineButton key={`${item.assignment.course_id}:${item.assignment.id}`} item={item} onOpen={onOpen}>
            <time className="timetable-due-badge" dateTime={item.time}>{item.time}</time> <strong>{item.assignment.title}</strong>
          </DeadlineButton>)}
        </section>)}
      </div>
    </div>
  </div>;
}

function DeadlineSummary({ items, view, current, partial, syllabusRooms, external, onOpen }: {
  items: Deadline[]; view: View; current: boolean; partial: boolean; syllabusRooms: boolean; external: string; onOpen: (item: Assignment) => void;
}) {
  const period = view === "week" ? current ? "이번 주" : "선택한 주" : current ? "이번 달" : "선택한 달";
  const label = partial ? "확인된 과제" : "남은 과제";
  return <section className="timetable-summary" aria-label="과제 마감 요약">
    <div className="timetable-summary-header">
      <h2>{period} {label}<span className="timetable-due-badge">{items.length}건</span></h2>
      {syllabusRooms && <p>일부 강의실은 강의계획서 기준이에요.</p>}
    </div>
    {items.length ? <ul>{items.map((item) => {
      const weekday = weekdays[dayOfWeek(item.date)];
      const shortDate = item.date.slice(5).replace("-", ".");
      return <li key={`${item.assignment.course_id}:${item.assignment.id}`}><DeadlineButton item={item} onOpen={onOpen}>
        <span className="timetable-summary-date">
          <span className="timetable-due-badge">{item.badge}</span>
          <time dateTime={`${item.date}T${item.time}+09:00`}>{shortDate}({weekday}) {item.time}</time>
        </span>
        <strong>{item.assignment.title}</strong>
        <span>{item.assignment.course_name}</span>
        <img className="timetable-summary-icon" src={external} alt="" />
      </DeadlineButton></li>;
    })}</ul> : <p>이 기간에 확인된 과제 마감이 없어요.</p>}
  </section>;
}

export function Timetable({ onSignIn, onOpenAssignment, visible, assignmentSettings, now, home, mode, courses }: {
  onSignIn: () => void; onOpenAssignment: (item: Assignment) => void; visible: boolean; assignmentSettings: AssignmentVisibility; now: Date;
  home?: HomeSnapshot | null; mode: WorkspaceMode; courses: readonly { id: string }[];
}) {
  const [date, setDate] = useState<string>();
  const [view, setView] = useState<View>("week");
  const [filter, setFilter] = useState<Filter>("all");
  const icons = timetableIcons[mode];
  const today = seoulDate.format(now);
  const selected = date ?? today;
  const start = view === "week" ? timetableWeekStart(selected) : `${selected.slice(0, 7)}-01`;
  const end = view === "week" ? shiftTimetableDate(start, 6) : shiftTimetableDate(shiftMonth(start, 1), -1);
  const load = useCallback((refresh: boolean) => readCalendar(start, end, view, refresh), [start, end, view]);
  const timetable = useScreenRead(`${view}:${start}`, visible, load, false);
  const legacyBriefing = useScreenRead("timetable-deadlines", visible && !home, readBriefing, false);
  const briefing = home ? { ...legacyBriefing, data: home.briefing, error: home.error ?? null, loading: home.assignmentsLoading || !home.briefing && !home.error,
    refresh: () => void window.ast.refreshHome() } : legacyBriefing;
  const loading = timetable.loading || briefing.loading;
  const entries = timetable.data?.entries ?? [];
  const deadlines = (briefing.data?.pending_assignments ?? []).flatMap((assignment): Deadline[] => {
    const due = assignmentDueTime(assignment.due_at);
    if (!due || !isAssignmentVisible(assignment.due_at, assignmentSettings, now)) return [];
    const dueDate = seoulDate.format(due);
    if (dueDate < start || dueDate > end) return [];
    const badge = assignmentDeadline(due, now).text.replace("D-day", "D-DAY");
    return [{ assignment, date: dueDate, time: seoulClock.format(due), badge }];
  }).sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
  const partialDeadlines = Boolean(briefing.data?.unavailable?.length);
  const classEntries = filter === "deadlines" ? [] : entries;
  const visibleDeadlines = filter === "classes" ? [] : deadlines;
  const courseIds = new Set([...courses.map(({ id }) => id), ...entries.map(({ course_id }) => course_id)]);
  const courseColors = new Map([...courseIds].map((id, index) => [id, index % icons.courses.length]));
  const syllabusRooms = view === "week" && classEntries.some((entry) => entry.room_source === "syllabus");

  function refresh() { timetable.refresh(); briefing.refresh(); }
  function move(step: number) {
    setDate(view === "week" ? shiftTimetableDate(start, step * 7) : shiftMonth(start, step));
  }

  const period = <h2 aria-live="polite">{periodLabel(start, end, view)}</h2>;
  const navigation = <div className="timetable-navigation" role="group" aria-label="기간 탐색">
    <button type="button" aria-label={view === "week" ? "이전 주" : "이전 달"} onClick={() => move(-1)}>
      <img src={icons.previous} alt="" />
    </button>
    <button type="button" onClick={() => setDate(undefined)}>오늘</button>
    <button type="button" aria-label={view === "week" ? "다음 주" : "다음 달"} onClick={() => move(1)}>
      <img src={icons.next} alt="" />
    </button>
  </div>;
  const viewSwitch = <div className="timetable-views" role="group" aria-label="보기 방식">
    <button type="button" aria-pressed={view === "week"} onClick={() => setView("week")}>주간</button>
    <button type="button" aria-pressed={view === "month"} onClick={() => setView("month")}>월간</button>
  </div>;
  const filters = <div className="timetable-filters" role="group" aria-label="일정 필터">
    <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>전체</button>
    <button type="button" aria-pressed={filter === "classes"} onClick={() => setFilter("classes")}>수업 <span>{timetable.data ? entries.length : "—"}</span></button>
    <button type="button" aria-pressed={filter === "deadlines"} onClick={() => setFilter("deadlines")}>마감 <span>{briefing.data && !home?.assignmentsLoading ? deadlines.length : "—"}</span></button>
  </div>;
  const refreshButton = <button className="timetable-refresh" type="button" disabled={loading} onClick={refresh}>
    <img src={icons.refresh} alt="" />{loading ? "불러오는 중…" : "새로고침"}
  </button>;

  return <section className="timetable-screen" data-layout={mode} data-view={view} aria-labelledby="timetable-title">
    <header className="timetable-toolbar">
      <div className="timetable-title">
        <p>{mode === "focus" ? "집중 모드" : "내 학습"}</p>
        <h1 id="timetable-title">시간표 및 캘린더</h1>
      </div>
      {viewSwitch}
    </header>
    <div className="timetable-options">
      <div className="timetable-period">{navigation}{period}</div>
      <div className="timetable-actions">{filters}{refreshButton}</div>
    </div>
    <div className="timetable-content" aria-busy={loading}>
      {timetable.error && <p className="notice-inline-error" role="status">{timetable.error.message}{timetable.data && " 이전 시간표를 표시하고 있어요."}</p>}
      {timetable.data?.partial && <p className="notice-inline-error" role="status">일부 주의 시간표를 확인하지 못했어요.</p>}
      {filter !== "classes" && briefing.error && timetable.error?.status !== "login_required" && <p className="notice-inline-error" role="status">과제 마감 · {briefing.error.message}{briefing.data && " 이전 마감을 표시하고 있어요."}</p>}
      {filter !== "classes" && partialDeadlines && <p className="notice-inline-error" role="status">일부 강좌의 과제 마감을 확인하지 못했어요.</p>}
      {!timetable.data && !briefing.data ? <div className="empty">
        {timetable.error?.status === "login_required" || briefing.error?.status === "login_required" ? <button className="button button--primary" type="button" onClick={onSignIn}>로그인으로 이동</button>
          : loading ? <p role="status">시간표와 과제 마감을 불러오고 있어요.</p>
          : <button className="button" type="button" onClick={refresh}>다시 시도</button>}
      </div> : <>
        {view === "week" ? <WeekCalendar dates={datesBetween(start, end)} entries={classEntries} deadlines={visibleDeadlines} today={today} filter={filter}
          courseColors={courseColors} onOpen={onOpenAssignment} />
          : <MonthCalendar start={start} end={end} today={today} entries={classEntries} deadlines={visibleDeadlines}
            courseMarkers={icons.courses} courseColors={courseColors} onOpen={onOpenAssignment}
            onDay={(day) => { setDate(day); setView("week"); }} />}
        {filter !== "deadlines" && timetable.data && !entries.length && !timetable.data.partial && <p className="timetable-empty" role="status">이 기간에 표시할 수업이 없어요.</p>}
        {filter !== "classes" && briefing.data && !home?.assignmentsLoading && <DeadlineSummary items={deadlines} view={view} current={today >= start && today <= end}
          partial={partialDeadlines} syllabusRooms={syllabusRooms} external={icons.external} onOpen={onOpenAssignment} />}
        {filter === "classes" && syllabusRooms && <p className="timetable-room-note">일부 강의실은 강의계획서 기준이에요.</p>}
      </>}
    </div>
  </section>;
}
