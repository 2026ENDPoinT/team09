import assert from "node:assert/strict";
import test from "node:test";
import { runChatTurn, ChatAgentError } from "../dist-desktop/desktop/chat-agent.js";
import { COURSE_PDF_ORIGINALS_TOOL } from "../dist-desktop/desktop/chat-course-pdfs.js";

const schema = { type: "object", properties: { dorm: { type: "string" } } };
const tool = (name) => ({ name, description: "Test-only read", inputSchema: schema });
const call = (name, id = "call1", args = {}) => ({ type: "function_call", call_id: id, name, arguments: JSON.stringify(args) });
const message = (text) => ({ type: "message", role: "assistant", content: [{ type: "output_text", text }] });
const assignmentGuide = (answer, canOfferSolution) => message(JSON.stringify({ answer, can_offer_solution: canOfferSolution }));
const options = (extra = {}) => ({ apiKey: "test-key-not-real", model: "test-model", question: "오늘 식단 알려줘", history: [], signal: new AbortController().signal, onProgress() {}, ...extra });
const response = (output) => new Response(JSON.stringify({ status: "completed", output }), { status: 200 });

test("the shared prompt interprets short reactions with the previous confirmed app result", async () => {
  let round = 0;
  const dependencies = {
    listTools: async () => [],
    callTool: async () => assert.fail("no LMS call expected"),
    workspace: { async dispatch(name, args) {
      assert.equal(name, "ast_navigate");
      assert.deepEqual(args, { screen: "classroom" });
      return { status: "ok", screen: "classroom" };
    } },
    fetch: async () => response(round++ === 0
      ? [call("ast_navigate", "classroom", { screen: "classroom" })]
      : [message("내 강의실로 이동했어요.")]),
  };
  const previous = await runChatTurn(options({ question: "내 강의실 열어줘" }), dependencies);
  const result = await runChatTurn(options({ question: "캬", history: previous.history }), {
    ...dependencies,
    workspace: { dispatch: async () => assert.fail("a reaction must not repeat the navigation") },
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.match(request.instructions, /‘캬’.+직전 대화와 앱 실행 결과/);
      assert.match(request.instructions, /문제나 정정을 구체적으로 말하면 그 내용에 답해요/);
      assert.match(request.instructions, /감탄사 뒤에 새 요청이 있으면 그 요청을 처리해요/);
      assert.ok(request.input.some(({ role, content }) => role === "assistant" && content.includes("앱에서 확인된 실행 결과: AST 화면 이동 완료")));
      assert.deepEqual(request.tools, []);
      return response([message("잘 됐네요!")]);
    },
  });
  assert.equal(result.text, "잘 됐네요!");
});

test("workspace actions receive their results before the model continues and run only once per target", async () => {
  const stages = [
    [message("프입 강의실을 확인할게요."), call("ast_lookup_workspace", "courses")],
    [call("ast_lookup_workspace", "assignments", { course_id: "programming" })],
    [call("ast_open_assignment", "open", { course_id: "programming", assignment_id: "101" })],
    [message("10주차 실습을 열었어요."), call("ast_continue", "next", { reason: "요청한 뒤이은 캘린더 이동" })],
    [call("ast_open_assignment", "repeat", { assignment_id: "101", course_id: "programming" }),
      call("ast_navigate", "calendar", { screen: "timetable" })],
    [message("10주차 실습을 열고 캘린더로 이동했어요.")],
  ];
  const results = [
    { status: "ok", courses: [{ course_id: "programming", name: "프로그래밍입문" }] },
    { status: "ok", assignments: [{ week: 10, assignment_id: "101", title: "10주차 실습" }] },
    { status: "ok", title: "10주차 실습" },
    { status: "ok", screen: "timetable" },
  ];
  const dispatched = [];
  let catalogueRequests = 0;
  let round = 0;
  const result = await runChatTurn(options({ question: "프입 과제 열어주고 캘린더로 이동해줘" }), {
    listTools: async () => { catalogueRequests++; return []; },
    callTool: async () => assert.fail("workspace calls must not be forwarded to MCP"),
    workspace: { async dispatch(name, args) {
      dispatched.push({ name, args });
      return results[dispatched.length - 1];
    } },
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.equal(request.tools.some(({ name }) => name === "ast_continue"), round < 4);
      const outputs = request.input.filter(({ type }) => type === "function_call_output");
      if (round === 3) assert.deepEqual(JSON.parse(outputs.at(-1).output), results[2]);
      if (round === 4) {
        assert.equal(outputs.at(-1).call_id, "next");
        assert.equal(JSON.parse(outputs.at(-1).output).status, "ok");
      }
      if (round === 5) assert.deepEqual(JSON.parse(outputs.at(-1).output), results[3]);
      return response(stages[round++]);
    },
  });
  assert.equal(result.text, "10주차 실습을 열고 캘린더로 이동했어요.");
  assert.equal(catalogueRequests, 0, "a request to open and navigate needs no MCP catalogue");
  assert.deepEqual(dispatched.map(({ name }) => name), ["ast_lookup_workspace", "ast_lookup_workspace", "ast_open_assignment", "ast_navigate"]);
});

test("workspace opening requires an action request and a user-provided or verified URL", async () => {
  const dispatch = async () => assert.fail("workspace must not open");
  for (const question of ["캘린더 여는 방법 알려줘", "과제 열지 말고 마감만 알려줘", "오늘 수업 일정 알려줘",
    "‘캘린더 열어줘’ 문장 번역해줘", "https://example.com/open 이 주소 요약해줘"]) {
    await runChatTurn(options({ question }), {
      listTools: async () => [], callTool: async () => assert.fail("no MCP call expected"), workspace: { dispatch },
      fetch: async (_url, init) => {
        const request = JSON.parse(init.body);
        assert.ok(request.tools.every(({ name }) => !name.startsWith("ast_")));
        assert.match(request.instructions, /AST 앱은 화면 이동, 주차별 과제 열기, 브라우저 열기를 지원해요/);
        assert.doesNotMatch(request.instructions, /ast_navigate|ast_open_assignment|ast_open_browser|ast_request_skill/);
        return response([message("테스트 답변이에요.")]);
      },
    });
  }
  let round = 0;
  await runChatTurn(options({ question: "이 링크 열어줘" }), {
    listTools: async () => [], callTool: async () => assert.fail("no MCP call expected"), workspace: { dispatch },
    fetch: async (_url, init) => {
      if (round++ === 0) return response([call("ast_open_browser", "bad", { url: "https://example.com/" })]);
      const output = JSON.parse(init.body).input.at(-1);
      assert.equal(JSON.parse(output.output).status, "error");
      return response([message("열 주소를 알려주세요.")]);
    },
  });
});

test("direct study mode commands open the matching home without invoking the model or LMS", async () => {
  for (const [question, mode, label] of [
    ["일반모드로 전환해줘.", "normal", "일반 모드"],
    ["학습 모드를 집중 모드로 좀 바꿔 줄 수 있어?", "focus", "집중 모드"],
    ["집중 모드 홈으로 이동해주세요", "focus", "집중 모드"],
    ["집중 모드로 다시 전환해줘", "focus", "집중 모드"],
  ]) {
    const actions = [];
    const result = await runChatTurn(options({ question }), {
      listTools: async () => assert.fail("mode changes must not read the LMS"),
      callTool: async () => assert.fail("mode changes must not call the LMS"),
      fetch: async () => assert.fail("a direct command must not call the model"),
      workspace: { async dispatch(name, args) {
        actions.push([name, args]);
        return { status: "ok", mode, screen: "home" };
      } },
    });
    assert.deepEqual(actions, [["ast_change_mode", { mode }]]);
    assert.equal(result.text, `${label} 홈으로 이동했어요.`);
  }
});

test("mode guidance and quoted commands cannot change mode, and combined requests are scoped to the requested mode", async () => {
  for (const question of ["집중 모드를 바꾸는 방법 알려줘", "집중모드로 바꿔 주지 마", "'집중모드로 바꿔줘'를 영어로 번역해줘"]) {
    await runChatTurn(options({ question }), {
      listTools: async () => [], callTool: async () => assert.fail("no LMS call expected"),
      workspace: { dispatch: async () => assert.fail("only direct requests may change mode") },
      fetch: async (_url, init) => {
        assert.ok(JSON.parse(init.body).tools.every(({ name }) => name !== "ast_change_mode"));
        return response([message("테스트 답변이에요.")]);
      },
    });
  }
  const actions = [];
  let round = 0;
  await runChatTurn(options({ question: "집중 모드로 전환하고 캘린더를 열어줘" }), {
    listTools: async () => assert.fail("local actions need no LMS catalogue"),
    callTool: async () => assert.fail("no LMS call expected"),
    workspace: { async dispatch(name, args) {
      actions.push([name, args]);
      return { status: "ok" };
    } },
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.ok(request.tools.some(({ name }) => name === "ast_change_mode"));
      switch (round++) {
        case 0: return response([call("ast_change_mode", "wrong", { mode: "normal" })]);
        case 1:
          assert.equal(JSON.parse(request.input.at(-1).output).status, "error");
          return response([call("ast_change_mode", "right", { mode: "focus" })]);
        case 2: return response([call("ast_navigate", "calendar", { screen: "timetable" })]);
        default: return response([message("집중 모드 캘린더를 열었어요.")]);
      }
    },
  });
  assert.deepEqual(actions, [["ast_change_mode", { mode: "focus" }], ["ast_navigate", { screen: "timetable" }]]);
});

