import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { ipcMain, type IpcMainInvokeEvent } from "electron";
import { defaultStudyFonts, studyFontMin, studyFontMax, type StudyFontSettings } from "../shared/study-font-settings.js";

// AST Study uses the same account-scoped file for its display settings dialog.
const fileName = "study-fonts.json";

function isFontSize(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= studyFontMin && value <= studyFontMax;
}

function parse(value: unknown): StudyFontSettings {
  const { summaryFont, tutorFont } = (value ?? {}) as Partial<StudyFontSettings>;
  if (!isFontSize(summaryFont) || !isFontSize(tutorFont)) throw new Error("글자 크기를 확인해 주세요.");
  return { summaryFont, tutorFont };
}

async function readOptional(path: string) {
  try {
    return await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

export async function readStudyFonts(settingsDir: string): Promise<StudyFontSettings> {
  const saved = await readOptional(join(settingsDir, fileName));
  if (saved !== undefined) return parse(JSON.parse(saved));
  const legacy = await readOptional(join(settingsDir, "preferences/user/dev/synesis/poc/pdf/values.properties"));
  // AST Study's old store writes integer values as key=value via Properties.store.
  const legacyFont = (key: keyof StudyFontSettings) => {
    const value = Number(legacy?.match(new RegExp(`^${key}=([+-]?\\d+)$`, "m"))?.[1]);
    return Number.isInteger(value) && value >= -2147483648 && value <= 2147483647
      ? Math.max(studyFontMin, Math.min(studyFontMax, value)) : defaultStudyFonts[key];
  };
  return { summaryFont: legacyFont("summaryFont"), tutorFont: legacyFont("tutorFont") };
}

export async function saveStudyFonts(settingsDir: string, input: unknown, current: () => boolean): Promise<StudyFontSettings> {
  const value = parse(input);
  const target = join(settingsDir, fileName);
  const temporary = target + "." + randomUUID() + ".tmp";
  await mkdir(settingsDir, { recursive: true, mode: 0o700 });
  try {
    await writeFile(temporary, JSON.stringify(value) + "\n", { mode: 0o600, flag: "wx" });
    if (!current()) throw new Error("로그인 상태가 바뀌었어요.");
    await rename(temporary, target);
    return value;
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
}

export function registerStudyFontSettings(
  verifySender: (event: IpcMainInvokeEvent) => void,
  activeDirectory: () => string | undefined,
  activeRevision: () => number | undefined,
) {
  const handle = (channel: string, action: (dir: string, input: unknown, current: () => boolean) => Promise<StudyFontSettings>) => {
    ipcMain.handle(channel, async (event, expected: unknown, input: unknown) => {
      verifySender(event);
      const directory = activeDirectory();
      const revision = activeRevision();
      const current = () => activeDirectory() === directory && activeRevision() === revision;
      if (!directory || revision === undefined || revision !== expected) throw new Error("로그인 상태가 바뀌었어요.");
      const value = await action(join(directory, "study", "settings"), input, current);
      if (!current()) throw new Error("로그인 상태가 바뀌었어요.");
      return value;
    });
  };
  handle("ast:study-fonts", readStudyFonts);
  handle("ast:save-study-fonts", saveStudyFonts);
}
