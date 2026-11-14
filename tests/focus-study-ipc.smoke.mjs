// Run after building AST and AST_Study: electron tests/focus-study-ipc.smoke.mjs --headless
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow } from "electron";
import { AstStudy } from "../dist-desktop/desktop/ast-study.js";
import { registerFocusLibrary } from "../dist-desktop/desktop/focus-library-ipc.js";
import { FocusLibraryStore } from "../dist-desktop/desktop/focus-library.js";
import { registerStudyFontSettings } from "../dist-desktop/desktop/study-font-settings.js";

const profile = mkdtempSync(join(tmpdir(), "ast-focus-study-ipc-"));
app.setPath("userData", profile);
app.disableHardwareAcceleration();
process.env.JDK_JAVA_OPTIONS = "-Dast.study.bridge.invisible=true";
const launcher = fileURLToPath(new URL("../AST_Study/run-study", import.meta.url));
const preload = fileURLToPath(new URL("../dist-desktop/desktop/preload.cjs", import.meta.url));

function pdfBytes(text = "AST Study fixture") {
  const content = `BT /F1 16 Tf 60 700 Td (${text}) Tj ET\n`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}endstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let bytes = "%PDF-1.4\n";
  const offsets = [];
  for (const [i, value] of objects.entries()) {
    offsets.push(bytes.length);
    bytes += `${i + 1} 0 obj\n${value}\nendobj\n`;
  }
  const table = bytes.length;
  bytes += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets) bytes += `${String(offset).padStart(10, "0")} 00000 n \n`;
  return bytes + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${table}\n%%EOF\n`;
}

async function waitForIndex(folder) {
  for (let attempt = 0; attempt < 200; attempt++) {
    try { return JSON.parse(await readFile(join(folder, "document.json"), "utf8")); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    await delay(50);
  }
  assert.fail("Swing did not prepare the imported PDF");
}

async function waitForPlanningRequest(folder) {
  const requests = join(folder, "requests");
  for (let attempt = 0; attempt < 200; attempt++) {
    try {
      const files = await readdir(requests);
      const request = files.find(name => /^[\da-f-]{36}\.json$/.test(name));
      if (request) return JSON.parse(await readFile(join(requests, request), "utf8"));
    } catch (error) {
      if (error.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error;
    }
    await delay(50);
  }
  assert.fail("Swing did not start automatic study planning");
}

async function main() {
  let window;
  const study = new AstStudy({ launcher });
  const accounts = [join(profile, "account-a"), join(profile, "account-b")];
  let account = accounts[0];
  let revision = 1;
  const source = join(profile, "강의 자료.pdf");
  const otherSource = join(profile, "두 번째 자료.pdf");
  const broken = join(profile, "손상.pdf");
  let exitCode = 0;
  try {
    await app.whenReady();
    app.dock?.hide();
    // Apply the empty credential path after Java has configured the Python worker environment.
    delete process.env.OPENAI_API_KEY;
    await writeFile(join(profile, "sitecustomize.py"), `import os