test("an obvious action starts with its own skill and an indirect action can load a missing skill", async () => {
  const dispatched = [];
  let catalogueRequests = 0;
  const dependencies = {
    listTools: async () => { catalogueRequests++; return []; },
    callTool: async () => assert.fail("navigation must not read LMS data"),
    workspace: { async dispatch(name, args) {
      dispatched.push([name, args]);
      return { status: "ok", screen: "timetable" };
    } },
  };
  let round = 0;
  await runChatTurn(options({ question: "캘린더 좀 보여줘" }), {
    ...dependencies,
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.deepEqual(request.tools.map(({ name }) => name), ["ast_navigate", "ast_continue", "ast_request_skill"]);
      assert.doesNotMatch(request.instructions, /다가오는 미제출 과제가 하나면/);
      return response(round++ === 0 ? [call("ast_navigate", "nav", { screen: "timetable" })] : [message("캘린더로 이동했어요.")]);
    },
  });
  assert.equal(catalogueRequests, 0, "a direct navigation skips the catalogue");
  round = 0;
  await runChatTurn(options({ question: "아까 거기로 이동해 줘" }), {
    ...dependencies, fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      const names = request.tools.map(({ name }) => name);
      switch (round++) {
        case 0:
          assert.deepEqual(names, ["ast_request_skill"]);
          return response([call("ast_request_skill", "load", { skill: "navigate" }),
            call("ast_navigate", "early", { screen: "timetable" })]);
        case 1: {
          const outcomes = request.input.filter(({ type }) => type === "function_call_output");
          assert.equal(JSON.parse(outcomes[0].output).skill, "navigate");
          assert.equal(JSON.parse(outcomes[1].output).status, "error");
          assert.ok(names.includes("ast_navigate") && !names.includes("ast_open_assignment"));
          return response([call("ast_navigate", "nav", { screen: "timetable" })]);
        }
        default: return response([message("캘린더로 이동했어요.")]);
      }
    },
  });
  assert.deepEqual(dispatched, Array(2).fill(["ast_navigate", { screen: "timetable" }]));
});

test("a short answer completes an assignment clarification and can open a verified prior source", async () => {
  const dispatched = [];
  const dependencies = {
    listTools: async () => [],
    callTool: async () => assert.fail("use the app skill"),
    workspace: { async dispatch(name, args) {
      dispatched.push([name, args]);
      return { status: "ok" };
    } },
  };
  const first = await runChatTurn(options({ question: "프입 과제 열어줘" }), {
    ...dependencies, fetch: async () => response([message("9주차와 10주차 실습이 있어요. 어느 과제를 열까요?")]),
  });
  let round = 0;
  await runChatTurn(options({ question: "10주차", history: first.history }), {
    ...dependencies, fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.ok(request.input.some(({ content }) => content === "프입 과제 열어줘"));
      assert.ok(request.tools.some(({ name }) => name === "ast_open_assignment"));
      return response(round++ === 0 ? [call("ast_open_assignment", "open", { course_id: "programming", assignment_id: "101" })]
        : [message("10주차 실습을 열었어요.")]);
    },
  });
  round = 0;
  const url = "https://www.seoultech.ac.kr/fixture";
  await runChatTurn(options({ question: "그거 열어줘", previousSources: [{ title: "테스트 공지", url }] }), {
    ...dependencies, fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.ok(request.tools.some(({ name }) => name === "ast_open_browser"));
      assert.ok(request.input.some(({ content }) => typeof content === "string" && content.includes(url)));
      return response(round++ === 0 ? [call("ast_open_browser", "open", { url })] : [message("공지를 열었어요.")]);
    },
  });
  assert.deepEqual(dispatched, [
    ["ast_open_assignment", { course_id: "programming", assignment_id: "101" }],
    ["ast_open_browser", { url }],
  ]);
});

test("structured assignment guidance streams only the decoded answer and retains the final solution flag", async () => {
  const assignment = { assignmentId: "1001", courseId: "test-course", courseName: "테스트 강의",
    title: "테스트 과제", description: "테스트 안내", attachments: [], dueAt: null };
  const answer = '제출 안내\n"예시"를 확인해요. 🙂';
  const json = '{"answer":"제출 안내\\n\\"예시\\"를 확인해요. \\uD83D\\uDE42","can_offer_solution":true}';
  const events = [
    { type: "response.in_progress" },
    ...Array.from(json, (delta) => ({ type: "response.output_text.delta", delta })),
    { type: "response.completed", response: { status: "completed", output: [assignmentGuide(answer, true)] } },
  ];
  const bytes = new TextEncoder().encode(events.map((event) => "data: " + JSON.stringify(event) + "\r\n\r\n").join(""));
  const pieces = [];
  const result = await runChatTurn(options({ assignment, question: "이 과제 어떻게 제출해?", onAnswer: (text) => pieces.push(text) }), {
    listTools: async () => [],
    callTool: async () => assert.fail("no tool call expected"),
    fetch: async (_url, init) => {
      assert.equal(JSON.parse(init.body).stream, true);
      assert.equal(JSON.parse(init.body).text.format.name, "assignment_guidance");
      return new Response(new ReadableStream({
        start(controller) {
          for (let index = 0; index < bytes.length; index += 37) controller.enqueue(bytes.slice(index, index + 37));
          controller.close();
        },
      }), { headers: { "Content-Type": "text/event-stream" } });
    },
  });
  assert.equal(pieces.join(""), answer);
  assert.ok(pieces.includes("🙂"));
  assert.equal(result.text, answer + "\n\n풀이도 해볼까요?");
});

const assignmentNow = new Date("2026-11-13T12:00:00+09:00");
const deadlineRows = [
  { id: "101", title: "범위 밖 실습", due_at: "2026-11-09T23:59:00+09:00", submitted: false },
  { id: "102", title: "다음 주 실습", due_at: "2026-11-17T23:59:00+09:00", submitted: false },
  { id: "103", title: "최근 지난 실습", due_at: "2026-11-10T11:00:00+09:00", submitted: false },
  { id: "104", title: "오늘 지난 실습", due_at: "2026-11-13T11:59:00+09:00", submitted: false },
  { id: "105", title: "오늘 남은 실습", due_at: "2026-11-13T14:59:00Z", submitted: false },
  { id: "106", title: "마감 미확인 실습", due_at: null, submitted: null },
].map((row) => ({ ...row, course_id: "test-course", course_name: "테스트 과목" }));

test("the pending-assignment answer puts Seoul D-days first and limits overdue results to the saved range", async () => {
  const run = (assignmentSettings) => runChatTurn(options({
    question: "나 뭐 안 한 과제 있어?", now: assignmentNow, assignmentSettings,
  }), {
    listTools: async () => [tool("get_pending_assignments")],
    callTool: async (name, args) => {
      assert.equal(name, "get_pending_assignments");
      assert.deepEqual(args, {});
      return { structuredContent: { result: deadlineRows } };
    },
    fetch: async () => assert.fail("This confirmed list needs no model"),
  });
  const current = await run(undefined);
  assert.deepEqual(current.sources.map(({ title }) => title), ["오늘 남은 실습", "다음 주 실습", "마감 미확인 실습"]);
  assert.match(current.text, /\*\*D-day\*\*.*오늘 남은 실습/);
  assert.match(current.text, /\*\*D-4\*\*.*다음 주 실습/);
  assert.match(current.text, /마감일 확인 필요[\s\S]*제출 여부 확인 필요/);
  assert.equal(current.cost.calls, 0);

  const including = await run({ includeOverdue: true, overdueDays: 3 });
  assert.match(including.text, /\*\*오늘 마감 지남\*\*.*오늘 지난 실습/);
  assert.match(including.text, /\*\*D\+3\*\*.*최근 지난 실습/);
  assert.doesNotMatch(including.text, /범위 밖 실습/);
});

