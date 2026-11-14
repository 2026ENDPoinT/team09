import { assignmentIdFromUrl, type AssignmentDetails } from "../shared/assignment-browser.js";
import { COURSE_PDF_ORIGINALS_TOOL } from "./chat-course-pdfs.js";
import { ASSIGNMENT_SUMMARY_TOOL, isAssignmentOverviewQuestion, isAssignmentStatusQuestion, pendingAssignmentPeriod } from "./chat-assignment-deadlines.js";

type RecordValue = Record<string, unknown>;
export type ToolInfo = { name: string; description?: string; inputSchema: RecordValue };

const GROUPS = {
  courses: { label: "수강 현황", tools: ["list_courses", "get_course_overview"] },
  assignments: { label: "과제·마감", tools: ["list_assignments", "get_pending_assignments", "get_upcoming_deadlines", ASSIGNMENT_SUMMARY_TOOL] },
  timetable: { label: "시간표·강의계획서", tools: ["get_course_timetable", "get_syllabus"] },
  classNotices: { label: "수업 공지", tools: ["list_notices", "search_notices"] },
  posts: { label: "강의실 게시물·토론", tools: ["list_posts", "get_post", "list_discussion_opinions", "get_discussion_opinion"] },
  files: { label: "강의실 파일·첨부", tools: ["list_course_files", "read_attachment", COURSE_PDF_ORIGINALS_TOOL] },
  campus: { label: "학교 공개 공지", tools: ["list_campus_notices", "get_campus_notice", "get_campus_briefing", "read_campus_notice_file"] },
  dorm: { label: "기숙사 식단", tools: ["get_dorm_menu"] },
  briefing: { label: "남은 과제·최근 수업 공지 모아 보기", tools: ["get_course_briefing"] },
};

export const REQUEST_TOOLS = "request_tools";

export function isPublicChatTool(name: string): boolean {
  return GROUPS.campus.tools.includes(name) || GROUPS.dorm.tools.includes(name);
}
const requestToolsDefinition = {
  type: "function",
  name: REQUEST_TOOLS,
  description: "목록에 있지만 현재 사용할 수 없는 조회 도구의 입력 규격을 요청해요. 규격을 받은 다음 응답에서 해당 도구를 호출해요.",
  parameters: {
    type: "object",
    properties: {
      names: { type: "array", items: { type: "string" }, minItems: 1, maxItems: 4 },
    },
    required: ["names"],
    additionalProperties: false,
  },
  strict: false,
};

const assignmentQuery = /과제|미제출|제출\s*기한|D[-−+]|D-day/i;
const attachmentQuery = /첨부|PDF|파일/i;
const postAttachmentQuery = /(?:과제|게시물|공지)\s*(?:(?:의|에서?|첨부된|첨부한|달린|올라온|있는|모든|전체)\s*)*(?:첨부|파일|pdf)/i;
const assignmentFollowUp = /\d+\s*주차|^(?:아냐|아니|그럼|그러면|그건|그거|그\s*과제|그\s*PDF)/i;
const fileTools = new Set(["list_course_files", "read_attachment", "read_campus_notice_file", COURSE_PDF_ORIGINALS_TOOL]);
const assignmentListTools = new Set(GROUPS.assignments.tools);
const briefingQuery = /브리핑|남은\s*할\s*일/;
const postQuery = /공지|토론|게시판|질의응답|강의자료/;
const genericAssignmentName = /^(?:과제|실습|과목|강좌|수업)$/;
const currentAssignmentMention = /(?:^|\s)(?:이|그|현재|해당|이번|지금\s*열린)\s*(?:과제|실습)/;
const quotedAssignment = /(?:과제|실습)\s*["'‘“「『][^"'’”」』\n]+["'’”」』]|^\s*(?:(?:그럼|그러면)\s+)?["'‘“「『][^"'’”」』\n]+["'’”」』]\s*(?:의\s*)?(?:과제|실습|제출\s*조건|마감)/;

export function isDocumentFollowUp(question: string): boolean {
  return /(?:이|그|해당|아까|방금|이전|앞서|앞에서)\s*(?:읽은\s*|확인한\s*|봤던\s*)?(?:PDF|첨부|파일|문서|자료)|다음\s*(?:페이지|쪽)|이어서\s*(?:읽|봐|확인)|(?:아까|방금|이전|앞서)\s*(?:읽|봤|확인)|(?:위|앞선|앞의|그)\s*내용/i.test(question);
}

