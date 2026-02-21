"""Projects API — budget tracking cross-referenced with Ramp bills."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db

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
    db = get_db()
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
    db.close()
    return {"projects": [dict(r) for r in rows]}


@router.post("")
def create_project(body: ProjectCreate):
    """Create a new project."""
    db = get_db()
    cursor = db.execute(
        """INSERT INTO projects (name, description, budget_amount, currency, vendor_id, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (body.name, body.description, body.budget_amount, body.currency, body.vendor_id, body.notes),
    )
    project_id = cursor.lastrowid
    db.commit()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    db.close()
    return dict(row)


@router.patch("/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    """Update a project's fields."""
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    fields = body.model_dump(exclude_none=True)
    if not fields:
        db.close()
        return dict(row)

    set_clauses = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [datetime.utcnow().isoformat(), project_id]
    db.execute(f"UPDATE projects SET {set_clauses}, updated_at = ? WHERE id = ?", values)
    db.commit()
    updated = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    db.close()
    return dict(updated)


@router.delete("/{project_id}")
def delete_project(project_id: int):
    """Delete a project and unlink its bills."""
    db = get_db()
    row = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Project not found")

    db.execute("UPDATE ramp_bills SET project_id = NULL WHERE project_id = ?", (project_id,))
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    db.close()
    return {"ok": True, "deleted_id": project_id}
