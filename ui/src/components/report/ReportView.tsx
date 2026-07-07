import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ResearchReport } from "../../types/domain";
import { EmptyState } from "../ui/primitives";

export function ReportView({ report }: { report: ResearchReport | null }) {
  if (!report || !report.markdown) {
    return <EmptyState>No report was produced for this run.</EmptyState>;
  }

  function download() {
    const blob = new Blob([report!.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report!.topic || "report"}.md`.replace(/[^\w.-]+/g, "_");
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div className="mb-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => navigator.clipboard?.writeText(report.markdown)}
          className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition hover:text-text"
        >
          Copy markdown
        </button>
        <button
          type="button"
          onClick={download}
          className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition hover:text-text"
        >
          Download .md
        </button>
      </div>
      <article className="report-prose">
        <Markdown remarkPlugins={[remarkGfm]}>{report.markdown}</Markdown>
      </article>
    </div>
  );
}
