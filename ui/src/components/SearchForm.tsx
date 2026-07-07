import { useState } from "react";
import type { ResearchParams } from "../types/domain";
import { cn } from "../lib/format";

const EXAMPLES = [
  "What limits the scalability of quantum error correction?",
  "Impact of intermittent fasting on metabolic health",
  "Transformer architectures for time-series forecasting",
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
    <div className="rise mx-auto w-full max-w-2xl">
      <div className="mb-8 text-center">
        <h1 className="bg-gradient-to-r from-accent to-accent2 bg-clip-text text-4xl font-bold tracking-tight text-transparent sm:text-5xl">
          Research Engine
        </h1>
        <p className="mx-auto mt-3 max-w-md text-balance text-muted">
          Ask a question or name a topic. The engine plans, searches, verifies
          across sources, and returns a grounded, cited report.
        </p>
      </div>

      <div className="rounded-2xl border border-border bg-surface p-2 shadow-lg shadow-black/5 focus-within:border-accent">
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="e.g. What are the trade-offs of solid-state batteries?"
          rows={3}
          disabled={disabled}
          className="w-full resize-none bg-transparent px-4 py-3 text-base text-text outline-none placeholder:text-muted"
        />
        <div className="flex items-center justify-between gap-3 px-2 pb-1">
          <button
            type="button"
            onClick={() => setShowAdvanced((s) => !s)}
            className="rounded-lg px-2 py-1.5 text-sm text-muted transition hover:text-text"
          >
            {showAdvanced ? "▾ Options" : "▸ Options"}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
              canSubmit
                ? "bg-accent text-accentfg hover:opacity-90 active:scale-[0.98]"
                : "cursor-not-allowed bg-surface2 text-muted",
            )}
          >
            Research <span className="opacity-70">↵</span>
          </button>
        </div>

        {showAdvanced && (
          <div className="rise mt-1 grid grid-cols-1 gap-4 border-t border-border px-3 pb-3 pt-4 sm:grid-cols-3">
            <Slider
              label="Research angles"
              value={maxSubtopics}
              min={1}
              max={7}
              onChange={setMaxSubtopics}
            />
            <Slider
              label="Docs per angle"
              value={docsPerQuery}
              min={1}
              max={10}
              onChange={setDocsPerQuery}
            />
            <Slider
              label="Max iterations"
              value={maxIterations}
              min={1}
              max={10}
              onChange={setMaxIterations}
            />
            <div className="col-span-full flex flex-wrap gap-2">
              <Toggle
                label="Offline sources"
                hint="Deterministic local knowledge — no network"
                checked={offline}
                onChange={setOffline}
              />
              <Toggle
                label="No LLM"
                hint="Deterministic synthesis only — no model calls"
                checked={noLlm}
                onChange={setNoLlm}
              />
            </div>
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            disabled={disabled}
            onClick={() => setTopic(ex)}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted transition hover:border-accent hover:text-text disabled:opacity-50"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="flex items-center justify-between text-xs text-muted">
        {label}
        <span className="font-semibold tabular-nums text-text">{value}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="accent-[var(--accent)]"
      />
    </label>
  );
}

function Toggle({
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
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition",
        checked
          ? "border-accent bg-accent/10 text-text"
          : "border-border bg-surface text-muted hover:text-text",
      )}
    >
      <span
        className={cn(
          "grid h-4 w-4 place-items-center rounded border text-[10px]",
          checked ? "border-accent bg-accent text-accentfg" : "border-border",
        )}
      >
        {checked ? "✓" : ""}
      </span>
      {label}
    </button>
  );
}
