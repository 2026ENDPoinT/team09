export const campusNoticeTags = {
  academic: "학사·수업",
  scholarship: "장학·등록",
  career: "취업·진로",
  learning: "비교과·교육",
  competition: "공모전·대회",
  international: "국제교류·어학",
  research: "연구·대학원",
  studentLife: "학생생활·복지",
  events: "행사·문화",
  systems: "시설·전산",
} as const;

export type CampusNoticeTag = keyof typeof campusNoticeTags;

const topicPatterns: Record<CampusNoticeTag, RegExp[]> = {
  academic: [
    /수강\s*(?:신청|정정|변경|철회|취소|편람)|강의\s*(?:계획서|평가|시간표)|교과\s*과정|교직\s*이수/,
    /휴\s*복학|휴학(?!생)|복학(?!생)|(?:복수|부|연계(?:\s*융합)?|융합)\s*전공|전과\s*(?:신청|안내|모집)|전공\s*(?:배정|선택)/,
    /학점\s*(?:인정|교류|포기)|성적\s*(?:열람|이의|정정|입력)|계절\s*학기|(?:중간|기말)\s*(?:고사|시험)|학내\s*(?:고사|시험)|시험\s*부정행위/,
    /학사\s*(?:일정|경고|제도)|졸업\s*(?:요건|자격|신청|심사|사정|학점|시험|인증)|학위\s*수여식/,
  ],
  scholarship: [
    /장학\s*(?:금|생|제도|사업|선발|지원|추천)|(?:교내|교외|근로)\s*장학|학자금\s*대출/,
    /등록\s*(?:금|고지서|납부)|(?:재학생|복학생|신입생)\s*등록\s*(?:안내|기간)|수업료/,
  ],
  career: [
    /취업|채용|인턴|현장\s*실습|창업\s*(?:지원|사업화|보육|상담)|직무\s*(?:교육|특강|캠프|체험)/,
    /진로\s*(?:상담|설계|특강|탐색|캠프|교육|프로그램)|이력서|자기\s*소개서|모의\s*면접/,
    /(?:로스쿨|법학\s*전문\s*대학원)\s*(?:진학|입시|입학|특강|설명회)/,
  ],
  learning: [
    /비교과|튜터링|학습\s*(?:지원|컨설팅|전략|공동체|코칭)|스터디\s*(?:그룹|모집)|멘토링/,
    /장비\s*(?:사용\s*)?교육|(?:3d\s*프린터|레이저\s*커터)\s*(?:장비\s*)?(?:교육|실습)|메이커\s*(?:교육|워크숍)/i,
    /글쓰기\s*(?:클리닉|워크숍|상담)|창업\s*(?:교육|캠프)/,
  ],
  competition: [
    /공모\s*전|경진\s*대회|경연\s*대회|해커톤|(?:코딩|프로그래밍|스포츠|체육|토론|발표|창업|영상|사진|디자인|창작|글쓰기)\s*대회/,
    /(?:아이디어|영상|사진|디자인|논문)\s*공모|챌린지\s*(?:공모|대회)/,
  ],
  international: [
    /로컬\s*메이트|교환\s*학생|파견\s*(?:학생|교환학생)|국제\s*교류|문화\s*교류|(?:해외|국외)\s*(?:파견|연수|교환|인턴|현장\s*실습|탐방)/,
    /어학\s*(?:연수|시험|강좌|특강|교육|클리닉|프로그램)|(?:영어|일본어|중국어|한국어|외국어)\s*(?:회화|클리닉|특강|교육|강좌|캠프|스터디)/,
    /\b(?:toeic|toefl|ielts|jlpt|hsk|topik)\b/i,
  ],
  research: [
    /대학원\s*(?:입학|신입생|설명회|연구|학사\s*일정|학위|논문)|대학원생\s*(?:연구|논문)|학위\s*(?:청구\s*)?논문|논문\s*제출\s*(?:연기|신청|안내|일정)/,
    /학술\s*(?:대회|발표|연구|세미나)|연구\s*(?:과제|지원|성과|윤리|방법론|장려)|(?:연구실|랩)\s*(?:인턴|모집)|학부\s*연구생/,
  ],
  studentLife: [
    /(?:기숙사|생활관)\s*(?:입사|퇴사|모집|신청|배정|생활|이용|운영)|학생\s*(?:복지|회비|식당|상담)|동아리\s*(?:모집|등록|박람회|활동)/,
    /마음\s*나눔\s*카페|심리\s*(?:상담|검사)|(?:마음|정신)\s*건강|건강\s*(?:검진|상담)|예방\s*접종/,
    /예비군|장애\s*학생\s*(?:지원|도우미)|학생증\s*(?:발급|신청)|통학\s*(?:버스|셔틀)/,
  ],
  events: [
    /로컬\s*메이트|축제|공연(?!히)|음악회|문화\s*(?:행사|체험|탐방)|(?:미술|사진|작품)\s*전시|전시회|영화\s*상영/,
    /개교\s*기념|(?:신입생|새내기)\s*(?:오리엔테이션|환영회)|(?:북|작가)\s*콘서트/,
  ],
  systems: [
    /(?:시설|설비|승강기|엘리베이터|냉난방|강의실|도서관|주차장|전기|전산|서버|네트워크|무선\s*인터넷|시스템)\s*(?:점검|정비|보수|개방|운영\s*시간|운영\s*중단|이용\s*안내|출입|공사|중단|장애|휴관)/,
    /정전|단수|정보\s*보안|보안\s*(?:패치|업데이트)|크롬.{0,20}(?:업데이트|보안|취약점)/,
    /\b(?:chrome|chromium|php)\b.{0,35}(?:버전|업데이트|점검|취약점|보안)|\bchrome\s*\/\s*php\b/i,
  ],
};

const tags = Object.keys(campusNoticeTags) as CampusNoticeTag[];
const topicField = /^(?:[\d.)·•○□■ -]+\s*)?(?:행사명|프로그램명|사업명|교육명|대회명|공모명|강좌명|모집\s*분야|주요\s*내용)\s*:/;
const administrativeField = /^(?:[\d.)·•○□■ -]+\s*)?(?:(?:모집|지원|신청|참가|참여)\s*)?(?:자격|대상|인원|기간|방법|서류|장소|혜택|시상|유의\s*사항|문의(?:처|\s*사항)?|첨부)(?:(?:은|는|을|를)?\s|\s*:|$)/;
const relatedTopic = /(?:와|과)\s+함께|연계(?:해|하여|한)|함께\s*(?:운영|개최|진행|제공)/;

export function classifyCampusNotice(title: string, content: string): CampusNoticeTag[] {
  const heading = title.normalize("NFKC");
  const titleTags = tags.filter((tag) => topicPatterns[tag].some((pattern) => pattern.test(heading)));
  if (titleTags.length >= 2) return titleTags.slice(0, 2);

  const lines = content.normalize("NFKC").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const topicLines = lines.filter((line) => !administrativeField.test(line));
  // A named subject can gain a second tag from a topic field or an explicitly related introduction.
  const evidence = titleTags.length
    ? topicLines.filter((line, index) => topicField.test(line) || (index < 3 && relatedTopic.test(line)))
    : topicLines.slice(0, 6);
  const bodyTags = tags.filter((tag) => !titleTags.includes(tag) &&
    evidence.some((line) => topicPatterns[tag].some((pattern) => pattern.test(line))));
  return [...titleTags, ...bodyTags].slice(0, 2);
}
