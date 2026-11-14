import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { app } from "electron";
import { CHAT_FONT_SIZES, DEFAULT_CHAT_FONT_SIZE, DEFAULT_USD_KRW, type ChatFontSize, type ChatPreferences, type ChatSettingsInput } from "../shared/chat.js";

const defaultModel = "gpt-6-luna";
const modelPattern = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,99}$/;

function validRate(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 100_000;
}

function validFontSize(value: unknown): value is ChatFontSize {
  return CHAT_FONT_SIZES.some((size) => size === value);
}

async function readSettingsFile(directory: string): Promise<Record<string, unknown>> {
  try {
    const path = join(directory, "chat-settings.json");
    const stored: unknown = JSON.parse(await readFile(path, "utf8"));
    if (stored && typeof stored === "object" && !Array.isArray(stored)) {
      return stored as Record<string, unknown>;
    }
  } catch {
    // Missing or invalid preferences fall back to defaults.
  }
  return {};
}

function preferences(stored: Record<string, unknown>): ChatPreferences {
  return {
    model: typeof stored.model === "string" && modelPattern.test(stored.model) ? stored.model : defaultModel,
    usdKrw: validRate(stored.usdKrw) ? stored.usdKrw : DEFAULT_USD_KRW,
    fontSize: validFontSize(stored.fontSize) ? stored.fontSize : DEFAULT_CHAT_FONT_SIZE,
  };
}

async function writeSettingsFile(value: ChatPreferences & { encryptedKey?: string }, directory: string): Promise<void> {
  const target = join(directory, "chat-settings.json");
  const temporary = target + "." + randomUUID() + ".tmp";
  await mkdir(directory, { recursive: true, mode: 0o700 });
  try {
    await writeFile(temporary, JSON.stringify(value), { mode: 0o600, flag: "wx" });
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true }).catch(() => {});
  }
}

export async function readChatSettings(directory: string | null = app.getPath("userData")): Promise<ChatPreferences> {
  return preferences(directory ? await readSettingsFile(directory) : {});
}

// Call after a key is configured in .env, before accepting any settings writes.
export async function removeLegacyChatKey(): Promise<void> {
  const directory = app.getPath("userData");
  const stored = await readSettingsFile(directory);
  if (Object.hasOwn(stored, "encryptedKey")) {
    await writeSettingsFile(preferences(stored), directory);
  }
}

export async function saveChatSettings(value: unknown, directory = app.getPath("userData")): Promise<ChatPreferences> {
  if (!value || typeof value !== "object") throw new Error("설정값을 다시 확인해 주세요.");
  const input = value as ChatSettingsInput;
  if (typeof input.model !== "string" || !modelPattern.test(input.model.trim())) {
    throw new Error("모델 이름을 다시 확인해 주세요.");
  }
  if (input.usdKrw !== undefined && !validRate(input.usdKrw)) {
    throw new Error("환율은 0보다 크고 100,000 이하인 숫자로 입력해 주세요.");
  }
  if (input.fontSize !== undefined && !validFontSize(input.fontSize)) {
    throw new Error("채팅 글자 크기를 다시 선택해 주세요.");
  }
  const stored = await readSettingsFile(directory);
  const current = preferences(stored);
  const saved = {
    model: input.model.trim(),
    usdKrw: input.usdKrw ?? current.usdKrw,
    fontSize: input.fontSize ?? current.fontSize,
  };
  // Preserve an existing ciphertext until the user configures .env.
  const encryptedKey = typeof stored.encryptedKey === "string" ? stored.encryptedKey : undefined;
  await writeSettingsFile({ ...saved, encryptedKey }, directory);
  return saved;
}
