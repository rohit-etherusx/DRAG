"""Research planner.

Understands the research question *before* any searching (``OBJECTIVE.md``
module 1). The planner turns the raw user input — a broad topic or a direct
question — into a structured :class:`ResearchPlan`: a research objective,
focused subquestions with targeted search queries, expected entities /
evidence types / source types, a scope statement, and exclusion criteria.

Two strategies produce the plan:

* an **LLM planner** (when a model is configured) that returns the plan as
  strict JSON — this is a genuinely semantic task, so it is one of the few
  places an LLM is justified;
* a **deterministic planner** that detects question-shaped input, extracts the
  underlying subject, and decomposes into targeted subquestions for questions
  or domain-agnostic facets for topics. It is the offline default and the
  fallback whenever the LLM output is unusable, keeping planning reproducible.

The planner also derives the executable :class:`TaskGraph` from the plan (one
collection task per subquestion converging on a synthesis task) and generates
deterministic follow-up queries for the research loop.
"""
from __future__ import annotations

from research_engine.domain.models import (
    ResearchPlan,
    ResearchRequest,
    SubQuestion,
    Task,
    TaskKind,
)
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.taskgraph.graph import TaskGraph
from research_engine.utils import keywords, parse_json_object, string_list

_log = get_logger("planner")

#: Interrogative openers that mark question-shaped input.
_QUESTION_STARTERS = {
    "what", "why", "how", "when", "where", "which", "who", "whom", "whose",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "should",
    "would", "will", "shall", "may", "might", "has", "have", "had",
}

#: Words stripped from the front of a question to recover its subject.
_SUBJECT_NOISE = _QUESTION_STARTERS | {
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "about", "between",
    "there", "it", "its", "and", "or", "not", "any", "some", "many", "much",
}

#: Domain-agnostic facets used to decompose a broad *topic*.
_TOPIC_FACETS = [
    ("What is {topic}, and how is it defined?", "{topic} overview definition"),
    ("How did {topic} originate and develop?", "{topic} history background"),
    ("What are the key concepts and components of {topic}?",
     "{topic} key concepts components"),
    ("What is the current state of {topic}?",
     "{topic} current state developments"),
    ("What challenges and open problems exist in {topic}?",
     "{topic} challenges open problems"),
    ("What are the applications and impact of {topic}?",
     "{topic} applications impact"),
    ("What future directions are expected for {topic}?",
     "{topic} future directions"),
]

_MAX_SUBQUESTIONS = 7
_MAX_QUERIES_PER_SUBQUESTION = 2


