"""Shared utility for content-hash-based LLM ranking cache validation."""

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# --- Hash computation ---


def compute_items_hash(items: list[dict]) -> str:
    """Deterministic hash of the items list sent to Gemini.

    Returns a short hex digest that can be stored alongside cached results
    to detect when input data has changed and re-ranking is needed.
    """
    raw = json.dumps(items, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- Reranking state tracking ---

_reranking_lock = threading.Lock()
_reranking_sources: set[str] = set()


def start_reranking(source: str) -> bool:
    """Mark source as reranking. Returns False if already in progress."""
    with _reranking_lock:
        if source in _reranking_sources:
            return False
        _reranking_sources.add(source)
        return True


def finish_reranking(source: str):
    """Clear reranking flag for a source."""
    with _reranking_lock:
        _reranking_sources.discard(source)


def is_reranking(source: str) -> bool:
    with _reranking_lock:
        return source in _reranking_sources


# --- Post-sync background reranking ---


def rerank_stale_sources():
    """Check all ranking sources and re-rank any with stale caches.

    Called after sync completes to pre-compute fresh rankings.
    """
    from routers.drive_api import rerank_drive
    from routers.gmail import rerank_email
    from routers.news import rerank_news
    from routers.notion_api import rerank_notion
    from routers.priorities import rerank_priorities
    from routers.ramp_api import rerank_ramp
    from routers.slack_api import rerank_slack

    sources = [
        ("email", rerank_email),
        ("slack", rerank_slack),
        ("notion", rerank_notion),
        ("news", rerank_news),
        ("drive", rerank_drive),
        ("ramp", rerank_ramp),
        ("priorities", rerank_priorities),
    ]

    updated = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(fn): name for name, fn in sources}
        for f in as_completed(futs):
            name = futs[f]
            try:
                if f.result():
                    updated.append(name)
            except Exception:
                logger.warning("Background rerank failed for %s", name, exc_info=True)

    if updated:
        logger.info("Post-sync rerank updated: %s", ", ".join(updated))
    else:
        logger.info("Post-sync rerank: all caches still valid")
