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


class SandboxAppCreate(BaseModel):
    name: str
    description: str = ""


class SandboxAppUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class SandboxFileWrite(BaseModel):
    content: str


class LongformCreate(BaseModel):
    title: str = "Untitled"
    body: str = ""
    status: str = "active"
    tags: Optional[list[str]] = None
    person_ids: Optional[list[str]] = None
    folder: Optional[str] = None


class LongformUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    person_ids: Optional[list[str]] = None
    folder: Optional[str] = None


class LongformCommentCreate(BaseModel):
    text: str
    is_thought: bool = False


class LongformAIEditRequest(BaseModel):
    instruction: str
    body: str
    title: str = ""
    selected_text: str = ""
    history: list[dict] = []


# --- Slack write models ---


class SlackMessageEdit(BaseModel):
    channel: str
    ts: str
    text: str


class SlackMessageDelete(BaseModel):
    channel: str
    ts: str


class SlackReaction(BaseModel):
    channel: str
    ts: str
    name: str  # emoji name without colons


# --- Notion write models ---


class NotionPageCreate(BaseModel):
    parent_id: str
    parent_type: str = "database_id"  # "database_id" or "page_id"
    title: str
    properties: Optional[dict] = None


class NotionPageUpdate(BaseModel):
    properties: dict


class NotionBlockAppend(BaseModel):
    blocks: Optional[list[dict]] = None  # raw Notion block objects
    text: Optional[str] = None  # convenience: auto-creates a paragraph block


# --- Gmail write models ---


class GmailSend(BaseModel):
    to: str  # comma-separated emails
    subject: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None
    reply_to_message_id: Optional[str] = None
    reply_to_thread_id: Optional[str] = None


class GmailDraftCreate(BaseModel):
    to: str
    subject: str
    body: str
    cc: Optional[str] = None
    bcc: Optional[str] = None


class GmailDraftUpdate(BaseModel):
    to: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None


class GmailArchive(BaseModel):
    message_ids: list[str]


class GmailTrash(BaseModel):
    message_ids: list[str]


# --- Calendar write models ---


class CalendarEventCreate(BaseModel):
    summary: str
    start_time: str  # ISO datetime
    end_time: str
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[list[str]] = None  # email addresses
    all_day: bool = False
    send_notifications: bool = True


class CalendarEventUpdate(BaseModel):
    summary: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[list[str]] = None
    send_notifications: bool = True


class CalendarRSVP(BaseModel):
    response: str  # "accepted", "declined", "tentative"


# --- Docs/Sheets write models ---


class GoogleDocCreate(BaseModel):
    title: str
    body: Optional[str] = None
    folder_id: Optional[str] = None


class GoogleDocAppend(BaseModel):
    text: str


class SheetsAppendRows(BaseModel):
    range: str = "Sheet1"
    values: list[list[str]]


class SheetsCellUpdate(BaseModel):
    range: str  # A1 notation
    values: list[list[str]]


# --- WhatsApp models ---


class WhatsAppIncoming(BaseModel):
    sender: str  # phone number e.g. "15551234567@s.whatsapp.net" or LID
    text: str
    message_id: str = ""
    timestamp: str = ""
    from_self: bool = False  # true when message is from the linked device owner
    is_group: bool = False
    group_name: Optional[str] = None
    group_jid: Optional[str] = None
    sender_jid: Optional[str] = None  # actual sender in group chats
