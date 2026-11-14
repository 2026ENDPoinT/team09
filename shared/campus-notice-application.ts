type NoticeApplication = { deadline?: string; audience?: string };

const application = String.raw`(?:참가\s*신청|신청|접수|지원|모집|응모)`;
const deadlineLabel = String.raw`${application}\s*(?:마감(?:일시?|\s*기한)?|기한|기간)`;
const audienceLabel = String.raw`(?:신청|지원|모집|참가|참여|응모)\s*(?:대상(?:자)?|자격)`;
const field = new RegExp(String.raw`^(${deadlineLabel})|^(${audienceLabel})`, "u");
const prefix = /^(?:[○●■□▷▶※•·*\-]+\s*|\(?\d{1,2}[.)]\s+|[가-하][.)]\s*)+/u;
const separator = /^(?:\s*[:：]\s*|\s+[-–]\s+|\s+)/u;
const nextLabel = /\s+(?:[○●■□▷▶※•·*|-]\s*)?(?:(?:신청|접수|지원|모집|참가|참여|응모|행사|운영|교육|면접|심사|합격자|선발|결과)\s*){0,2}(?:방법|기간|일정|일시|대상|자격|인원|장소|결과|발표|서류|문의(?:처)?|마감(?:일(?:시)?)?)\s*[:：]/u;
const unresolved = /(?:추후\s*(?:공지|안내|확정)|미정|(?:첨부|붙임|별첨|아래|위|본문)(?:\s*(?:파일|참고자료|내용))?\s*(?:참고|참조|확인)|별도\s*(?:공지|안내))/u;

const monthDay = String.raw`(?:(?:\d{4}\s*년\s*)?(?:1[0-2]|0?[1-9])\s*월\s*(?:3[01]|[12]\d|0?[1-9])\s*일|(?:\d{4}\s*[./-]\s*)?(?:1[0-2]|0?[1-9])\s*[./-]\s*(?:3[01]|[12]\d|0?[1-9])\.?)`;
const dateTime = String.raw`${monthDay}(?:\s*\([월화수목금토일](?:요일)?\))?(?:\s*(?:오전|오후)?\s*(?:[01]?\d|2[0-4])(?::[0-5]\d|\s*시(?:\s*[0-5]?\d\s*분)?))?`;
const dateRange = new RegExp(String.raw`^(?:${dateTime}|공고일(?:로부터|부터)?)\s*(?:[~∼〜]|\s[-–—]\s)\s*${dateTime}\s*(?:까지|마감)?[.!]?$`, "u");
const dateEnd = new RegExp(String.raw`^[~∼〜]?\s*${dateTime}\s*(까지|마감)?[.!]?$`, "u");
const closingCondition = /^(?:선착순\s*마감|(?:정원|인원|예산)\s*(?:충원|소진)\s*시)(?:까지)?[.!]?$/u;
const audienceEvidence = /(?:학생|재학|휴학|복학|졸업|수료|입학|신입|청년|교직원|직원|교원|교수|연구원|구성원|주민|근로자|재직|국민|외국인|기업|사업자|대학원|동아리|학과|전공|학년|희망자|참여자|신청자|지원자|누구나|모두|팀|이수자|보유자|수상자|자격증)/u;
const audienceUnspecified = /^(?:신청자|지원자|참여자)(?:\s*전원)?[.!]?$/u;

function valueAfterLabel(line: string, following?: string): { label: string; value: string; deadline: boolean } | undefined {
  const match = line.match(field);
  if (!match) return;
  const remainder = line.slice(match[0].length);
  if (remainder && !separator.test(remainder)) return;
  const inline = remainder.replace(separator, "").trim();
  const value = inline || following;
  if (!value || (!inline && (field.test(value) || /^[^:\d：]{1,24}[:：]/u.test(value)))) return;
  return { label: match[0], value: value.split(nextLabel, 1)[0].trim(), deadline: !!match[1] };
}

function clearDeadline(value: string, label: string): boolean {
  if (closingCondition.test(value) || dateRange.test(value)) return true;
  const end = value.match(dateEnd);
  return !!end && (!label.endsWith("기간") || !!end[1] || /^[~∼〜]/u.test(value));
}

export function campusNoticeApplication(content: string): NoticeApplication {
  const lines = content.split(/\r?\n|[｜|]/u).map((line) => line.trim().replace(prefix, "")).filter(Boolean);
  const deadlines = new Set<string>();
  const audiences = new Set<string>();
  for (let index = 0; index < lines.length; index++) {
    const field = valueAfterLabel(lines[index], lines[index + 1]);
    if (!field) continue;
    const { label, value, deadline } = field;
    if (!value || value.length > 180 || unresolved.test(value)) continue;
    if (deadline) {
      if (clearDeadline(value, label)) deadlines.add(value);
    } else if (audienceEvidence.test(value) && !audienceUnspecified.test(value)) {
      audiences.add(value);
    }
  }
  return {
    ...(deadlines.size === 1 && { deadline: [...deadlines][0] }),
    ...(audiences.size === 1 && { audience: [...audiences][0] }),
  };
}
