import { useState } from "react";
import type { ResearchSession } from "../types/domain";
import { confidenceTone, pct } from "../lib/format";
import { Badge, Card, Stat } from "./ui/primitives";
import { ReportView } from "./report/ReportView";
import {
  ClaimList,
  ConfidencePanel,
  ContradictionList,
  FindingList,
  SourceList,
} from "./explorer/Explorer";

type TabKey = "report" | "findings" | "claims" | "sources" | "contradictions";

export function Results({
  session,
  onReset,
}: {
  session: ResearchSession;
  onReset: () => void;
}) {
  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "report", label: "Report" },
    { key: "findings", label: "Findings", count: session.findings.length },
    { key: "claims", label: "Claims", count: session.claims.length },
    { key: "sources", label: "Sources", count: session.sources.length },
    {
      key: "contradictions",
      label: "Contradictions",
      count: session.contradictions.length,
    },
  ];
  const [tab, setTab] = useState<TabKey>("report");
  const answer = session.answer?.text || session.direct_answer;

  return (
    <div className="rise mx-auto w-full max-w-6xl">
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-success">
            ✓ Complete
          </div>
          <h2 className="text-2xl font-semibold text-text">
            {session.request.topic}
          </h2>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="shrink-0 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-accentfg transition hover:opacity-90"
        >
          New research
        </button>
      </div>

      {/* Answer hero */}
      {answer && (
        <Card className="mb-5 overflow-hidden">
          <div className="border-l-4 border-accent p-5">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-accent">
                Answer
              </span>
              <Badge tone={confidenceTone(session.overall_confidence)}>
                {pct(session.overall_confidence)} confidence
              </Badge>
            </div>
            <p className="text-[15px] leading-relaxed text-text">{answer}</p>
            {session.answer?.remaining_uncertainty && (
              <p className="mt-3 text-sm text-muted">
                <span className="font-medium text-warning">Uncertainty: </span>
                {session.answer.remaining_uncertainty}
              </p>
            )}
          </div>
        </Card>
      )}

      {/* Stat strip */}
      <Card className="mb-5 p-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat
            label="Confidence"
            value={pct(session.overall_confidence)}
            tone={confidenceTone(session.overall_confidence)}
          />
          <Stat label="Iterations" value={session.iterations} />
          <Stat label="Sources" value={session.sources.length} tone="info" />
          <Stat label="Verified claims" value={session.claims.length} tone="accent" />
          <Stat
            label="Docs downloaded"
            value={session.documents_downloaded}
            tone="info"
          />
        </div>
        {session.stop_reason && (
          <p className="mt-4 border-t border-border pt-3 text-xs text-muted">
            <span className="font-medium text-text">Stopped: </span>
            {session.stop_reason}
          </p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
        {/* Main: tabs */}
        <div>
          <div className="mb-4 flex flex-wrap gap-1 rounded-xl border border-border bg-surface p-1">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={
                  "flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition " +
                  (tab === t.key
                    ? "bg-accent text-accentfg"
                    : "text-muted hover:text-text")
                }
              >
                {t.label}
                {t.count != null && (
                  <span
                    className={
                      "rounded-full px-1.5 text-[11px] tabular-nums " +
                      (tab === t.key ? "bg-black/15" : "bg-surface2")
                    }
                  >
                    {t.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          <Card className="p-5">
            {tab === "report" && <ReportView report={session.report} />}
            {tab === "findings" && <FindingList findings={session.findings} />}
            {tab === "claims" && <ClaimList claims={session.claims} />}
            {tab === "sources" && <SourceList sources={session.sources} />}
            {tab === "contradictions" && (
              <ContradictionList items={session.contradictions} />
            )}
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-5">
          <ConfidencePanel confidence={session.confidence} />
          {session.open_questions.length > 0 && (
            <Card className="p-5">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">
                Open questions
              </h3>
              <ul className="space-y-2 text-sm text-text">
                {session.open_questions.map((q, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-accent">?</span>
                    {q}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
