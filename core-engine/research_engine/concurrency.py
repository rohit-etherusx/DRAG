"""Bounded concurrency (Layer 7 infrastructure).

The research loop's slow stages are I/O-bound — provider searches, document
downloads, and LLM claim-extraction calls each spend almost all their time
waiting on the network, during which CPython releases the GIL. Running them on a
small thread pool therefore delivers real wall-clock parallelism without any of
the complexity of rewriting the synchronous provider interfaces to async.

This module exposes exactly one primitive, :func:`parallel_map`, deliberately
kept tiny and free of research logic (``ARCHITECTURE.md``: infrastructure holds
no research knowledge). Two properties make it safe to build the deterministic
agent loop on top of:

* **Order-preserving.** The result list is aligned to the input list regardless
  of the order in which workers finish, so callers can merge results into the
  single-source-of-truth :class:`ResearchState` sequentially and reproducibly.
* **Bounded.** Concurrency never exceeds ``max_workers`` (and never exceeds the
  number of items), so a run cannot open an unbounded number of provider
  connections. ``max_workers <= 1`` runs fully sequentially — identical results,
  no threads — which keeps offline/unit runs simple.

Worker functions must be *total* (return a value rather than raise) and must not
mutate shared state; callers own the sequential merge that follows.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    fn: Callable[[T], R], items: Iterable[T], max_workers: int = 1
) -> List[R]:
    """Apply ``fn`` to every item, concurrently, preserving input order.

    Runs on at most ``max_workers`` threads (further capped by the item count).
    With one worker — or one item — it degrades to a plain sequential
    comprehension, so behaviour and results are identical to the non-threaded
    path. Exceptions from ``fn`` propagate on result collection; give ``fn`` its
    own error handling when partial failure must not abort the batch.
    """
    materialized = list(items)
    if not materialized:
        return []
    workers = max(1, min(int(max_workers), len(materialized)))
    if workers == 1:
        return [fn(item) for item in materialized]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # ThreadPoolExecutor.map yields results in submission (input) order.
        return list(executor.map(fn, materialized))


__all__ = ["parallel_map"]
