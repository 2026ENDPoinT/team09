import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createAssignmentAnalysis } from "../dist-desktop/desktop/assignment-analysis.js";
import { CURRENT_ASSIGNMENT_GUIDE_FORMAT } from "../dist-desktop/shared/assignment-browser.js";

const assignment = {
  courseId: "course-a", assignmentId: "100", courseName: "예시 과목", title: "과제 제목", description: "교수자 자료",
  dueAt: "2026-11-14T23:59:00+09:00", submissionFormat: "글 입력 / 파일첨부",
  attachments: [{ id: "7", name: "과제 안내.pdf" }],
};
const syntheticPdf = Buffer.from("%PDF-1.4\n");

function ok(text) {
  return Response.json({ status: "completed", output: [{ type: "message", content: [{ type: "output_text",
    text: JSON.stringify({ markdown: text, documents: [{
      inputFile: "assignment-1.pdf", overview: "상속 실습", coverage: "complete",
      sections: [{ from: 1, to: 1, text: "부모 클래스를 선언해요.", visuals: "그림에 두 자식 클래스의 화살표가 보여요." }],
    }] }),
  }] }] });
}

async function fixture(t) {
  const temp = await mkdtemp(join(tmpdir(), "ast-assignment-analysis-"));
  t.after(() => rm(temp, { recursive: true, force: true }));
  const directories = [join(temp, "account-a"), join(temp, "account-b")];
  let account = 0;
  const requests = [];
  const downloads = [];
  const options = {
    apiKey: "fixture-key", activeDirectory: () => directories[account], activeRevision: () => account + 1,
    readModel: async () => "fixture-model",
    connector: { async requestTool(name, target) {
      assert.equal(name, "get_assignment_attachment_file");
      downloads.push(target);
      return { status: "ok", ...target, base64: syntheticPdf.toString("base64"), size_bytes: syntheticPdf.byteLength };
    } },
    async fetch(url, init) {
      assert.equal(url, "https://api.openai.com/v1/responses");
      requests.push(JSON.parse(init.body));
      return ok(`## 계정 ${account + 1} 해설`);
    },
  };
  return { directories, requests, downloads, options, switchAccount: () => { account = 1; } };
}

test("concurrent views share one request and a reopened account reuses the private saved explanation", async (t) => {
  const { options, directories, requests, downloads, switchAccount } = await fixture(t);
  const reader = createAssignmentAnalysis(options);
  const first = reader.analyze(assignment);
  assert.equal(first, reader.analyze(assignment));
  assert.equal((await first).markdown, "## 계정 1 해설");
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0].for_analysis, true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].store, false);
  assert.equal(requests[0].text.format.name, "assignment_pdf_notes");
  assert.match(requests[0].instructions, /과제 목표.*풀이에 필요한 배경지식.*핵심 개념.*스스로 풀어보기.*내 풀이 점검.*제출 전 확인/s);
  assert.match(requests[0].instructions, /최종 정답, 제출 가능한 완성 코드·보고서.*제공하지 마세요/);
  const [instructor, file] = requests[0].input[0].content;
  assert.equal(JSON.parse(instructor.text).submissionFormat, assignment.submissionFormat);
  assert.equal(file.file_data, `data:application/pdf;base64,${syntheticPdf.toString("base64")}`);
  assert.equal((await readdir(join(directories[0], "assignment-analysis"))).length, 1);

  const reopened = createAssignmentAnalysis({ ...options, apiKey: "" });
  const saved = await reopened.analyze({ ...assignment, submitted: true }, false, true);
  assert.equal(saved.markdown, "## 계정 1 해설");
  assert.equal(saved.pdfNotes.documents[0].sections[0].visuals, "그림에 두 자식 클래스의 화살표가 보여요.");
  assert.equal(saved.pdfNotes.documents[0].id, assignment.attachments[0].id);
  assert.equal(downloads.length, 1);
  assert.equal(requests.length, 1);

  switchAccount();
  reader.sessionChanged();
  assert.equal((await reader.analyze(assignment)).markdown, "## 계정 2 해설");
  assert.equal(downloads.length, 2);
  assert.equal(requests.length, 2);
});

