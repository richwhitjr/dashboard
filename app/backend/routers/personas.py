"""CRUD endpoints for Claude persona management with avatar upload."""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config import DATA_DIR
from database import get_db_connection, get_write_db
from models import PersonaCreate, PersonaUpdate
from utils.safe_sql import safe_update_query

PERSONA_ALLOWED_COLUMNS = {"name", "description", "system_prompt"}

router = APIRouter(prefix="/api/personas", tags=["personas"])

AVATARS_DIR = DATA_DIR / "personas"
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _avatar_path(persona_id: int, filename: str) -> Path:
    return AVATARS_DIR / filename


@router.get("")
def list_personas():
    """List all personas, defaults first, then by name."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM personas ORDER BY is_default DESC, name ASC").fetchall()
        result = [dict(r) for r in rows]
    return result


@router.get("/{persona_id}")
def get_persona(persona_id: int):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")
    return dict(row)


@router.post("")
def create_persona(persona: PersonaCreate):
    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO personas (name, description, system_prompt) VALUES (?, ?, ?)",
            (persona.name, persona.description, persona.system_prompt),
        )
        db.commit()
        row = db.execute("SELECT * FROM personas WHERE id = ?", (cursor.lastrowid,)).fetchone()
        result = dict(row)
    return result


@router.patch("/{persona_id}")
def update_persona(persona_id: int, update: PersonaUpdate):
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Persona not found")

        update_fields = dict(update.model_dump(exclude_unset=True))

        if update_fields:
            set_clause, params = safe_update_query(
                "personas",
                update_fields,
                PERSONA_ALLOWED_COLUMNS,
                extra_set_clauses=["updated_at = datetime('now')"],
            )
            params.append(persona_id)
            db.execute(f"UPDATE personas SET {set_clause} WHERE id = ?", params)
            db.commit()

        row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        result = dict(row)
    return result


@router.delete("/{persona_id}")
def delete_persona(persona_id: int):
    with get_write_db() as db:
        row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Persona not found")
        if row["is_default"]:
            raise HTTPException(status_code=400, detail="Cannot delete built-in persona")

        # Clean up avatar file if exists
        if row["avatar_filename"]:
            avatar = _avatar_path(persona_id, row["avatar_filename"])
            if avatar.exists():
                avatar.unlink()

        db.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        db.commit()
    return {"ok": True}


# --- Avatar upload/serve ---


@router.post("/{persona_id}/avatar")
async def upload_avatar(persona_id: int, file: UploadFile = File(...)):
    """Upload an avatar image for a persona."""
    # Validate persona exists
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Validate file type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type} not allowed. Use PNG, JPEG, WebP, or GIF.",
        )

    # Read and validate size
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum 5 MB.")

    # Determine extension from content type
    ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    ext = ext_map.get(file.content_type, "png")
    filename = f"{persona_id}.{ext}"

    # Create directory if needed
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old avatar if different extension
    old_filename = row["avatar_filename"]
    if old_filename and old_filename != filename:
        old_path = _avatar_path(persona_id, old_filename)
        if old_path.exists():
            old_path.unlink()

    # Write file
    avatar = _avatar_path(persona_id, filename)
    avatar.write_bytes(data)

    # Update database
    with get_write_db() as db:
        db.execute(
            "UPDATE personas SET avatar_filename = ?, updated_at = datetime('now') WHERE id = ?",
            (filename, persona_id),
        )
        db.commit()

    return {"ok": True, "avatar_filename": filename}


@router.get("/{persona_id}/avatar")
def get_avatar(persona_id: int):
    """Serve the avatar image for a persona."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT avatar_filename FROM personas WHERE id = ?", (persona_id,)).fetchone()
    if not row or not row["avatar_filename"]:
        raise HTTPException(status_code=404, detail="No avatar")

    avatar = _avatar_path(persona_id, row["avatar_filename"])
    if not avatar.exists():
        raise HTTPException(status_code=404, detail="Avatar file missing")

    return FileResponse(
        avatar,
        headers={"Cache-Control": "public, max-age=3600"},
    )
