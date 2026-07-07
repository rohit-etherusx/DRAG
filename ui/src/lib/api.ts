/**
 * Engine API client.
 *
 * `streamResearch` posts to `/research/stream` and parses the Server-Sent
 * Events response incrementally, invoking `onEvent` for each typed progress
 * event as it arrives. We use fetch + a streaming body reader (not the native
 * EventSource) because the request is a POST *and* because EventSource would
 * auto-reconnect on close — which would restart a finished research run.
 */
import type { ProgressEvent, ResearchParams } from "../types/domain";

export interface StreamHandlers {
  onEvent: (event: ProgressEvent) => void;
  signal?: AbortSignal;
}

export async function checkHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch("/health");
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  return res.json();
}

function requestBody(params: ResearchParams): string {
  // Drop undefined optionals so the server applies its own defaults.
  const body: Record<string, unknown> = {
    topic: params.topic,
    offline: params.offline,
    no_llm: params.no_llm,
  };
  if (params.max_subtopics != null) body.max_subtopics = params.max_subtopics;
  if (params.documents_per_query != null)
    body.documents_per_query = params.documents_per_query;
  if (params.max_iterations != null) body.max_iterations = params.max_iterations;
  return JSON.stringify(body);
}

export async function streamResearch(
  params: ResearchParams,
  { onEvent, signal }: StreamHandlers,
): Promise<void> {
  const res = await fetch("/research/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: requestBody(params),
    signal,
  });

  if (!res.ok || !res.body) {
    // Validation errors (422) and the like come back as regular JSON, not SSE.
    let detail = `request failed: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) {
        detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ")
          : String(data.detail);
      }
    } catch {
      /* keep the status-based message */
    }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const dataLines = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(l.startsWith("data: ") ? 6 : 5));
      if (dataLines.length === 0) continue;
      try {
        onEvent(JSON.parse(dataLines.join("\n")) as ProgressEvent);
      } catch {
        /* ignore keep-alive/comment frames */
      }
    }
  }
}
