import type { CourseTimetable, LmsBridgeError } from "../shared/lms.js";
import { shiftTimetableDate } from "../shared/timetable-week.js";

type ClassQuestion = "now" | "next";
type Entry = CourseTimetable["entries"][number];
type Slot = { entry: Entry; start: number; end: number };
type Timetable = Pick<CourseTimetable, "week_end" | "entries">;

const seoulDate = new Intl.DateTimeFormat("sv-SE", { dateStyle: "short", timeZone: "Asia/Seoul" });
const soonMs = 120 * 60_000;
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const timetableError = { status: "error", message: "수업 시간표를 확인하지 못했어요. 잠시 후 다시 물어봐 주세요." } as const;
const asksWhere = /^어디(?:야|예요|인가요|서(?:해(?:요)?|하나요)|(?:로)?가야(?:해(?:요)?|돼(?:요)?|하나요))?$/;
const asksWhich = /^(?:있어(?:요)?|있나요|뭐야|뭐예요|뭔가요)$/;

export function classQuestion(question: string): ClassQuestion | undefined {
  const text = question.trim().replace(/[ \t]/g, "").replace(/[?!.？！。]+$/u, "").replace(/^(?:나는|저는|나)/, "");
  const next = /^(?:지금)?다음(?:수업|강의)[은이]?(.*)$/.exec(text)?.[1];
  if (next !== undefined && (!next || asksWhere.test(next) || asksWhich.test(next) ||
      /^(?:언제(?:야|예요|시작해(?:요)?|시작하나요)?|알려줘(?:요)?)$/.test(next))) return "next";

  const now = /^(?:지금|현재)(?:수업|강의실?)[은이]?(.+)$/.exec(text)?.[1];
  if (now && (asksWhere.test(now) || asksWhich.test(now))) return "now";
  if (/^(?:지금|현재)(?:어느|무슨|어떤)(?:수업|강의)(?:이야|이에요|인가요|이있어(?:요)?|이있나요)$/.test(text)) return "now";
  const trip = /^(?:지금)?(.+)가야(?:해(?:요)?|돼(?:요)?|하나요)$/.exec(text)?.[1];
  if (trip && /^(?:(?:어느|무슨|어떤)(?:수업|강의)[을를]?(?:들으러)?|(?:어느|어떤)강의실(?:로)?|어디(?:로)?수업[을를]?들으러|수업[을를]?들으러어디(?:로)?)$/.test(trip)) return "now";
}

function timetableResult(reply: unknown): Timetable | LmsBridgeError {
  if (!reply || typeof reply !== "object" || ("isError" in reply && reply.isError)) return timetableError;
  const data = "structuredContent" in reply ? reply.structuredContent : reply;
  if (!data || typeof data !== "object") return timetableError;
  if ("status" in data && data.status === "login_required") {
    return { status: "login_required", message: "수업 시간표를 보려면 내 강의실에서 로그인 확인을 마쳐 주세요." };
  }
  if ("entries" in data && Array.isArray(data.entries) && "week_end" in data && typeof data.week_end === "string" &&
      datePattern.test(data.week_end) && Number.isFinite(atSeoul(data.week_end, "00:00"))) {
    return { week_end: data.week_end, entries: data.entries };
  }
  return timetableError;
}

function atSeoul(date: string, clock: string) {
  return Date.parse(`${date}T${clock}:00+09:00`);
}

function slots(entries: Entry[]): Slot[] {
  return entries.flatMap((entry) => {
    if (!entry || typeof entry.course_name !== "string" || !entry.course_name.trim()) return [];
    const start = atSeoul(entry.date, entry.start_time);
    const end = atSeoul(entry.date, entry.end_time);
    return end > start ? [{ entry, start, end }] : [];
  }).sort((a, b) => a.start - b.start);
}

function nextSlots(ordered: Slot[], now: number) {
  const first = ordered.find(({ start }) => start > now);
  return first ? ordered.filter(({ start }) => start === first.start) : [];
}

function clockText(clock: string) {
  const [hour, minute] = clock.split(":").map(Number);
  return `${hour}시${minute ? ` ${minute}분` : ""}`;
}

function startsAt(entry: Entry, today: string) {
  const [, month, day] = entry.date.split("-").map(Number);
  return `${entry.date === today ? "" : `${month}월 ${day}일 `}${clockText(entry.start_time)}`;
}

function minutesLeft(ms: number) {
  const total = Math.ceil(ms / 60_000);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return [hours ? `${hours}시간` : "", minutes ? `${minutes}분` : ""].filter(Boolean).join(" ");
}

function roomDirection(room: string) {
  const last = room.charCodeAt(room.length - 1);
  const jongseong = last >= 0xac00 && last <= 0xd7a3 ? (last - 0xac00) % 28 : 0;
  return (jongseong > 0 && jongseong !== 8) || /[036]$/.test(room) ? "으로" : "로";
}

export async function answerClassQuestion(
  intent: ClassQuestion,
  readTimetable: (date: string) => Promise<unknown>,
  signal: AbortSignal,
  now = new Date(),
): Promise<string> {
  const today = seoulDate.format(now);
  const timestamp = now.getTime();
  async function load(date: string) {
    signal.throwIfAborted();
    const reply = await readTimetable(date).catch(() => undefined);
    signal.throwIfAborted();
    return timetableResult(reply);
  }

  const week = await load(today);
  if ("status" in week) return week.message;
  const ordered = slots(week.entries);
  if (intent === "now") {
    const current = ordered.filter(({ start, end }) => start <= timestamp && timestamp < end);
    if (current.length) {
      return current.map(({ entry }) => `지금은 **${entry.course_name}** 수업 시간이에요. ${entry.room ? `**${entry.room}**에서 ` : ""}${clockText(entry.end_time)}까지 수업해요.${entry.room ? "" : " 시간표에서 강의실은 확인되지 않아요."}`).join("\n\n");
    }
  }

  let next = nextSlots(ordered, timestamp);
  const nextWeek = shiftTimetableDate(week.week_end, 1);
  if (!next.length && (intent === "next" || atSeoul(nextWeek, "00:00") - timestamp <= soonMs)) {
    const following = await load(nextWeek);
    if ("status" in following) return following.message;
    next = nextSlots(slots(following.entries), timestamp);
  }

  if (!next.length) {
    return intent === "now" ? "지금 진행 중인 수업은 없어요. 조회한 시간표에 남은 수업도 없어요." : "조회한 시간표에 다음 수업이 표시되지 않아요.";
  }
  const delay = next[0].start - timestamp;
  if (delay <= soonMs && next.length === 1) {
    const { entry } = next[0];
    const start = `${minutesLeft(delay)} 뒤인 ${startsAt(entry, today)}에 **${entry.course_name}** 수업이 시작해요.`;
    return entry.room ? `**${entry.room}**${roomDirection(entry.room)} 가면 돼요. ${start}` : `${start} 시간표에서 강의실은 확인되지 않아요.`;
  }

  const introduction = delay <= soonMs ? `${minutesLeft(delay)} 뒤에 시작하는 수업이 ${next.length}개 있어요.\n\n`
    : intent === "now" ? "지금 진행 중인 수업은 없어요. 다음 수업이에요.\n\n" : "";
  return introduction + next.map(({ entry }) => `**${entry.course_name}** 수업은 ${startsAt(entry, today)}에${entry.room ? ` **${entry.room}**에서` : ""} 시작해요.${entry.room ? "" : " 시간표에서 강의실은 확인되지 않아요."}`).join("\n\n");
}