class ResearchPlanner:
    """Builds a :class:`ResearchPlan` (and its task graph) from a request."""

    def __init__(self, llm: LLMProvider | None = None, attempts: int = 2) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)

    # -- planning ----------------------------------------------------------

    def plan(self, request: ResearchRequest) -> ResearchPlan:
        question = request.topic.strip()
        if not question:
            raise ValueError("research question must not be empty")
        limit = max(1, min(request.max_subtopics, _MAX_SUBQUESTIONS))

        if self._llm is not None and self._llm.available:
            plan = self._llm_plan(question, limit)
            if plan is not None:
                return plan
            _log.warning("LLM plan unusable; falling back to deterministic planner")
        return self._deterministic_plan(question, limit)

    def tasks_for(self, plan: ResearchPlan) -> TaskGraph:
        """Derive the executable task graph from a plan."""
        graph = TaskGraph()
        collect_ids: list[str] = []
        for index, subquestion in enumerate(plan.subquestions, start=1):
            task_id = f"collect-{index}"
            graph.add(
                Task(
                    id=task_id,
                    description=f"Collect evidence: {subquestion.question}",
                    kind=TaskKind.COLLECT,
                    query=subquestion.question,
                    subquestion_id=subquestion.id,
                )
            )
            collect_ids.append(task_id)
        graph.add(
            Task(
                id="synthesize-1",
                description=f"Synthesize an answer to: {plan.objective}",
                kind=TaskKind.SYNTHESIZE,
                query=plan.question,
                depends_on=collect_ids,
            )
        )
        return graph

    def follow_up_queries(
        self, plan: ResearchPlan, subquestion: SubQuestion, iteration: int
    ) -> list[str]:
        """Deterministic reformulations for a research-loop iteration.

        When evidence for a subquestion is missing or weak, the loop retries
        retrieval with differently-angled queries rather than repeating the
        ones that already failed.
        """
        angles = ["evidence", "explained", "research", "analysis"]
        angle = angles[(iteration - 2) % len(angles)]  # iteration 2 -> "evidence"
        base = " ".join(keywords(subquestion.question, limit=6)) or plan.subject
        queries = [f"{base} {angle}"]
        if plan.subject and plan.subject.lower() not in base.lower():
            queries.append(f"{plan.subject} {angle}")
        return queries[:_MAX_QUERIES_PER_SUBQUESTION]

    # -- deterministic strategy --------------------------------------------

    def _deterministic_plan(self, question: str, limit: int) -> ResearchPlan:
        is_question = _is_question(question)
        subject = _extract_subject(question) if is_question else question.rstrip("?. ")

        if is_question:
            subquestions = _question_subquestions(question, subject, limit)
            objective = f"Answer the question: {question.rstrip('?')}?"
            evidence_types = ["definitions", "facts", "numerical data",
                              "limitations", "counter-evidence"]
        else:
            subquestions = _topic_subquestions(subject, limit)
            objective = f"Build a verified, multi-angle understanding of {subject}."
            evidence_types = ["definitions", "facts", "dates", "numerical data",
                              "limitations"]

        return ResearchPlan(
            objective=objective,
            question=question,
            is_question=is_question,
            subject=subject,
            subquestions=subquestions,
            expected_entities=keywords(subject, limit=6),
            expected_evidence_types=evidence_types,
            expected_source_types=["encyclopedia", "peer-reviewed", "open web"],
            scope=(
                f"Evidence that helps answer '{question}'"
                if is_question
                else f"Evidence describing {subject} and its context"
            ),
            exclusion_criteria=[],
            planner="deterministic",
        )

    # -- LLM strategy --------------------------------------------------------

    def _llm_plan(self, question: str, limit: int) -> ResearchPlan | None:
        prompt = (
            f"You are planning autonomous research for the input below. Understand "
            f"it before searching: decide whether it is a direct question or a broad "
            f"topic, extract the core subject, and decompose it into at most {limit} "
            f"focused subquestions whose answers together satisfy the input. For "
            f"each subquestion give up to {_MAX_QUERIES_PER_SUBQUESTION} short "
            f"search-engine queries.\n\n"
            f"INPUT: {question}\n\n"
            f"Return ONLY a JSON object with keys:\n"
            f'  "objective": one sentence stating what the research must establish,\n'
            f'  "is_question": boolean,\n'
            f'  "subject": the core subject as a short phrase,\n'
            f'  "subquestions": array of {{"question": string, '
            f'"search_queries": array of strings}},\n'
            f'  "expected_entities": array of strings,\n'
            f'  "expected_evidence_types": array of strings,\n'
            f'  "expected_source_types": array of strings,\n'
            f'  "scope": one sentence stating what is in scope,\n'
            f'  "exclusion_criteria": array of terms indicating an irrelevant '
            f"result.\nNo prose."
        )
        for _ in range(self._attempts):
            raw = self._llm.generate(
                prompt, system="You produce structured research plans as strict JSON."
            )
            plan = _parse_plan(raw, question, limit)
            if plan is not None:
                return plan
        return None


# -- deterministic helpers ---------------------------------------------------


def _is_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    first = stripped.split(maxsplit=1)[0].lower() if stripped else ""
    return first in _QUESTION_STARTERS


