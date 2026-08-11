import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ResearchReport } from "../../types/domain";
import { EmptyState } from "../ui/primitives";

export function ReportView({ report }: { report: ResearchReport | null }) {
  const [copied, setCopied] = useState(false);

  if (!report || !report.markdown) {
    return <EmptyState>no report was produced for this run</EmptyState>;
  }

  const filename = `${report.topic || "report"}.md`.replace(/[^\w.-]+/g, "_");

  function copy() {
    navigator.clipboard?.writeText(report!.markdown).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => {
        /* clipboard blocked — the download button still works */
      },
    );
  }

  function download() {
    const blob = new Blob([report!.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      {/* Document strip: what this file is, and how to take it with you. */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-[1.5px] border-border bg-surface2 px-3 py-2">
        <span className="flex min-w-0 items-center gap-2 text-[11px] lowercase text-muted">
          <svg
            width="12"
            height="15"
            viewBox="0 0 40 50"
            className="shrink-0 text-border"
            aria-hidden="true"
          >
            <g stroke="currentColor" strokeWidth="3.5" strokeLinejoin="round">
              <path d="M2.5 2.5h23l12 12v33.5H2.5z" fill="var(--color-p-cream)" />
              <path d="M25.5 2.5v12h12" fill="none" />
            </g>
          </svg>
          <span className="truncate">{filename}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={copy}
            className="btn-paper px-2.5 py-1 text-[11px] lowercase"
          >
            {copied ? "✓ copied" : "copy markdown"}
          </button>
          <button
            type="button"
            onClick={download}
            className="btn-paper px-2.5 py-1 text-[11px] lowercase"
          >
            download .md
          </button>
        </span>
      </div>

      <article className="report-prose">
        <Markdown remarkPlugins={[remarkGfm]}>{report.markdown}</Markdown>
      </article>
    </div>
  );
}
