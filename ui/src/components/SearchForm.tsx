import { useState } from "react";
import type { ResearchParams } from "../types/domain";
import { cn } from "../lib/format";
import { PaperDocs, StepChip } from "./ui/primitives";

const EXAMPLES = [
  "What limits the scalability of quantum error correction?",
  "Impact of intermittent fasting on metabolic health",
  "Transformer architectures for time-series forecasting",
  "Trade-offs of solid-state batteries",
];

export function SearchForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (params: ResearchParams) => void;
  disabled?: boolean;
}) {
  const [topic, setTopic] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxSubtopics, setMaxSubtopics] = useState(4);
  const [docsPerQuery, setDocsPerQuery] = useState(3);
  const [maxIterations, setMaxIterations] = useState(3);
  const [offline, setOffline] = useState(false);
  const [noLlm, setNoLlm] = useState(false);

  const canSubmit = topic.trim().length > 0 && !disabled;

  function submit() {
    if (!canSubmit) return;
    onSubmit({
      topic: topic.trim(),
      max_subtopics: maxSubtopics,
      documents_per_query: docsPerQuery,
      max_iterations: maxIterations,
      offline,
      no_llm: noLlm,
    });
  }

  return (
    <div className="rise mx-auto w-full max-w-3xl">
      {/* Masthead */}
      <div className="mb-10 text-center">
        <h1 className="display text-4xl lowercase sm:text-5xl">
          from question to
          <br />
          verified answer
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-sm leading-relaxed text-muted">
          plans the investigation, searches, extracts typed claims, verifies them
          across independent sources — and stops when it has learned enough
        </p>
      </div>

      {/* The query sheet */}
      <div className="sheet sheet-focus lift-6">
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="ask a question, or name a topic…"
          rows={3}
          disabled={disabled}
          autoFocus
          className="w-full resize-none bg-transparent px-4 py-3.5 text-[15px] text-text outline-none placeholder:lowercase placeholder:text-muted"
        />

        <div className="flex items-center justify-between gap-3 border-t-[1.5px] border-border px-3 py-2.5">
          <button
            type="button"
            onClick={() => setShowAdvanced((s) => !s)}
            className="flex items-center gap-1.5 px-1 text-xs lowercase text-muted transition hover:text-text"
            aria-expanded={showAdvanced}
          >
            <span className="inline-block w-3 text-center">
              {showAdvanced ? "▾" : "▸"}
            </span>
            options
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="btn-ink px-6 py-2 text-sm lowercase"
          >
            research
            <span className="text-[11px] opacity-60">⌘↵</span>
          </button>
        </div>

        {showAdvanced && (
          <div className="rise grid grid-cols-1 gap-x-6 gap-y-4 border-t-[1.5px] border-dashed border-border bg-surface2 px-4 py-4 sm:grid-cols-3">
            <Stepper
              label="research angles"
              hint="subquestions the planner decomposes into"
              value={maxSubtopics}
              min={1}
              max={7}
              onChange={setMaxSubtopics}
            />
            <Stepper
              label="docs per angle"
              hint="accepted candidates downloaded per angle"
              value={docsPerQuery}
              min={1}
              max={10}
              onChange={setDocsPerQuery}
            />
            <Stepper
              label="max iterations"
              hint="search budget for the research loop"
              value={maxIterations}
              min={1}
              max={10}
              onChange={setMaxIterations}
            />
            <div className="col-span-full flex flex-wrap gap-2">
              <Check
                label="offline sources"
                hint="Deterministic local knowledge — no network"
                checked={offline}
                onChange={setOffline}
              />
              <Check
                label="no llm"
                hint="Deterministic synthesis only — no model calls"
                checked={noLlm}
                onChange={setNoLlm}
              />
            </div>
          </div>
        )}
      </div>

      {/* Example ticker */}
      <div className="mt-8 border-y-[1.5px] border-border py-2.5">
        <div className="flex items-center gap-3 overflow-x-auto text-xs text-muted [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <span className="shrink-0 font-bold lowercase text-text">try</span>
          {EXAMPLES.map((ex, i) => (
            <span key={ex} className="flex shrink-0 items-center gap-3">
              {i > 0 && (
                <span className="h-1.5 w-1.5 shrink-0 bg-text" aria-hidden="true" />
              )}
              <button
                type="button"
                disabled={disabled}
                onClick={() => setTopic(ex)}
                className="whitespace-nowrap lowercase transition hover:text-text hover:underline hover:decoration-accent hover:decoration-2 hover:underline-offset-4 disabled:opacity-50"
              >
                {ex}
              </button>
            </span>
          ))}
        </div>
      </div>

      <PaperDocs className="mt-6 -mb-4" />
    </div>
  );
}

/** A square [−]/[+] spinner. Reads like a form printed on the page. */
function Stepper({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] lowercase text-muted" title={hint}>
        {label}
      </span>
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={() => onChange(Math.max(min, value - 1))}
          disabled={value <= min}
          className="btn-paper h-8 w-8 text-sm disabled:opacity-40"
          aria-label={`decrease ${label}`}
        >
          −
        </button>
        <span className="grid h-8 min-w-10 flex-1 place-items-center border-y-[1.5px] border-border bg-surface text-sm font-bold tabular-nums">
          {value}
        </span>
        <button
          type="button"
          onClick={() => onChange(Math.min(max, value + 1))}
          disabled={value >= max}
          className="btn-paper h-8 w-8 text-sm disabled:opacity-40"
          aria-label={`increase ${label}`}
        >
          +
        </button>
      </div>
    </div>
  );
}

/** A square checkbox with a mono tick. */
function Check({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      title={hint}
      aria-pressed={checked}
      className={cn(
        "inline-flex items-center gap-2 border-[1.5px] border-border px-3 py-1.5 text-xs lowercase transition",
        checked ? "bg-text text-surface" : "bg-surface text-muted hover:text-text",
      )}
    >
      <StepChip n={checked ? "✓" : " "} variant="paper" />
      {label}
    </button>
  );
}
