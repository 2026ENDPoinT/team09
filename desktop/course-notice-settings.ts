import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { app } from "electron";
import type { CourseNoticeSettings } from "../shared/course-notice-index.js";

const fileName = "course-notice-settings.json";

function parse(value: unknown): CourseNoticeSettings {
  if (value && typeof value === "object" && "includeNonRegular" in value && typeof value.includeNonRegular === "boolean") {
    return { includeNonRegular: value.includeNonRegular };
  }
  throw new Error("수업 공지 설정을 확인하지 못했어요.");
}

export async function readCourseNoticeSettings(directory = app.getPath("userData")): Promise<CourseNoticeSettings> {
  try {
    return parse(JSON.parse(await readFile(join(directory, fileName), "utf8")));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { includeNonRegular: false };
    throw error;
  }
}

export async function saveCourseNoticeSettings(input: unknown, directory = app.getPath("userData")): Promise<CourseNoticeSettings> {
  const settings = parse(input);
  const target = join(directory, fileName);
  const temporary = target + "." + randomUUID() + ".tmp";
  await mkdir(directory, { recursive: true, mode: 0o700 });
  try {
    await writeFile(temporary, JSON.stringify(settings) + "\n", { mode: 0o600, flag: "wx" });
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
  return settings;
}
