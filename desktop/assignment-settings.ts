import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { app } from "electron";
import { DEFAULT_ASSIGNMENT_FONT_SIZE, isAssignmentFontSize, type AssignmentFontSize } from "../shared/assignment-browser.js";
import { defaultAssignmentVisibility, parseAssignmentVisibility } from "../shared/assignment-visibility.js";

const fileName = "assignment-settings.json";
const appearanceFileName = "assignment-appearance.json";

export async function readAssignmentSettings(directory: string | null = app.getPath("userData")) {
  if (directory) {
    try {
      return parseAssignmentVisibility(JSON.parse(await readFile(join(directory, fileName), "utf8"))) ?? defaultAssignmentVisibility;
    } catch {
      return defaultAssignmentVisibility;
    }
  }
  return defaultAssignmentVisibility;
}

export async function saveAssignmentSettings(value: unknown, directory = app.getPath("userData")) {
  const settings = parseAssignmentVisibility(value);
  if (!settings) throw new Error("표시 기간은 1일 이상의 정수로 입력해 주세요.");
  await writeSettings(directory, fileName, settings);
  return settings;
}

export async function readAssignmentFontSize(directory = app.getPath("userData")): Promise<AssignmentFontSize> {
  try {
    const stored = JSON.parse(await readFile(join(directory, appearanceFileName), "utf8"));
    if (isAssignmentFontSize(stored?.fontSize)) return stored.fontSize;
  } catch { /* Reset missing or unreadable appearance settings to the default. */ }
  return DEFAULT_ASSIGNMENT_FONT_SIZE;
}

export async function saveAssignmentFontSize(fontSize: unknown, directory = app.getPath("userData")): Promise<AssignmentFontSize> {
  if (!isAssignmentFontSize(fontSize)) throw new Error("지원하는 글자 크기를 선택해 주세요.");
  await writeSettings(directory, appearanceFileName, { fontSize });
  return fontSize;
}

async function writeSettings(directory: string, file: string, settings: object) {
  const target = join(directory, file);
  const temporary = target + "." + randomUUID() + ".tmp";
  await mkdir(directory, { recursive: true, mode: 0o700 });
  try {
    await writeFile(temporary, JSON.stringify(settings) + "\n", { mode: 0o600, flag: "wx" });
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
}
