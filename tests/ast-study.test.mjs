import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { AstStudy } from "../dist-desktop/desktop/ast-study.js";

const fakeStudy = `
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const [mode, directory] = process.argv.slice(2);
if (mode !== '--ast-bridge') process.exit(2);
const log = join(directory, 'events.jsonl');
const record = entry => appendFileSync(log, JSON.stringify(entry) + '\\n');
const send = event => console.log(JSON.stringify(event));
record({ type: 'start' });
send({ type: 'ready' });
for await (const line of createInterface({ input: process.stdin })) {
  const { id, command, path, name } = JSON.parse(line);
  record({ type: command, path, name });
  if (command === 'shutdown') {
    send({ type: 'closed', id });
    break;
  }
  if (name === 'bad.pdf') send({ type: 'error', id, code: 'pdf-open-failed' });
  else if (name !== 'pending.pdf') {
    record({ type: 'opened', name });
    send({ type: 'opened', id });
  }
}
`;

function shellArgument(value) { return "'" + value.replaceAll("'", "'\\''") + "'"; }

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "ast-study-test-"));
  const fake = join(root, "fake-study.mjs");
  const launcher = join(root, "run-study");
  await writeFile(fake, fakeStudy);
  await writeFile(launcher, `#!/bin/sh\nexec ${shellArgument(process.execPath)} ${shellArgument(fake)} "$@"\n`, { mode: 0o700 });
  const study = new AstStudy({ launcher });
  t.after(async () => {
    await study.close();
    await rm(root, { recursive: true, force: true });
  });
  const events = async directory => (await readFile(join(directory, "study", "events.jsonl"), "utf8"))
    .trim().split("\n").map(line => JSON.parse(line));
  return { root, study, events };
}

test("one AST login reuses its Swing process and returns the document's open result", async t => {
  const { root, study, events } = await fixture(t);
  const account = join(root, "account-a");
  const pdf = { path: join(root, "원본 자료", "source.pdf"), name: "3주차 강의.pdf" };
  await study.open(account, 1, pdf, () => true);
  await study.open(account, 1, pdf, () => true);
  await assert.rejects(study.open(account, 1, { ...pdf, name: "bad.pdf" }, () => true), /파일이 손상되었거나 암호로/);
  await study.close();
  const log = await events(account);
  assert.deepEqual(log.map(entry => entry.type), ["start", "open", "opened", "open", "opened", "open", "shutdown"]);
  assert.deepEqual(log[1], { type: "open", ...pdf });
});

test("changing AST accounts closes the previous Swing process and rejects its pending open", async t => {
  const { root, study, events } = await fixture(t);
  const first = join(root, "account-a");
  const second = join(root, "account-b");
  const pdf = { path: join(root, "source.pdf"), name: "강의.pdf" };
  let account = first;
  await study.open(first, 1, pdf, () => account === first);
  const pending = study.open(first, 1, { ...pdf, name: "pending.pdf" }, () => account === first);
  const rejected = assert.rejects(pending, /로그인 상태가 바뀌었어요/);
  for (let tries = 0; !(await events(first)).some(entry => entry.name === "pending.pdf"); tries++) {
    assert.ok(tries < 100, "the first account's open was never submitted");
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  account = second;
  study.sessionChanged(second, 2);
  await rejected;
  await study.open(second, 2, pdf, () => account === second);
  assert.equal((await events(first)).at(-1).type, "shutdown");
  assert.deepEqual((await events(second)).map(entry => entry.type), ["start", "open", "opened"]);
});