test("weekly assignment questions verify once without model calls and use the Seoul calendar week", async () => {
  const weeklyRows = [
    ...deadlineRows.slice(0, -1),
    { ...deadlineRows[4], id: "107", title: "일요일 밤 과제", due_at: "2026-11-15T14:59:00Z", late_due_at: "2026-11-18T23:59:00+09:00" },
    { ...deadlineRows[4], id: "108", title: "월요일 자정 과제", due_at: "2026-11-15T15:00:00Z" },
    { ...deadlineRows[4], id: "109", title: "날짜를 확인하지 못한 새 과제", due_at: "2026-12-02", submitted: null, deadline_checked: false },
    { ...deadlineRows[4], id: "110", title: "이미 제출한 과제", submitted: true },
  ];
  const calls = [];
  const deps = {
    listTools: async () => ["get_pending_assignments", "get_upcoming_deadlines", "get_assignment_summary"].map(tool),
    callTool: async (name, args) => {
      calls.push([name, args]);
      return { structuredContent: { status: "ok", as_of: assignmentNow.toISOString(), assignments: weeklyRows, unavailable: ["미확인 강좌"] } };
    },
    fetch: async () => assert.fail("Confirmed assignment rows should be rendered locally"),
  };
  const weekly = await runChatTurn(options({ question: "이번 주 남은 과제 알려줘", now: assignmentNow }), deps);
  assert.deepEqual(calls, [["get_assignment_summary", {}]]);
  assert.deepEqual(weekly.sources.map(({ assignment }) => assignment.assignmentId), ["105", "107", "109"]);
  assert.match(weekly.text, /이번 주 미제출 과제 2개/);
  assert.match(weekly.text, /일요일 밤 과제[\s\S]*11월 15일.+마감 · 지각 제출 11월 18일.+까지/);
  assert.match(weekly.text, /### 마감일 확인 필요[\s\S]*날짜를 확인하지 못한 새 과제[\s\S]*제출 여부 확인 필요/);
  assert.match(weekly.text, /일부 강좌의 목록이나 과제 상세를 확인하지 못했어요/);
  assert.match(weekly.text, /e-Class 목록 확인/);
  assert.doesNotMatch(weekly.text, /월요일 자정 과제|다음 주 실습|이미 제출한 과제|12월 2일/);
  assert.equal(weekly.cost.calls, 0);

  const rolling = await runChatTurn(options({ question: "앞으로 7일 안에 마감되는 과제 알려줘", now: assignmentNow }), deps);
  assert.deepEqual(calls, [["get_assignment_summary", {}], ["get_assignment_summary", {}]]);
  assert.match(rolling.text, /앞으로 7일 미제출 과제 4개/);
  assert.match(rolling.text, /월요일 자정 과제/);
  assert.match(rolling.text, /다음 주 실습/);
});

test("empty partial assignment data and login errors never become a confirmed empty list", async () => {
  for (const [reply, expected] of [
    [{ status: "ok", assignments: [], unavailable: ["미확인 강좌"] }, /확인된 미제출 과제가 없어요[\s\S]*일부 강좌/],
    [{ status: "login_required", message: "e-Class에 로그인해 주세요." }, /^e-Class에 로그인해 주세요\.$/],
  ]) {
    const result = await runChatTurn(options({ question: "남은 과제 알려줘", now: assignmentNow }), {
      listTools: async () => [tool("get_assignment_summary")],
      callTool: async () => ({ structuredContent: reply }),
      fetch: async () => assert.fail("Summary errors are handled locally"),
    });
    assert.match(result.text, expected);
    assert.doesNotMatch(result.text, /표시할 미제출 과제가 없어요/);
    assert.deepEqual(result.sources, []);
    assert.equal(result.cost.calls, 0);
  }
});

test("a named-course deadline lookup gets one latest summary after resolving the course", async () => {
  const calls = [];
  const requests = [];
  const result = await runChatTurn(options({ question: "테스트 과목 남은 과제 마감 알려줘", now: assignmentNow }), {
    listTools: async () => ["list_courses", "get_assignment_summary", "get_pending_assignments", "get_upcoming_deadlines", "list_assignments"].map(tool),
    callTool: async (name, args) => {
      calls.push([name, args]);
      if (name === "list_courses") return [{ id: "test-course", name: "테스트 과목" }];
      return { structuredContent: { status: "ok", assignments: [
        deadlineRows[4],
        { ...deadlineRows[4], id: "201", title: "기한 갱신 확인 중", due_at: "2026-12-20", late_due_at: "2026-12-21", deadline_checked: false },
        deadlineRows[0],
      ], unavailable: ["상세 일부 확인 필요"] } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      requests.push(body);
      assert.deepEqual(body.tools.map(({ name }) => name), ["list_courses", "get_assignment_summary"]);
      if (requests.length === 1) return response([call("list_courses")]);
      if (requests.length === 2) return response([call("get_assignment_summary", "summary", { course_id: "test-course" })]);
      const evidence = body.input.find(({ type, call_id }) => type === "function_call_output" && call_id === "summary");
      assert.match(evidence.output, /기한 갱신 확인 중.*"due_at":null.*"late_due_at":null/);
      assert.match(evidence.output, /상세 일부 확인 필요/);
      assert.doesNotMatch(evidence.output, /범위 밖 실습|2026-12-20|2026-12-21/);
      return response([message("오늘 남은 실습을 확인했어요.")]);
    },
  });
  assert.deepEqual(calls, [["list_courses", {}], ["get_assignment_summary", { course_id: "test-course" }]]);
  assert.match(result.text, /오늘 남은 실습/);
});

test("an assignment overview checks the course and pending work before reading only confirmed assignment directions", async () => {
  const executed = [];
  const courseId = "test-course";
  const post = { kind: "assignment", course_id: courseId, post_id: "105" };
  const question = "프입 과제 확인해봐. 나 할만한거 있어?";
  let round = 0;
  const result = await runChatTurn(options({ question, now: assignmentNow }), {
    listTools: async () => ["list_courses", "list_assignments", "get_assignment_summary", "get_post", "read_attachment", "list_course_files"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      if (name === "list_courses") return [{ id: courseId, name: "프로그래밍입문" }];
      if (name === "get_assignment_summary") return { status: "ok", assignments: [deadlineRows[4]] };
      assert.deepEqual([name, args], ["get_post", post]);
      return { ...deadlineRows[4], kind: "assignment", content: "문자열을 입력받아 길이를 출력하는 프로그램을 작성하세요.",
        attachments: [{ id: "901", name: "강의자료.pdf" }] };
    },
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.match(request.instructions, /첫 문장은 확인된 미제출 과제의 유무와 개수부터/);
      assert.match(request.instructions, /제목과 파일명만 보고 과제 내용이나 난이도를 추측하지 않아요/);
      const names = request.tools.map(({ name }) => name);
      switch (round++) {
        case 0:
          assert.deepEqual(names, ["list_courses", "get_assignment_summary"]);
          return response([call("list_courses")]);
        case 1:
          assert.ok(!names.includes("get_post"));
          return response([call("get_assignment_summary", "overview", { course_id: courseId })]);
        case 2:
          assert.deepEqual(names, ["list_courses", "get_assignment_summary", "get_post"]);
          return response([call("get_post", "unverified", { ...post, post_id: "999" })]);
        case 3:
          assert.equal(JSON.parse(request.input.at(-1).output).status, "error");
          return response([call("get_post", "directions", post)]);
        default:
          assert.match(request.input.at(-1).output, /문자열을 입력받아 길이를 출력/);
          return response([message("미제출 과제가 1개 있어요. 오늘 남은 실습은 문자열을 입력받아 길이를 출력하는 과제예요.")]);
      }
    },
  });
  assert.deepEqual(executed, [["list_courses", {}], ["get_assignment_summary", { course_id: courseId }], ["get_post", post]]);
  assert.match(result.text, /^미제출 과제가 1개 있어요/);
  assert.deepEqual(result.sources.map(({ assignment }) => assignment), [{ courseId, assignmentId: "105" }]);
});

test("an empty assignment overview cannot open posts or attachments", async () => {
  await runChatTurn(options({ question: "아직 할 만한 과제 있어?" }), {
    listTools: async () => ["get_assignment_summary", "get_post", "read_attachment"].map(tool),
    callTool: async (name) => {
      assert.equal(name, "get_assignment_summary");
      return { status: "ok", assignments: [], unavailable: ["확인하지 못한 강좌가 있어요."] };
    },
    fetch: async (_url, init) => {
      const request = JSON.parse(init.body);
      assert.deepEqual(request.tools.map(({ name }) => name), ["get_assignment_summary"]);
      const evidence = request.input.at(-1);
      if (evidence.role === "user") return response([call("get_assignment_summary")]);
      assert.match(evidence.output, /unavailable/);
      return response([message("확인된 미제출 과제는 없어요. 일부 강좌는 확인하지 못했어요.")]);
    },
  });
});

test("a detailed follow-up reads only PDFs attached to the previously identified assignment", async () => {
  const question = "그 과제 좀 더 자세히 봐줘";
  const target = { title: "오늘 남은 실습", assignment: { courseId: "test-course", assignmentId: "105" } };
  const locator = { kind: "assignment", course_id: "test-course", post_id: "105" };
  const calls = [];
  const result = await runChatTurn(options({ question, previousSources: [target, { title: "다른 과목 자료.pdf" }] }), {
    listTools: async () => assert.fail("the target is already confirmed"),
    callTool: async (name, args) => {
      calls.push([name, args]);
      if (name === "get_post") return { id: "105", course_id: "test-course", kind: "assignment", content: "FYI",
        attachments: [{ id: "901", name: "실습 안내.PDF" }, { id: "902", name: "입력 예시.txt" }] };
      return { id: "901", pages: ["문자열 길이를 계산하는 프로그램을 만들고 소스 코드를 제출하세요."], total_pages: 1, start_page: 1, next_page: null };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.tools, []);
      assert.match(body.instructions, /작업 순서와 제출물/);
      const evidence = JSON.parse(body.input[0].content);
      assert.equal(evidence.assignment, target.title);
      assert.deepEqual(evidence.attachments.map(({ name }) => name), ["실습 안내.PDF"]);
      assert.match(evidence.attachments[0].output, /소스 코드를 제출/);
      assert.doesNotMatch(body.input[0].content, /다른 과목 자료|입력 예시|FYI/);
      return response([message("문자열 길이를 계산하는 프로그램을 만든 뒤 소스 코드를 제출해요. 실습 안내.PDF 1쪽에 나와 있어요.")]);
    },
  });
  assert.deepEqual(calls, [["get_post", locator], ["read_attachment", { ...locator, attachment_id: "901", max_pages: 25 }]]);
  assert.equal(result.sources[0].assignment.assignmentId, "105");
  assert.match(result.text, /소스 코드를 제출해요/);
});

test("an ambiguous assignment follow-up asks for a choice before reading and handles assignments without PDFs", async () => {
  const question = "그 과제 좀 더 자세히 봐줘";
  const previousSources = ["첫 번째 실습", "두 번째 실습"].map((title, index) => ({
    title, assignment: { courseId: "test-course", assignmentId: String(105 + index) },
  }));
  const dependencies = {
    listTools: async () => assert.fail("the target is already confirmed"),
    callTool: async () => assert.fail("an ambiguous request must not read attachments"),
    fetch: async () => assert.fail("no model is needed to ask for a choice"),
  };
  const clarification = await runChatTurn(options({ question, previousSources }), dependencies);
  assert.match(clarification.text, /어느 과제.*\n\n1\. 첫 번째 실습\n2\. 두 번째 실습/);
  const result = await runChatTurn(options({ question: "2번이요", history: clarification.history, previousSources: clarification.sources }), {
    ...dependencies,
    callTool: async (name, args) => {
      assert.deepEqual([name, args], ["get_post", { kind: "assignment", course_id: "test-course", post_id: "106" }]);
      return { attachments: [{ id: "902", name: "제출 양식.txt" }] };
    },
  });
  assert.match(result.text, /첨부된 PDF가 없어요/);
  assert.deepEqual(result.sources.map(({ title }) => title), ["두 번째 실습"]);
});

test("a casual difficulty question uses saved PDF text and visual evidence without requesting the original", async () => {
  const assignment = {
    assignmentId: "101", courseId: "test-course", courseName: "테스트 과목", title: "10주차 실습",
    description: "FYI", dueAt: null, attachments: [{ id: "901", name: "실습.pdf" }],
  };
  let notesReads = 0;
  const reply = await runChatTurn(options({ question: "이거 과제 어려워보여 ㅑ ?", assignment }), {
    listTools: async () => [],
    callTool: async () => assert.fail("do not reread cached material"),
    openAssignmentPdf: async () => assert.fail("the notes are sufficient"),
    assignmentPdfNotes: async (target, requireNotes) => {
      assert.equal(target, assignment);
      assert.equal(requireNotes, true);
      notesReads++;
      return { omittedFiles: [], documents: [{ id: "901", name: "실습.pdf", overview: "상속 실습", coverage: "complete",
        sections: [{ from: 2, to: 3, text: "기본 생성자와 인수 전단 생성자를 구현해요.", visuals: "클래스 상속 화살표가 두 개예요." }] }] };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.match(body.instructions, /현재 과제의 난이도/);
      assert.match(JSON.stringify(body.input), /클래스 상속 화살표가 두 개/);
      assert.doesNotMatch(JSON.stringify(body.input), /file_data|base64/);
      return response([message("중간 정도예요. 실습.pdf 2~3쪽의 두 종류 생성자와 클래스 상속을 함께 구현해야 해요.")]);
    },
  });
  assert.equal(notesReads, 1);
  assert.equal(reply.cost.calls, 1);
  assert.match(reply.text, /중간 정도/);
});