test("a question upgrades a study guide without PDF notes once and an attachment change invalidates the cache", async (t) => {
  const { options, directories, requests, downloads } = await fixture(t);
  const directory = join(directories[0], "assignment-analysis");
  const id = createHash("sha256").update(JSON.stringify([assignment.courseId, assignment.assignmentId])).digest("hex");
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, id + ".json"), JSON.stringify({ status: "ready", format: "study-guide", markdown: "## 기존 가이드" }));
  const reader = createAssignmentAnalysis(options);
  const background = reader.analyze(assignment);
  const question = reader.analyze(assignment, false, true);
  assert.equal((await background).markdown, "## 기존 가이드");
  assert.ok((await question).pdfNotes);
  assert.ok((await reader.analyze(assignment, false, true)).pdfNotes);
  assert.equal(requests.length, 1);
  assert.equal(await reader.openPdf(assignment, "another-assignment-file", new AbortController().signal), undefined);
  assert.equal(downloads.length, 1);
  const replaced = { ...assignment, attachments: [{ id: "8", name: "수정본.pdf" }] };
  assert.equal((await reader.analyze(replaced, false, true)).pdfNotes.documents[0].id, "8");
  assert.deepEqual(downloads.map(({ attachment_id }) => attachment_id), ["7", "8"]);
});

test("a saved explanation upgrades only on request and is replaced only after a successful study guide", async (t) => {
  const { options, directories, requests, downloads } = await fixture(t);
  const directory = join(directories[0], "assignment-analysis");
  const id = createHash("sha256").update(JSON.stringify([assignment.courseId, assignment.assignmentId])).digest("hex");
  const path = join(directory, id + ".json");
  const legacy = { status: "ready", markdown: "## 기존 제출 안내" };
  await mkdir(directory, { recursive: true });
  await writeFile(path, JSON.stringify(legacy));
  const reader = createAssignmentAnalysis(options);
  assert.equal((await reader.analyze(assignment)).markdown, legacy.markdown);
  assert.equal(downloads.length, 0);

  const unavailable = createAssignmentAnalysis({ ...options, apiKey: "" });
  assert.equal((await unavailable.analyze(assignment, true)).status, "unavailable");
  assert.deepEqual(JSON.parse(await readFile(path, "utf8")), legacy);

  const instructor = { courseName: assignment.courseName, title: assignment.title, dueAt: assignment.dueAt,
    submissionFormat: assignment.submissionFormat, description: assignment.description, attachments: [["7", "과제 안내.pdf"]] };
  const fingerprint = createHash("sha256").update(JSON.stringify(instructor)).digest("hex");
  await writeFile(path, JSON.stringify({ ...legacy, format: "study-guide", fingerprint }));

  // A concurrent normal lookup may still be reading the old cache when the user clicks upgrade.
  const cached = reader.analyze(assignment);
  const upgrade = reader.analyze(assignment, true);
  assert.equal((await cached).format, "study-guide");
  assert.equal((await upgrade).format, CURRENT_ASSIGNMENT_GUIDE_FORMAT);
  assert.equal(downloads.length, 1);
  assert.equal(requests.length, 1);
  assert.equal((await unavailable.analyze(assignment)).format, CURRENT_ASSIGNMENT_GUIDE_FORMAT);
});

test("an account switch cancels in-flight analysis and a late provider result cannot enter either account cache", async (t) => {
  const { options, directories, switchAccount } = await fixture(t);
  const started = Promise.withResolvers();
  const reply = Promise.withResolvers();
  const reader = createAssignmentAnalysis({ ...options, fetch: async (_url, init) => {
    started.resolve(init.signal);
    return reply.promise;
  } });
  const pending = reader.analyze(assignment);
  const signal = await started.promise;
  switchAccount();
  reader.sessionChanged();
  assert.equal(signal.aborted, true);
  reply.resolve(ok("## 이 결과는 취소됨"));
  assert.deepEqual(await pending, { status: "cancelled" });
  for (const directory of directories) {
    await assert.rejects(readdir(join(directory, "assignment-analysis")), { code: "ENOENT" });
  }
});

