import type { CourseNotice } from "./lms.js";

export const COURSE_NOTICE_QUERY_LIMIT = 160;

export type CourseClassroomActivity = {
  id: string;
  kind: "assignment" | "material" | "discussion" | "lecture" | "quiz" | "survey" | "other_activity";
  title: string;
  status: "submitted" | "not_submitted" | "complete" | "incomplete" | null;
  due_at: string | null;
  details: string | null;
  url: string | null;
};

export type CourseClassroomWeek = {
  number: number | null;
  date_label: string | null;
  activities: CourseClassroomActivity[];
};

export type CourseClassroomData = {
  weeks: CourseClassroomWeek[];
  open_boards: { id: string; title: string }[];
};

export type CourseClassroomInfo = {
  course_code: string | null;
  meetings: ({ weekday: string; room: string | null } & (
    { start_time: string; end_time: string } | { periods: string }
  ))[];
};

export type CourseRecentNotices = {
  notices: CourseNotice[];
  partial?: boolean;
};

export type CourseNoticePage = CourseRecentNotices & { has_next: boolean };
