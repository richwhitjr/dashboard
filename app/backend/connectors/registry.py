"""Connector plugin registry — each connector self-registers with metadata."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConnectorInfo:
    id: str
    name: str
    description: str
    category: str  # "oauth" | "token" | "client_credentials" | "cli" | "local" | "none"
    secret_keys: list[str] = field(default_factory=list)
    help_steps: list[str] = field(default_factory=list)
    help_url: str | None = None
    sync_sources: list[str] = field(default_factory=list)
    default_enabled: bool = False
    # Dotted path to sync function, e.g. "connectors.slack.sync_slack_data"
    sync_fn: str | None = None
    # Dotted path to auth check function
    check_fn: str | None = None


REGISTRY: dict[str, ConnectorInfo] = {}


def register(info: ConnectorInfo):
    """Register a connector. Called at import time by each connector module."""
    REGISTRY[info.id] = info


def get_all() -> list[ConnectorInfo]:
    """Return all registered connectors."""
    return list(REGISTRY.values())


def get_enabled() -> list[ConnectorInfo]:
    """Return only enabled connectors (based on config.json + defaults)."""
    from app_config import get_connector_config

    config = get_connector_config()
    result = []
    for c in REGISTRY.values():
        entry = config.get(c.id, {})
        enabled = entry.get("enabled", c.default_enabled)
        if enabled:
            result.append(c)
    return result


def is_enabled(connector_id: str) -> bool:
    """Check if a specific connector is enabled."""
    from app_config import get_connector_config

    info = REGISTRY.get(connector_id)
    if not info:
        return False
    config = get_connector_config()
    entry = config.get(connector_id, {})
    return entry.get("enabled", info.default_enabled)


def get_by_id(connector_id: str) -> ConnectorInfo | None:
    return REGISTRY.get(connector_id)


def resolve_sync_fn(dotted_path: str):
    """Import and return the sync function from a dotted path like 'connectors.slack.sync_slack_data'."""
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid sync function path: {dotted_path}")
    module_path, fn_name = parts
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


def resolve_check_fn(dotted_path: str):
    """Import and return the auth check function from a dotted path."""
    return resolve_sync_fn(dotted_path)  # Same mechanism


def init_registry():
    """Import all connector modules to trigger their register() calls.

    Call this once at app startup.
    """
    # Each module calls register() at import time
    _modules = [
        "connectors._registrations",
    ]
    import importlib

    for mod in _modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            pass
