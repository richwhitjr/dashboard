"""Projects API — budget tracking cross-referenced with Ramp bills."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db_connection, get_write_db
from utils.safe_sql import safe_update_query

PROJECT_ALLOWED_COLUMNS = {"name", "description", "budget_amount", "currency", "status", "vendor_id", "notes"}

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    budget_amount: float = 0
    currency: str = "USD"
    vendor_id: Optional[str] = None
    notes: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    budget_amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    vendor_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
def list_projects():
    """List all projects with budget + committed/paid spend rollup from linked bills."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT p.*,
                   COALESCE(SUM(b.amount), 0) as committed_amount,
                   COALESCE(SUM(CASE WHEN b.payment_status IN ('PAID','PAYMENT_COMPLETED')
                       THEN b.amount ELSE 0 END), 0) as paid_amount
               FROM projects p
               LEFT JOIN ramp_bills b ON b.project_id = p.id
               GROUP BY p.id
               ORDER BY p.name"""
        ).fetchall()
    return {"projects": [dict(r) for r in rows]}


@router.post("")
def create_project(body: ProjectCreate):
    """Create a new project."""
    with get_write_db() as db:
        cursor = db.execute(
            """INSERT INTO projects (name, description, budget_amount, currency, vendor_id, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.name, body.description, body.budget_amount, body.currency, body.vendor_id, body.notes),
        )
        project_id = cursor.lastrowid
        db.commit()
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row)


@router.patch("/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    """Update a project's fields."""
    with get_write_db() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

        update_fields = body.model_dump(exclude_none=True)
        if not update_fields:
            return dict(row)

        set_clause, params = safe_update_query(
            "projects",
            update_fields,
            PROJECT_ALLOWED_COLUMNS,
            extra_set_clauses=["updated_at = ?"],
        )
        params.append(datetime.utcnow().isoformat())
        params.append(project_id)
        db.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", params)
        db.commit()
        updated = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(updated)


@router.delete("/{project_id}")
def delete_project(project_id: int):
    """Delete a project and unlink its bills."""
    with get_write_db() as db:
        row = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

        db.execute("UPDATE ramp_bills SET project_id = NULL WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
    return {"ok": True, "deleted_id": project_id}