os.environ.pop("OPENAI_API_KEY", None)
os.environ["SYNESIS_CREDENTIALS_FILE"] = os.path.join(os.path.dirname(__file__), "unused.env")
`);
    process.env.PYTHONPATH = profile;
    await writeFile(source, pdfBytes());
    await writeFile(otherSource, pdfBytes("Second fixture"));
    await writeFile(broken, "%PDF-1.4\n%%EOF\n");
    for (const directory of accounts) await mkdir(directory);
    const stores = accounts.map(directory => new FocusLibraryStore(join(directory, "focus-library")));
    const [first, second] = await Promise.all(stores.map(store => store.importPdf(source, null, () => true)));
    const other = await stores[0].importPdf(otherSource, null, () => true);
    await stores[0].edit({ kind: "rename", id: first.pdfId, name: "연결 확인 강의.pdf" }, () => true);
    const damaged = await stores[0].importPdf(broken, null, () => true);
    window = new BrowserWindow({ show: false, webPreferences: { preload, sandbox: true, contextIsolation: true, nodeIntegration: false } });
    const verifySender = event => assert.equal(event.senderFrame, window.webContents.mainFrame);
    registerFocusLibrary(verifySender, () => account, () => revision, study);
    registerStudyFontSettings(verifySender, () => account, () => revision);
    await window.loadURL("data:text/html,<title>AST study IPC smoke</title>");
    const run = (code) => window.webContents.executeJavaScript(code);
    assert.deepEqual(await run("window.ast.getStudyFonts(1)"), { summaryFont: 20, tutorFont: 18 });
    const legacyFonts = join(account, "study", "settings", "preferences", "user", "dev", "synesis", "poc", "pdf");
    await mkdir(legacyFonts, { recursive: true });
    await writeFile(join(legacyFonts, "values.properties"), "# Legacy settings\nsummaryFont=22\n");
    assert.deepEqual(await run("window.ast.getStudyFonts(1)"), { summaryFont: 22, tutorFont: 18 });
    const newFonts = { summaryFont: 24, tutorFont: 19 };
    assert.deepEqual(await run(`window.ast.saveStudyFonts(1, ${JSON.stringify(newFonts)})`), newFonts);
    assert.equal(await run("window.ast.saveStudyFonts(1, { summaryFont: 24, tutorFont: 3 }).then(() => true, () => false)"), false);
    assert.deepEqual(await run("window.ast.getStudyFonts(1)"), newFonts);
    const open = (document, expected = revision) => window.webContents.executeJavaScript(
      `window.ast.openFocusPdf(${JSON.stringify(expected)}, ${JSON.stringify(document)})`,
    );

    assert.deepEqual(await open(first.pdfId), { ok: true, value: null });
    assert.deepEqual(await open(first.pdfId), { ok: true, value: null });
    const digest = first.library.items.find(item => item.id === first.pdfId).digest;
    const firstStudy = join(account, "study", "library", digest);
    assert.equal(await readFile(join(firstStudy, "source.pdf"), "utf8"), pdfBytes());
    assert.match(await readFile(join(firstStudy, "library.properties"), "utf8"), /^name=\\uC5F0\\uACB0 /m);
    assert.match((await waitForIndex(firstStudy)).pages[0].nativeText, /AST Study fixture/);
    const plan = await waitForPlanningRequest(firstStudy);
    assert.equal(plan.strategy, "newest-k1-2-5");
    assert.equal(plan.scope, "document");
    assert.equal(plan.page, 0);
    assert.deepEqual(plan.pages, [1]);
    assert.deepEqual(await open(other.pdfId), { ok: true, value: null });
    assert.deepEqual(await open(first.pdfId), { ok: true, value: null });
    assert.equal((await open(damaged.pdfId)).ok, false);

    account = accounts[1];
    revision = 2;
    study.sessionChanged(account, revision);
    assert.equal(await run("window.ast.getStudyFonts(1).then(() => true, () => false)"), false);
    assert.deepEqual(await run("window.ast.getStudyFonts(2)"), { summaryFont: 20, tutorFont: 18 });
    assert.equal((await open(first.pdfId, 1)).ok, false);
    assert.equal((await open(first.pdfId)).ok, false);
    assert.deepEqual(await open(second.pdfId), { ok: true, value: null });
    assert.equal(await readFile(join(account, "study", "library", digest, "source.pdf"), "utf8"), pdfBytes());
    assert.ok(!(await readdir(firstStudy)).includes("usage"), "Offline study planning must not create paid usage");
    assert.equal(window.isVisible(), false);
    console.log("PASS: AST preload → verified PDF IPC → real Swing bridge, automatic K1.2.5 planning, bad PDF, document switching and account separation");
  } catch (error) {
    console.error(error);
    exitCode = 1;
  } finally {
    await study.close();
    window?.destroy();
    await rm(profile, { recursive: true, force: true });
    app.exit(exitCode);
  }
}

void main();
