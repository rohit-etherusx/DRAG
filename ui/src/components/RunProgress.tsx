import { useMemo } from "react";
import type { ProgressEvent } from "../types/domain";
import { deriveRun } from "../lib/runModel";
import type { IterationView } from "../lib/runModel";
import { confidenceTone, pct } from "../lib/format";
import { Card, ConfidenceBar, Stat, ToneDot, SectionLabel } from "./ui/primitives";

export function RunProgress({
  events,
  onCancel,
}: {
  events: ProgressEvent[];
  onCancel: () => void;
}) {
  const run = useMemo(() => deriveRun(events), [events]);

  return (
    <div className="rise mx-auto w-full max-w-5xl">
      {/* Header: topic + live phase + cancel */}
      <Card className="mb-5 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-accent">
              <ToneDot tone="accent" live /> Researching
            </div>
            <h2 className="truncate text-xl font-semibold text-text">
              {run.topic || "…"}
            </h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted">
              <span className="shimmer inline-block h-3 w-3 rounded-full bg-surface2" />
              {run.phase}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-sm text-muted transition hover:border-danger hover:text-danger"
          >
            Cancel
          </button>
        </div>

        <div className="mt-5">
          <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
            <span>Confidence</span>
            <span className="font-semibold tabular-nums text-text">
              {pct(run.confidence)}
            </span>
          </div>
          <ConfidenceBar value={run.confidence} tone={confidenceTone(run.confidence)} />
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat label="Searches" value={run.totals.searchTasks} />
          <Stat label="Documents" value={run.totals.documents} tone="info" />
          <Stat label="Sources" value={run.totals.sources} tone="info" />
          <Stat label="Claims" value={run.totals.claims} tone="accent" />
          <Stat label="Corroborated" value={run.totals.corroborated} tone="success" />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
        {/* Plan */}
        <Card className="h-fit p-5">
          <SectionLabel>Research plan</SectionLabel>
          {run.subquestions.length === 0 ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="shimmer h-8 rounded-lg bg-surface2" />
              ))}
            </div>
          ) : (
            <ol className="space-y-2.5">
              {run.subquestions.map((sq, i) => (
                <li key={sq.id} className="flex gap-2.5 text-sm">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent/15 text-[11px] font-semibold text-accent">
                    {i + 1}
                  </span>
                  <span className="text-text">{sq.question}</span>
                </li>
              ))}
            </ol>
          )}
          {run.planner && (
            <p className="mt-4 text-xs text-muted">Planner: {run.planner}</p>
          )}
        </Card>

        {/* Iteration timeline */}
        <div className="space-y-4">
          {run.iterations.length === 0 ? (
            <Card className="p-8 text-center text-sm text-muted">
              Waiting for the first iteration…
            </Card>
          ) : (
            run.iterations.map((it) => <IterationCard key={it.iteration} it={it} />)
          )}
          {run.stopReason && (
            <Card className="border-warning/40 p-4 text-sm text-muted">
              <span className="font-medium text-warning">Stopping · </span>
              {run.stopReason}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function IterationCard({ it }: { it: IterationView }) {
  const done = it.summary;
  return (
    <Card className="rise p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ToneDot tone={done ? "success" : "accent"} live={!done} />
          <span className="font-semibold text-text">Iteration {it.iteration}</span>
          {it.source && <span className="text-xs text-muted">· {it.source}</span>}
        </div>
        {done && (
          <span className="text-xs font-medium tabular-nums text-success">
            {pct(done.confidence)} confidence
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        {it.tasks.map((t) => (
          <div
            key={t.task_id}
            className="flex items-center gap-2 text-sm text-muted"
          >
            <span className={t.failed ? "text-danger" : "text-success"}>
              {t.failed ? "✕" : "✓"}
            </span>
            <span className="truncate text-text">{t.query}</span>
            <span className="ml-auto shrink-0 tabular-nums text-xs">
              {t.accepted}/{t.candidates} · {t.documents} docs
            </span>
          </div>
        ))}
        {it.tasks.length < it.taskCount &&
          Array.from({ length: it.taskCount - it.tasks.length }).map((_, i) => (
            <div key={`p${i}`} className="shimmer h-5 rounded bg-surface2" />
          ))}
      </div>

      {(it.extraction || it.verification || done) && (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-border pt-3 text-xs text-muted">
          {it.extraction && (
            <span>
              <b className="text-text">{it.extraction.claims}</b> claims from{" "}
              {it.extraction.documents} docs
            </span>
          )}
          {it.verification && (
            <span>
              <b className="text-success">{it.verification.corroborated}</b> corroborated
              {it.verification.unsupported > 0 && (
                <>
                  {" · "}
                  <b className="text-warning">{it.verification.unsupported}</b> unsupported
                </>
              )}
            </span>
          )}
          {done && (
            <>
              <span>novelty {pct(done.novelty)}</span>
              <span>gain {pct(done.knowledge_gain)}</span>
              {done.open_gaps > 0 && <span>{done.open_gaps} open gap(s)</span>}
            </>
          )}
        </div>
      )}
    </Card>
  );
}