test("only the verified PDF is sent once when the stored record lacks a visual detail", async () => {
  const assignment = {
    assignmentId: "101", courseId: "test-course", courseName: "테스트 과목", title: "실습",
    description: "FYI", dueAt: null, attachments: [{ id: "901", name: "실습.pdf" }],
  };
  const original = { type: "input_file", filename: "assignment-original.pdf", file_data: "data:application/pdf;base64,JVBERi0=", detail: "high" };
  let requests = 0;
  let opened = 0;
  const reply = await runChatTurn(options({ question: "첨부 PDF 4쪽 그림 오른쪽에 적힌 정확한 값 알려줘", assignment }), {
    listTools: async () => [],
    callTool: async () => assert.fail("the selected file supplies the visual"),
    assignmentPdfNotes: async () => ({ omittedFiles: [], documents: [{ id: "901", name: "실습.pdf", overview: "그래프",
      coverage: "partial", sections: [{ from: 1, to: 1, text: "그래프 제목", visuals: "" }] }] }),
    openAssignmentPdf: async (target, id) => {
      assert.equal(target, assignment);
      assert.equal(id, "901");
      opened++;
      return original;
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      if (++requests === 1) {
        assert.ok(body.tools.some(({ name }) => name === "open_assignment_pdf"));
        return response([
          call("open_assignment_pdf", "wrong", { attachment_id: "other" }),
          call("open_assignment_pdf", "right", { attachment_id: "901" }),
        ]);
      }
      const result = body.input.find(({ type, call_id }) => type === "function_call_output" && call_id === "right");
      assert.deepEqual(result.output[1], original);
      assert.equal(body.tools.length, 0, "the final answer does not resend a PDF in another round");
      return response([message("실습.pdf 4쪽 오른쪽 그래프의 값은 15예요.")]);
    },
  });
  assert.equal(requests, 2);
  assert.equal(opened, 1);
  assert.doesNotMatch(JSON.stringify(reply.history), /JVBERi0|file_data/);
});

test("an already open overdue assignment answers with its own materials even when overdue listings are hidden", async () => {
  const assignment = {
    assignmentId: "101", courseId: "test-course", courseName: "테스트 과목", title: "지난 주 실습",
    dueAt: "2026-10-20T23:59:00+09:00", lateDueAt: "2026-10-24T23:59:00+09:00",
    submissionMethod: "온라인", submissionFormat: "파일첨부", description: "교수자 안내", attachments: null,
  };
  const now = new Date("2026-11-14T06:55:00+09:00");
  const documents = [];
  const reply = await runChatTurn(options({
    question: "첨부파일 확인해서 풀이 진행해줘.", assignment, now, assignmentAnalysis: "이 창에 표시한 예제 요약",
    assignmentSettings: { includeOverdue: false, overdueDays: 7 },
  }), {
    listTools: async () => ["get_post", "read_attachment"].map(tool),
    callTool: async (name, args) => {
      documents.push([name, args]);
      assert.equal(args.course_id, assignment.courseId);
      assert.equal(args.post_id, assignment.assignmentId);
      return name === "get_post"
        ? { title: assignment.title, due_at: assignment.dueAt, attachments: [{ id: "901", name: "실습 문제.pdf" }] }
        : { filename: "실습 문제.pdf", pages: ["테스트 배열을 정렬해요."] };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      const context = body.input.find(({ content }) => typeof content === "string" && content.startsWith("현재 과제 참고 자료"));
      const snapshot = JSON.parse(context.content.split("\n")[1]);
      assert.equal(snapshot.dueAt, assignment.dueAt);
      assert.equal(snapshot.lateDueAt, assignment.lateDueAt);
      assert.equal(snapshot.submissionFormat, assignment.submissionFormat);
      assert.equal(snapshot.analysisExcerpt, "이 창에 표시한 예제 요약");
      assert.match(JSON.stringify(body.input), /테스트 배열을 정렬해요/);
      assert.match(body.instructions, /이미 열린 과제는 마감이 지났어도 학습 질문에 답해요/);
      return response([message("첨부 문제를 바탕으로 풀이를 설명해요.")]);
    },
  });
  assert.equal(reply.cost.calls, 1);
  assert.equal(reply.text, "첨부 문제를 바탕으로 풀이를 설명해요.");
  assert.deepEqual(documents.map(([name]) => name), ["get_post", "read_attachment"]);
  assert.equal(documents[1][1].attachment_id, "901");
});

test("overdue assignment data is filtered before reaching the model even via briefing and post lookup", async () => {
  const question = "테스트 과목의 과제와 브리핑 알려줘";
  const tools = ["list_posts", "list_assignments", "get_course_briefing", "get_post"].map(tool);
  const calls = [];
  const requests = [];
  const result = await runChatTurn(options({ question, now: assignmentNow }), {
    listTools: async () => tools,
    callTool: async (name, args) => {
      calls.push([name, args]);
      if (name === "get_course_briefing") return { pending_assignments: deadlineRows, completed_assignments: [], recent_notices: [] };
      if (name === "get_post") return { kind: "assignment", ...deadlineRows[0], content: "범위 밖 원문" };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      requests.push(body);
      const round = requests.length;
      if (round === 1 && !body.tools.some(({ name }) => name === "get_post")) {
        return response([call("request_tools", "discover", { names: ["get_post"] })]);
      }
      if (!body.input.some(({ call_id, type }) => call_id === "briefing" && type === "function_call_output")) {
        return response([call("get_course_briefing", "briefing")]);
      }
      if (!body.input.some(({ call_id, type }) => call_id === "post" && type === "function_call_output")) {
        return response([call("get_post", "post", { kind: "assignment", post_id: "101", course_id: "test-course" })]);
      }
      const outputs = body.input.filter(({ type }) => type === "function_call_output").map(({ output }) => output).join("\n");
      assert.match(outputs, /deadline_label.*D-4/);
      assert.doesNotMatch(outputs, /범위 밖 실습|범위 밖 원문|오늘 지난 실습/);
      return response([message("**D-4** 다음 주 실습")]);
    },
  });
  assert.equal(result.text, "**D-4** 다음 주 실습");
  assert.deepEqual(calls.map(([name]) => name), ["get_course_briefing", "get_post"]);
});

test("tool data and encrypted reasoning are available within a turn and dropped before the next request", async () => {
  const requests = [];
  const executed = [];
  const opaque = { type: "reasoning", id: "rs_test", encrypted_content: "encrypted-test-only", summary: [] };
  const deps = {
    listTools: async () => [tool("get_dorm_menu"), tool("list_assignments"), tool("start_desktop_login"), tool("download_campus_notice_file"), tool("submit_assignment")],
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: { dorm_name: "KB학사", source_url: "https://housing.seoultech.ac.kr/livng/dining/", meals: ["검증용 메뉴"], nested: { url: "https://evil.example/", title: "Reject" } } };
    },
    fetch: async (url, init) => {
      assert.equal(url, "https://api.openai.com/v1/responses");
      assert.equal(init.redirect, "error");
      const body = JSON.parse(init.body); requests.push(body);
      assert.equal(body.store, false);
      assert.deepEqual(body.tools.map((item) => item.name), ["get_dorm_menu", "request_tools"]);
      assert.match(body.instructions, /list_assignments/);
      assert.doesNotMatch(body.instructions, /submit_assignment|download_campus_notice_file|start_desktop_login/);
      return response(requests.length === 1 ? [opaque, call("get_dorm_menu", "c1", { dorm: "kb" })] : [message("확인했어요.")]);
    },
  };
  const result = await runChatTurn(options(), deps);
  assert.equal(result.text, "확인했어요.");
  assert.deepEqual(executed, [["get_dorm_menu", { dorm: "kb" }]]);
  assert.match(requests[1].input.find((item) => item.type === "function_call_output").output, /검증용 메뉴/);
  assert.deepEqual(result.sources, [{ title: "KB학사", url: "https://housing.seoultech.ac.kr/livng/dining/" }]);
  assert.ok(requests[1].input.some((item) => item.encrypted_content === opaque.encrypted_content));
  assert.doesNotMatch(JSON.stringify(result.history), /검증용 메뉴|encrypted-test-only|function_call/);
  const follow = await runChatTurn(options({ question: "그럼 저녁은?", history: result.history }), deps);
  assert.equal(follow.history.length, 2);
  assert.doesNotMatch(JSON.stringify(requests[2].input), /검증용 메뉴|encrypted-test-only|function_call/);
  assert.deepEqual(follow.sources, []);
});

test("unknown mutations and malformed arguments are never dispatched", async () => {
  let round = 0;
  const result = await runChatTurn(options(), {
    listTools: async () => [tool("get_dorm_menu"), tool("submit_assignment")],
    callTool: async () => { assert.fail("untrusted calls must not reach MCP"); },
    fetch: async (_url, init) => {
      round++;
      if (round === 1) return response([call("submit_assignment"), { ...call("get_dorm_menu", "c2"), arguments: "null" }]);
      const body = JSON.parse(init.body);
      const errors = body.input.filter((item) => item.type === "function_call_output");
      assert.equal(errors.length, 2);
      assert.ok(errors.every((item) => JSON.parse(item.output).status === "error"));
      return response([message("허용된 조회만 가능해요.")]);
    },
  });
  assert.match(result.text, /조회/);
});

