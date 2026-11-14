import type { CampusNotice, CampusNoticeBridge, SchoolCampusNoticeBoard } from "./campus-notices.js";
import type { ChatBridge } from "./chat.js";
import type { AssignmentFontSize, AssignmentTarget, CourseBrowserPage } from "./assignment-browser.js";
import type { WorkspaceActionEvent, WorkspaceActionStatus } from "./chat-workspace.js";
import type { CourseClassroomData, CourseClassroomInfo, CourseNoticePage, CourseRecentNotices } from "./course-classroom.js";
import type { CourseNoticeIndexSnapshot, CourseNoticeSettings } from "./course-notice-index.js";
import type { StudentPreferences } from "./student-preferences.js";
import type { AssignmentVisibility } from "./assignment-visibility.js";
import type { FocusLibraryBridge } from "./focus-library.js";
import type { StudyFontSettings } from "./study-font-settings.js";
import type { LectureHistoryResult, Result as LiveLectureResult } from "./live-lecture.js";

export type LmsBridgeError = {
  status: "login_required" | "error";
  message: string;
};

export type PrefetchStatus = {
  state: "idle" | "loading" | "ready" | "partial";
  completed: number;
  total: number;
  sessionRevision: number;
  homeVersion?: number;
};

export type CourseTimetable = {
  on_date: string;
  week_start: string;
  week_end: string;
  timezone: string;
  entries: {
    course_id: string;
    course_name: string;
    professor?: string;
    date: string;
    weekday: string;
    start_time: string;
    end_time: string;
    room: string | null;
    room_source?: "syllabus";
  }[];
};

type AssignmentSummary = {
  id: string;
  course_id: string;
  course_name: string;
  title: string;
  due_at: string | null;
  late_due_at?: string | null;
  deadline_checked?: boolean;
};

export type CourseNotice = {
  id: string;
  course_id: string;
  course_name: string;
  title: string;
  created_at: string | null;
  content?: string | null;
  url?: string | null;
  page?: number;
};

export type CourseNoticeDetail = {
  body_html: string;
  attachments: { id: string; name: string }[];
};

export type CourseBriefing = {
  as_of: string;
  pending_assignments: (AssignmentSummary & { submitted: false | null })[];
  completed_assignments: (AssignmentSummary & { submitted: true; submitted_at: string })[];
  recent_notices: CourseNotice[];
  unavailable?: string[];
};

export type HomeSnapshot = {
  checkedAt?: number;
  assignmentsLoading?: boolean;
  timetable: CourseTimetable | null;
  overview: CourseOverview | null;
  briefing: CourseBriefing | null;
  changes: { kind: "assignment" | "notice"; title: string; courseName: string; courseId: string; id: string; changedAt: number }[];
  error?: LmsBridgeError;
};

export type CampusBriefing = {
  as_of: string;
  notices: CampusNotice[];
  unavailable?: SchoolCampusNoticeBoard[];
};

export type Dorm = "kb" | "seonglim" | "surim";
export const dormNames = { kb: "KB학사", seonglim: "성림학사", surim: "수림학사" } satisfies Record<Dorm, string>;
export type DormMenuPeriod = "today" | "week";

export type DormMenu = {
  dorm: Dorm;
  dorm_name: string;
  period: DormMenuPeriod;
  on_date: string;
  week_start: string;
  week_end: string;
  days: {
    date: string;
    weekday: string;
    meals: { breakfast: string | null; lunch: string | null; dinner: string | null };
    notes: string[];
  }[];
  source_url: string;
};

export type LoginWindowResult = {
  status: "opened" | "already_open" | "error";
  message: string;
};

export type LoginResult = {
  status: "authenticated" | "login_required" | "error";
  message: string;
  display_name?: string;
  account_key?: string;
  course_roster?: CourseRoster;
  student_profile?: StudentProfile;
};

export type StudentProfile = { department: string | null; year: number | null };
export type StudentProfileDetails = StudentProfile & {
  display_name: string;
  phone: string | null;
  email: string | null;
};

export type AstraLoginStatus = {
  state: "idle" | "opening" | "waiting" | "verifying" | "authenticated" | "error";
  message: string;
  displayName?: string;
  courseRoster?: CourseRoster;
  studentProfile?: StudentProfile;
};

export type LoginSettings = { keepLogin: boolean };

export type CourseStats = {
  course: {
    id: string;
    name: string;
    professor: string | null;
    category: "regular" | "non_regular";
  };
  counts: Record<string, number | null>;
  total_posts: number | null;
  learning_activity?: { completed: number; total: number } | null;
  attendance?: { present: number; late: number; absent: number; early_leave: number; excused: number; unconfirmed: number } | null;
};

export type CourseOverview = {
  regular: number;
  non_regular: number | null;
  courses: CourseStats[];
};

export type CourseRoster = Omit<CourseOverview, "courses"> & { courses: CourseStats["course"][] };

