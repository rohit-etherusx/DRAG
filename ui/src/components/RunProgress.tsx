import { useMemo } from "react";
import type { ProgressEvent } from "../types/domain";
import { deriveRun } from "../lib/runModel";
import type { IterationView } from "../lib/runModel";
import { confidenceTone, pct } from "../lib/format";
import {
  Card,
  ConfidenceBar,
  SectionHeader,
  SectionLabel,
  Stat,
  StepChip,
  ToneDot,
} from "./ui/primitives";

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
      {/* Run header: what is being researched, and where the run is now. */}
      <Card lift={6} className="mb-6">
        <div className="flex items-start justify-between gap-4 p-5">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-bold lowercase tracking-widest text-accent">
              <ToneDot tone="accent" live /> researching
            </div>
            <h2 className="display display-sm truncate text-2xl">
              {run.topic || "…"}
            </h2>
            <p className="caret mt-2 text-xs text-muted">{run.phase}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="btn-danger shrink-0 px-3 py-1.5 text-xs lowercase"
          >
            cancel
          </button>
        </div>

        <div className="border-t-[1.5px] border-border px-5 py-4">
          <div className="mb-2 flex items-center justify-between text-[11px] lowercase text-muted">
            <span>confidence</span>
            <span className="font-bold tabular-nums text-text">
              {pct(run.confidence)}
            </span>
          </div>
          <ConfidenceBar
            value={run.confidence}
            tone={confidenceTone(run.confidence)}
          />
        </div>

        <div className="grid grid-cols-2 divide-x-[1.5px] divide-y-[1.5px] divide-border border-t-[1.5px] border-border sm:grid-cols-5 sm:divide-y-0">
          <div className="px-4 py-3">
            <Stat label="searches" value={run.totals.searchTasks} tone="accent" />
          </div>
          <div className="px-4 py-3">
            <Stat label="documents" value={run.totals.documents} tone="info" />
          </div>
          <div className="px-4 py-3">
            <Stat label="sources" value={run.totals.sources} tone="info" />
          </div>
          <div className="px-4 py-3">
            <Stat label="claims" value={run.totals.claims} tone="accent" />
          </div>
          <div className="px-4 py-3">
            <Stat
              label="corroborated"
              value={run.totals.corroborated}
              tone="success"
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[290px_1fr]">
        {/* The plan — fixed for the run, so it sits flush on the page. */}
        <Card lift={2} className="h-fit p-5">
          <SectionLabel>research plan</SectionLabel>
          {run.subquestions.length === 0 ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="feeding h-7" />
              ))}
            </div>
          ) : (
            <ol className="space-y-3">
              {run.subquestions.map((sq, i) => (
                <li key={sq.id} className="flex gap-2.5 text-[13px] leading-snug">
                  <StepChip n={i + 1} />
                  <span>{sq.question}</span>
                </li>
              ))}
            </ol>
          )}
          {run.planner && (
            <p className="mt-5 border-t-[1.5px] border-dashed border-border pt-3 text-[11px] lowercase text-muted">
              planner: <span className="text-text">{run.planner}</span>
            </p>
          )}
        </Card>

        {/* One sheet per research-loop iteration, in order. */}
        <div className="space-y-5">
          {run.iterations.length === 0 ? (
            <Card lift={2} className="p-8 text-center text-xs lowercase text-muted">
              waiting for the first iteration…
            </Card>
          ) : (
            run.iterations.map((it) => <IterationCard key={it.iteration} it={it} />)
          )}
          {run.stopReason && (
            <div className="rise relative border-[1.5px] border-dashed border-border bg-surface2 p-4 pt-5 text-xs leading-relaxed text-muted">
              <span className="stamp absolute -top-2.5 left-4 border-[1.5px] border-warning bg-bg px-2 py-0.5 text-[10px] font-bold lowercase tracking-widest text-warning">
                stopping
              </span>
              {run.stopReason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function IterationCard({ it }: { it: IterationView }) {
  const done = it.summary;
  const pending = Math.max(0, it.taskCount - it.tasks.length);

  return (
    <Card lift={4} className="rise">
      <SectionHeader
        index={String(it.iteration).padStart(2, "0")}
        icon={done ? "✓" : <span className="livedot">▮</span>}
        title={`iteration ${it.iteration}`}
        meta={
          done ? (
            <span className="font-bold tabular-nums text-success">
              {pct(done.confidence)}
            </span>
          ) : (
            it.source && <span className="lowercase">{it.source}</span>
          )
        }
      />

      <div className="p-4">
        {it.source && done && (
          <p className="mb-3 text-[11px] lowercase text-muted">
            tasks from {it.source}
          </p>
        )}
        <div className="space-y-1.5">
          {it.tasks.map((t) => (
            <div
              key={t.task_id}
              className="flex items-center gap-2.5 border-[1.5px] border-border bg-surface px-2.5 py-1.5 text-[13px]"
            >
              <span
                className={
                  "shrink-0 font-bold " + (t.failed ? "text-danger" : "text-success")
                }
                title={t.failed ? "search failed" : "search completed"}
              >
                {t.failed ? "✕" : "✓"}
              </span>
              <span className="truncate">{t.query}</span>
              <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted">
                {t.accepted}/{t.candidates} kept · {t.documents} docs ·{" "}
                {t.passages} psg
              </span>
            </div>
          ))}
          {Array.from({ length: pending }).map((_, i) => (
            <div key={`p${i}`} className="feeding h-8" />
          ))}
        </div>

        {(it.extraction || it.verification || done) && (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t-[1.5px] border-dashed border-border pt-3 text-[11px] lowercase text-muted">
            {it.extraction && (
              <span>
                <b className="tabular-nums text-text">{it.extraction.claims}</b>{" "}
                claims from {it.extraction.documents} docs
              </span>
            )}
            {it.verification && (
              <span>
                <b className="tabular-nums text-success">
                  {it.verification.corroborated}
                </b>{" "}
                corroborated
                {it.verification.unsupported > 0 && (
                  <>
                    {" · "}
                    <b className="tabular-nums text-warning">
                      {it.verification.unsupported}
                    </b>{" "}
                    single-source
                  </>
                )}
              </span>
            )}
            {done && (
              <>
                <span>
                  novelty{" "}
                  <b className="tabular-nums text-text">{pct(done.novelty)}</b>
                </span>
                <span>
                  gain{" "}
                  <b className="tabular-nums text-text">
                    {pct(done.knowledge_gain)}
                  </b>
                </span>
                {done.open_gaps > 0 && (
                  <span>
                    <b className="tabular-nums text-text">{done.open_gaps}</b> open
                    gap(s)
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
