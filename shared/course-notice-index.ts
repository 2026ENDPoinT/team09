import type { CourseNotice, CourseRoster, LmsBridgeError } from "./lms.js";

export const COURSE_NOTICE_BODY_BATCH = 6;

export type CourseNoticeSettings = { includeNonRegular: boolean };

export type CourseNoticeIndexedBody = {
  id: string;
  text: string;
  body_html: string;
};

export type IndexedCourseNotice = {
  notice: CourseNotice;
  body?: CourseNoticeIndexedBody;
};

export type CourseNoticeIndexSnapshot = {
  version: number;
  courses: Pick<CourseRoster["courses"][number], "id" | "name" | "category">[];
  entries: IndexedCourseNotice[];
  loading: boolean;
  partial: boolean;
  checkedAt?: number;
  error?: LmsBridgeError;
};
