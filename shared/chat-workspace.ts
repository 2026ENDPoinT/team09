export const workspaceScreens = [
  "home", "classroom", "course", "timetable", "class-notice-index", "course-notices",
  "campus-notices", "dorm-menu", "profile", "settings", "briefing", "focus-files",
] as const;

export type WorkspaceScreen = typeof workspaceScreens[number];
export const workspaceModeLabels = { normal: "일반 모드", focus: "집중 모드" } as const;
export type WorkspaceMode = keyof typeof workspaceModeLabels;

export function isWorkspaceMode(value: unknown): value is WorkspaceMode {
  return value === "normal" || value === "focus";
}

export type WorkspaceAction =
  | { kind: "navigate"; screen: WorkspaceScreen; courseId?: string }
  | { kind: "change-mode"; mode: WorkspaceMode }
  | { kind: "assignment"; courseId: string; assignmentId: string; title: string; dueAt: string | null };

export type WorkspaceActionStatus = "ok" | "unavailable" | "assignment_missing" | "browser_failed" | "cancelled";
export type WorkspaceActionEvent = { id: string; action: WorkspaceAction } | { id: string; action?: never };
