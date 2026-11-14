import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { app } from "electron";
import type { LoginSettings } from "../shared/lms.js";

const fileName = "login-settings.json";

function parse(value: unknown): LoginSettings {
  if (value && typeof value === "object" && "keepLogin" in value && typeof value.keepLogin === "boolean") {
    return { keepLogin: value.keepLogin };
  }
  throw new Error("로그인 유지 설정을 확인하지 못했어요.");
}

export async function readLoginSettings(directory = app.getPath("userData")): Promise<LoginSettings> {
  try {
    return parse(JSON.parse(await readFile(join(directory, fileName), "utf8")));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { keepLogin: true };
    throw error;
  }
}

export async function saveLoginSettings(input: unknown, directory = app.getPath("userData")): Promise<LoginSettings> {
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