export function excludesAttachmentReading(question: string): boolean {
  return /읽지\s*마|읽을\s*필요\s*없|(?:교수자\s*안내|과제\s*본문)\s*만|(?:첨부\s*파일|첨부|pdf|파일|문서)(?:은|는|을|를)?\s*(?:빼고|제외|없이|보지\s*마|안\s*(?:읽|봐|보))/i.test(question);
}

function allowsFiles(question: string, previousQuestion?: string): boolean {
  if (excludesAttachmentReading(question)) return false;
  if (/첨부|pdf|파일|문서|자료|지원서|신청서/i.test(question) || isDocumentFollowUp(question)) return true;
  if (/(?:과제|실습).{0,18}(?:내용|조건|요구사항|풀이|풀어)/.test(question)) return true;
  return !!previousQuestion && attachmentQuery.test(previousQuestion) && /^\s*(?:(?:아냐|아니)[.!\s]*)?\d+\s*주차/.test(question);
}

export function isCourseFileRequest(question: string): boolean {
  return /파일\s*모음|(?:과목|강좌|강의실|수업)\s*(?:(?:내|의|에서?|전체|올라온|있는|모든|올린)\s*)*(?:PDF|파일)/i.test(question);
}

export function isCoursePdfBatchRequest(question: string): boolean {
  if (!allowsFiles(question) || /(?:목록|제목|이름)\s*만/.test(question)) return false;
  return /pdf/i.test(question) && /읽|내용|요약|정리|분석|살펴|확인해|봐줘/.test(question) &&
    /모든|전부|전체|모두|다\s*(?:읽|확인|정리|요약)/.test(question) &&
    (isCourseFileRequest(question) || !postAttachmentQuery.test(question));
}

export function refersToCurrentCourse(question: string): boolean {
  return /^(?:(?:그럼|그러면)\s+)?(?:이|현재|해당)\s*(?:과목|강좌|강의실|수업)\s*(?:(?:의|내|에서?|에|파일모음|있는|올라온|모든|전체|전부)\s*)*pdf/i.test(question.trim());
}

type AssignmentIdentity = Pick<AssignmentDetails, "assignmentId" | "courseName" | "title">;

