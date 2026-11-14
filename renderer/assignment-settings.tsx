import { useEffect, useState, type FormEvent } from "react";
import { ASSIGNMENT_FONT_SIZES, DEFAULT_ASSIGNMENT_FONT_SIZE, isAssignmentFontSize, type AssignmentFontSize } from "../shared/assignment-browser.js";
import { parseAssignmentVisibility, type AssignmentVisibility } from "../shared/assignment-visibility.js";
import "./assignment-settings.css";

function AssignmentFontPreference({ revision }: { revision: number }) {
  const [fontSize, setFontSize] = useState<AssignmentFontSize | null>(null);
  const [status, setStatus] = useState<"loading" | "idle" | "saving" | "saved">("loading");
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const size = await window.ast.getAssignmentFontSize(revision);
        if (active) setFontSize(size);
      } catch {
        if (active) setError("저장된 글자 크기를 불러오지 못했어요. 다시 설정할 수 있어요.");
      } finally {
        if (active) setStatus("idle");
      }
    })();
    return () => { active = false; };
  }, [revision]);

  async function save(size: number) {
    if (!isAssignmentFontSize(size)) return;
    setStatus("saving");
    setError(undefined);
    try {
      setFontSize(await window.ast.saveAssignmentFontSize(size, revision));
      setStatus("saved");
    } catch {
      setError("글자 크기를 저장하지 못했어요. 다시 시도해 주세요.");
      setStatus("idle");
    }
  }

  return <div className="assignment-font-preference">
    <label htmlFor="assignment-font-size">과제 화면 글자 크기</label>
    <select id="assignment-font-size" value={fontSize ?? ""} disabled={status === "loading" || status === "saving"}
      aria-describedby="assignment-font-help" onChange={(event) => void save(Number(event.currentTarget.value))}>
      <option value="" disabled>{status === "loading" ? "불러오는 중…" : "크기 선택"}</option>
      {ASSIGNMENT_FONT_SIZES.map((size) => <option key={size} value={size}>{size}px{size === DEFAULT_ASSIGNMENT_FONT_SIZE && " (기본)"}</option>)}
    </select>
    <p id="assignment-font-help">과제 해설, 제출 정보, 교수자 안내에 적용해요.</p>
    {status === "saving" && <p role="status">저장 중…</p>}
    {status === "saved" && <p role="status">글자 크기를 적용했어요.</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

export function AssignmentSettings({ settings, revision, onSave }: {
  settings: AssignmentVisibility;
  revision: number;
  onSave: (settings: AssignmentVisibility) => void;
}) {
  const [includeOverdue, setIncludeOverdue] = useState(settings.includeOverdue);
  const [days, setDays] = useState(String(settings.overdueDays));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const value = parseAssignmentVisibility({ includeOverdue, overdueDays: includeOverdue ? Number(days) : settings.overdueDays });
    if (!value) { setError("표시 기간은 1일 이상의 정수로 입력해 주세요."); return; }
    setSaving(true);
    setError("");
    try {
      const next = await window.ast.saveAssignmentSettings(value, revision);
      onSave(next);
      setDays(String(next.overdueDays));
      setSaved(true);
    } catch {
      setError("설정을 저장하지 못했어요. 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  }

  return <section className="settings-card assignment-settings" aria-labelledby="assignment-settings-title">
    <h2 id="assignment-settings-title">과제 표시</h2>
    <form onSubmit={(event) => void save(event)} onChange={() => { setSaved(false); setError(""); }}>
      <label className="assignment-settings-toggle">
        <input type="checkbox" checked={includeOverdue} disabled={saving} onChange={(event) => setIncludeOverdue(event.target.checked)} />
        제출기한이 지난 과제도 표시
      </label>
      <div className="assignment-settings-range" data-inactive={!includeOverdue || undefined}>
        <label htmlFor="assignment-overdue-days">마감이 지난 뒤 며칠까지 표시할까요?</label>
        <div><input id="assignment-overdue-days" type="number" min="1" step="1" required disabled={!includeOverdue || saving}
          value={days} onChange={(event) => setDays(event.target.value)} aria-describedby="assignment-settings-help" /> 일 이내</div>
      </div>
      <p id="assignment-settings-help">홈, 과제 목록, 시간표와 채팅에 적용해요. 표시 기간은 한국 날짜 기준이에요.</p>
      {error && <p role="alert">{error}</p>}
      <footer className="settings-actions">
        {saved && <p role="status">저장했어요.</p>}
        <button className="button button--primary" type="submit" disabled={saving}>{saving ? "저장 중…" : "저장"}</button>
      </footer>
    </form>
    <AssignmentFontPreference key={revision} revision={revision} />
  </section>;
}
