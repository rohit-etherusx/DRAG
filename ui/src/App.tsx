import { useCallback, useEffect, useRef, useState } from "react";
import type { ProgressEvent, ResearchParams, ResearchSession } from "./types/domain";
import { checkHealth, streamResearch } from "./lib/api";
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
  const [version, setVersion] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  // Stamp the running engine's version in the masthead. Best-effort: the UI is
  // fully usable if the probe fails (e.g. backend still starting).
  useEffect(() => {
    let cancelled = false;
    checkHealth()
      .then((h) => {
        if (!cancelled) setVersion(h.version);
      })
      .catch(() => {
        /* no badge, no problem */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    <div className="app-paper flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b-[1.5px] border-border bg-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <button
            type="button"
            onClick={reset}
            className="group flex items-center gap-2"
            title="Start over"
          >
            <svg
              width="20"
              height="24"
              viewBox="0 0 40 50"
              className="shrink-0 text-border"
              aria-hidden="true"
            >
              <g stroke="currentColor" strokeWidth="3" strokeLinejoin="round">
                <path d="M2.5 2.5h23l12 12v33.5H2.5z" fill="var(--color-p-pink)" />
                <path d="M25.5 2.5v12h12" fill="none" />
                <path d="M10 27h20M10 35h13" strokeLinecap="round" />
              </g>
            </svg>
            <span className="text-sm font-bold lowercase tracking-tight">
              research<span className="text-accent">-</span>engine
            </span>
            {version && (
              <span className="border-[1.5px] border-border bg-text px-1 py-px text-[10px] font-bold tabular-nums text-surface">
                v{version}
              </span>
            )}
          </button>

          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] lowercase text-muted sm:inline">
              grounded · cited · confidence-scored
            </span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-1 px-4 py-10 sm:py-14">
        {phase === "idle" && <SearchForm onSubmit={start} />}

        {phase === "running" && <RunProgress events={events} onCancel={reset} />}

        {phase === "done" && session && (
          <Results session={session} onReset={reset} />
        )}

        {phase === "error" && (
          <div className="rise mx-auto max-w-lg">
            <div className="sheet lift-6 relative p-6 text-center">
              <span className="stamp absolute -top-3 right-4 border-[1.5px] border-danger px-2 py-0.5 text-[11px] font-bold lowercase tracking-widest text-danger">
                failed
              </span>
              <h2 className="display display-sm mb-3 text-2xl lowercase">
                run did not complete
              </h2>
              <p className="mb-6 break-words border-[1.5px] border-dashed border-border bg-surface2 p-3 text-left text-xs text-muted">
                {error}
              </p>
              <button type="button" onClick={reset} className="btn-ink px-5 py-2.5 text-sm">
                start over
              </button>
            </div>
          </div>
        )}
      </main>

      <footer className="border-t-[1.5px] border-border px-4 py-5">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 text-[11px] lowercase text-muted">
          <span>
            knowledge is the product — the report is one rendering of it
          </span>
          <span>not a chatbot</span>
        </div>
      </footer>
    </div>
  );
}
