"""Obsidian vault connector — reads local markdown files."""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Vault discovery ---


def get_vault_path() -> Path | None:
    """Return the Obsidian vault path.

    Checks config.json first, then auto-detects from Obsidian's own config.
    """
    # 1. Explicit config
    try:
        from app_config import load_config

        cfg = load_config()
        vault = cfg.get("connectors", {}).get("obsidian", {}).get("vault_path")
        if vault:
            p = Path(vault).expanduser()
            if p.is_dir():
                return p
    except Exception:
        pass

    # 2. Auto-detect from Obsidian app config
    obsidian_cfg = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if obsidian_cfg.exists():
        try:
            data = json.loads(obsidian_cfg.read_text())
            vaults = data.get("vaults", {})
            for vault_info in vaults.values():
                vault_path = vault_info.get("path")
                if vault_path:
                    p = Path(vault_path)
                    if p.is_dir():
                        return p
        except Exception:
            pass

    return None


def get_vault_name() -> str | None:
    """Return the vault directory name (used for obsidian:// URIs)."""
    vault = get_vault_path()
    return vault.name if vault else None


# --- Markdown parsing helpers ---


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata_dict, body_without_frontmatter)."""
    if not content.startswith("---"):
        return {}, content

    end = content.find("\n---", 3)
    if end == -1:
        return {}, content

    yaml_block = content[3:end].strip()
    body = content[end + 4 :].strip()

    # Simple key: value parsing (avoids yaml dependency)
    meta = {}
    for line in yaml_block.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                meta[key] = value
    return meta, body


def _extract_wiki_links(content: str) -> list[str]:
    """Extract [[wiki link]] targets from markdown content."""
    return re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content)


def _extract_tags(content: str, frontmatter: dict) -> list[str]:
    """Extract tags from both frontmatter and inline #tags."""
    tags = set()

    # Frontmatter tags
    fm_tags = frontmatter.get("tags", "")
    if fm_tags:
        for t in re.split(r"[,\s]+", fm_tags):
            t = t.strip().strip("#")
            if t:
                tags.add(t)

    # Inline #tags (not inside code blocks or URLs)
    for match in re.finditer(r"(?:^|\s)#([a-zA-Z][a-zA-Z0-9_/-]*)", content):
        tags.add(match.group(1))

    return sorted(tags)


def _make_preview(body: str, max_len: int = 500) -> str:
    """Create a content preview: strip headers/separators, take first N chars."""
    lines = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        if stripped == "---":
            continue
        if stripped:
            lines.append(stripped)
    preview = " ".join(lines)
    if len(preview) > max_len:
        preview = preview[:max_len].rsplit(" ", 1)[0] + "…"
    return preview


# --- Sync function ---


def sync_obsidian_notes() -> int:
    """Sync all markdown files from the Obsidian vault to the database.

    Full replace strategy: delete all rows, re-insert. Local files are fast to scan.
    """
    from database import get_write_db

    vault = get_vault_path()
    if not vault:
        raise RuntimeError("No Obsidian vault found — configure vault_path or install Obsidian")

    # Phase 1: Read all markdown files
    md_files = sorted(vault.rglob("*.md"))
    # Skip .obsidian directory and .trash
    md_files = [f for f in md_files if not any(p.startswith(".") for p in f.relative_to(vault).parts)]

    if not md_files:
        # Distinguish empty vault from TCC permission block.
        # macOS silently returns empty directory listings (no PermissionError) when the app
        # lacks Documents/Full Disk Access — but stat() still works for path traversal.
        _tcc_msg = (
            f"Vault {vault} appears empty but Obsidian metadata exists — "
            "this app likely lacks macOS Full Disk Access. "
            "Go to System Settings > Privacy & Security > Full Disk Access and add this app, "
            "or run the backend from Terminal (make dev) instead of the native Dashboard app."
        )
        try:
            children = list(vault.iterdir())
        except PermissionError:
            raise RuntimeError(
                f"Access denied to vault {vault} — grant Full Disk Access to this app in "
                "System Settings > Privacy & Security > Full Disk Access"
            )
        if children:
            # iterdir sees entries but rglob found no .md files — unexpected, likely TCC
            raise RuntimeError(_tcc_msg)
        # iterdir returned 0 children — could be TCC silently blocking OR genuinely empty vault.
        # .obsidian/ is always created by Obsidian in any initialized vault (stat works even w/o FDA).
        if (vault / ".obsidian").is_dir():
            raise RuntimeError(_tcc_msg)

    logger.info("Obsidian sync — found %d markdown files in %s", len(md_files), vault)

    # Phase 2: Build rows
    rows = []
    for filepath in md_files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Skipping %s: %s", filepath, e)
            continue

        rel_path = str(filepath.relative_to(vault))
        note_id = hashlib.sha256(rel_path.encode()).hexdigest()[:16]
        title = filepath.stem  # filename without .md

        # Folder = first path component (or None for root files)
        parts = filepath.relative_to(vault).parts
        folder = parts[0] if len(parts) > 1 else None

        frontmatter, body = _parse_frontmatter(content)
        wiki_links = _extract_wiki_links(content)
        tags = _extract_tags(content, frontmatter)
        preview = _make_preview(body)
        word_count = len(body.split())

        stat = filepath.stat()
        created_time = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc).isoformat()
        modified_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        rows.append(
            (
                note_id,
                title,
                rel_path,
                folder,
                content,
                preview,
                json.dumps(frontmatter) if frontmatter else None,
                ", ".join(tags) if tags else None,
                ", ".join(wiki_links) if wiki_links else None,
                word_count,
                created_time,
                modified_time,
            )
        )

    # Phase 3: Write to database (full replace)
    with get_write_db() as db:
        db.execute("DELETE FROM obsidian_notes")
        for row in rows:
            db.execute(
                """INSERT INTO obsidian_notes
                   (id, title, relative_path, folder, content, content_preview,
                    frontmatter_json, tags, wiki_links, word_count, created_time, modified_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        db.commit()

    logger.info("Obsidian sync complete — %d notes synced", len(rows))
    return len(rows)