test("aborted tool response cannot become a completed answer or new history", async () => {
  const abort = new AbortController();
  const results = [];
  let fetched = 0;
  await assert.rejects(runChatTurn(options({ signal: abort.signal, onResult: (text) => results.push(text) }), {
    listTools: async () => [tool("get_dorm_menu")],
    callTool: async () => { abort.abort(); return { dorm_name: "KB학사", days: [{}] }; },
    fetch: async () => { fetched++; return response([call("get_dorm_menu")]); },
  }), (error) => error instanceof ChatAgentError && /중지/.test(error.message));
  assert.equal(fetched, 1);
  assert.deepEqual(results, []);
});

test("oversized results are explicitly partial and rounds terminate with tools disabled", async () => {
  let round = 0;
  let dispatched = 0;
  let sawTruncation = false;
  const result = await runChatTurn(options({ question: "최근 수업 공지 알려줘" }), {
    listTools: async () => [tool("list_notices")],
    callTool: async () => { dispatched++; return { content: "가".repeat(20000) }; },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body); round++;
      if (round > 1) sawTruncation ||= body.input.some((item) => item.type === "function_call_output" && JSON.parse(item.output).truncated);
      if (body.tool_choice === "none") return response([message("확인한 일부 공지만 정리했어요.")]);
      assert.ok(round <= 6);
      return response([call("list_notices", "c" + round)]);
    },
  });
  assert.ok(sawTruncation);
  assert.ok(dispatched <= 6 && round <= 7);
  assert.match(result.text, /일부/);
});

test("legacy tool history is reduced to bounded conversational messages", async () => {
  const history = Array.from({ length: 10 }, (_, i) => ({ items: [
    { role: "user", content: "old-" + i }, call("get_dorm_menu", "c" + i),
    { type: "function_call_output", call_id: "c" + i, output: JSON.stringify({ value: "x".repeat(18000) }) }, message("done"),
  ] }));
  await runChatTurn(options({ history }), {
    listTools: async () => [], callTool: async () => {},
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      const callIds = body.input.filter((i) => i.type === "function_call").map((i) => i.call_id);
      const outputs = body.input.filter((i) => i.type === "function_call_output").map((i) => i.call_id);
      assert.deepEqual(outputs, []);
      assert.deepEqual(callIds, []);
      assert.equal(body.input.filter(({ role, content }) => role === "user" && content.startsWith("old-")).length, 8);
      return response([message("답변")]);
    },
  });
});

test("API errors expose a safe message, not provider response or key", async () => {
  await assert.rejects(runChatTurn(options(), {
    listTools: async () => [], callTool: async () => {},
    fetch: async () => new Response("private-server-debug-and-api-key", { status: 401 }),
  }), (error) => error instanceof ChatAgentError && /키/.test(error.message) && !/private|test-key/.test(error.message));
});

test("old source cap never crowds out the current verified source", async () => {
  const history = [{ items: [
    { role: "user", content: "학교 공지" }, call("list_campus_notices", "old1"),
    { type: "function_call_output", call_id: "old1", output: JSON.stringify(Array.from({ length: 25 }, (_, index) => ({
      title: "Old source " + index, url: "https://www.seoultech.ac.kr/service/info/notice?bidx=" + index,
    }))) }, message("이전 공지들이에요."),
  ] }];
  let round = 0;
  const result = await runChatTurn(options({ history }), {
    listTools: async () => [tool("get_dorm_menu")],
    callTool: async () => ({ dorm_name: "새 식단", source_url: "https://housing.seoultech.ac.kr/livng/dining/" }),
    fetch: async () => response(++round === 1 ? [call("get_dorm_menu", "fresh")] : [message("오늘의 식단이에요.")]),
  });
  assert.deepEqual(result.sources, [{ title: "새 식단", url: "https://housing.seoultech.ac.kr/livng/dining/" }]);
});

test("an unrelated deadline question cannot read or reuse an earlier PDF, and explicit continuation rereads it", async () => {
  const attachment = { kind: "file_collection", course_id: "course-a", attachment_id: "fixture-pdf" };
  const tools = ["read_attachment", "get_assignment_summary"].map(tool);
  const calls = [];
  const requests = [];
  const deps = {
    listTools: async () => tools,
    callTool: async (name, args) => {
      calls.push([name, args]);
      if (name === "get_assignment_summary") return { structuredContent: { status: "ok", assignments: [] } };
      return { structuredContent: { name: "예시 강의.pdf", pages: [args.start_page ? "NEW_PAGE" : "OLD_RAW_PAGE"], next_page: 2 } };
    },
  };
  async function run(question, history, outputs) {
    let round = 0;
    return runChatTurn(options({ question, history }), { ...deps, fetch: async (_url, init) => {
      requests.push(JSON.parse(init.body));
      return response(outputs[round++]);
    } });
  }
  const first = await run("이 PDF 읽어줘", [], [[call("read_attachment", "old", attachment)], [message("OLD_ANSWER_QUOTE")]]);
  assert.deepEqual(first.sources, [{ title: "예시 강의.pdf" }]);
  assert.doesNotMatch(JSON.stringify(first.history), /OLD_RAW_PAGE|OLD_ANSWER_QUOTE|function_call_output/);
  const unrelated = await run("이번 주 남은 과제 알려줘", first.history, []);
  assert.equal(requests.length, 2);
  assert.deepEqual(unrelated.sources, []);
  assert.deepEqual(calls, [["read_attachment", attachment], ["get_assignment_summary", {}]]);

  const next = await run("아까 읽은 PDF 다음 페이지도 읽어줘", unrelated.history,
    [[call("read_attachment", "new", { ...attachment, start_page: 2 })], [message("다음 페이지를 확인했어요.")]]);
  assert.match(requests[2].instructions, /예시 강의\.pdf.*nextPage.*2/);
  assert.doesNotMatch(JSON.stringify(requests[2]), /OLD_RAW_PAGE|OLD_ANSWER_QUOTE/);
  assert.match(JSON.stringify(requests[3].input), /NEW_PAGE/);
  assert.deepEqual(calls.at(-1), ["read_attachment", { ...attachment, start_page: 2 }]);
  assert.deepEqual(next.sources, [{ title: "예시 강의.pdf" }]);
});

test("course-dependent LMS lists are not presented as direct sources", async () => {
  let round = 0;
  const result = await runChatTurn(options({ question: "수업 공지 알려줘" }), {
    listTools: async () => [tool("list_notices")],
    callTool: async () => [
      { title: "Misleading notice", url: "https://eclass.seoultech.ac.kr/ilos/cls/st/notice/notice_list_form.acl" },
      { course_name: "Misleading course", url: "https://eclass.seoultech.ac.kr/ilos/cls/st/submain/submain_form.acl" },
      { title: "Course switch", url: "https://eclass.seoultech.ac.kr/ilos/cls/st/co/eclass_room2.acl" },
      { title: "Exact activity", url: "https://eclass.seoultech.ac.kr/ilos/cls/st/activity/activity_form.acl?m=discuss&n=123" },
      { title: "Public notice", url: "https://www.seoultech.ac.kr/service/info/notice?do=commonview&bidx=123" },
      { dorm_name: "Dorm", source_url: "https://housing.seoultech.ac.kr/livng/dining/?foodtype=kb" },
    ],
    fetch: async () => response(++round === 1 ? [call("list_notices")] : [message("공지와 식단을 확인했어요.")]),
  });
  assert.deepEqual(result.sources.map((item) => item.title), ["Exact activity", "Public notice", "Dorm"]);
});

test("a verified course notice gets its own link and keeps its course and page", async () => {
  const sourceUrl = "https://eclass.seoultech.ac.kr/ilos/cls/st/notice/notice_list_form.acl";
  const noticeUrl = sourceUrl + "#notice=123";
  let round = 0;
  const result = await runChatTurn(options({ question: "수업 공지 알려줘" }), {
    listTools: async () => [tool("list_notices")],
    callTool: async () => [{ course_id: "course-a", id: "123", page: 2, title: "일정 안내", url: sourceUrl }],
    fetch: async (_url, init) => {
      if (++round === 1) return response([call("list_notices")]);
      const request = JSON.parse(init.body);
      assert.equal(JSON.parse(request.input.at(-1).output)[0].notice_url, noticeUrl);
      return response([message(`[일정 안내](${noticeUrl})를 확인해요.`)]);
    },
  });
  assert.deepEqual(result.sources, [{ title: "일정 안내", url: noticeUrl, courseNotice: { courseId: "course-a", noticeId: "123", page: 2 } }]);
});

test("assignment lookup discovers only requested schemas and emits verified lookup results", async () => {
  const outputs = [
    [call("list_assignments", "a")],
    [call("request_tools", "b", { names: ["get_post"] })],
    [call("get_post", "c", { kind: "assignment", course_id: "fixture-course", post_id: "fixture-post" })],
    [call("request_tools", "d", { names: ["read_attachment"] })],
    [call("read_attachment", "e", { attachment_id: "fixture-file" })],
    [message("실습 요구사항을 확인했어요.")],
  ];
  const requests = [];
  const executed = [];
  const results = [];
  const result = await runChatTurn(options({
    question: "프입 과제 내용 알려줘",
    onResult: (text) => results.push(text),
  }), {
    listTools: async () => ["list_courses", "list_assignments", "get_post", "read_attachment", "get_dorm_menu"].map(tool),
    callTool: async (name) => {
      executed.push(name);
      if (name === "list_assignments") {
        return { structuredContent: { result: [{ title: "10주차 실습 과제", id: "fixture-post" }] } };
      }
      if (name === "get_post") {
        return { structuredContent: { title: "10주차 실습 과제", content: "첨부 참고", attachments: [{ id: "fixture-file" }] } };
      }
      return { structuredContent: { name: "실습.pdf", pages: ["테스트용 요구사항"] } };
    },
    fetch: async (_url, init) => {
      requests.push(JSON.parse(init.body));
      return response(outputs[requests.length - 1]);
    },
  });

  assert.deepEqual(requests[0].tools.map(({ name }) => name), ["list_courses", "list_assignments", "request_tools"]);
  assert.ok(requests[2].tools.some(({ name }) => name === "get_post"));
  assert.ok(!requests[2].tools.some(({ name }) => name === "read_attachment"));
  assert.ok(requests[4].tools.some(({ name }) => name === "read_attachment"));
  assert.ok(requests.every(({ tools }) => tools.every(({ name }) => name !== "get_dorm_menu")));
  assert.deepEqual(executed, ["list_assignments", "get_post", "read_attachment"]);
  assert.deepEqual(results, ["10주차 실습 과제 확인", "10주차 실습 과제 본문 확인", "첨부파일 텍스트 확인"]);
  assert.match(requests[5].input.find(({ call_id, type }) => call_id === "e" && type === "function_call_output").output, /테스트용 요구사항/);
  assert.equal(result.cost.calls, 6);
});

