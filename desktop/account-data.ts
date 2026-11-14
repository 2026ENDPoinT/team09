import { join } from "node:path";
import type { LoginResult } from "../shared/lms.js";

export type VerifiedAccount = { key: string; displayName?: string };

export function verifiedAccount(result: LoginResult): VerifiedAccount | undefined {
  if (result.status === "authenticated" && typeof result.account_key === "string" && /^[a-f0-9]{64}$/.test(result.account_key)) {
    return { key: result.account_key, displayName: result.display_name };
  }
}

export function accountDirectory(root: string, account: VerifiedAccount) {
  return join(root, account.key);
}
