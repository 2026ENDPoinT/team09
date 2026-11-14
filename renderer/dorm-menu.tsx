import { useCallback, useState } from "react";
import { dormNames, type Dorm, type DormMenu, type DormMenuPeriod } from "../shared/lms.js";
import { useScreenRead } from "./use-screen-read.js";
import "./dorm-menu.css";

const periods = { today: "오늘", week: "이번 주" } satisfies Record<DormMenuPeriod, string>;
const meals = [["breakfast", "아침"], ["lunch", "점심"], ["dinner", "저녁"]] as const;
const dorms = Object.keys(dormNames) as Dorm[];

const dayFormat = new Intl.DateTimeFormat("ko-KR", {
  month: "long", day: "numeric", weekday: "short", timeZone: "UTC",
});
const weekFormat = new Intl.DateTimeFormat("ko-KR", { dateStyle: "long", timeZone: "UTC" });

type MenuDay = DormMenu["days"][number];
type MenuQuery = { dorm: Dorm; period: DormMenuPeriod; preferredDorm?: Dorm };

function dateFromIso(value: string) {
  return new Date(`${value}T00:00:00Z`);
}

function DailyMenu({ day, weekly, current }: { day: MenuDay; weekly: boolean; current: boolean }) {
  const hasMeals = meals.some(([key]) => Boolean(day.meals[key]?.trim()));
  const notes = day.notes.map((note) => note.trim()).filter(Boolean);
  return (
    <article className={`dorm-menu-day${weekly && current ? " dorm-menu-day--current" : ""}`} aria-labelledby={`menu-${day.date}`}>
      <header className="dorm-menu-date">
        <time id={`menu-${day.date}`} dateTime={day.date} aria-current={current ? "date" : undefined}>
          {dayFormat.format(dateFromIso(day.date))}
        </time>
        {weekly && current && <span className="dorm-menu-today">오늘</span>}
      </header>
      {hasMeals || notes.length > 0 ? (
        <div className="dorm-menu-day-content">
          {hasMeals && (
            <dl className="dorm-menu-meals">
              {meals.map(([key, label]) => {
                const description = day.meals[key]?.trim();
                return (
                  <div className="dorm-menu-meal" key={key}>
                    <dt>{label}</dt>
                    <dd className={description ? undefined : "dorm-menu-muted"}>{description || "미게시"}</dd>
                  </div>
                );
              })}
            </dl>
          )}
          {notes.length > 0 && (
            <ul className="dorm-menu-notes" aria-label="식단 참고 사항">
              {notes.map((note, index) => <li key={index}>{note}</li>)}
            </ul>
          )}
        </div>
      ) : <p className="dorm-menu-no-day">게시된 식단이 없어요.</p>}
    </article>
  );
}

export function DormMenuView({ visible, preferredDorm }: { visible: boolean; preferredDorm?: Dorm }) {
  const [query, setQuery] = useState<MenuQuery>({ dorm: preferredDorm ?? "kb", period: "week", preferredDorm });
  if (query.preferredDorm !== preferredDorm) setQuery({ ...query, dorm: preferredDorm ?? "kb", preferredDorm });
  const dormOptions = preferredDorm ? [preferredDorm, ...dorms.filter((dorm) => dorm !== preferredDorm)] : dorms;
  const [sourceError, setSourceError] = useState(false);
  const load = useCallback((refresh: boolean) => window.ast.getDormMenu(query.dorm, query.period, refresh), [query]);
  const { data: menu, error, loading, refresh } = useScreenRead(query.dorm + ":" + query.period, visible, load);

  async function openSource() {
    setSourceError(false);
    try {
      if (!await window.ast.openDormMenuSource()) setSourceError(true);
    } catch {
      setSourceError(true);
    }
  }

  return (
    <section aria-labelledby="dorm-menu-title">
      <div className="intro">
        <h1 id="dorm-menu-title">기숙사 식단</h1>
        <div className="actions">
          <button type="button" className="button" disabled={loading} onClick={refresh}>{loading ? "불러오는 중…" : "새로고침"}</button>
          <button type="button" className="button" onClick={openSource}>생활관 식단표 보기 <span aria-hidden="true">↗</span></button>
        </div>
      </div>
      {sourceError && <p className="notice-inline-error dorm-menu-source-error" role="status">생활관 식단표를 브라우저에서 열지 못했어요.</p>}
      <div className="dorm-menu-controls">
        <div className="notice-boards dorm-menu-choices" role="group" aria-label="학사 선택">
          {dormOptions.map((dorm) => (
            <button className="button" key={dorm} type="button" aria-pressed={query.dorm === dorm}
              onClick={() => setQuery((current) => current.dorm === dorm ? current : { ...current, dorm })}>
              {dormNames[dorm]}
            </button>
          ))}
        </div>
        <div className="notice-boards dorm-menu-choices" role="group" aria-label="식단 조회 기간">
          {(Object.keys(periods) as DormMenuPeriod[]).map((period) => (
            <button className="button" key={period} type="button" aria-pressed={query.period === period}
              onClick={() => setQuery((current) => current.period === period ? current : { ...current, period })}>
              {periods[period]}
            </button>
          ))}
        </div>
      </div>
      <div aria-busy={loading}>
        {menu && error && <p className="notice-inline-error" role="status">{error.message} 이전 식단을 표시하고 있어요.</p>}
        {menu ? (
          <div className={`dorm-menu-results dorm-menu-results--${menu.period}`}>
            {menu.period === "week" && (
              <h2>{weekFormat.formatRange(dateFromIso(menu.week_start), dateFromIso(menu.week_end))}</h2>
            )}
            {menu.days.length > 0 ? menu.days.map((day) => (
              <DailyMenu key={day.date} day={day} weekly={menu.period === "week"} current={day.date === menu.on_date} />
            )) : (
              <div className="empty" role="status">
                {menu.period === "today" && <time dateTime={menu.on_date}>{dayFormat.format(dateFromIso(menu.on_date))}</time>}
                <p>게시된 식단이 없어요.</p>
              </div>
            )}
          </div>
        ) : error ? (
          <div className="empty">
            <p role="status">{error.message}</p>
            <button className="button" type="button" onClick={refresh}>다시 시도</button>
          </div>
        ) : <div className="empty"><p role="status">식단을 불러오고 있어요.</p></div>}
      </div>
    </section>
  );
}
