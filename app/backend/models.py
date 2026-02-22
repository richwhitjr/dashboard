from typing import Optional

from pydantic import BaseModel


class NoteCreate(BaseModel):
    text: str
    priority: int = 0
    employee_id: Optional[str] = None
    employee_ids: Optional[list[str]] = None
    is_one_on_one: bool = False
    due_date: Optional[str] = None


class NoteUpdate(BaseModel):
    text: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    employee_id: Optional[str] = None
    employee_ids: Optional[list[str]] = None
    is_one_on_one: Optional[bool] = None
    due_date: Optional[str] = None


class EmployeeCreate(BaseModel):
    id: Optional[str] = None  # auto-generated from name if not provided
    name: str
    title: Optional[str] = None
    reports_to: Optional[str] = None
    group_name: str = "team"  # free-form group name; "team" is the default
    email: Optional[str] = None


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    reports_to: Optional[str] = None
    group_name: Optional[str] = None
    email: Optional[str] = None
    role_content: Optional[str] = None


class OneOnOneNoteCreate(BaseModel):
    meeting_date: str  # YYYY-MM-DD
    title: Optional[str] = None
    content: str = ""


class OneOnOneNoteUpdate(BaseModel):
    meeting_date: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None


class IssueCreate(BaseModel):
    title: str
    description: str = ""
    priority: int = 1
    tshirt_size: str = "m"
    employee_ids: Optional[list[str]] = None
    meeting_ids: Optional[list[dict]] = None


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    tshirt_size: Optional[str] = None
    status: Optional[str] = None
    employee_ids: Optional[list[str]] = None
    meeting_ids: Optional[list[dict]] = None


class MeetingNoteUpsert(BaseModel):
    content: str


class SyncRequest(BaseModel):
    sources: Optional[list[str]] = None  # None = sync all


class ClaudeSessionCreate(BaseModel):
    title: str = "Untitled Session"
    content: str  # base64-encoded serialized terminal output
    plain_text: str = ""
    rows: int = 24
    cols: int = 80


class ClaudeSessionUpdate(BaseModel):
    title: Optional[str] = None


class PersonaCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