test("explicit assignment attachments are callable immediately, including a correction about a specific week", async () => {
  const tools = ["list_courses", "list_assignments", "get_post", "read_attachment", "list_course_files", COURSE_PDF_ORIGINALS_TOOL, "get_dorm_menu"].map(tool);
  const firstQuestion = "프입 이번 과제 첨부파일 읽고 파악해줘";
  const courseId = "fixture-course";
  const postId = "fixture-post";
  const attachmentId = "fixture-file";
  const detailArgs = { kind: "assignment", course_id: courseId, post_id: postId };
  const fileArgs = { ...detailArgs, attachment_id: attachmentId };
  for (const question of [firstQuestion, "아냐. 10주차 봐봐 첨부파일 있을 거야", "10주차 봐봐", "이 과제에 첨부된 PDF 전부 읽어줘"]) {
    const requests = [];
    const executed = [];
    const results = [];
    const history = question === firstQuestion ? [] : [{ items: [{ role: "user", content: firstQuestion }] }];
    const outputs = [
      [call("list_assignments", "index", { course_id: courseId })],
      [call("get_post", "post", detailArgs)],
      [call("read_attachment", "pdf", fileArgs)],
      [message("첨부 PDF를 읽었어요.")],
    ];
    await runChatTurn(options({ question, history, onResult: (text) => results.push(text) }), {
      listTools: async () => tools,
      callTool: async (name, args) => {
        executed.push([name, args]);
        if (name === "list_assignments") return { structuredContent: { result: [{ id: postId, course_id: courseId, title: "테스트 실습" }] } };
        if (name === "get_post") return { structuredContent: { kind: "assignment", title: "테스트 실습", content: null, attachments: [{ id: attachmentId, name: "예시.pdf" }] } };
        return { structuredContent: { name: "예시.pdf", pages: ["테스트용 본문"] } };
      },
      fetch: async (_url, init) => {
        requests.push(JSON.parse(init.body));
        return response(outputs[requests.length - 1]);
      },
    });
    assert.deepEqual(requests[0].tools.map(({ name }) => name), ["list_courses", "list_assignments", "get_post", "read_attachment", "request_tools"]);
    assert.deepEqual(executed, [["list_assignments", { course_id: courseId }], ["get_post", detailArgs], ["read_attachment", fileArgs]]);
    assert.deepEqual(results, ["테스트 실습 확인", "테스트 실습 첨부 1건 확인", "첨부파일 텍스트 확인"]);
  }
});

const openAssignment = {
  assignmentId: "1001", courseId: "course-a", courseName: "테스트 강좌", title: "테스트 실습",
  description: "소스 코드를 제출하세요. 보고서는 A4 두 장 분량이에요.",
  dueAt: "2026-11-20T23:59:00+09:00", lateDueAt: "2026-11-23T23:59:00+09:00", submitted: false,
  attachments: [{ id: "9001", name: "예시 안내.pdf" }],
};

test("both reported phrasings read the current PDF before asking the model to solve", async () => {
  const assignment = { ...openAssignment, dueAt: null, description: "FYI" };
  const locator = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId, attachment_id: "9001" };
  const executed = [];
  const problem = "테스트 문제: 배열을 선택 정렬로 정렬하세요.";
  const solution = "가장 작은 값을 골라 현재 위치와 바꾸는 작업을 반복해요.";
  const statements = ["어 그럼 어캐 풀음?", "첨부파일 확인해서 풀이 진행해줘."];
  let history = [];
  for (const question of statements) {
    const result = await runChatTurn(options({ assignment, question, history }), {
      listTools: async () => ["get_post", "read_attachment", "list_course_files"].map(tool),
      callTool: async (name, args) => {
        executed.push([name, args]);
        return { structuredContent: { name: "예시 안내.pdf", pages: [problem], next_page: null } };
      },
      fetch: async (_url, init) => {
        const body = JSON.parse(init.body);
        const evidence = body.input.find(({ content }) => typeof content === "string" && content.startsWith("현재 과제 PDF 조회 결과\n"));
        assert.ok(evidence?.content.includes(problem));
        assert.match(body.instructions, /현재 과제의 풀이/);
        assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
        return response([message(solution)]);
      },
    });
    assert.equal(result.text, solution);
    assert.equal(result.cost.calls, 1);
    assert.deepEqual(result.sources, [{ title: "예시 안내.pdf" }]);
    assert.doesNotMatch(JSON.stringify(result.history), /선택 정렬로 정렬하세요/);
    history = result.history;
  }
  assert.deepEqual(executed, [["read_attachment", locator], ["read_attachment", locator]]);
});

test("short implementation questions read the current assignment PDF before the model answers", async () => {
  const assignment = { ...openAssignment, dueAt: null, description: "첨부 자료를 확인하세요." };
  const locator = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId, attachment_id: "9001" };
  const evidence = "첫 번째로 SampleBase 클래스를 정의하세요.";
  const answer = "먼저 SampleBase 클래스를 정의해요.";
  for (const question of ["처음으로 만들어야 하는 클래스는?", "어떤 클래스부터 만들어야 해?", "구현 순서 알려줘"]) {
    const executed = [];
    const result = await runChatTurn(options({ assignment, question }), {
      listTools: async () => [tool("read_attachment")],
      callTool: async (name, args) => {
        executed.push([name, args]);
        return { structuredContent: { name: "예시 안내.pdf", pages: [evidence] } };
      },
      fetch: async (_url, init) => {
        const body = JSON.parse(init.body);
        assert.deepEqual(executed, [["read_attachment", locator]]);
        assert.ok(body.input.some(({ content }) => typeof content === "string" &&
          content.startsWith("현재 과제 PDF 조회 결과\n") && content.includes(evidence)));
        assert.equal(body.tool_choice, "auto");
        assert.equal(body.stream, true);
        return response([message(answer)]);
      },
    });
    assert.equal(result.text, answer);
    assert.deepEqual(result.sources, [{ title: "예시 안내.pdf" }]);
  }
});

test("implementation questions can select a verified PDF after checking an unknown attachment list", async () => {
  const assignment = { ...openAssignment, dueAt: null, attachments: null };
  const locator = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId };
  const attachments = [...openAssignment.attachments, { id: "9002", name: "예시 클래스 명세.pdf" }];
  const evidence = "SampleBase 클래스부터 구현하세요.";
  const executed = [];
  const toolChoices = [];
  const result = await runChatTurn(options({ assignment, question: "처음으로 만들어야 하는 클래스는?" }), {
    listTools: async () => ["get_post", "read_attachment", "list_course_files"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: name === "get_post" ? { status: "ok", attachments }
        : { name: attachments[1].name, pages: [evidence] } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
      toolChoices.push(body.tool_choice);
      if (body.tool_choice === "required") {
        assert.ok(JSON.stringify(body.input).includes(attachments[1].name));
        return response([call("read_attachment", "spec", { attachment_id: "9002" })]);
      }
      assert.ok(JSON.stringify(body.input).includes(evidence));
      return response([message(evidence)]);
    },
  });
  assert.deepEqual(toolChoices, ["required", "auto"]);
  assert.deepEqual(executed, [["get_post", locator], ["read_attachment", { ...locator, attachment_id: "9002" }]]);
  assert.equal(result.text, evidence);
});

test("a solve request checks an unknown attachment list and reports a PDF with no extractable text", async () => {
  const { assignmentId, courseId, attachments } = openAssignment;
  const executed = [];
  const progress = [];
  const result = await runChatTurn(options({
    assignment: { ...openAssignment, dueAt: null, attachments: null }, question: "어떻게 풀어?",
    onResult: (text) => progress.push(text),
  }), {
    listTools: async () => ["get_post", "read_attachment"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: name === "get_post" ? { kind: "assignment", attachments }
        : { name: "예시 안내.pdf", pages: [""], next_page: null } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.match(JSON.stringify(body.input), /현재 과제 PDF 조회 결과/);
      assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
      return response([message("첨부 PDF에서 텍스트를 추출하지 못했어요.")]);
    },
  });
  const locator = { kind: "assignment", course_id: courseId, post_id: assignmentId };
  assert.deepEqual(executed, [["get_post", locator], ["read_attachment", { ...locator, attachment_id: attachments[0].id }]]);
  assert.deepEqual(progress, ["PDF에서 추출할 수 있는 텍스트 없음"]);
  assert.ok(!result.sources.some(({ title }) => title === "예시 안내.pdf"));
});

test("an explicit attachment exclusion prevents PDF lookup for solution and implementation questions", async () => {
  for (const question of ["첨부파일은 빼고 본문만 보고 풀이 진행해줘.", "첨부파일은 빼고 처음으로 만들어야 하는 클래스 알려줘."]) {
    const result = await runChatTurn(options({ assignment: { ...openAssignment, dueAt: null }, question }), {
      listTools: async () => assert.fail("excluded attachments do not need any tools"),
      callTool: async () => assert.fail("excluded attachments cannot be read"),
      fetch: async (_url, init) => {
        const body = JSON.parse(init.body);
        assert.deepEqual(body.tools, []);
        assert.doesNotMatch(JSON.stringify(body.input), /현재 과제 PDF 조회 결과/);
        return response([message("제공된 본문 범위에서 설명할게요.")]);
      },
    });
    assert.match(result.text, /본문 범위/);
  }
});

