import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { AssignmentVisibility } from "../shared/assignment-visibility.js";
import type { ChatConfig } from "../shared/chat.js";
import type { CourseNoticeSettings } from "../shared/course-notice-index.js";
import type { LoginSettings as LoginPreference } from "../shared/lms.js";
import { departments } from "../shared/seoultech-departments.js";
import { parseStudentPreferences, residences, type StudentPreferences } from "../shared/student-preferences.js";
import { AssignmentSettings } from "./assignment-settings.js";
import { ChatSettings } from "./chat-settings.js";
import { StudyFontSettings } from "./study-font-settings.js";
import { useScreenRead } from "./use-screen-read.js";
import "./settings.css";

const colleges = [...new Set(departments.map(({ college }) => college))];

function LoginSettings() {
  const load = useCallback(() => window.ast.getLoginSettings(), []);
  const stored = useScreenRead("login-settings", true, load, false);
  const [saved, setSaved] = useState<LoginPreference>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const current = saved ?? stored.data;

  async function save(keepLogin: boolean) {
    setSaving(true);
    setError(false);
    try {
      setSaved(await window.ast.saveLoginSettings({ keepLogin }));
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  }

  return <section className="settings-card settings-login" aria-labelledby="settings-login-title">
    <h2 id="settings-login-title">로그인 유지</h2>
    {current || stored.error ? <>
      <div className="settings-login-options" role="radiogroup" aria-labelledby="settings-login-title" aria-describedby="settings-login-help">
        <label><input type="radio" name="keep-login" value="true" checked={current?.keepLogin === true} disabled={saving}
          onChange={() => void save(true)} />매번 열 때마다 기존 로그인 세션을 재사용해요.</label>
        <label><input type="radio" name="keep-login" value="false" checked={current?.keepLogin === false} disabled={saving}
          onChange={() => void save(false)} />매번 기존 세션을 지우고 새로 로그인해요.</label>
      </div>
      <p id="settings-login-help" role="status">{saving ? "저장 중…" : saved && !error ? "저장했어요. 다음 실행부터 적용돼요." : "다음 실행부터 적용돼요."}</p>
      {error ? <p role="alert">설정을 저장하지 못했어요. 다시 시도해 주세요.</p>
        : !current && <p role="alert">저장된 설정을 불러오지 못했어요. 원하는 방식을 다시 선택해 주세요.</p>}
    </> : <p role="status">로그인 유지 설정을 불러오고 있어요.</p>}
  </section>;
}

function PreferencesForm({ initial, revision, onSave }: {
  initial: StudentPreferences;
  revision: number;
  onSave: (value: StudentPreferences) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState(initial);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const value = parseStudentPreferences(draft);
    if (!value) { setError("선택한 설정을 다시 확인해 주세요."); return; }
    setSaving(true);
    setError("");
    try {
      const next = await window.ast.saveStudentPreferences(value, revision);
      if (!next) { setError("로그인 상태를 확인한 뒤 다시 시도해 주세요."); return; }
      setDraft(next);
      onSave(next);
      setSaved(true);
    } catch {
      setError("설정을 저장하지 못했어요. 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  }

  return <form className="settings-preferences-form" onSubmit={(event) => void save(event)}
    onChange={() => { setSaved(false); setError(""); }} onReset={(event) => {
      event.preventDefault();
      setDraft(initial);
      setSaved(false);
      setError("");
    }}>
    <label>소속 학과
      <select name="departmentId" value={draft.departmentId} disabled={saving}
        onChange={(event) => {
          const departmentId = event.target.value;
          setDraft((current) => ({ ...current, departmentId }));
        }}>
        {colleges.map((college) => <optgroup key={college} label={college}>
          {departments.filter((item) => item.college === college).map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
        </optgroup>)}
      </select>
    </label>
    <label>기숙사
      <select name="residence" value={draft.residence} disabled={saving}
        onChange={(event) => {
          const residence = event.target.value as StudentPreferences["residence"];
          setDraft((current) => ({ ...current, residence }));
        }}>
        {residences.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select>
    </label>
    {error && <p className="notice-inline-error" role="alert">{error}</p>}
    <div className="settings-actions">
      {saved && <p role="status">저장했어요.</p>}
      <button className="button" type="reset" disabled={saving}>되돌리기</button>
      <button className="button button--primary" type="submit" disabled={saving}>{saving ? "저장 중…" : "저장"}</button>
    </div>
  </form>;
}

function CourseNoticePreference({ settings, loading, revision, onSave }: {
  settings: CourseNoticeSettings | null;
  loading: boolean;
  revision: number;
  onSave: (value: CourseNoticeSettings) => void;
}) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  async function save(includeNonRegular: boolean) {
    setStatus("saving");
    try {
      onSave(await window.ast.saveCourseNoticeSettings({ includeNonRegular }, revision));
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  return <section className="settings-card settings-course-notices" aria-labelledby="settings-course-notices-title">
    <h2 id="settings-course-notices-title">수업 공지 모아보기</h2>
    <label>
      <input type="checkbox" checked={settings?.includeNonRegular ?? false} disabled={loading || status === "saving"}
        onChange={(event) => void save(event.currentTarget.checked)} />
      비정규 과목 포함
    </label>
    {status === "saving" && <p role="status">저장 중…</p>}
    {status === "saved" && <p role="status">저장했어요.</p>}
    {status === "error" && <p role="alert">설정을 저장하지 못했어요. 다시 시도해 주세요.</p>}
    {!loading && !settings && status === "idle" && <p role="status">저장된 설정을 불러오지 못했어요.</p>}
  </section>;
}

type SettingsProps = {
  revision: number;
  connected: boolean;
  displayName?: string;
  preferences?: StudentPreferences | null;
  assignmentSettings: AssignmentVisibility;
  courseNoticeSettings: CourseNoticeSettings | null;
  courseNoticeSettingsLoading: boolean;
  onSignIn: () => void;
  onPreferencesSaved: (value: StudentPreferences) => void;
  onAssignmentsSaved: (value: AssignmentVisibility) => void;
  onCourseNoticeSettingsSaved: (value: CourseNoticeSettings) => void;
  onChatSaved: (value: ChatConfig) => void;
  focusChat?: boolean;
};

export function Settings({ revision, connected, displayName, preferences, assignmentSettings, courseNoticeSettings,
  courseNoticeSettingsLoading, onSignIn, onPreferencesSaved, onAssignmentsSaved, onCourseNoticeSettingsSaved, onChatSaved, focusChat }: SettingsProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const chatHeading = useRef<HTMLHeadingElement>(null);
  const load = useCallback(() => window.ast.getChatConfig(), []);
  const chat = useScreenRead("chat-config", true, load, false);
  const [config, setConfig] = useState<ChatConfig>();
  const [chatSaved, setChatSaved] = useState(false);
  const currentConfig = config ?? chat.data;

  useEffect(() => {
    const title = focusChat ? chatHeading.current : heading.current;
    title?.focus({ preventScroll: !focusChat });
  }, [focusChat]);

  return <section className="settings-page" aria-labelledby="settings-title">
    <h1 id="settings-title" ref={heading} tabIndex={-1}>설정</h1>
    <div className="settings-grid">
      <section className="settings-card settings-account" aria-labelledby="settings-account-title">
        <div>
          <h2 id="settings-account-title">ASTRA 연결</h2>
          <p>{connected ? "e-Class 연결됨" : "e-Class 로그인 필요"}{connected && displayName && ` · ${displayName}`}</p>
        </div>
        <button className="button" type="button" onClick={onSignIn}>{connected ? "ASTRA로 다시 로그인" : "ASTRA로 로그인"}</button>
      </section>
      <LoginSettings />
      <section className="settings-card" aria-labelledby="settings-preferences-title">
        <h2 id="settings-preferences-title">학교생활</h2>
        {preferences && connected ? <PreferencesForm initial={preferences} revision={revision} onSave={onPreferencesSaved} />
          : <p>로그인하면 소속 학과, 언어와 기숙사를 설정할 수 있어요.</p>}
      </section>
      {connected && <AssignmentSettings settings={assignmentSettings} revision={revision} onSave={onAssignmentsSaved} />}
      {connected && <CourseNoticePreference settings={courseNoticeSettings} loading={courseNoticeSettingsLoading} revision={revision}
        onSave={onCourseNoticeSettingsSaved} />}
      <StudyFontSettings revision={revision} connected={connected} />
      <section className="settings-card settings-chat" aria-labelledby="settings-chat-title">
        <h2 id="settings-chat-title" ref={chatHeading} tabIndex={-1}>AI 대화</h2>
        {currentConfig ? <ChatSettings config={currentConfig} onSaved={(value) => {
          setConfig(value);
          onChatSaved(value);
          setChatSaved(true);
        }} /> : chat.error ? <div className="settings-actions">
          <p role="status">{chat.error.message}</p>
          <button className="button" type="button" onClick={chat.refresh}>다시 시도</button>
        </div> : <p role="status">대화 설정을 불러오고 있어요.</p>}
        {chatSaved && <p role="status">대화 설정을 저장했어요.</p>}
      </section>
    </div>
  </section>;
}