def _extract_subject(question: str) -> str:
    """Recover the core subject phrase from a question.

    Drops leading interrogative/auxiliary words, then returns the remaining
    phrase. "What are the risks of X to Y?" -> "risks of X to Y".
    """
    words = question.strip().rstrip("?.!").split()
    start = 0
    for index, word in enumerate(words):
        if word.lower().strip(",") not in _SUBJECT_NOISE:
            start = index
            break
    else:
        return question.strip().rstrip("?.!")
    subject = " ".join(words[start:])
    return subject or question.strip().rstrip("?.!")


def _question_subquestions(
    question: str, subject: str, limit: int
) -> list[SubQuestion]:
    """Subquestions targeted at *answering* a question (not surveying a topic)."""
    core = question.rstrip("?. ")
    candidates = [
        (
            f"What is {subject}, and what background is needed to answer the question?",
            [f"{subject} overview definition"],
        ),
        (
            f"{core}?",
            [core, " ".join(keywords(question, limit=6))],
        ),
        (
            f"What evidence supports or contradicts an answer to: {core}?",
            [f"{subject} evidence analysis", f"{subject} criticism limitations"],
        ),
        (
            f"What context, factors, or recent developments affect {subject}?",
            [f"{subject} factors developments"],
        ),
        (
            f"What do authoritative sources conclude about {subject}?",
            [f"{subject} research findings"],
        ),
    ]
    return _to_subquestions(candidates[:limit])


def _topic_subquestions(topic: str, limit: int) -> list[SubQuestion]:
    """Domain-agnostic facet decomposition for a broad topic."""
    candidates = [
        (facet.format(topic=topic), [query.format(topic=topic)])
        for facet, query in _TOPIC_FACETS[:limit]
    ]
    return _to_subquestions(candidates)


def _to_subquestions(candidates: list[tuple[str, list[str]]]) -> list[SubQuestion]:
    subquestions: list[SubQuestion] = []
    for index, (text, queries) in enumerate(candidates, start=1):
        cleaned = [q.strip() for q in queries if q.strip()]
        # De-duplicate queries while preserving order.
        seen: set[str] = set()
        unique = [q for q in cleaned if not (q.lower() in seen or seen.add(q.lower()))]
        subquestions.append(
            SubQuestion(
                id=f"sq-{index}",
                question=text,
                search_queries=unique[:_MAX_QUERIES_PER_SUBQUESTION],
            )
        )
    return subquestions


# -- LLM response parsing ------------------------------------------------------


def _parse_plan(raw: str | None, question: str, limit: int) -> ResearchPlan | None:
    data = parse_json_object(raw)
    if data is None:
        return None

    subquestions: list[SubQuestion] = []
    for index, item in enumerate(data.get("subquestions", [])[:limit], start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("question", "")).strip()
        if not text:
            continue
        queries = string_list(
            item.get("search_queries", []), _MAX_QUERIES_PER_SUBQUESTION
        ) or [text]
        subquestions.append(
            SubQuestion(id=f"sq-{index}", question=text, search_queries=queries)
        )
    if not subquestions:
        return None  # a plan with nothing to research is unusable

    objective = str(data.get("objective", "")).strip() or f"Research: {question}"
    subject = str(data.get("subject", "")).strip() or question.rstrip("?. ")
    return ResearchPlan(
        objective=objective,
        question=question,
        is_question=bool(data.get("is_question", _is_question(question))),
        subject=subject,
        subquestions=subquestions,
        expected_entities=string_list(data.get("expected_entities", []), 12),
        expected_evidence_types=string_list(data.get("expected_evidence_types", []), 8),
        expected_source_types=string_list(data.get("expected_source_types", []), 8),
        scope=str(data.get("scope", "")).strip(),
        exclusion_criteria=string_list(data.get("exclusion_criteria", []), 12),
        planner="llm",
    )
