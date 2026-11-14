import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { app } from "electron";
import { parseStudentPreferences, type StudentPreferences } from "../shared/student-preferences.js";

const fileName = "student-preferences.json";

export async function readStudentPreferences(directory = app.getPath("userData")): Promise<StudentPreferences | null> {
  try {
    const preferences = parseStudentPreferences(JSON.parse(await readFile(join(directory, fileName), "utf8")));
    if (!preferences) throw new Error("저장된 계정 설정의 형식이 올바르지 않아요.");
    return preferences;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export async function saveStudentPreferences(input: unknown, directory = app.getPath("userData")): Promise<StudentPreferences | null> {
  const preferences = parseStudentPreferences(input);
  if (!preferences) return null;
  const target = join(directory, fileName);
  const temporary = target + "." + randomUUID() + ".tmp";
  await mkdir(directory, { recursive: true, mode: 0o700 });
  try {
    await writeFile(temporary, JSON.stringify(preferences) + "\n", { mode: 0o600, flag: "wx" });
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
  return preferences;
}
