import { useCallback, useRef, useState } from "react";
import type { ProgressEvent, ResearchParams, ResearchSession } from "./types/domain";
import { streamResearch } from "./lib/api";
import { SearchForm } from "./components/SearchForm";
import { RunProgress } from "./components/RunProgress";
import { Results } from "./components/Results";
import { ThemeToggle } from "./components/ui/primitives";

type Phase = "idle" | "running" | "done" | "error";

export default function App() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [error, setError] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async (params: ResearchParams) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setEvents([]);
    setSession(null);
    setError("");
    setPhase("running");

    try {
      await streamResearch(params, {
        signal: controller.signal,
        onEvent: (ev) => {
          if (ev.type === "SessionComplete") {
            setSession(ev.session);
            setPhase("done");
          } else if (ev.type === "Error") {
            setError(ev.detail);
            setPhase("error");
          } else if (ev.type !== "Done") {
            setEvents((prev) => [...prev, ev]);
          }
        },
      });
    } catch (err) {
      if (controller.signal.aborted) return; // user cancelled — stay reset
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPhase("idle");
    setEvents([]);
    setSession(null);
    setError("");
  }, []);

  return (
    <div className="app-aurora min-h-full">
      <header className="sticky top-0 z-10 border-b border-border bg-bg/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <button
            type="button"
            onClick={reset}
            className="flex items-center gap-2 text-sm font-semibold text-text"
          >
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-accent to-accent2 text-accentfg">
              ◈
            </span>
            Research Engine
          </button>
          <ThemeToggle />
        </div>
      </header>

      <main className="px-4 py-10 sm:py-14">
        {phase === "idle" && <SearchForm onSubmit={start} />}

        {phase === "running" && <RunProgress events={events} onCancel={reset} />}

        {phase === "done" && session && (
          <Results session={session} onReset={reset} />
        )}

        {phase === "error" && (
          <div className="rise mx-auto max-w-lg text-center">
            <div className="mb-4 text-4xl">⚠</div>
            <h2 className="mb-2 text-xl font-semibold text-text">
              Research could not complete
            </h2>
            <p className="mb-6 text-sm text-muted">{error}</p>
            <button
              type="button"
              onClick={reset}
              className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-accentfg transition hover:opacity-90"
            >
              Try again
            </button>
          </div>
        )}
      </main>

      <footer className="border-t border-border py-6 text-center text-xs text-muted">
        Grounded · cited · confidence-scored — not a chatbot.
      </footer>
    </div>
  );
}
