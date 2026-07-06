"""Tests for v0.6 bounded concurrency.

Two guarantees underpin the parallel acquisition loop:

* :func:`parallel_map` preserves input order and stays within its worker bound,
  so results can be merged into the research state deterministically;
* a full offline run produces **identical** knowledge whether acquisition runs
  sequentially (``max_workers=1``) or concurrently — parallelism must never
  change what the engine learns, only how fast it learns it.
"""
import os
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine.concurrency import parallel_map
from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchRequest
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.providers.offline import NullLLMProvider, OfflineSearchProvider
from research_engine.storage.storage import SessionStorage


class ParallelMapTests(unittest.TestCase):
    def test_preserves_input_order(self):
        # Even though larger inputs would finish "first" under threads, the
        # result list must stay aligned to the input order.
        items = list(range(50))
        result = parallel_map(lambda x: x * x, items, max_workers=8)
        self.assertEqual(result, [x * x for x in items])

    def test_empty_input_returns_empty(self):
        self.assertEqual(parallel_map(lambda x: x, [], max_workers=8), [])

    def test_single_worker_runs_sequentially(self):
        calls = []
        parallel_map(calls.append, [1, 2, 3], max_workers=1)
        self.assertEqual(calls, [1, 2, 3])

    def test_worker_count_never_exceeds_items_or_bound(self):
        # One item, many allowed workers → still one invocation, correct result.
        self.assertEqual(parallel_map(lambda x: x + 1, [41], max_workers=16), [42])

    def test_exceptions_propagate(self):
        def boom(x):
            if x == 2:
                raise ValueError("boom")
            return x

        with self.assertRaises(ValueError):
            parallel_map(boom, [1, 2, 3], max_workers=4)


def _run(tmp, max_workers, topic="photosynthesis"):
    config = EngineConfig(
        output_dir=os.path.join(tmp, "report"),
        sessions_dir=os.path.join(tmp, "sessions"),
        max_workers=max_workers,
    )
    orchestrator = ResearchOrchestrator(
        config=config,
        search_provider=OfflineSearchProvider(),
        llm_provider=NullLLMProvider(),
        storage=SessionStorage(config.output_dir, config.sessions_dir),
    )
    return orchestrator.run(
        ResearchRequest(
            topic=topic,
            max_subtopics=config.max_subtopics,
            documents_per_query=config.documents_per_query,
        )
    )


class AcquisitionDeterminismTests(unittest.TestCase):
    def test_parallel_matches_sequential(self):
        with tempfile.TemporaryDirectory() as tmp1, \
                tempfile.TemporaryDirectory() as tmp2:
            seq = _run(tmp1, max_workers=1)
            par = _run(tmp2, max_workers=6)

        # The knowledge model must be byte-identical in content and order.
        self.assertEqual(
            [c.text for c in seq.claims], [c.text for c in par.claims]
        )
        self.assertEqual(
            [sorted(c.source_ids) for c in seq.claims],
            [sorted(c.source_ids) for c in par.claims],
        )
        self.assertEqual(
            [e.passage for e in seq.evidence], [e.passage for e in par.evidence]
        )
        self.assertEqual(
            sorted(s.id for s in seq.sources),
            sorted(s.id for s in par.sources),
        )
        self.assertEqual(seq.overall_confidence, par.overall_confidence)


class LlmTimeoutConfigTests(unittest.TestCase):
    def test_provider_stores_timeout_and_retries(self):
        from research_engine.providers.openrouter_provider import OpenRouterProvider

        provider = OpenRouterProvider(timeout_seconds=12.5, max_retries=1)
        self.assertEqual(provider.timeout_seconds, 12.5)
        self.assertEqual(provider.max_retries, 1)

    def test_config_parses_performance_knobs_from_env(self):
        keys = {
            "RE_MAX_WORKERS": "3",
            "RE_LLM_TIMEOUT_SECONDS": "30",
            "RE_LLM_MAX_RETRIES": "5",
        }
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update(keys)
            cfg = EngineConfig.from_env()
            self.assertEqual(cfg.max_workers, 3)
            self.assertEqual(cfg.llm_timeout_seconds, 30.0)
            self.assertEqual(cfg.llm_max_retries, 5)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
