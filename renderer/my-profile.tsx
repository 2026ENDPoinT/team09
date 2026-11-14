import { useCallback, useEffect, useRef } from "react";
import type { CourseRoster, StudentProfile } from "../shared/lms.js";
import { useScreenRead } from "./use-screen-read.js";
import "./my-profile.css";

type Props = {
  revision: number;
  displayName?: string;
  profile?: StudentProfile;
  roster?: CourseRoster;
  onSignIn: () => void;
  onOpenSettings: () => void;
};

export function MyProfile({ revision, displayName, profile, roster, onSignIn, onOpenSettings }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  const load = useCallback((refresh: boolean) => window.ast.getStudentProfile(revision, refresh), [revision]);
  const { data, loading, error, refresh } = useScreenRead(String(revision), true, load, false);
  const expired = error?.status === "login_required";
  const name = data?.display_name || displayName;
  const { department, year } = data ?? profile ?? {};
  const missingField = loading ? "불러오는 중…" : error ? "확인하지 못했어요" : "확인된 정보 없음";

  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);

  return (
    <section className="my-profile" aria-labelledby="my-profile-title">
      <header className="my-profile-header">
        <h1 id="my-profile-title" ref={heading} tabIndex={-1}>내 정보</h1>
        {expired
          ? <button type="button" className="button button--primary" onClick={onSignIn}>다시 로그인</button>
          : <div className="actions">
              <button type="button" className="button" onClick={refresh} disabled={loading}>프로필 새로고침</button>
              <button type="button" className="button" onClick={onOpenSettings}>설정</button>
            </div>}
      </header>
      {error && <p className="notice-inline-error" role="status">{error.message}</p>}
      {!expired && <div className="my-profile-grid">
        <section className="my-profile-card" aria-labelledby="my-profile-account">
          <h2 id="my-profile-account">e-Class 프로필</h2>
          <div className="my-profile-identity">
            <span aria-hidden="true">{name ? Array.from(name)[0] : "AST"}</span>
            <div>
              <strong>{name || (loading ? "이름 확인 중…" : "이름 미확인")}</strong>
              <p>서울과학기술대학교</p>
            </div>
          </div>
          <dl className="my-profile-fields" aria-busy={loading}>
            <div><dt>소속 학과</dt><dd>{department || missingField}</dd></div>
            <div><dt>학년</dt><dd>{year ? `${year}학년` : missingField}</dd></div>
            <div><dt>전화번호</dt><dd>{data?.phone || missingField}</dd></div>
            <div><dt>이메일</dt><dd>{data?.email || missingField}</dd></div>
          </dl>
        </section>
        <section className="my-profile-card my-profile-courses" aria-labelledby="my-profile-courses">
          <h2 id="my-profile-courses">현재 수강 과목</h2>
          {roster && <p>
            정규 {roster.regular}개 · {roster.non_regular === null ? "비정규 확인 불가" : `비정규 ${roster.non_regular}개`}
          </p>}
          {roster?.courses.length ? (
            <ul className="my-profile-course-list">
              {roster.courses.map(({ id, name, professor, category }) => <li key={id}>
                <div><strong>{name}</strong>{professor && <p>{professor}</p>}</div>
                <span>{category === "regular" ? "정규" : "비정규"}</span>
              </li>)}
            </ul>
          ) : <p>{roster ? "현재 수강 중인 과목이 없어요." : "수강 과목을 확인하지 못했어요."}</p>}
        </section>
      </div>}
    </section>
  );
}
