import { useCallback, useState, type FormEvent } from "react";
import { defaultStudyFonts, studyFontMin, studyFontMax } from "../shared/study-font-settings.js";
import { useScreenRead } from "./use-screen-read.js";

export function StudyFontSettings({ revision, connected }: { revision: number; connected: boolean }) {
  const load = useCallback(() => window.ast.getStudyFonts(revision), [revision]);
  const stored = useScreenRead("study-fonts", connected, load, false);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const saving = status === "saving";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const fields = new FormData(event.currentTarget);
    setStatus("saving");
    try {
      await window.ast.saveStudyFonts(revision, {
        summaryFont: Number(fields.get("summaryFont")),
        tutorFont: Number(fields.get("tutorFont")),
      });
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  return <section className="settings-card" aria-labelledby="settings-study-font-title">
    <h2 id="settings-study-font-title">AST 학습</h2>
    {!connected ? <p>로그인하면 강의 해설과 AI멘토의 기본 글자 크기를 설정할 수 있어요.</p>
      : stored.data ? <form className="settings-preferences-form" onSubmit={(event) => void save(event)}
        onChange={() => setStatus("idle")}>
        <label>강의 해설 글자 크기 (px)
          <input name="summaryFont" type="number" min={studyFontMin} max={studyFontMax} required
            defaultValue={stored.data.summaryFont} disabled={saving} />
        </label>
        <label>AI멘토 글자 크기 (px)
          <input name="tutorFont" type="number" min={studyFontMin} max={studyFontMax} required
            defaultValue={stored.data.tutorFont} disabled={saving} />
        </label>
        <p>기본값은 강의 해설 {defaultStudyFonts.summaryFont}px, AI멘토 {defaultStudyFonts.tutorFont}px예요.</p>
        {status === "error" && <p role="alert">글자 크기를 저장하지 못했어요. 다시 시도해 주세요.</p>}
        <div className="settings-actions">
          {status === "saved" && <p role="status">저장했어요.</p>}
          <button className="button button--primary" type="submit" disabled={saving}>{saving ? "저장 중…" : "저장"}</button>
        </div>
      </form> : stored.error ? <div className="settings-actions">
        <p role="alert">학습 글자 크기를 불러오지 못했어요.</p>
        <button className="button" type="button" onClick={stored.refresh}>다시 시도</button>
      </div> : <p role="status">학습 글자 크기를 불러오고 있어요.</p>}
  </section>;
}