function requestsOtherAssignments(question: string, assignment?: AssignmentIdentity): boolean {
  if (pendingAssignmentPeriod(question)) return true;
  if ((isAssignmentStatusQuestion(question) || isAssignmentOverviewQuestion(question)) && !currentAssignmentMention.test(question) &&
      !(assignment?.title && !genericAssignmentName.test(assignment.title) && question.includes(assignment.title))) return true;
  const links = question.match(/https:\/\/[^\s<>"']+/g) ?? [];
  if (links.some((link) => {
    const id = assignmentIdFromUrl(link);
    return id && id !== assignment?.assignmentId;
  })) return true;

  let target = question;
  for (const label of [assignment?.title, assignment?.courseName]) {
    if (label?.trim() && !genericAssignmentName.test(label)) target = target.replaceAll(label, " ");
  }
  if (/(?:다른|별도|지난번|저번|이전|다음)\s*(?:(?:과목|강좌|수업)(?:의|에\s*있는)?\s*)?(?:과제|실습)/.test(target)) return true;
  if (/^\s*(?:(?:그럼|그러면)\s+)?전체\s*(?:목록|리스트)/.test(target)) return true;
  if (/(?:전체|모든|남은|미제출|다가오는)\s*(?:수업\s*)?(?:과제|실습)|(?:과제|실습)(?:의|를|들)?\s*(?:전체\s*)?(?:목록|리스트)|(?:과제|실습)(?:가|는)?\s*(?:뭐가|뭐\s*있|몇\s*(?:개|건))/.test(target)) return true;
  if (!currentAssignmentMention.test(target) && /(?:과제|실습)(?:를|을|들)?\s*전부(?!\s*(?:내용|본문))/.test(target)) return true;
  if (/(?:이번|다음|지난)\s*주\s*(?:에\s*)?(?:(?:마감(?:되는)?|제출(?:할|해야\s*하는)?)\s*(?:과제|실습)|(?:과제|실습)\s*마감)/.test(target)) return true;
  if (/\d+\s*주차(?=\s|(?:과제|실습)|$)/.test(target) && /과제|실습|제출|마감|첨부|찾|봐/.test(target)) return true;
  if (/[\p{L}\p{N}]\s*(?:과목|강좌|수업)(?:의|에\s*있는)?\s*(?:과제|실습)/u.test(target) &&
      !/(?:^|\s)(?:이|현재|해당|지금|이번)\s*(?:과목|강좌|수업)/.test(target)) return true;
  const namedSearch = target.match(/^\s*(?:(?:그럼|그러면)\s+)?(.+?)\s+(?:과제|실습)(?:을|를)?\s*(?:찾아|검색|조회)/)?.[1].trim();
  if (namedSearch && !/^(?:이|그|현재|해당|이번|지금|열린|내|우리|수업|강의실)(?:\s|$)/.test(namedSearch)) return true;
  return quotedAssignment.test(target);
}

export function assignmentQuestionScope(question: string, assignment?: AssignmentIdentity): "current" | "course-files" | "other-assignment" | "other" {
  if (requestsOtherAssignments(question, assignment)) return "other-assignment";
  if (isCourseFileRequest(question)) return "course-files";
  if (currentAssignmentMention.test(question) ||
      (assignment?.title && !genericAssignmentName.test(assignment.title) && question.includes(assignment.title))) return "current";
  if (/식단|시간표|강의\s*계획서|장학\s*(?:금|공지)|(?:학교|대학|학사|대학원|취업|수업|교수)\s*공지|수강\s*(?:과목|강좌|현황)|출결|(?:내|정규\s*수업)\s*(?:출석|결석)|(?:출석|결석)\s*(?:현황|내역|기록|횟수)|열린\s*게시판|질의응답/.test(question) || briefingQuery.test(question)) return "other";
  return "current";
}

export type CurrentAssignmentIntent = "guidance" | "solve" | "implementation" | "difficulty";

export function currentAssignmentIntent(question: string): CurrentAssignmentIntent | undefined {
  const excludesSolution = /풀(?:지|어\s*주지)\s*마|(?:풀이|정답|해설)(?:은|는|을|를)?\s*(?:빼고|말고|제외|없이|하지\s*마|필요\s*없)/.test(question);
  const asksForSolution = /풀어\s*(?:줘|주세요|줄래|봐)|(?:풀이|정답|해설)(?:을|를|도|까지)?\s*(?:(?:진행|설명|정리)\s*)?(?:해|알려|보여)\s*(?:줘|주세요|줄래)/.test(question) ||
    /(?:어떻게|어케|어캐|어찌)\s*(?:풀(?:어|음|지|면|까)|푸(?:는|나요|냐))/.test(question) ||
    /(?:푸는|풀어야\s*하는)\s*(?:법|방법).{0,8}(?:알려|설명)|(?:풀이|해설)(?:을|를)?\s*(?:보고\s*싶|부탁)/.test(question);
  if (!excludesSolution && asksForSolution) return "solve";

  const requestsUpload = /(?:제출|업로드)(?:을|를)?\s*해\s*(?:줘|주세요|줄래)/.test(question);
  const asksOnlyForDetail = /(?:마감(?:일|\s*시간)?|기한|파일\s*(?:형식|이름|명)|확장자|첨부\s*(?:목록|개수))\s*만/.test(question);
  if (requestsUpload || asksOnlyForDetail) return;
  if (/난이도|어려\s*워|어렵|어려울|쉬\s*워|쉬울|쉬운|쉽[게지도]|얼마나\s*(?:걸|힘들)|할\s*만해|빡세/.test(question)) return "difficulty";

  if (/(?:구현\s*(?:순서|절차)|뭐(?:를)?\s*부터\s*해야)/.test(question) ||
      /(?:처음(?:으로)?|먼저|우선|뭐(?:를)?\s*부터).{0,24}(?:만들|작성|구현|정의|시작)/.test(question) ||
      /(?:어떤|무슨|어느)\s*(?:클래스|함수|메서드|구조체|기능|파일(?!\s*(?:형식|이름|명(?:[이가을를은는]|\s|$)|확장자|목록|개수))).{0,16}(?:부터|만들|작성|구현|정의|필요)/.test(question) ||
      /(?:만들어야|작성해야|구현해야|정의해야)\s*(?:할|하는)\s*(?:클래스|함수|메서드|구조체|기능|파일)/.test(question)) {
    return "implementation";
  }

  if (/제출(?:은|을|하려면|하는)?\s*(?:방법|방식|절차|조건|요건|요구\s*사항|순서|어떻게|어떡해|어케|어캐|어찌)|(?:어떻게|어케|어캐|어찌)\s*(?:제출|진행|수행|시작|작성)/.test(question) ||
      /(?:진행|수행|작업|작성)\s*(?:순서|절차|방법|조건|요구\s*사항)|(?:과제|실습)(?:의|은|는|에서)?\s*(?:전체\s*)?(?:내용|요구\s*사항|조건)/.test(question) ||
      /^\s*(?:(?:그럼|그러면)\s+)?(?:필수\s*)?(?:조건|요구\s*사항)(?:을|은|이)?\s*(?:알려|정리|설명|뭐|[?？]|$)/.test(question) ||
      /(?:과제|실습|이거|이것|이걸).{0,12}(?:(?:어떻게|어케|어캐|어찌)\s*(?:해|하면|하는)|어떡해|(?:뭐\s*부터|뭐(?:를)?|뭘)\s*(?:해|해야))/.test(question)) {
    return "guidance";
  }
}

export function currentAssignmentTools(
  question: string, attachments: AssignmentDetails["attachments"], hasPreviousAttachment = false, intent?: CurrentAssignmentIntent,
): Set<string> {
  const names = new Set<string>();
  const asksPage = /\d+\s*(?:쪽|페이지)|(?:그림|도표|스크린샷|그래프|코드\s*이미지).{0,24}(?:설명|무슨|뭐|값|몇|읽|해석|보여|알려)/.test(question);
  if (excludesAttachmentReading(question) || (!intent && !asksPage && !allowsFiles(question))) return names;

  const readsFile = /읽|본문|내용|요약|분석|정리|설명|살펴|열어|봐\s*줘|확인해|확인하고|보고|참고해/.test(question);
  const asksFormat = /(?:제출(?:할)?\s*)?(?:파일\s*)?(?:형식|확장자)|\bPDF\b\s*로\s*제출/i.test(question);
  const mentionsAttachment = asksPage || /첨부|(?:파일|문서)(?:의)?\s*(?:이름|목록|내용)/.test(question) ||
    (!asksFormat && /\bPDF\b|파일|문서/i.test(question) && readsFile);
  const metadataOnly = /(?:목록|제목|이름)\s*만|(?:첨부|파일|문서)(?:의|된)?\s*(?:파일\s*)?(?:목록|리스트|제목|이름|형식|확장자|개수)/.test(question);
  const continuesReading = hasPreviousAttachment && isDocumentFollowUp(question);
  const readsContent = intent !== undefined || (!metadataOnly && (asksPage || continuesReading || mentionsAttachment && readsFile));
  if (attachments === null && (intent || mentionsAttachment) && !continuesReading) names.add("get_post");
  if (readsContent && (attachments === null || hasPreviousAttachment || attachments.some(({ name }) => /\.pdf$/i.test(name)))) {
    names.add("read_attachment");
  }
  return names;
}

function initialNames(question: string): Set<string> {
  const names = new Set<string>();
  const add = (...tools: string[]) => tools.forEach((name) => names.add(name));

  if (assignmentQuery.test(question)) add("list_courses", ...GROUPS.assignments.tools);
  if (/시간표|강의실.{0,8}(?:어디|알려)|수업\s*(?:시간|언제)|몇\s*교시/.test(question)) add("list_courses", "get_course_timetable");
  if (/강의\s*계획서/.test(question)) add("list_courses", "get_syllabus");
  if (/수강\s*(?:과목|강좌|현황)|듣는\s*(?:과목|수업)/.test(question)) add(...GROUPS.courses.tools);
  if (/출결|출석|결석|지각/.test(question)) add("get_course_overview");
  if (/토론|열린\s*게시판|질의응답|강의자료/.test(question)) add("list_courses", "list_posts");
  if (isCourseFileRequest(question)) add("list_courses", "list_course_files", "read_attachment");
  if (briefingQuery.test(question)) add("get_course_briefing");
  if (/식단|메뉴|학사.{0,10}(?:아침|점심|저녁)|기숙사.{0,10}(?:아침|점심|저녁)/.test(question)) add("get_dorm_menu");

  if (/장학|(?:학교|대학|학사|대학원|취업)\s*공지/.test(question)) {
    add("list_campus_notices", "get_campus_briefing");
  }
  if (/공지/.test(question) && /수업|강의|과목|교수|프입|e[- ]?class|이클래스|LMS/i.test(question)) {
    add("list_courses", ...GROUPS.classNotices.tools);
  }
  return names;
}

export function createToolScope(tools: ToolInfo[], question: string, previousQuestion?: string, currentTools?: ReadonlySet<string>, allowAssignmentSearch = true, assignmentOverview = false) {
  const allowed = currentTools ?? new Set(Object.values(GROUPS).flatMap(({ tools }) => tools));
  const filesAllowed = allowsFiles(question, previousQuestion);
  const metadataOnly = /(?:목록|제목|이름)\s*만/.test(question);
  const useSummary = allowAssignmentSearch && (assignmentOverview || isAssignmentStatusQuestion(question)) && tools.some(({ name }) => name === ASSIGNMENT_SUMMARY_TOOL);
  const overviewList = useSummary ? ASSIGNMENT_SUMMARY_TOOL
    : tools.some(({ name }) => name === "get_pending_assignments") ? "get_pending_assignments" : "list_assignments";
  const catalogue = new Map(tools.filter(({ name }) => {
    if (!allowed.has(name)) return false;
    if (assignmentOverview) return name === "list_courses" || name === overviewList || name === "get_post";
    if (currentTools) return true;
    if (name === ASSIGNMENT_SUMMARY_TOOL) return useSummary;
    if (useSummary && assignmentListTools.has(name)) return false;
    if (fileTools.has(name) && (!filesAllowed || (metadataOnly && name !== "list_course_files"))) return false;
    if (allowAssignmentSearch) return true;
    if (name === "get_course_briefing") return briefingQuery.test(question);
    if (name === "get_post" || name === "list_posts") return postQuery.test(question);
    return !assignmentListTools.has(name);
  }).map((tool) => [tool.name, tool]));
  const batch = !currentTools && isCoursePdfBatchRequest(question) && catalogue.has(COURSE_PDF_ORIGINALS_TOOL);
  if (!batch) catalogue.delete(COURSE_PDF_ORIGINALS_TOOL);
  let initial = batch ? new Set(["list_courses", COURSE_PDF_ORIGINALS_TOOL]) : initialNames(question);
  const followsAssignment = !initial.size && Boolean(previousQuestion && assignmentQuery.test(previousQuestion)) &&
    (attachmentQuery.test(question) || assignmentFollowUp.test(question));
  if (!initial.size && previousQuestion && (followsAssignment || /^(?:그럼|그러면|그건|그거|거기|같은)|^(?:아침|점심|저녁)(?:은|도)/.test(question))) {
    initial = initialNames(previousQuestion);
  }
  if (initial.has("list_assignments") && (attachmentQuery.test(question) ||
      (followsAssignment && attachmentQuery.test(previousQuestion ?? "")))) {
    initial.add("get_post");
    initial.add("read_attachment");
  }
  if (isDocumentFollowUp(question)) {
    initial.add("read_attachment");
    initial.add("read_campus_notice_file");
  }
  const enabled = new Set([...(currentTools ?? initial)].filter((name) => catalogue.has(name)));
  if (assignmentOverview) {
    for (const name of ["list_courses", overviewList]) {
      if (catalogue.has(name)) enabled.add(name);
    }
  }

  return {
    index: Object.values(GROUPS).map(({ label, tools }) => {
      const available = tools.filter((name) => catalogue.has(name));
      return available.length ? label + " — " + available.join(", ") : "";
    }).filter(Boolean).join("\n"),
    canDiscover: () => !assignmentOverview && !currentTools && !batch && enabled.size < catalogue.size,
    enableAssignmentOverviewDetails() {
      if (assignmentOverview && catalogue.has("get_post")) enabled.add("get_post");
    },
    definitions(discovery: boolean) {
      const visible = [...enabled].map((name) => {
        const tool = catalogue.get(name)!;
        return { type: "function", name, description: tool.description ?? "", parameters: tool.inputSchema, strict: false };
      });
      return !currentTools && discovery ? [...visible, requestToolsDefinition] : visible;
    },
    request(args: RecordValue) {
      const names = args.names;
      if (!Array.isArray(names) || names.length < 1 || names.length > 4 ||
          !names.every((name): name is string => typeof name === "string" && catalogue.has(name))) {
        return { status: "error", message: "목록에 있는 조회 도구 이름을 1~4개 지정해 주세요." };
      }
      const added = [...new Set(names)].filter((name) => !enabled.has(name));
      if (!added.length) return { status: "error", message: "이미 사용할 수 있어요. 해당 도구를 직접 호출해 주세요." };
      for (const name of added) enabled.add(name);
      return { status: "ok", enabled_tools: added };
    },
  };
}