export type OverviewResult =
  | { status: "ok"; overview: CourseOverview }
  | { status: "login_required" | "error"; message: string };

export type LmsBridge = CampusNoticeBridge & ChatBridge & FocusLibraryBridge & {
  getStudyFonts: (sessionRevision: number) => Promise<StudyFontSettings>;
  saveStudyFonts: (sessionRevision: number, input: StudyFontSettings) => Promise<StudyFontSettings>;
  openLiveLecture(): Promise<LiveLectureResult>;
  getLectureHistory(revision: number): Promise<LectureHistoryResult>;
  openLectureRecord(revision: number, id: string): Promise<LiveLectureResult>;
  onLectureHistoryChanged(listener: () => void): () => void;
  openAssignment: (target: AssignmentTarget) => Promise<boolean>;
  prepareAssignment: (target: AssignmentTarget, request: number, revision: number) => Promise<boolean>;
  showPreparedAssignment: (request: number) => Promise<boolean>;
  cancelPreparedAssignment: (request: number) => Promise<void>;
  openLogin: () => Promise<LoginWindowResult>;
  confirmLogin: () => Promise<LoginResult>;
  startAstraLogin: () => Promise<AstraLoginStatus>;
  getAstraLoginStatus: () => Promise<AstraLoginStatus>;
  onChatWorkspaceAction: (listener: (event: WorkspaceActionEvent) => void) => () => void;
  completeChatWorkspaceAction: (id: string, status: WorkspaceActionStatus) => Promise<void>;
  onAstraLoginStatus: (listener: (status: AstraLoginStatus) => void) => () => void;
  getLoginSettings: () => Promise<LoginSettings>;
  saveLoginSettings: (input: LoginSettings) => Promise<LoginSettings>;
  getStudentProfile: (sessionRevision: number, refresh?: boolean) => Promise<StudentProfileDetails | LmsBridgeError>;
  getStudentPreferences: () => Promise<StudentPreferences | null>;
  saveStudentPreferences: (input: StudentPreferences, sessionRevision: number) => Promise<StudentPreferences | null>;
  getAssignmentSettings: () => Promise<AssignmentVisibility>;
  saveAssignmentSettings: (input: AssignmentVisibility, sessionRevision: number) => Promise<AssignmentVisibility>;
  getAssignmentFontSize: (sessionRevision: number) => Promise<AssignmentFontSize>;
  saveAssignmentFontSize: (size: AssignmentFontSize, sessionRevision: number) => Promise<AssignmentFontSize>;
  getCourseNoticeSettings: (sessionRevision: number) => Promise<CourseNoticeSettings | LmsBridgeError>;
  saveCourseNoticeSettings: (input: CourseNoticeSettings, sessionRevision: number) => Promise<CourseNoticeSettings>;
  getPrefetchStatus: () => Promise<PrefetchStatus>;
  getHomeSnapshot: () => Promise<HomeSnapshot | null>;
  refreshHome: () => Promise<void>;
  onPrefetchStatus: (listener: (status: PrefetchStatus) => void) => () => void;
  getCourseOverview: (refresh?: boolean) => Promise<OverviewResult>;
  getCourseTimetable: (onDate?: string, refresh?: boolean, background?: boolean) => Promise<CourseTimetable | LmsBridgeError>;
  getCourseBriefing: (refresh?: boolean) => Promise<CourseBriefing | LmsBridgeError>;
  getCourseClassroom: (courseId: string, revision: number, refresh?: boolean) => Promise<CourseClassroomData | LmsBridgeError>;
  getCourseClassroomInfo: (courseId: string, revision: number, refresh?: boolean) => Promise<CourseClassroomInfo | LmsBridgeError>;
  getCourseRecentNotices: (courseId: string, revision: number, refresh?: boolean) => Promise<CourseRecentNotices | LmsBridgeError>;
  getCourseNoticePage: (courseId: string, page: number, revision: number, query?: string, refresh?: boolean) => Promise<CourseNoticePage | LmsBridgeError>;
  getCourseNoticeIndex: (revision: number, afterVersion?: number) => Promise<CourseNoticeIndexSnapshot | LmsBridgeError | null>;
  refreshCourseNoticeIndex: (revision: number) => Promise<boolean>;
  openCoursePage: (courseId: string, page: CourseBrowserPage, revision: number) => Promise<boolean>;
  getCourseNotice: (courseId: string, noticeId: string, refresh?: boolean, page?: number) => Promise<CourseNoticeDetail | LmsBridgeError>;
  openCourseNoticeOriginal: (courseId: string, noticeId: string, page?: number) => Promise<boolean>;
  openCourseNoticeLink: (courseId: string, url: string) => Promise<boolean>;
  getCampusBriefing: (refresh?: boolean) => Promise<CampusBriefing | LmsBridgeError>;
  getDormMenu: (dorm: Dorm, period: DormMenuPeriod, refresh?: boolean) => Promise<DormMenu | LmsBridgeError>;
  openDormMenuSource: () => Promise<boolean>;
};
