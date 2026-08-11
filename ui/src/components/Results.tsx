import { useState } from "react";
import type { ResearchSession } from "../types/domain";
import { cn, confidenceLabel, confidenceTone, pct } from "../lib/format";
import { Badge, Card, StatBox } from "./ui/primitives";
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
    { key: "report", label: "report" },
    { key: "findings", label: "findings", count: session.findings.length },
    { key: "claims", label: "claims", count: session.claims.length },
    { key: "sources", label: "sources", count: session.sources.length },
    {
      key: "contradictions",
      label: "contradictions",
      count: session.contradictions.length,
    },
  ];
  const [tab, setTab] = useState<TabKey>("report");
  const answer = session.answer?.text || session.direct_answer;
  const isQuestion = session.plan?.is_question ?? false;

  return (
    <div className="rise mx-auto w-full max-w-6xl">
      {/* Masthead */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-[11px] font-bold lowercase tracking-widest text-success">
            <span className="inline-block h-2 w-2 border border-border bg-success" />
            research complete
          </div>
          <h2 className="display display-sm text-2xl sm:text-3xl">
            {session.request.topic}
          </h2>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="btn-ink shrink-0 px-5 py-2.5 text-sm lowercase"
        >
          new research
        </button>
      </div>

      {/* The answer — the product of the run, pinned to the page. */}
      {answer && (
        <div className="sheet lift-8 relative mb-8 mt-3 p-6 pt-7">
          <span className="tape" aria-hidden="true" />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold lowercase tracking-widest text-accent">
              {isQuestion ? "direct answer" : "answer"}
            </span>
            <Badge tone={confidenceTone(session.overall_confidence)}>
              {pct(session.overall_confidence)}{" "}
              {confidenceLabel(session.overall_confidence)} confidence
            </Badge>
          </div>
          <p className="font-serif text-[17px] leading-relaxed">{answer}</p>
          {session.answer?.remaining_uncertainty && (
            <p className="mt-4 border-t-[1.5px] border-dashed border-border pt-3 text-xs leading-relaxed text-muted">
              <span className="font-bold lowercase text-warning">
                remaining uncertainty ·{" "}
              </span>
              {session.answer.remaining_uncertainty}
            </p>
          )}
        </div>
      )}

      {/* Headline measurements */}
      <div className="mb-8 grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-5">
        <StatBox
          value={pct(session.overall_confidence)}
          label="overall confidence"
          sub={confidenceLabel(session.overall_confidence)}
        />
        <StatBox
          value={session.iterations}
          label="loop iterations"
          sub="search passes"
        />
        <StatBox
          value={session.sources.length}
          label="independent sources"
          sub={`${session.documents_downloaded} docs downloaded`}
        />
        <StatBox
          value={session.claims.length}
          label="verified claims"
          sub={`${session.evidence.length} evidence passages`}
        />
        <StatBox
          value={session.candidates_rejected}
          label="candidates rejected"
          sub={`of ${session.candidates_evaluated} evaluated`}
        />
      </div>

      {session.stop_reason && (
        <p className="mb-8 border-y-[1.5px] border-border py-2.5 text-[11px] lowercase text-muted">
          <span className="font-bold text-text">research stopped because · </span>
          {session.stop_reason}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_330px]">
        <div className="min-w-0">
          {/* Segmented control: one square cell per view. */}
          <div className="mb-5 flex flex-wrap border-[1.5px] border-border bg-surface">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                aria-current={tab === t.key}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 border-r-[1.5px] border-border px-3 py-2.5 text-xs font-bold lowercase transition last:border-r-0",
                  tab === t.key
                    ? "bg-text text-surface"
                    : "text-muted hover:bg-surface2 hover:text-text",
                )}
              >
                {t.label}
                {t.count != null && (
                  <span
                    className={cn(
                      "border px-1 text-[10px] tabular-nums",
                      tab === t.key
                        ? "border-surface/40 text-surface"
                        : "border-border text-muted",
                    )}
                  >
                    {t.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          <Card lift={4} className="p-5 sm:p-6">
            {tab === "report" && <ReportView report={session.report} />}
            {tab === "findings" && <FindingList findings={session.findings} />}
            {tab === "claims" && <ClaimList claims={session.claims} />}
            {tab === "sources" && <SourceList sources={session.sources} />}
            {tab === "contradictions" && (
              <ContradictionList items={session.contradictions} />
            )}
          </Card>
        </div>

        {/* Margin notes */}
        <div className="space-y-6">
          <ConfidencePanel confidence={session.confidence} />

          {session.open_questions.length > 0 && (
            <Card lift={2} className="p-5">
              <h3 className="mb-3 flex items-center gap-2 text-[11px] font-bold lowercase tracking-widest text-muted">
                <span className="inline-block h-2.5 w-2.5 border-[1.5px] border-border bg-coral" />
                open questions
              </h3>
              <ul className="space-y-2.5 text-[13px] leading-snug">
                {session.open_questions.map((q, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="shrink-0 font-bold text-accent">?</span>
                    {q}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {session.knowledge_gaps.length > 0 && (
            <Card lift={2} className="p-5">
              <h3 className="mb-3 flex items-center gap-2 text-[11px] font-bold lowercase tracking-widest text-muted">
                <span className="inline-block h-2.5 w-2.5 border-[1.5px] border-border bg-coral" />
                knowledge gaps
              </h3>
              <ul className="space-y-2.5 text-[13px] leading-snug">
                {session.knowledge_gaps.slice(0, 8).map((g) => (
                  <li key={g.id} className="flex gap-2">
                    <span
                      className={cn(
                        "mt-px shrink-0 border px-1 text-[10px] font-bold lowercase",
                        g.investigated
                          ? "border-success text-success"
                          : "border-warning text-warning",
                      )}
                      title={
                        g.investigated
                          ? "investigated during the run"
                          : "still open when research stopped"
                      }
                    >
                      {g.investigated ? "closed" : "open"}
                    </span>
                    <span className="text-muted">{g.description}</span>
                  </li>
                ))}
              </ul>
              {session.knowledge_gaps.length > 8 && (
                <p className="mt-3 text-[11px] lowercase text-muted">
                  +{session.knowledge_gaps.length - 8} more in the session snapshot
                </p>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