test("submission conditions use the current assignment and never contact LMS again", async () => {
  for (const question of ["제출 조건을 정리해줘", "이 과제 전체 내용을 정리해줘", "이 과제에 시간표를 넣어야 해?",
    "제출 파일 형식 알려줘", "어떤 파일 형식이 필요해?"]) {
    const assignment = question === "제출 파일 형식 알려줘" ? { ...openAssignment, attachments: null } : openAssignment;
    const broadGuide = question === "제출 조건을 정리해줘" || question === "이 과제 전체 내용을 정리해줘";
    let requests = 0;
    const result = await runChatTurn(options({ assignment, question, now: new Date("2026-11-13T12:00:00+09:00") }), {
      listTools: async () => {
        assert.ok(broadGuide, "Narrow questions use the already loaded assignment");
        return [tool("read_attachment")];
      },
      callTool: async () => assert.fail("No e-Class query is needed"),
      fetch: async (_url, init) => {
        requests++;
        const body = JSON.parse(init.body);
        const [reference, user] = body.input;
        assert.equal(user.content, question);
        assert.match(reference.content, /^현재 과제 참고 자료\n/);
        const { url, deadline_label, ...fields } = JSON.parse(reference.content.slice(reference.content.indexOf("\n") + 1));
        assert.equal(deadline_label, "D-7");
        assert.deepEqual(fields, assignment);
        assert.match(url, /n=1001/);
        assert.ok(!body.instructions.includes(assignment.description));
        assert.deepEqual(body.tools.map(({ name }) => name), broadGuide ? ["read_attachment"] : []);
        assert.equal(body.tool_choice, broadGuide ? "auto" : "none");
        const answer = "보고서를 A4 2장으로 작성해 제출해요.";
        return response([body.text?.format ? assignmentGuide(answer, false) : message(answer)]);
      },
    });
    assert.equal(requests, 1);
    assert.equal(result.sources[0].assignment.assignmentId, assignment.assignmentId);
    assert.match(result.text, /A4 2장/);
    assert.ok(!JSON.stringify(result.history).includes(assignment.description));
  }
});

test("assignment guidance reads the current PDF and an affirmative reply requests the same solution", async () => {
  const assignment = { ...openAssignment, dueAt: null, description: "첨부를 확인하세요." };
  const question = "이 과제 어캐 제출해야함?";
  const problem = "테스트 문제: 정수 n부터 1까지 재귀로 합산하세요.";
  const guide = "소스 코드와 결과를 보고서에 넣어 e-Class에 올려요. 먼저 재귀 함수를 작성하고 예제로 확인해요.";
  const offer = "풀이도 해볼까요?";
  const solution = "기저 조건은 n = 0이에요. 그 외에는 n + sum(n - 1)을 반환해요.";
  const executed = [];
  const deps = {
    listTools: async () => ["read_attachment", "get_post", "list_assignments", "submit_assignment"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: { filename: "예시 안내.pdf", pages: [problem], next_page: null, truncated: false } };
    },
  };
  const locator = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId, attachment_id: "9001" };
  const first = await runChatTurn(options({ assignment, question }), {
    ...deps,
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.equal(body.text?.format?.type, "json_schema");
      assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
      const evidence = body.input.find(({ type }) => type === "function_call_output");
      if (!evidence) return response([call("read_attachment", "guide-pdf", { attachment_id: locator.attachment_id })]);
      assert.match(evidence.output, /재귀로 합산/);
      return response([assignmentGuide(guide, true)]);
    },
  });
  assert.deepEqual(executed, [["read_attachment", locator]]);
  assert.equal(first.text, `${guide}\n\n${offer}`);
  assert.doesNotMatch(JSON.stringify(first.history), /재귀로 합산/);

  const follow = await runChatTurn(options({ assignment, question: "응", history: first.history }), {
    ...deps,
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.equal(body.text?.format, undefined);
      assert.match(body.instructions, /현재 과제의 풀이/);
      assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
      const evidence = body.input.find(({ content }) => typeof content === "string" && content.startsWith("현재 과제 PDF 조회 결과\n"));
      assert.match(evidence?.content ?? "", /재귀로 합산/);
      return response([message(solution)]);
    },
  });
  assert.deepEqual(executed, [["read_attachment", locator], ["read_attachment", locator]]);
  assert.equal(follow.text, solution);
  assert.ok(follow.sources.some(({ title }) => title === "예시 안내.pdf"));

  const noRead = async (question, history, current = assignment) => runChatTurn(options({ assignment: current, question, history }), {
    listTools: async () => assert.fail("An answer without an active offer needs no lookup"),
    callTool: async () => assert.fail("An answer without an active offer must not read a PDF"),
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.tools, []);
      assert.equal(body.text?.format, undefined);
      assert.doesNotMatch(body.instructions, /현재 과제의 풀이/);
      assert.doesNotMatch(JSON.stringify(body.input), /재귀로 합산/);
      return response([message("알겠어요.")]);
    },
  });
  const declined = await noRead("아니 괜찮아", first.history);
  await noRead("응", declined.history);
  await noRead("응", first.history, { ...assignment, assignmentId: "1002", title: "다른 실습" });
});

test("assignment guidance with insufficient problem details does not offer a solution", async () => {
  const assignment = { ...openAssignment, description: "제출 방법: e-Class에 결과 보고서를 올려요. 실습에 필요한 데이터는 수업에서 별도 제공해요.", attachments: [] };
  const guide = "e-Class에 결과 보고서를 올려요. 수업에서 배포한 데이터가 필요해요.";
  const result = await runChatTurn(options({ assignment, question: "이 과제 어캐 제출해야함?" }), {
    listTools: async () => assert.fail("No attachment can be read"),
    callTool: async () => assert.fail("No attachment can be read"),
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.equal(body.text?.format?.type, "json_schema");
      return response([assignmentGuide(guide, false)]);
    },
  });
  assert.equal(result.text, guide);
});

test("an assignment window still searches when the user explicitly asks for another assignment or a list", async () => {
  for (const question of ["다른 과제 찾아줘", "이번 주 과제 마감 알려줘", "전체 목록 보여줘", "브레인 라이팅 과제 찾아줘"]) {
    const executed = [];
    let requests = 0;
    await runChatTurn(options({ assignment: openAssignment, question }), {
      listTools: async () => [tool("list_assignments")],
      callTool: async (name) => {
        executed.push(name);
        return { structuredContent: { result: [{ id: "2001", course_id: "course-b", title: "다른 실습" }] } };
      },
      fetch: async (_url, init) => {
        const body = JSON.parse(init.body);
        assert.ok(!JSON.stringify(body.input).includes(openAssignment.description));
        if (++requests > 1) return response([message("다른 실습 과제가 있어요.")]);
        assert.deepEqual(body.tools.map(({ name }) => name), ["list_assignments"]);
        return response([call("list_assignments")]);
      },
    });
    assert.deepEqual(executed, ["list_assignments"]);
  }
});

test("a current assignment attachment uses its verified ID without looking up the post or course", async () => {
  const executed = [];
  let requests = 0;
  await runChatTurn(options({ assignment: openAssignment, question: "첨부 PDF 전부 읽어줘" }), {
    listTools: async () => ["list_courses", "list_assignments", "get_post", "read_attachment", COURSE_PDF_ORIGINALS_TOOL].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: { filename: "예시 안내.pdf", pages: ["내용"] } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.tools.map(({ name }) => name), ["read_attachment"]);
      if (++requests === 1) return response([call("read_attachment", "wrong-file", { attachment_id: "9002" })]);
      if (requests === 2) {
        const error = body.input.find(({ call_id, type }) => call_id === "wrong-file" && type === "function_call_output");
        assert.equal(JSON.parse(error.output).status, "error");
        return response([call("read_attachment", "correct-file", { kind: "assignment", attachment_id: "9001" })]);
      }
      return response([message("현재 과제의 PDF 안내를 확인했어요.")]);
    },
  });
  assert.deepEqual(executed, [["read_attachment", {
    kind: "assignment", course_id: "course-a", post_id: "1001", attachment_id: "9001",
  }]]);
});

test("a missing attachment list can query only the current post", async () => {
  const assignment = { ...openAssignment, attachments: null };
  const executed = [];
  let requests = 0;
  await runChatTurn(options({ assignment, question: "첨부 목록 알려줘" }), {
    listTools: async () => ["get_post", "list_posts", "list_assignments", "read_attachment"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      return { structuredContent: { kind: "assignment", title: assignment.title, attachments: openAssignment.attachments } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.tools.map(({ name }) => name), ["get_post"]);
      if (++requests === 1) return response([call("get_post", "wrong-post", { kind: "assignment", post_id: "2001" })]);
      if (requests === 2) return response([call("get_post", "current-post", { kind: "assignment", post_id: "1001" })]);
      return response([message("현재 과제에 예시 안내.pdf가 첨부되어 있어요.")]);
    },
  });
  assert.deepEqual(executed, [["get_post", { kind: "assignment", course_id: "course-a", post_id: "1001" }]]);
});

