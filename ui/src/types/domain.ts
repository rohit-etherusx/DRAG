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
  evidence_ids: string[];
  source_ids: string[];
  subquestion_ids: string[];
  supporting_sources: number;
  independent_domains: number;
  agreement: number;
  contradicts: string[];
  status: VerificationStatus;
  confidence: number;
  confidence_explanation: string;
  /** Deterministic 0..1 importance to the objective (stamped by reasoning). */
  importance: number;
}

/** A relevant passage extracted from a document — a claim's provenance. */
export interface Evidence {
  id: string;
  passage: string;
  document_id: string;
  source_id: string;
  subquestion_id: string;
  relevance_score: number;
}

export type GapKind =
  | "missing_evidence"
  | "uncorroborated"
  | "missing_definition"
  | "missing_relationship"
  | "contradiction"
  | "missing_primary_source";

/** A piece of missing knowledge the curiosity engine discovered. */
export interface KnowledgeGap {
  id: string;
  kind: GapKind;
  description: string;
  suggested_query: string;
  subquestion_id: string;
  entity: string;
  priority: number;
  /** Whether the planner turned this gap into a search task. */
  investigated: boolean;
}

/** What one research-loop iteration contributed to the knowledge model. */
export interface IterationRecord {
  iteration: number;
  search_tasks: number;
  documents_downloaded: number;
  claims_before: number;
  claims_after: number;
  corroborated: number;
  novelty: number;
  knowledge_gain: number;
  confidence: number;
  gaps_open: number;
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
  evidence: Evidence[];
  claims: Claim[];
  findings: Finding[];
  hypotheses: Hypothesis[];
  contradictions: Contradiction[];
  direct_answer: string;
  answer: Answer | null;
  patterns: string[];
  missing_evidence: string[];
  open_questions: string[];
  suggestions: string[];
  confidence: ConfidenceReport | null;
  overall_confidence: number;
  /** Every gap curiosity discovered — investigated or still open. */
  knowledge_gaps: KnowledgeGap[];
  iteration_records: IterationRecord[];
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
