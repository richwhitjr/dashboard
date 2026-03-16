"""Lightweight change-version tracking for background agent writes.

In-memory version counter per entity type. The frontend polls GET /api/changes
every few seconds and invalidates React Query caches only when versions change.
"""

from fastapi import APIRouter

router = APIRouter(tags=["changes"])

_versions: dict[str, int] = {}


def bump(entity: str) -> None:
    """Increment the version counter for an entity type."""
    _versions[entity] = _versions.get(entity, 0) + 1


@router.get("/api/changes")
def get_changes() -> dict[str, int]:
    return _versions