test("an incomplete response does not become a saved explanation and can be retried", async (t) => {
  const { options, directories } = await fixture(t);
  const started = Promise.withResolvers();
  const encoder = new TextEncoder();
  let attempts = 0;
  const reader = createAssignmentAnalysis({ ...options, fetch: async () => {
    attempts++;
    if (attempts > 1) return ok("## 다시 받아온 해설");
    return new Response(new ReadableStream({
      start(controller) { started.resolve(controller); },
    }), { headers: { "Content-Type": "text/event-stream" } });
  } });
  const first = Promise.withResolvers();
  const result = reader.analyze(assignment, false, false, first.resolve);
  const stream = await started.promise;
  const push = (event) => stream.enqueue(encoder.encode("data: " + JSON.stringify(event) + "\n\n"));
  push({ type: "response.output_text.delta", delta: '{"markdown":"## 풀이 힌트\\n\\' });
  assert.equal(await first.promise, "## 풀이 힌트\n");

  const updates = [];
  assert.equal(reader.analyze(assignment, false, false, (text) => updates.push(text)), result);
  assert.deepEqual(updates, ["## 풀이 힌트\n"]);
  const body = '{"markdown":"## 풀이 힌트\\n\\n예제 \\uAC00를 확인해요.","documents":[{"overview":"비공개 근거"}]}';
  push({ type: "response.output_text.delta", delta: body.slice('{"markdown":"## 풀이 힌트\\n\\'.length) });
  await new Promise((resolve) => setTimeout(resolve, 90));
  assert.equal(updates.at(-1), "## 풀이 힌트\n\n예제 가를 확인해요.");
  push({ type: "response.incomplete", response: { status: "incomplete", output: [] } });
  stream.close();
  assert.equal((await result).status, "error");
  await assert.rejects(readdir(join(directories[0], "assignment-analysis")), { code: "ENOENT" });
  assert.equal((await reader.analyze(assignment)).markdown, "## 다시 받아온 해설");
  assert.equal((await reader.analyze(assignment)).markdown, "## 다시 받아온 해설");
  assert.equal(attempts, 2);
});

test("encrypted PDFs produce a specific message and never reach the AI request", async (t) => {
  const { options, requests } = await fixture(t);
  const connector = {
    requestTool: (name, args) => args.attachment_id === "7"
      ? { status: "error", code: "pdf_encrypted", message: "Encrypted PDF" }
      : options.connector.requestTool(name, args),
  };
  const reader = createAssignmentAnalysis({ ...options, connector });
  assert.deepEqual(await reader.analyze(assignment), { status: "error", message: "암호화된 PDF라 열 수 없어요." });
  assert.equal(await reader.openPdf(assignment, "7", new AbortController().signal), undefined);
  assert.equal(requests.length, 0);

  const mixed = { ...assignment, attachments: [...assignment.attachments, { id: "8", name: "일반.pdf" }] };
  const result = await reader.analyze(mixed);
  assert.equal(result.status, "ready");
  assert.deepEqual(result.encryptedFiles, ["과제 안내.pdf"]);
  assert.deepEqual(result.pdfNotes.documents.map(({ id }) => id), ["8"]);
  assert.deepEqual(requests[0].input[0].content.filter(({ type }) => type === "input_file").map(({ filename }) => filename),
    ["assignment-1.pdf"]);
  assert.deepEqual((await createAssignmentAnalysis({ ...options, connector }).analyze(mixed)).encryptedFiles, result.encryptedFiles);
  assert.equal(requests.length, 1);
});
