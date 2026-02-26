from typing import Optional

from pydantic import BaseModel


class NoteCreate(BaseModel):
    text: str
    priority: int = 0
    person_id: Optional[str] = None
    person_ids: Optional[list[str]] = None
    is_one_on_one: bool = False
    due_date: Optional[str] = None


class NoteUpdate(BaseModel):
    text: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    person_id: Optional[str] = None
    person_ids: Optional[list[str]] = None
    is_one_on_one: Optional[bool] = None
    due_date: Optional[str] = None


class PersonCreate(BaseModel):
    id: Optional[str] = None  # auto-generated from name if not provided
    name: str
    title: Optional[str] = None
    reports_to: Optional[str] = None
    group_name: Optional[str] = "team"  # free-form group name; "team" is the default for coworkers
    email: Optional[str] = None
    is_coworker: bool = True
    company: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    reports_to: Optional[str] = None
    group_name: Optional[str] = None
    email: Optional[str] = None
    role_content: Optional[str] = None
    is_coworker: Optional[bool] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None


class PersonLinkCreate(BaseModel):
    link_type: str  # 'linkedin', 'twitter', 'github', 'website', 'other'
    url: str
    label: Optional[str] = None


class PersonAttributeCreate(BaseModel):
    key: str
    value: str


class PersonConnectionCreate(BaseModel):
    person_id: str  # the other person to connect to
    relationship: Optional[str] = None
    notes: Optional[str] = None


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
    person_ids: Optional[list[str]] = None
    meeting_ids: Optional[list[dict]] = None
    project_id: Optional[int] = None
    tags: Optional[list[str]] = None
    due_date: Optional[str] = None


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    tshirt_size: Optional[str] = None
    status: Optional[str] = None
    person_ids: Optional[list[str]] = None
    meeting_ids: Optional[list[dict]] = None
    project_id: Optional[int] = None
    tags: Optional[list[str]] = None
    due_date: Optional[str] = None


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


class LongformCreate(BaseModel):
    title: str = "Untitled"
    body: str = ""
    status: str = "draft"
    tags: Optional[list[str]] = None


class LongformUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None


class LongformCommentCreate(BaseModel):
    text: str
    is_thought: bool = False
