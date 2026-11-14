import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { parseEnv } from "node:util";

export async function loadChatApiKey(projectRoot: string): Promise<string> {
  try {
    // Keep file values in the main process without changing the process environment.
    const values = parseEnv(await readFile(join(projectRoot, ".env"), "utf8"));
    const key = values.OPENAI_API_KEY?.trim() ?? "";
    return /^[\x21-\x7e]{1,1024}$/.test(key) ? key : "";
  } catch {
    return "";
  }
}
