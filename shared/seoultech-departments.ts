// https://www.seoultech.ac.kr/univ/univ/intro
// ST자유전공학부 및 단과대학 자유전공학부는 학교의 전공자율선택제 안내를 따른다.
type Department = { id: string; name: string; college: string; website?: string };
type DepartmentGroup = [college: string, entries: [id: string, name: string, host?: string][]];

const groups: DepartmentGroup[] = [
  ["공과대학", [
    ["mechanical-systems", "기계시스템공학부", "mechsys"],
    ["intelligent-robotics", "기계시스템공학부 지능형로봇전공", "ir"],
    ["future-automotive", "기계시스템공학부 미래자동차전공", "car"],
    ["mechanical", "기계공학과", "mech"],
    ["safety", "안전공학과", "safety"],
    ["materials", "신소재공학과", "mse"],
    ["civil", "건설시스템공학과", "civil"],
    ["architecture-engineering", "건축학부 건축공학전공", "architecture"],
    ["architecture-design", "건축학부 건축학전공", "archidesign"],
    ["building-systems", "건축기계설비공학과", "ebse"],
    ["mechanical-design", "기계시스템디자인공학과", "msd"],
    ["automotive", "기계·자동차공학과", "mae"],
    ["open-engineering", "자유전공학부"],
  ]],
  ["정보통신대학", [
    ["electrical", "전기정보공학과", "eie"],
    ["electronics", "전자공학과", "ee"],
    ["computer", "컴퓨터공학과", "computer"],
    ["smart-ict", "스마트ICT융합공학과", "icte"],
    ["open-information", "자유전공학부"],
  ]],
  ["에너지바이오대학", [
    ["chemical-engineering", "화공생명공학과", "che"],
    ["environmental", "환경공학과", "enviro"],
    ["food", "식품생명공학과", "food"],
    ["chemistry", "정밀화학과", "fchem"],
    ["sports", "스포츠과학과", "sports"],
    ["optometry", "안경광학과", "optometry"],
    ["biomedical", "바이오메디컬학과", "bms"],
    ["quantum-physics", "양자융합물리학과", "physics"],
    ["open-energy-bio", "자유전공학부"],
  ]],
  ["조형대학", [
    ["industrial-design", "디자인학과 산업디자인전공", "id"],
    ["visual-design", "디자인학과 시각디자인전공", "vd"],
    ["ceramics", "도예학과", "ceramics"],
    ["metal-art", "금속공예디자인학과", "metalartdesign"],
    ["fine-art", "조형예술학과", "fineart"],
  ]],
  ["인문사회대학", [
    ["public-administration", "행정학과", "pa"],
    ["english-literature", "영어영문학과", "eng"],
    ["creative-writing", "문예창작학과", "writing-creative"],
    ["open-humanities", "자유전공학부"],
  ]],
  ["기술경영융합대학", [
    ["industrial-engineering", "산업공학과", "sgc"],
    ["industrial-information", "산업공학과 산업정보시스템전공", "iise"],
    ["itm", "산업공학과 ITM전공", "itm"],
    ["msde", "MSDE학과", "msde"],
    ["business", "경영학과", "sgc"],
    ["business-major", "경영학과 경영학전공", "biz"],
    ["gtm", "경영학과 글로벌테크노경영전공", "gtm"],
    ["open-business", "자유전공학부"],
  ]],
  ["미래융합대학", [
    ["convergence-mechanical", "융합기계공학과", "cme"],
    ["convergence-civil", "건설환경융합공학과", "civil-environmental"],
    ["fitness", "헬스피트니스학과", "wellness"],
    ["culture-art", "문화예술학과", "cab"],
    ["english", "영어과", "engculture"],
    ["venture", "벤처경영학과", "v-biz"],
    ["communications", "정보통신융합공학과", "comm"],
    ["open-future", "자유전공학부"],
  ]],
  ["창의융합대학", [
    ["ai", "인공지능응용학과", "aai"],
    ["semiconductor", "지능형반도체공학과", "dse"],
    ["future-energy", "미래에너지융합학과", "future-energy"],
    ["open-convergence", "자유전공학부"],
  ]],
  ["교양대학", [
    ["open-st", "ST자유전공학부"],
  ]],
  ["국제대학", [
    ["global-foundations", "글로벌기초교육학부", "ic"],
    ["global-open", "글로벌자유전공학부", "ic"],
    ["global-korean", "글로벌한국어문화학과", "gsklc"],
    ["global-it", "글로벌IT컨버전스학과", "gitc"],
    ["ai-media", "AI·미디어학과", "aimedia"],
  ]],
];

export const departments: Department[] = groups.flatMap(([college, entries]) =>
  entries.map(([id, name, host]) => ({ id, name, college, website: host && `https://${host}.seoultech.ac.kr/` }))
);
