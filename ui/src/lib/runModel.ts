/**
 * Derives a live view-model from the ordered stream of progress events.
 *
 * Pure and idempotent: given the events accumulated so far, it reconstructs the
 * current state of the run (plan, per-iteration activity, running totals, latest
 * confidence, phase). The UI re-derives on every new event — no imperative state
 * to keep in sync.
 */
import type {
  ProgressEvent,
  IterationDone,
  ExtractionDone,
  VerificationDone,
  SearchTaskDone,
} from "../types/domain";

export interface IterationView {
  iteration: number;
  source: string;
  taskCount: number;
  tasks: SearchTaskDone[];
  extraction?: ExtractionDone;
  verification?: VerificationDone;
  summary?: IterationDone;
}

export interface RunModel {
  topic: string;
  planObjective: string;
  planner: string;
  subquestions: { id: string; question: string }[];
  iterations: IterationView[];
  phase: string;
  confidence: number;
  answerPreview: string;
  stopReason: string;
  totals: {
    searchTasks: number;
    documents: number;
    claims: number;
    corroborated: number;
    sources: number;
  };
}

export function deriveRun(events: ProgressEvent[]): RunModel {
  const model: RunModel = {
    topic: "",
    planObjective: "",
    planner: "",
    subquestions: [],
    iterations: [],
    phase: "Starting…",
    confidence: 0,
    answerPreview: "",
    stopReason: "",
    totals: { searchTasks: 0, documents: 0, claims: 0, corroborated: 0, sources: 0 },
  };
  const iterMap = new Map<number, IterationView>();

  const iter = (n: number): IterationView => {
    let v = iterMap.get(n);
    if (!v) {
      v = { iteration: n, source: "", taskCount: 0, tasks: [] };
      iterMap.set(n, v);
      model.iterations.push(v);
    }
    return v;
  };

  for (const ev of events) {
    switch (ev.type) {
      case "SessionStarted":
        model.topic = ev.topic;
        model.phase = "Planning the investigation…";
        break;
      case "PlanReady":
        model.planObjective = ev.objective;
        model.planner = ev.planner;
        model.subquestions = ev.subquestions.map(([id, question]) => ({ id, question }));
        model.phase = "Plan ready — gathering evidence…";
        break;
      case "IterationStarted": {
        const v = iter(ev.iteration);
        v.source = ev.source;
        v.taskCount = ev.task_count;
        model.phase = `Iteration ${ev.iteration} · searching ${ev.task_count} angle(s)…`;
        break;
      }
      case "SearchTaskDone": {
        iter(ev.iteration).tasks.push(ev);
        model.totals.searchTasks += 1;
        model.totals.documents += ev.documents;
        model.totals.sources += ev.accepted;
        model.phase = `Iteration ${ev.iteration} · read “${ev.query}”`;
        break;
      }
      case "ExtractionDone": {
        iter(ev.iteration).extraction = ev;
        model.totals.claims += ev.claims;
        model.phase = `Iteration ${ev.iteration} · extracted ${ev.claims} claim(s)…`;
        break;
      }
      case "VerificationDone": {
        iter(ev.iteration).verification = ev;
        model.totals.corroborated = ev.corroborated;
        model.phase = `Iteration ${ev.iteration} · verifying claims…`;
        break;
      }
      case "IterationDone": {
        iter(ev.iteration).summary = ev;
        model.confidence = ev.confidence;
        model.phase = `Iteration ${ev.iteration} complete · confidence ${Math.round(
          ev.confidence * 100,
        )}%`;
        break;
      }
      case "Stopping":
        model.stopReason = ev.reason;
        model.phase = "Synthesizing the answer…";
        break;
      case "AnswerReady":
        model.answerPreview = ev.text;
        model.confidence = ev.confidence;
        model.phase = "Answer ready · writing report…";
        break;
      case "ReportReady":
        model.phase = "Report ready.";
        break;
      default:
        break;
    }
  }

  return model;
}
