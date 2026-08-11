import { useState } from "react";
import type {
  Claim,
  ConfidenceReport,
  Contradiction,
  Finding,
  Source,
} from "../../types/domain";
import {
  claimStatusMeta,
  cn,
  confidenceLabel,
  confidenceTone,
  hostOf,
  pct,
  providerGlyph,
} from "../../lib/format";
import {
  Badge,
  ConfidenceBar,
  EmptyState,
  SectionLabel,
  StepChip,
} from "../ui/primitives";

/* ---- Findings --------------------------------------------------------- */
export function FindingList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0)
    return <EmptyState>no findings were synthesized</EmptyState>;
  return (
    <div className="space-y-4">
      {findings.map((f, i) => (
        <div key={f.id} className="border-[1.5px] border-border bg-surface">
          <div className="flex items-center justify-between gap-3 border-b-[1.5px] border-border bg-surface2 px-3 py-1.5">
            <span className="flex items-center gap-2 text-[11px] lowercase text-muted">
              <StepChip n={String(i + 1).padStart(2, "0")} />
              finding · {f.subquestion_id || "cross-cutting"}
            </span>
            <Badge tone={confidenceTone(f.confidence)}>
              {pct(f.confidence)} {confidenceLabel(f.confidence)}
            </Badge>
          </div>
          <div className="p-3.5">
            <p className="font-serif text-[15px] leading-relaxed">{f.statement}</p>
            <div className="mt-3">
              <ConfidenceBar
                value={f.confidence}
                tone={confidenceTone(f.confidence)}
                cells={24}
              />
            </div>
            {f.confidence_explanation && (
              <p className="mt-2.5 text-[11px] leading-relaxed text-muted">
                {f.confidence_explanation}
              </p>
            )}
            <p className="mt-2 text-[11px] lowercase text-muted">
              cites{" "}
              <b className="tabular-nums text-text">{f.claim_ids.length}</b> verified
              claim(s)
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---- Claims ----------------------------------------------------------- */
export function ClaimList({ claims }: { claims: Claim[] }) {
  const [filter, setFilter] = useState<"all" | Claim["status"]>("all");
  if (claims.length === 0) return <EmptyState>no claims were extracted</EmptyState>;

  const filtered =
    filter === "all" ? claims : claims.filter((c) => c.status === filter);
  const counts = claims.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});

  const chips: ["all" | Claim["status"], string, number][] = [
    ["all", "all", claims.length],
    ["corroborated", "corroborated", counts.corroborated ?? 0],
    ["single_source", "single source", counts.single_source ?? 0],
    ["contradicted", "contested", counts.contradicted ?? 0],
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap border-[1.5px] border-border">
        {chips.map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            aria-current={filter === key}
            className={cn(
              "flex items-center gap-1.5 border-r-[1.5px] border-border px-3 py-1.5 text-[11px] font-bold lowercase transition last:border-r-0",
              filter === key
                ? "bg-text text-surface"
                : "text-muted hover:bg-surface2 hover:text-text",
            )}
          >
            {label}
            <span className="tabular-nums opacity-70">{count}</span>
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {filtered.length === 0 && <EmptyState>no claims in this category</EmptyState>}
        {filtered.map((c) => {
          const meta = claimStatusMeta(c.status);
          const toneText =
            meta.tone === "success"
              ? "text-success"
              : meta.tone === "danger"
                ? "text-danger"
                : meta.tone === "warning"
                  ? "text-warning"
                  : "text-muted";
          return (
            <div key={c.id} className="border-[1.5px] border-border bg-surface">
              <div className="flex items-start gap-3 p-3.5">
                <span
                  className={cn(
                    "grid h-6 w-6 shrink-0 place-items-center border-[1.5px] border-border text-xs font-bold",
                    toneText,
                  )}
                  title={meta.label}
                >
                  {meta.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] leading-relaxed">{c.text}</p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] lowercase text-muted">
                    <Badge tone="muted">{c.claim_type.replace(/_/g, " ")}</Badge>
                    <span>
                      <b className="tabular-nums text-text">
                        {c.supporting_sources}
                      </b>{" "}
                      source(s)
                    </span>
                    <span>
                      <b className="tabular-nums text-text">
                        {c.independent_domains}
                      </b>{" "}
                      domain(s)
                    </span>
                    {c.agreement > 0 && (
                      <span>
                        agreement{" "}
                        <b className="tabular-nums text-text">{pct(c.agreement)}</b>
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-2">
                      <span title="importance to the research objective">
                        imp{" "}
                        <b className="tabular-nums text-text">{pct(c.importance)}</b>
                      </span>
                      <span
                        className="border-[1.5px] border-border px-1 font-bold tabular-nums text-text"
                        title={c.confidence_explanation}
                      >
                        {pct(c.confidence)}
                      </span>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---- Sources ---------------------------------------------------------- */
export function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return <EmptyState>no sources were used</EmptyState>;
  const sorted = [...sources].sort((a, b) => b.authority - a.authority);
  return (
    <div className="border-[1.5px] border-border">
      {/* Ledger header */}
      <div className="flex items-center gap-3 bg-text px-3 py-2 text-[11px] font-bold lowercase text-surface">
        <span className="w-6 shrink-0 text-center">#</span>
        <span className="min-w-0 flex-1">source</span>
        <span className="w-24 shrink-0 text-right">authority</span>
      </div>
      {sorted.map((s, i) => (
        <a
          key={s.id}
          href={s.locator || undefined}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-3 border-t-[1.5px] border-border bg-surface px-3 py-2.5 transition hover:bg-surface2"
        >
          <span
            className="grid h-6 w-6 shrink-0 place-items-center border-[1.5px] border-border bg-surface2 text-[11px] font-bold"
            title={s.provider}
          >
            {providerGlyph(s.provider)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px]">{s.title}</span>
            <span className="block truncate text-[11px] lowercase text-muted">
              S{i + 1} · {s.provider} · {hostOf(s.locator)}
            </span>
          </span>
          <span className="w-24 shrink-0 text-right">
            <span className="block text-[13px] font-bold tabular-nums text-accent">
              {pct(s.authority)}
            </span>
            <span className="block truncate text-[10px] lowercase text-muted">
              {s.authority_tier}
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

/* ---- Contradictions --------------------------------------------------- */
export function ContradictionList({ items }: { items: Contradiction[] }) {
  if (items.length === 0)
    return <EmptyState>no conflicting claims were detected across sources</EmptyState>;
  return (
    <div className="space-y-4">
      {items.map((c) => (
        <div
          key={c.id}
          className="relative border-[1.5px] border-danger bg-surface p-4 pt-5"
        >
          <span className="absolute -top-2.5 left-3 border-[1.5px] border-danger bg-surface px-2 py-0.5 text-[10px] font-bold lowercase tracking-widest text-danger">
            ⚠ contradiction
          </span>
          <p className="text-[13px] leading-relaxed">{c.description}</p>
          <p className="mt-2.5 text-[11px] lowercase text-muted">
            between{" "}
            <b className="tabular-nums text-text">{c.claim_ids.length}</b> claim(s) ·{" "}
            {c.claim_ids.join(", ")}
          </p>
        </div>
      ))}
    </div>
  );
}

/* ---- Confidence breakdown -------------------------------------------- */
export function ConfidencePanel({
  confidence,
}: {
  confidence: ConfidenceReport | null;
}) {
  if (!confidence) return null;
  const rows: [string, number][] = [
    ["agreement", confidence.agreement],
    ["coverage", confidence.coverage],
    ["authority", confidence.authority],
    ["evidence quality", confidence.evidence_quality],
    ["specificity", confidence.specificity],
  ];
  return (
    <div className="sheet lift-2 p-5">
      <SectionLabel>confidence breakdown</SectionLabel>

      <div className="mb-5 flex items-end justify-between gap-2 border-b-[1.5px] border-border pb-4">
        <span className="display display-sm text-4xl tabular-nums">
          {pct(confidence.score)}
        </span>
        <Badge tone={confidenceTone(confidence.score)} className="mb-1.5">
          {confidenceLabel(confidence.score)}
        </Badge>
      </div>

      <div className="space-y-3.5">
        {rows.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 flex justify-between text-[11px] lowercase text-muted">
              <span>{label}</span>
              <span className="font-bold tabular-nums text-text">{pct(value)}</span>
            </div>
            <ConfidenceBar value={value} tone={confidenceTone(value)} cells={16} />
          </div>
        ))}
      </div>

      <dl className="mt-4 space-y-1.5 border-t-[1.5px] border-dashed border-border pt-3 text-[11px] lowercase text-muted">
        <div className="flex justify-between">
          <dt>independent sources</dt>
          <dd className="font-bold tabular-nums text-text">
            {confidence.independent_sources}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt>contradictions</dt>
          <dd className="font-bold tabular-nums text-text">
            {confidence.contradictions}
          </dd>
        </div>
      </dl>

      {confidence.explanation && (
        <p className="mt-3 border-t-[1.5px] border-dashed border-border pt-3 text-[11px] leading-relaxed text-muted">
          {confidence.explanation}
        </p>
      )}
    </div>
  );
}
