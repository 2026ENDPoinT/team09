type ResponseEvent = { type: string; response?: unknown; delta?: unknown; code?: unknown };

export async function readResponseStream(
  body: ReadableStream<Uint8Array>, signal: AbortSignal, onEvent: (event: ResponseEvent) => void,
): Promise<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let data: string[] = [];
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() + "\n\n" : decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const raw of lines) {
        const line = raw.replace(/\r$/, "");
        if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        if (line !== "" || data.length === 0) continue;
        const json = data.join("\n");
        data = [];
        if (json === "[DONE]") continue;
        const event = JSON.parse(json) as ResponseEvent;
        onEvent(event);
        if (["response.completed", "response.incomplete", "response.failed"].includes(event.type)) return event.response;
        if (event.type === "error") return { error: event, status: "failed" };
      }
      if (done) return undefined;
    }
    return undefined;
  } finally {
    signal.removeEventListener("abort", cancel);
    cancel();
    reader.releaseLock();
  }
}

export function guidanceAnswerPrefix(text: string): string {
  const field = /^\s*\{\s*(?:"can_offer_solution"\s*:\s*(?:true|false)\s*,\s*)?"answer"\s*:\s*"/.exec(text);
  return field ? decodeJsonStringPrefix(text.slice(field[0].length)) : "";
}

export function decodeJsonStringPrefix(text: string): string {
  // A chunk can end inside an escape sequence or between surrogate halves.
  const prefix = /^(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*/.exec(text)![0];
  return (JSON.parse('"' + prefix + '"') as string).replace(/[\uD800-\uDBFF]$/, "");
}
