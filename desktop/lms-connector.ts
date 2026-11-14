import { existsSync } from "node:fs";
import { join } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { getDefaultEnvironment, StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import type { CampusNoticeError } from "../shared/campus-notices.js";
import { COURSE_PDF_LIMIT_BYTES } from "./chat-course-pdfs.js";
import { isPublicChatTool } from "./chat-tool-scope.js";
import { BackgroundReadDeferred, LmsAccess } from "./lms-access.js";

class ConnectorSetupError extends Error {}

export function createLmsConnector(projectRoot: string, dataDirectory: string, access = new LmsAccess(), accountDirectory?: string) {
  let client: Client | undefined;
  let connection: Promise<Client> | undefined;
  let closing = false;

  function getClient(): Promise<Client> {
    if (closing) throw new ConnectorSetupError("로컬 LMS 커넥터를 종료하고 있어요.");
    if (connection) return connection;

    const python = join(projectRoot, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (!existsSync(python)) {
      throw new ConnectorSetupError("Python 가상환경이 없어요. README의 설치 단계부터 진행해 주세요.");
    }

    const localClient = new Client({ name: "agent-for-seoultech", version: "0.1.0" });
    const transport = new StdioClientTransport({
      command: python,
      args: ["-m", "seoultech_lms.mcp_server"],
      cwd: projectRoot,
      env: {
        ...getDefaultEnvironment(),
        AST_LMS_DATA_DIR: dataDirectory,
        ...(accountDirectory ? { AST_LMS_ACCOUNT_DIR: accountDirectory } : {}),
        PLAYWRIGHT_BROWSERS_PATH: join(projectRoot, ".playwright-browsers"),
        PYTHONUTF8: "1",
      },
      stderr: "ignore",
      // One structured result can contain up to 50 MB of PDF bytes plus Base64 and JSON overhead.
      maxBufferSize: Math.ceil(COURSE_PDF_LIMIT_BYTES / 3) * 4 + 4 * 1024 * 1024,
    });

    const reset = () => {
      if (client === localClient) {
        client = undefined;
        connection = undefined;
      }
    };
    client = localClient;
    localClient.onclose = reset;
    connection = localClient.connect(transport, { timeout: 15_000 }).then(() => localClient, async () => {
      reset();
      await localClient.close().catch(() => {});
      throw new ConnectorSetupError("로컬 LMS 커넥터를 시작하지 못했어요. 설치 상태를 확인해 주세요.");
    });
    return connection;
  }

  async function requestTool<T>(
    tool: string,
    args: Record<string, unknown>,
    timeout: number,
    errorMessage: string,
    signal?: AbortSignal,
    mayStart?: () => boolean,
  ): Promise<T | CampusNoticeError> {
    try {
      const result = await callTool(tool, args, { timeout, signal, mayStart });
      if (result.isError || !result.structuredContent) {
        return { status: "error", message: errorMessage };
      }
      return result.structuredContent as T;
    } catch (error) {
      if (error instanceof BackgroundReadDeferred) throw error;
      return { status: "error", message: error instanceof ConnectorSetupError ? error.message : errorMessage };
    }
  }

  function callTool(name: string, args: Record<string, unknown>, options: { timeout: number; signal?: AbortSignal; mayStart?: () => boolean }) {
    const publicRead = isPublicChatTool(name) || name === "list_department_notices" || name === "get_department_notice";
    const read = async () => {
      options.signal?.throwIfAborted();
      const connected = await getClient();
      options.signal?.throwIfAborted();
      if (options.mayStart && !options.mayStart()) throw new BackgroundReadDeferred();
      // Keep the LMS lane until an in-flight read settles even if its chat closes.
      return connected.callTool({ name, arguments: args }, undefined, publicRead ? options : { timeout: options.timeout });
    };
    return publicRead ? read() : access.connectorRead(read, options.mayStart);
  }

  function close(): Promise<void> | undefined {
    closing = true;
    if (!client) return;
    const active = client;
    client = undefined;
    connection = undefined;
    return active.close();
  }

  return { getClient, callTool, requestTool, close, access };
}
