import calendarHomeIcon from "./assets/timetable/focus/mode-home.svg?no-inline";
import calendarFocusIcon from "./assets/timetable/focus/mode-focus.svg?no-inline";
import { workspaceModeLabels, type WorkspaceMode } from "../shared/chat-workspace.js";

export type { WorkspaceMode } from "../shared/chat-workspace.js";

const modes = ["normal", "focus"] as const;
const focusCalendarIcons = { normal: calendarHomeIcon, focus: calendarFocusIcon };

export function WorkspaceModeSwitch({ mode, onChange, focusCalendar = false }: {
  mode: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
  focusCalendar?: boolean;
}) {
  return <div className="ast-mode-switch" role="group" aria-label="홈 화면 모드" data-focus-calendar={focusCalendar || undefined}>
    {modes.map(value => (
      <button key={value} type="button" aria-pressed={mode === value} onClick={() => onChange(value)}>
        {focusCalendar && <img src={focusCalendarIcons[value]} alt="" />}
        {workspaceModeLabels[value]}
      </button>
    ))}
  </div>;
}
