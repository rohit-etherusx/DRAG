/**
 * TypeScript mirror of the engine's serialized session and progress events.
 *
 * These shapes track `serialize_session` (storage.py) and the `ProgressEvent`
 * dataclasses (progress.py). Enums serialize to their string values. Only the
 * fields the UI reads are typed; the payloads may carry more (that is fine).
 */

export type VerificationStatus =
  | "unverified"
  | "corroborated"
  | "single_source"
  | "contradicted";

export type ClaimType =
  | "fact"
  | "definition"
  | "numerical"
  | "date"
  | "limitation"
  | "assumption"
  | "method"
  | "open_question";

export interface Source {
  id: string;
  title: string;
  provider: string;
  locator: string;
  retrieved_at: string;
  domain: string;
  authority: number;
  authority_tier: string;
}

export interface Claim {
  id: string;
  text: string;
  claim_type: ClaimType;
  entities: string[];
  source_ids: string[];
  subquestion_ids: string[];
  supporting_sources: number;
  independent_domains: number;
  agreement: number;
  contradicts: string[];
  status: VerificationStatus;
  confidence: number;
  confidence_explanation: string;
}

export interface Finding {
  id: string;
  statement: string;
  claim_ids: string[];
  subquestion_id: string;
  confidence: number;
  confidence_explanation: string;
}

export interface Hypothesis {
  id: string;
  statement: string;
  claim_ids: string[];
  confidence: number;
}

export interface Contradiction {
  id: string;
  description: string;
  claim_ids: string[];
}

export interface Answer {
  text: string;
  reasoning: string;
  confidence: number;
  claim_ids: string[];
  remaining_uncertainty: string;
}

export interface ConfidenceReport {
  score: number;
  independent_sources: number;
  authority: number;
  agreement: number;
  coverage: number;
  contradictions: number;
  evidence_quality: number;
  specificity: number;
  explanation: string;
}

export interface ResearchReport {
  topic: string;
  executive_summary: string;
  markdown: string;
  file_path: string;
}

export interface SubQuestion {
  id: string;
  question: string;
  search_queries: string[];
}

export interface ResearchPlan {
  objective: string;
  question: string;
  is_question: boolean;
  subject: string;
  subquestions: SubQuestion[];
  scope: string;
  planner: string;
}

export interface ResearchRequest {
  topic: string;
  max_subtopics: number;
  documents_per_query: number;
}

export interface ResearchSession {
  id: string;
  request: ResearchRequest;
  status: string;
  created_at: string;
  completed_at: string;
  provider_info: Record<string, string>;
  plan: ResearchPlan | null;
  sources: Source[];
  claims: Claim[];
  findings: Finding[];
  hypotheses: Hypothesis[];
  contradictions: Contradiction[];
  direct_answer: string;
  answer: Answer | null;
  open_questions: string[];
  suggestions: string[];
  confidence: ConfidenceReport | null;
  overall_confidence: number;
  stop_reason: string;
  iterations: number;
  candidates_evaluated: number;
  candidates_rejected: number;
  documents_downloaded: number;
  report: ResearchReport | null;
}

/* ---- Progress events (SSE) -------------------------------------------- */

export interface BaseEvent {
  type: string;
}
export interface SessionStarted extends BaseEvent {
  type: "SessionStarted";
  topic: string;
  session_id: string;
}
export interface PlanReady extends BaseEvent {
  type: "PlanReady";
  objective: string;
  subquestions: [string, string][];
  planner: string;
}
export interface IterationStarted extends BaseEvent {
  type: "IterationStarted";
  iteration: number;
  task_count: number;
  source: string;
}
export interface SearchTaskDone extends BaseEvent {
  type: "SearchTaskDone";
  iteration: number;
  task_id: string;
  query: string;
  subquestion_id: string;
  candidates: number;
  accepted: number;
  documents: number;
  passages: number;
  failed: boolean;
}
export interface ExtractionDone extends BaseEvent {
  type: "ExtractionDone";
  iteration: number;
  documents: number;
  claims: number;
}
export interface VerificationDone extends BaseEvent {
  type: "VerificationDone";
  iteration: number;
  claims: number;
  corroborated: number;
  unsupported: number;
}
export interface IterationDone extends BaseEvent {
  type: "IterationDone";
  iteration: number;
  novelty: number;
  knowledge_gain: number;
  confidence: number;
  new_gaps: number;
  open_gaps: number;
}
export interface Stopping extends BaseEvent {
  type: "Stopping";
  iteration: number;
  reason: string;
}
export interface AnswerReady extends BaseEvent {
  type: "AnswerReady";
  text: string;
  confidence: number;
}
export interface ReportReady extends BaseEvent {
  type: "ReportReady";
  markdown: string;
  path: string;
}
export interface SessionComplete extends BaseEvent {
  type: "SessionComplete";
  session: ResearchSession;
}
export interface ErrorEvent extends BaseEvent {
  type: "Error";
  status: number;
  detail: string;
}
export interface DoneEvent extends BaseEvent {
  type: "Done";
}

export type ProgressEvent =
  | SessionStarted
  | PlanReady
  | IterationStarted
  | SearchTaskDone
  | ExtractionDone
  | VerificationDone
  | IterationDone
  | Stopping
  | AnswerReady
  | ReportReady
  | SessionComplete
  | ErrorEvent
  | DoneEvent;

export interface ResearchParams {
  topic: string;
  max_subtopics?: number;
  documents_per_query?: number;
  max_iterations?: number;
  offline: boolean;
  no_llm: boolean;
}
