import { createDecipheriv, scrypt as deriveKey } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { promisify } from "node:util";

const scrypt = promisify(deriveKey);

export async function loadDemoEnv(projectRoot: string): Promise<Record<string, string>> {
  const payload = await readFile(join(projectRoot, "config", "demo-credentials.enc"));
  if (payload.length <= 76) throw new Error("Invalid demo credentials");
  // The portable demo bundles the unlock material for unattended startup.
  const passphrase = payload.subarray(0, 32);
  const salt = payload.subarray(32, 48);
  const iv = payload.subarray(48, 60);
  const tag = payload.subarray(60, 76);
  const key = await scrypt(passphrase, salt, 32) as Buffer;
  try {
    const decipher = createDecipheriv("aes-256-gcm", key, iv);
    decipher.setAuthTag(tag);
    return JSON.parse(Buffer.concat([
      decipher.update(payload.subarray(76)),
      decipher.final(),
    ]).toString("utf8")) as Record<string, string>;
  } finally {
    key.fill(0);
  }
}
