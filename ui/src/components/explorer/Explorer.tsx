import { useState } from "react";
import type {
  Claim,
  Contradiction,
  Finding,
  Source,
} from "../../types/domain";
import {
  claimStatusMeta,
  confidenceTone,
  hostOf,
  pct,
  providerGlyph,
  titleCase,
} from "../../lib/format";
import { Badge, ConfidenceBar, EmptyState, SectionLabel } from "../ui/primitives";

/* ---- Findings --------------------------------------------------------- */
export function FindingList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0)
    return <EmptyState>No findings were synthesized.</EmptyState>;
  return (
    <div className="space-y-3">
      {findings.map((f) => (
        <div key={f.id} className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-text">{f.statement}</p>
            <Badge tone={confidenceTone(f.confidence)}>{pct(f.confidence)}</Badge>
          </div>
          {f.confidence_explanation && (
            <p className="mt-2 text-xs text-muted">{f.confidence_explanation}</p>
          )}
          <p className="mt-2 text-xs text-muted">
            {f.claim_ids.length} supporting claim(s)
          </p>
        </div>
      ))}
    </div>
  );
}

/* ---- Claims ----------------------------------------------------------- */
export function ClaimList({ claims }: { claims: Claim[] }) {
  const [filter, setFilter] = useState<"all" | Claim["status"]>("all");
  if (claims.length === 0) return <EmptyState>No claims were extracted.</EmptyState>;

  const filtered =
    filter === "all" ? claims : claims.filter((c) => c.status === filter);
  const counts = claims.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});

  const chips: ["all" | Claim["status"], string][] = [
    ["all", `All ${claims.length}`],
    ["corroborated", `Corroborated ${counts.corroborated ?? 0}`],
    ["single_source", `Single ${counts.single_source ?? 0}`],
    ["contradicted", `Contested ${counts.contradicted ?? 0}`],
  ];

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {chips.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={
              "rounded-full border px-3 py-1 text-xs transition " +
              (filter === key
                ? "border-accent bg-accent/10 text-text"
                : "border-border text-muted hover:text-text")
            }
          >
            {label}
          </button>
        ))}
      </div>
      <div className="space-y-2">
        {filtered.map((c) => {
          const meta = claimStatusMeta(c.status);
          return (
            <div
              key={c.id}
              className="rounded-xl border border-border bg-surface p-3.5"
            >
              <div className="flex items-start gap-3">
                <span
                  className={
                    "mt-0.5 shrink-0 text-sm " +
                    (meta.tone === "success"
                      ? "text-success"
                      : meta.tone === "danger"
                        ? "text-danger"
                        : meta.tone === "warning"
                          ? "text-warning"
                          : "text-muted")
                  }
                  title={meta.label}
                >
                  {meta.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-text">{c.text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                    <Badge tone="muted">{titleCase(c.claim_type)}</Badge>
                    <span>{c.supporting_sources} source(s)</span>
                    <span>{c.independent_domains} domain(s)</span>
                    {c.agreement > 0 && <span>{pct(c.agreement)} agreement</span>}
                    <span className="ml-auto font-medium text-text">
                      {pct(c.confidence)}
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
  if (sources.length === 0) return <EmptyState>No sources were used.</EmptyState>;
  const sorted = [...sources].sort((a, b) => b.authority - a.authority);
  return (
    <div className="space-y-2">
      {sorted.map((s) => (
        <a
          key={s.id}
          href={s.locator || undefined}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-3 rounded-xl border border-border bg-surface p-3.5 transition hover:border-accent"
        >
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface2 text-sm font-semibold text-accent">
            {providerGlyph(s.provider)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-text">{s.title}</p>
            <p className="truncate text-xs text-muted">
              {s.provider} · {hostOf(s.locator)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-xs font-medium text-text">{pct(s.authority)}</div>
            <div className="text-[11px] text-muted">{titleCase(s.authority_tier)}</div>
          </div>
        </a>
      ))}
    </div>
  );
}

/* ---- Contradictions --------------------------------------------------- */
export function ContradictionList({ items }: { items: Contradiction[] }) {
  if (items.length === 0)
    return <EmptyState>No contradictions were detected across sources.</EmptyState>;
  return (
    <div className="space-y-3">
      {items.map((c) => (
        <div
          key={c.id}
          className="rounded-xl border border-danger/40 bg-danger/5 p-4"
        >
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-danger">
            ⚠ Contradiction
          </div>
          <p className="text-sm text-text">{c.description}</p>
          <p className="mt-2 text-xs text-muted">
            Between {c.claim_ids.length} claim(s)
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
  confidence: import("../../types/domain").ConfidenceReport | null;
}) {
  if (!confidence) return null;
  const rows: [string, number][] = [
    ["Agreement", confidence.agreement],
    ["Coverage", confidence.coverage],
    ["Authority", confidence.authority],
    ["Evidence quality", confidence.evidence_quality],
    ["Specificity", confidence.specificity],
  ];
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <SectionLabel>Confidence breakdown</SectionLabel>
      <div className="mb-4 flex items-end gap-2">
        <span className="text-3xl font-bold tabular-nums text-text">
          {pct(confidence.score)}
        </span>
        <Badge tone={confidenceTone(confidence.score)} className="mb-1.5">
          {confidenceTone(confidence.score) === "success"
            ? "high"
            : confidenceTone(confidence.score) === "warning"
              ? "medium"
              : "low"}
        </Badge>
      </div>
      <div className="space-y-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 flex justify-between text-xs text-muted">
              <span>{label}</span>
              <span className="tabular-nums text-text">{pct(value)}</span>
            </div>
            <ConfidenceBar value={value} tone={confidenceTone(value)} />
          </div>
        ))}
        <div className="flex justify-between border-t border-border pt-3 text-xs text-muted">
          <span>Independent sources</span>
          <span className="tabular-nums text-text">
            {confidence.independent_sources}
          </span>
        </div>
        <div className="flex justify-between text-xs text-muted">
          <span>Contradictions</span>
          <span className="tabular-nums text-text">{confidence.contradictions}</span>
        </div>
      </div>
      {confidence.explanation && (
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted">
          {confidence.explanation}
        </p>
      )}
    </div>
  );
}
