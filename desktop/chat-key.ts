import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { parseEnv } from "node:util";
import { loadDemoEnv } from "./demo-credentials.js";

export async function loadRuntimeEnv(projectRoot: string): Promise<ReturnType<typeof parseEnv>> {
  const configuredPath = process.env.AST_ENV_FILE?.trim();
  try {
    return parseEnv(await readFile(configuredPath || join(projectRoot, ".env"), "utf8"));
  } catch (error) {
    if (configuredPath || (error as NodeJS.ErrnoException).code !== "ENOENT") {
      console.warn("API 설정 파일을 읽지 못했어요.");
      return {};
    }
  }

  try {
    return await loadDemoEnv(projectRoot);
  } catch {
    console.warn("시연용 API 설정을 읽지 못했어요.");
    return {};
  }
}

export async function loadChatApiKey(projectRoot: string): Promise<string> {
  const values = await loadRuntimeEnv(projectRoot);
  const key = values.OPENAI_API_KEY?.trim() ?? "";
  return /^[\x21-\x7e]{1,1024}$/.test(key) ? key : "";
}
