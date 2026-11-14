import { useLayoutEffect, useRef, useState } from "react";
import type { StudentProfile } from "../shared/lms.js";
import { departments } from "../shared/seoultech-departments.js";
import { residences, type StudentPreferences } from "../shared/student-preferences.js";
import "./student-setup.css";

const steps = [
  { key: "residence", question: "기숙사에 거주하고 계신가요?" },
  { key: "department", question: "어느 학과 소속이신가요?" },
] as const;

function searchKey(value: string) {
  return value.normalize("NFKC").toLowerCase().replace(/[\s·ㆍ()\-]/g, "");
}

function Choices<T extends string>({ name, options, value, onChange }: {
  name: string;
  options: readonly (readonly [T, string])[];
  value: T | undefined;
  onChange: (value: T) => void;
}) {
  return (
    <div className="student-setup-choices">
      {options.map(([id, label]) => (
        <label key={id} className="student-setup-option">
          <input type="radio" name={name} value={id} checked={value === id} onChange={() => onChange(id)} />
          <span>{label}</span>
        </label>
      ))}
    </div>
  );
}

export function StudentSetup({ displayName, profile, completed, sessionRevision, onComplete }: {
  displayName?: string;
  profile?: StudentProfile;
  completed: boolean;
  sessionRevision: number;
  onComplete: (preferences: StudentPreferences) => void;
}) {
  const [step, setStep] = useState(0);
  const [residence, setResidence] = useState<StudentPreferences["residence"]>();
  const [manualDepartmentId, setManualDepartmentId] = useState<string>();
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const saveInFlight = useRef(false);
  const [error, setError] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const departmentList = useRef<HTMLDivElement>(null);
  const keyword = searchKey(search);
  const matches = departments.filter(({ name, college }) => searchKey(name + college).includes(keyword));
  const reportedDepartment = profile?.department ? searchKey(profile.department) : "";
  const exactMatches = reportedDepartment ? departments.filter(({ name, college }) =>
    searchKey(name) === reportedDepartment || searchKey(college + name) === reportedDepartment) : [];
  const detectedDepartment = exactMatches.length === 1 ? exactMatches[0] : undefined;
  const departmentId = manualDepartmentId ?? detectedDepartment?.id ?? "";
  const selected = departments.find(({ id }) => id === departmentId);
  const stepCount = detectedDepartment && step === 0 ? 1 : steps.length;
  const { key, question } = steps[step];
  const ready = key === "residence" ? residence : departmentId;
  const lastStep = step === stepCount - 1;

  useLayoutEffect(() => { heading.current?.focus({ preventScroll: true }); }, [step]);

  async function advance() {
    if (!ready || saveInFlight.current || completed) return;
    if (!lastStep) {
      setStep(step + 1);
      return;
    }
    if (!residence || !departmentId) return;
    saveInFlight.current = true;
    setSaving(true);
    setError(false);
    try {
      const saved = await window.ast.saveStudentPreferences({ residence, departmentId }, sessionRevision);
      if (!saved) { setError(true); return; }
      onComplete(saved);
    } catch {
      setError(true);
    } finally {
      saveInFlight.current = false;
      setSaving(false);
    }
  }

  return (
    <section className="student-setup" aria-labelledby="student-setup-title">
      <header className="student-setup-header">
        <h1 id="student-setup-title">{displayName ? `${displayName}님 안녕하세요!` : "안녕하세요!"}</h1>
        <p aria-label={`설정 ${stepCount}단계 중 ${step + 1}단계`}>{step + 1} / {stepCount}</p>
      </header>
      <div className="student-setup-step" data-step={key} role="group" aria-labelledby="student-setup-question" aria-disabled={completed || saving}>
        <span className={`student-setup-icon student-setup-icon--${key}`} aria-hidden="true"><span /></span>
        <h2 id="student-setup-question" ref={heading} tabIndex={-1}>{question}</h2>
        <fieldset disabled={completed || saving} aria-labelledby="student-setup-question">
          {key === "residence" && <Choices name="residence" options={residences} value={residence} onChange={setResidence} />}
          {key === "department" && <>
            <p className="student-setup-hint">주 소속 학과를 선택해 주세요.</p>
            <input className="student-setup-search" type="search" aria-label="학과 이름 검색" placeholder="학과 또는 단과대학 검색"
              value={search} onChange={(event) => {
                setSearch(event.target.value);
                if (departmentList.current) departmentList.current.scrollTop = 0;
              }} />
            <div className="student-setup-departments" ref={departmentList} role="group" aria-label="검색된 학과">
              {matches.map(({ id, name, college }) => (
                <label key={id} className="student-setup-option">
                  <input type="radio" name="department" value={id} checked={departmentId === id} onChange={() => setManualDepartmentId(id)} />
                  <span>{name}<small>{college}</small></span>
                </label>
              ))}
              {!matches.length && <p className="student-setup-empty" role="status">검색 결과가 없어요.</p>}
            </div>
          </>}
        </fieldset>
      </div>
      <footer className="student-setup-footer">
        {step > 0 && <button className="student-setup-back" type="button" onClick={() => setStep(step - 1)} disabled={saving || completed}>이전</button>}
        <div className="student-setup-feedback" role="status">
          {error ? "설정을 저장하지 못했어요. 다시 시도해 주세요."
            : completed ? "홈 화면을 준비하고 있어요." : lastStep && selected ? `${selected.name} · ${selected.college}` : ""}
        </div>
        <button className="student-setup-next" type="button" disabled={!ready || saving || completed} onClick={() => void advance()}>
          {saving ? "저장 중…" : lastStep ? "설정 완료" : "계속"} <span aria-hidden="true">→</span>
        </button>
      </footer>
    </section>
  );
}
