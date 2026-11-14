import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { FocusLibraryStore } from "../dist-desktop/desktop/focus-library.js";
import { focusFolderPath } from "../dist-desktop/shared/focus-library.js";

const current = () => true;

async function fixture(t) {
  const temp = await mkdtemp(join(tmpdir(), "ast-focus-library-"));
  t.after(() => rm(temp, { recursive: true, force: true }));
  const root = join(temp, "account-a");
  const source = join(temp, "강의자료.pdf");
  const contents = "%PDF-1.4\n% test fixture\n%%EOF\n";
  await writeFile(source, contents);
  return { temp, root, source, contents, store: new FocusLibraryStore(root) };
}

test("PDFs survive renaming and moving their folders, and reopen under the same account", async t => {
  const { temp, root, source, contents, store } = await fixture(t);
  const { items: [semester] } = await store.edit({ kind: "create", parentId: null, name: "2학기" }, current);
  const imported = await store.importPdf(source, semester.id, current);
  await store.edit({ kind: "create", parentId: imported.folderId, name: "복습 자료" }, current);
  await store.edit({ kind: "rename", id: imported.folderId, name: "경제학" }, current);
  await store.edit({ kind: "move", id: imported.folderId, parentId: null }, current);
  const reopened = new FocusLibraryStore(root);
  const { items } = await reopened.read();
  assert.deepEqual(focusFolderPath(items, items.find(item => item.name === "복습 자료").id).map(item => item.name), ["경제학", "복습 자료"]);
  assert.equal(await readFile(await reopened.pdfPath(imported.pdfId), "utf8"), contents);
  assert.equal((await reopened.importPdf(source, semester.id, current)).folderId, imported.folderId);
  assert.equal((await readdir(join(root, "documents"))).length, 1);
  await assert.rejects(new FocusLibraryStore(join(temp, "account-b")).pdfPath(imported.pdfId), /PDF를 찾을 수 없어요/);
});

test("invalid imports and folder cycles leave previously saved files intact", async t => {
  const { root, source, store } = await fixture(t);
  const { items: [parent] } = await store.edit({ kind: "create", parentId: null, name: "수업" }, current);
  const { folderId } = await store.importPdf(source, parent.id, current);
  const original = await store.read();
  await assert.rejects(store.edit({ kind: "move", id: parent.id, parentId: folderId }, current), /하위 폴더로는 이동할 수 없어요/);
  await assert.rejects(store.edit({ kind: "create", parentId: null, name: "수업" }, current), /이미 있어요/);
  await writeFile(source, "not a PDF");
  await assert.rejects(store.importPdf(source, null, current), /올바른 PDF/);
  await assert.rejects(store.edit({ kind: "create", parentId: null, name: "미저장" }, () => false), /로그인 상태/);
  assert.deepEqual(await store.read(), original);
  assert.deepEqual(await readdir(join(root, "documents")), [folderId]);
});

test("bulk moves save all selected folders together, including on name conflicts", async t => {
  const { store } = await fixture(t);
  const { items: [destination] } = await store.edit({ kind: "create", parentId: null, name: "수업" }, current);
  const { items: [, first] } = await store.edit({ kind: "create", parentId: null, name: "강의" }, current);
  const { items: [, , second] } = await store.edit({ kind: "create", parentId: null, name: "복습" }, current);
  const before = await store.edit({ kind: "create", parentId: destination.id, name: second.name }, current);
  const move = { kind: "move-folders", ids: [first.id, second.id], parentId: destination.id };
  await assert.rejects(store.edit(move, current), /이미 있어요/);
  assert.deepEqual(await store.read(), before);
  await store.edit({ kind: "rename", id: second.id, name: "시험 대비" }, current);
  const { items } = await store.edit(move, current);
  for (const id of move.ids) assert.equal(items.find(item => item.id === id).parentId, destination.id);
});

test("opening a PDF records recent access without changing modification dates", async t => {
  const { root, source, store } = await fixture(t);
  const { items: [course] } = await store.edit({ kind: "create", parentId: null, name: "수업" }, current);
  const { library, folderId, pdfId } = await store.importPdf(source, course.id, current);
  assert.ok(library.items.every(item => item.lastOpenedAt === undefined));
  await store.edit({ kind: "visit-folder", id: folderId }, current);
  await store.recordPdfOpen(pdfId, current);
  const { items } = await new FocusLibraryStore(root).read();
  const openedAt = items.find(item => item.id === pdfId).lastOpenedAt;
  assert.ok(Number.isFinite(openedAt));
  assert.deepEqual(items, library.items.map(item => ({ ...item, lastOpenedAt: openedAt })));
});