test("an assignment window reads course PDFs from the listed source even if the model supplies the current post", async () => {
  const assignment = {
    assignmentId: "1001", courseId: "course-a", courseName: "테스트 강좌", title: "테스트 과제",
    dueAt: null, description: null, attachments: [],
  };
  const files = [1, 2, 3].map((week) => ({ id: `pdf-${week}`, name: `테스트 ${week}주차.pdf` }));
  const executed = [];
  const deps = {
    listTools: async () => ["list_courses", "list_assignments", "list_course_files", "read_attachment"].map(tool),
    callTool: async (name, args) => {
      executed.push([name, args]);
      if (name === "list_course_files") return { structuredContent: { result: files } };
      // Recreate the LMS rejecting a collection ID supplied as an assignment attachment.
      if (args.kind === "assignment") return { isError: true, content: [{ type: "text", text: "첨부 ID 불일치" }] };
      return { structuredContent: { name: files.find(({ id }) => id === args.attachment_id).name, pages: ["확인할 내용"] } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      const outputs = body.input.filter(({ type }) => type === "function_call_output");
      if (!outputs.some(({ call_id }) => call_id === "course-files")) {
        assert.ok(body.tools.some(({ name }) => name === "list_course_files"));
        assert.ok(body.tools.some(({ name }) => name === "read_attachment"));
        return response([call("list_course_files", "course-files", { course_id: assignment.courseId })]);
      }
      const reads = outputs.filter(({ call_id }) => call_id.startsWith("pdf-"));
      if (reads.length < files.length) return response([call("read_attachment", `pdf-${reads.length}`, {
        kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId,
        attachment_id: files[reads.length].id,
      })]);
      assert.ok(reads.every(({ output }) => JSON.parse(output).pages?.length === 1));
      return response([message("파일모음의 테스트 PDF 3개를 확인했어요.")]);
    },
  };

  const result = await runChatTurn(options({ assignment, question: "이 과목 내 모든 PDF 읽어줘" }), deps);
  assert.match(result.text, /3개/);
  assert.deepEqual(executed.slice(1), files.map(({ id }) => ["read_attachment", {
    kind: "file_collection", course_id: assignment.courseId, attachment_id: id,
  }]));

  let requests = 0;
  await runChatTurn(options({ assignment, question: "그 PDF 다음 페이지도 읽어줘", history: result.history }), {
    ...deps,
    fetch: async () => response(++requests === 1 ? [call("read_attachment", "continued", {
      kind: "file_collection", attachment_id: files[0].id, start_page: 11,
    })] : [message("다음 페이지를 확인했어요.")]),
  });
  assert.deepEqual(executed.at(-1), ["read_attachment", {
    kind: "file_collection", course_id: assignment.courseId, attachment_id: files[0].id, start_page: 11,
  }]);
});

test("a confirmed post attachment keeps its source and an explicit mismatched course is not substituted", async () => {
  const assignment = {
    assignmentId: "1001", courseId: "course-a", courseName: "테스트 강좌", title: "테스트 과제",
    dueAt: null, description: null, attachments: [{ id: "shared-file", name: "테스트.pdf" }],
  };
  const postRead = { kind: "assignment", course_id: assignment.courseId, post_id: assignment.assignmentId, attachment_id: "shared-file" };
  const wrongCourse = { kind: "file_collection", course_id: "course-b", attachment_id: "shared-file" };
  const failure = { status: "error", code: "attachment_not_found", message: "이 강좌에서 첨부 ID를 확인하지 못했어요." };
  const results = [];
  const executed = [];
  const outputs = [
    [call("list_course_files", "list", { course_id: assignment.courseId })],
    [call("read_attachment", "post", postRead)],
    [call("read_attachment", "mismatch", wrongCourse)],
    [message("과제 첨부를 읽었고 다른 강좌에서는 찾지 못했어요.")],
  ];
  let round = 0;
  await runChatTurn(options({ assignment, question: "과제 첨부와 파일모음 PDF 확인해줘", onResult: (text) => results.push(text) }), {
    listTools: async () => ["list_course_files", "read_attachment"].map(tool),
    callTool: async (name, args) => {
      if (name === "list_course_files") return { structuredContent: { result: assignment.attachments } };
      executed.push(args);
      return { structuredContent: args.course_id === wrongCourse.course_id ? failure : { name: "테스트.pdf", pages: ["내용"] } };
    },
    fetch: async (_url, init) => {
      if (round === 3) {
        const output = JSON.parse(init.body).input.find(({ type, call_id }) => type === "function_call_output" && call_id === "mismatch");
        assert.deepEqual(JSON.parse(output.output), failure);
      }
      return response(outputs[round++]);
    },
  });
  assert.deepEqual(executed, [postRead, wrongCourse]);
  assert.ok(results.includes(`PDF 읽기 실패 · ${failure.message}`));
});

function originalPdf(index) {
  const bytes = Buffer.from(`%PDF-1.4\n테스트 원본 ${index}\n${"가".repeat(1600)}\n%%EOF\n`);
  return { id: `pdf-${index}`, name: `테스트 자료 ${index}.pdf`, status: "ok",
    size_bytes: bytes.length, base64: bytes.toString("base64") };
}

test("all 11 originals go in one low-detail request and only the answer stays in chat history", async () => {
  const assignment = { assignmentId: "1001", courseId: "course-a", courseName: "테스트 강좌", title: "테스트 과제",
    dueAt: null, description: "과제에만 필요한 안내", attachments: [] };
  const files = Array.from({ length: 11 }, (_, index) => originalPdf(index + 1));
  const calls = [];
  const paid = [];
  const result = await runChatTurn(options({ model: "gpt-6-luna", assignment, question: "이 과목 PDF 전부 읽어줘" }), {
    listTools: async () => [tool(COURSE_PDF_ORIGINALS_TOOL)],
    callTool: async (name, args) => {
      calls.push([name, args]);
      return { structuredContent: { status: "ok", course_id: "course-a", total_files: 11, files } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      paid.push(body);
      assert.equal(body.tools, undefined);
      assert.equal(body.store, false);
      assert.equal(body.truncation, "disabled");
      const content = body.input[0].content;
      assert.deepEqual(content.filter((item) => item.type === "input_file"), files.map((file, index) => ({
        type: "input_file", filename: `F${String(index + 1).padStart(2, "0")}.pdf`,
        file_data: `data:application/pdf;base64,${file.base64}`, detail: "low",
      })));
      const question = content.find((item) => item.type === "input_text").text;
      assert.match(question, /이 과목 PDF 전부 읽어줘/);
      assert.doesNotMatch(question, /과제에만 필요한 안내/);
      return Response.json({ status: "completed", model: "gpt-6-luna", service_tier: "default",
        usage: { input_tokens: 1000, input_tokens_details: { cached_tokens: 0 }, output_tokens: 200 },
        output: [message("수업 자료의 핵심이에요.")] });
    },
  });
  assert.deepEqual(calls, [[COURSE_PDF_ORIGINALS_TOOL, { course_id: "course-a" }]]);
  assert.equal(paid.length, 1);
  assert.equal(result.cost.calls, 1);
  assert.equal(result.cost.usd, 0.0002);
  assert.match(result.text, /PDF 11개 중 11개 원본 전송/);
  assert.doesNotMatch(result.text, /F11 테스트 자료 11.pdf/);
  assert.deepEqual(result.sources, files.map(({ name }) => ({ title: name })));
  assert.doesNotMatch(JSON.stringify(result.history), /file_data|base64|수업 자료의 핵심/);
});

test("a different course is resolved before bulk reading and file failures stay in the answer", async () => {
  const assignment = { assignmentId: "1001", courseId: "course-a", courseName: "원래 강좌", title: "테스트 과제",
    dueAt: null, description: null, attachments: [] };
  const files = [originalPdf(1), { id: "failed", name: "실패.pdf", status: "error", message: "파일을 내려받지 못했어요." }];
  const calls = [];
  let paid = 0;
  const result = await runChatTurn(options({ assignment, question: "다른강좌 PDF를 모두 읽어줘" }), {
    listTools: async () => ["list_courses", COURSE_PDF_ORIGINALS_TOOL, "read_attachment"].map(tool),
    callTool: async (name, args) => {
      calls.push([name, args]);
      return { structuredContent: name === "list_courses" ? { result: [{ id: "course-b", name: "다른강좌" }] }
        : { status: "ok", course_id: "course-b", total_files: 2, files } };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      switch (++paid) {
        case 1:
          assert.deepEqual(body.tools.map(({ name }) => name), ["list_courses", COURSE_PDF_ORIGINALS_TOOL]);
          return response([call("list_courses", "courses")]);
        case 2: return response([call(COURSE_PDF_ORIGINALS_TOOL, "batch", { course_id: "course-b" })]);
        default:
          assert.equal(body.input[0].content.filter((item) => item.type === "input_file").length, 1);
          return response([message("읽을 수 있는 파일을 정리했어요.")]);
      }
    },
  });
  assert.deepEqual(calls, [["list_courses", {}], [COURSE_PDF_ORIGINALS_TOOL, { course_id: "course-b" }]]);
  assert.equal(paid, 3);
  assert.match(result.text, /실패 1개/);
  assert.match(result.text, /실패.pdf · 파일을 내려받지 못했어요/);
});

test("a bundle over the one-request limit stops before a paid request", async () => {
  const assignment = { assignmentId: "1001", courseId: "course-a", courseName: "테스트 강좌", title: "테스트 과제",
    dueAt: null, description: null, attachments: [] };
  const result = await runChatTurn(options({ assignment, question: "이 과목 PDF 전부 읽어줘" }), {
    listTools: async () => [tool(COURSE_PDF_ORIGINALS_TOOL)],
    callTool: async () => ({ structuredContent: { status: "error", code: "pdf_batch_too_large",
      message: "PDF 원본이 한 요청의 50 MB 한도를 넘어요." } }),
    fetch: async () => assert.fail("An oversized bundle must not be sent to the API"),
  });
  assert.match(result.text, /50 MB 한도/);
  assert.equal(result.cost.calls, 0);
});

test("unscoped questions expose discovery and cannot use a schema before it is sent", async () => {
  let round = 0;
  const results = [];
  const executed = [];
  const result = await runChatTurn(options({ question: "최근 소식 좀 찾아줘", onResult: (text) => results.push(text) }), {
    listTools: async () => ["list_notices", "list_campus_notices", "submit_assignment"].map(tool),
    callTool: async (name) => {
      executed.push(name);
      return { content: [{ type: "text", text: JSON.stringify({ status: "login_required" }) }] };
    },
    fetch: async (_url, init) => {
      const body = JSON.parse(init.body);
      round++;
      if (round === 1) {
        assert.deepEqual(body.tools.map(({ name }) => name), ["request_tools"]);
        return response([
          call("request_tools", "invalid", { names: ["list_notices", "submit_assignment"] }),
          call("request_tools", "valid", { names: ["list_notices"] }),
          call("list_notices", "early"),
        ]);
      }
      if (round === 2) {
        const getOutput = (id) => JSON.parse(body.input.find(({ call_id, type }) => call_id === id && type === "function_call_output").output);
        assert.equal(getOutput("invalid").status, "error");
        assert.deepEqual(getOutput("valid").enabled_tools, ["list_notices"]);
        assert.equal(getOutput("early").status, "error");
        return response([call("list_notices", "after-discovery")]);
      }
      return response([message("로그인이 필요해요.")]);
    },
  });
  assert.deepEqual(executed, ["list_notices"]);
  assert.deepEqual(results, []);
  assert.match(result.text, /로그인/);
});
