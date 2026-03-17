export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface Person {
  id: string;
  name: string;
  title: string;
  reports_to: string | null;
  depth: number;
  has_meetings_dir: boolean;
  is_executive: boolean;
  group_name: string;
  email?: string;
  dir_path?: string;
  is_coworker: boolean;
  company?: string;
  phone?: string;
  bio?: string;
  linkedin_url?: string;
  source?: string;
}

// Backward compat alias
export type Employee = Person;

export interface PersonLink {
  id: number;
  person_id: string;
  link_type: string;
  url: string;
  label: string | null;
  created_at: string;
}

export interface PersonAttribute {
  id: number;
  person_id: string;
  key: string;
  value: string;
}

export interface PersonConnection {
  id: number;
  person_id: string;
  person_name: string;
  relationship: string | null;
  notes: string | null;
  created_at: string;
}

export interface OneOnOneNote {
  id: number;
  person_id: string;
  meeting_date: string;
  title: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface PersonDetail extends Person {
  role_content: string;
  direct_reports: { id: string; name: string; title: string }[];
  meeting_files: MeetingFile[];
  meeting_notes: MeetingNote[];
  granola_meetings: MeetingNote[]; // Legacy alias
  linked_notes: Note[];
  one_on_one_notes: OneOnOneNote[];
  linked_issues: Issue[];
  linked_longform_posts: {
    id: number;
    title: string;
    status: string;
    word_count: number;
    updated_at: string;
  }[];
  links: PersonLink[];
  attributes: PersonAttribute[];
  connections: PersonConnection[];
  next_meeting: {
    summary: string;
    start_time: string;
    end_time: string;
    html_link?: string;
  } | null;
  recent_meeting_summaries: {
    date: string;
    title: string;
    summary: string;
    source: string;
  }[];
}

// Backward compat alias
export type EmployeeDetail = PersonDetail;

export interface Note {
  id: number;
  text: string;
  priority: number;
  status: 'open' | 'done' | 'archived';
  person_id: string | null;
  person_name: string | null;
  people: { id: string; name: string }[];
  // backward compat
  employee_id?: string | null;
  employee_name?: string | null;
  employees?: { id: string; name: string }[];
  is_one_on_one: boolean;
  created_at: string;
  completed_at: string | null;
  due_date: string | null;
  claude_session_id: number | null;
}

export interface Issue {
  id: number;
  title: string;
  description: string;
  priority: number;
  status: 'open' | 'in_progress' | 'done';
  tshirt_size: 's' | 'm' | 'l' | 'xl';
  people: { id: string; name: string }[];
  // backward compat
  employees?: { id: string; name: string }[];
  meetings: { ref_type: 'calendar' | 'granola'; ref_id: string; summary: string; start_time: string | null }[];
  project_id: number | null;
  project_name: string | null;
  tags: string[];
  due_date: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  _type?: 'issue';
}

// --- Issue Discovery ---

export interface ProposedIssue {
  id: number;
  run_id: number;
  title: string;
  description: string;
  priority: number;
  tshirt_size: 's' | 'm' | 'l' | 'xl';
  source: string;
  source_context: string;
  suggested_tags: string[];
  suggested_people: string[];
  status: 'pending' | 'accepted' | 'rejected';
  created_issue_id: number | null;
  created_at: string;
}

export interface DiscoveryRun {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  items_found: number;
  items_accepted: number;
  items_rejected: number;
  error: string | null;
  since_timestamp: string | null;
}

export interface DiscoveryStatus {
  running: boolean;
  run_id: number | null;
  current_step: string;
  steps_done: string[];
}

export interface DiscoveryProposalsResponse {
  proposals: ProposedIssue[];
  run_id: number | null;
  run: DiscoveryRun | null;
}

export interface IssueGroup {
  name: string;
  description: string;
  issue_ids: number[];
}

export interface IssueGroupResponse {
  groups: IssueGroup[];
  error?: string;
}

export interface MeetingSearchResult {
  ref_type: 'calendar' | 'granola';
  ref_id: string;
  summary: string;
  start_time: string | null;
}

export interface CalendarEvent {
  id: string;
  summary: string;
  description?: string;
  location?: string;
  start_time: string;
  end_time: string;
  all_day: boolean;
  attendees_json?: string;
  html_link?: string;
}

export interface Email {
  id: string;
  thread_id?: string;
  subject: string;
  snippet: string;
  from_name: string;
  from_email: string;
  date: string;
  is_unread: boolean;
  message_count?: number;
}

export interface SlackMessage {
  id: string;
  channel_name: string;
  channel_type: 'dm' | 'mpim' | 'channel';
  user_name: string;
  text: string;
  ts: string;
  is_mention: boolean;
  permalink?: string;
}

export interface NotionPage {
  id: string;
  title: string;
  url: string;
  last_edited_time: string;
  last_edited_by?: string;
  snippet?: string;
  relevance_score?: number;
  relevance_reason?: string;
}

// Provider-agnostic meeting note from any source (Granola, Notion, etc.)
export interface MeetingNote {
  id: string;
  provider: string;
  title: string;
  created_at: string;
  updated_at?: string;
  attendees_json?: string;
  summary_html?: string;
  summary_plain?: string;
  transcript_text?: string;
  external_link?: string;
  person_id?: string;
  // Legacy aliases for backward compat
  panel_summary_html?: string;
  panel_summary_plain?: string;
  granola_link?: string;
}

// Legacy alias
export type GranolaMeeting = MeetingNote;

export interface MeetingFile {
  id: number;
  person_id: string;
  filename: string;
  filepath: string;
  meeting_date: string;
  title: string;
  summary: string;
  action_items_json?: string;
  granola_link?: string;
  content_markdown: string;
}

export interface GitHubPullRequest {
  number: number;
  title: string;
  state: string;
  draft: boolean;
  author: string;
  html_url: string;
  created_at: string;
  updated_at: string;
  merged_at: string | null;
  head_ref: string;
  base_ref: string;
  labels: string[];
  requested_reviewers: string[];
  review_requested: boolean;
}

export interface GitHubPullRequestDetail extends GitHubPullRequest {
  body: string;
  additions: number;
  deletions: number;
  changed_files: number;
  files: { filename: string; status: string; additions: number; deletions: number }[];
  reviews: { user: string; state: string; submitted_at: string }[];
  comments: number;
  review_comments: number;
}

export interface GitHubSearchResult {
  number: number;
  title: string;
  type: 'pr' | 'issue';
  state: string;
  author: string;
  html_url: string;
  created_at: string;
  updated_at: string;
  labels: string[];
  comments: number;
}

export interface GitHubCodeSearchResult {
  name: string;
  path: string;
  html_url: string;
  text_matches?: { fragment: string }[];
}

export interface SyncStatus {
  running: boolean;
  active_sources: string[];
  sources: Record<
    string,
    {
      source: string;
      last_sync_at: string;
      last_sync_status: string;
      last_error: string | null;
      items_synced: number;
      duration_seconds: number | null;
    }
  >;
  auto_sync?: {
    enabled: boolean;
    interval_seconds: number;
  };
}

export interface SyncSourceInfo {
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
  items_synced: number;
}

export interface ServiceAuthStatus {
  configured: boolean;
  connected: boolean;
  error: string | null;
  detail: string | null;
  sync: Record<string, SyncSourceInfo>;
}

export interface AuthStatus {
  google: ServiceAuthStatus;
  google_drive: ServiceAuthStatus;
  microsoft: ServiceAuthStatus;
  slack: ServiceAuthStatus;
  notion: ServiceAuthStatus;
  granola: ServiceAuthStatus;
  github: ServiceAuthStatus;
  ramp: ServiceAuthStatus;
}

export interface NewsItem {
  id: string;
  title: string;
  url: string | null;
  source: 'slack' | 'email' | 'web';
  source_detail: string | null;
  domain: string | null;
  snippet: string | null;
  found_at: string;
  published_at: string | null;
}

export interface NewsResponse {
  items: NewsItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface PriorityItem {
  title: string;
  reason: string;
  source: 'slack' | 'email' | 'calendar' | 'note' | 'drive';
  urgency: 'high' | 'medium' | 'low';
}

export interface PrioritiesData {
  items: PriorityItem[];
  summary?: string | null;
  error?: string;
}

// --- Search ---

export interface SearchExternalItem {
  id: string;
  title: string;
  subtitle?: string;
  snippet?: string;
  date?: string;
  url?: string;
  permalink?: string;
}

export interface SearchExternalResults {
  items: SearchExternalItem[];
  error?: string;
}

export interface SearchResults {
  query: string;
  results: {
    people?: {
      id: string;
      name: string;
      title: string;
      email?: string;
      group_name: string;
      is_coworker?: boolean;
      company?: string;
      name_hl?: string;
      title_hl?: string;
    }[];
    notes?: {
      id: number;
      text: string;
      status: string;
      person_id: string | null;
      person_name: string | null;
      is_one_on_one: boolean;
      text_hl?: string;
      created_at: string;
    }[];
    granola_meetings?: {
      id: string;
      title: string;
      created_at: string;
      person_id: string | null;
      person_name: string | null;
      granola_link: string | null;
      title_hl?: string;
      summary_snippet?: string;
    }[];
    meeting_files?: {
      id: number;
      title: string;
      meeting_date: string;
      person_id: string;
      person_name: string | null;
      title_hl?: string;
      summary_snippet?: string;
    }[];
    one_on_one_notes?: {
      id: number;
      title: string | null;
      meeting_date: string;
      person_id: string;
      person_name: string | null;
      title_hl?: string;
      content_snippet?: string;
    }[];
    emails?: {
      id: string;
      thread_id: string;
      subject: string;
      snippet: string;
      from_name: string;
      from_email: string;
      date: string;
      is_unread: boolean;
      subject_hl?: string;
      snippet_hl?: string;
    }[];
    issues?: {
      id: number;
      title: string;
      description: string;
      status: string;
      priority: number;
      tshirt_size: string;
      title_hl?: string;
      description_snippet?: string;
      created_at: string;
    }[];
    drive_files?: {
      id: string;
      name: string;
      mime_type: string;
      web_view_link: string;
      modified_time: string;
      owner_name: string | null;
      name_hl?: string;
      preview_snippet?: string;
    }[];
    longform?: {
      id: number;
      title: string;
      body_snippet: string;
      status: string;
      word_count: number;
      title_hl?: string;
      body_snippet_hl?: string;
      created_at: string;
    }[];
    gmail?: SearchExternalResults;
    slack?: SearchExternalResults;
    calendar?: SearchExternalResults;
    notion?: SearchExternalResults;
    github?: SearchExternalResults;
    drive?: SearchExternalResults;
  };
}

export interface MeetingWithContext {
  event_id: string | null;
  notes_id: string | null;
  notes_provider: string | null;
  source_type: 'calendar' | 'external';
  summary: string;
  start_time: string;
  end_time: string | null;
  all_day: boolean;
  attendees_json?: string;
  html_link?: string;
  description?: string;
  notes_title?: string;
  notes_summary_html?: string;
  notes_summary_plain?: string;
  notes_link?: string;
  notes_transcript?: string;
  note_id?: number;
  note_content?: string;
  // Legacy aliases (backward compat)
  granola_id?: string | null;
  granola_title?: string;
  granola_summary_html?: string;
  granola_summary_plain?: string;
  granola_link?: string;
  granola_transcript?: string;
}

export interface MeetingsResponse {
  meetings: MeetingWithContext[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface DashboardData {
  calendar_today: CalendarEvent[];
  emails_recent: Email[];
  slack_recent: SlackMessage[];
  meetings_upcoming: CalendarEvent[];
  notion_recent: NotionPage[];
  github_review_requests: GitHubPullRequest[];
  drive_recent?: DriveFile[];
  notes_open_count: number;
  sync_status: Record<string, unknown>;
}

// --- Drive / Sheets / Docs ---

export interface DriveFile {
  id: string;
  name: string;
  mime_type: string;
  web_view_link: string;
  icon_link: string | null;
  created_time: string;
  modified_time: string;
  modified_by_name: string | null;
  owner_name: string | null;
  shared: boolean;
  starred: boolean;
  trashed: boolean;
  parent_name: string | null;
  size_bytes: number | null;
  description: string | null;
  content_preview: string | null;
  thumbnail_link: string | null;
}

export interface PrioritizedDriveFile extends DriveFile {
  priority_score: number;
  priority_reason: string;
}

export interface PrioritizedDriveData {
  items: PrioritizedDriveFile[];
  error?: string;
  stale?: boolean;
}

export interface GoogleSheet {
  id: string;
  title: string;
  web_view_link: string;
  owner_name: string | null;
  modified_time: string;
  sheet_tabs: { title: string; row_count: number; col_count: number }[];
  locale: string | null;
  time_zone: string | null;
}

export interface GoogleSheetsResponse {
  sheets: GoogleSheet[];
  total: number;
}

export interface GoogleDoc {
  id: string;
  title: string;
  web_view_link: string;
  owner_name: string | null;
  modified_time: string;
  content_preview: string | null;
  word_count: number | null;
}

export interface GoogleDocsResponse {
  docs: GoogleDoc[];
  total: number;
}

export interface SheetValuesResponse {
  sheet_id: string;
  range: string;
  values: (string | number | null)[][];
}

export interface PrioritizedNewsItem {
  id: string;
  title: string;
  url: string | null;
  source: 'slack' | 'email' | 'web';
  source_detail: string | null;
  domain: string | null;
  snippet: string | null;
  published_at: string | null;
  found_at: string;
  priority_score: number;
  priority_reason: string;
}

export interface PrioritizedNewsData {
  items: PrioritizedNewsItem[];
  error?: string;
  stale?: boolean;
}

export interface PrioritizedSlackMessage {
  id: string;
  user_name: string;
  text: string;
  channel_name: string;
  channel_type: string;
  ts: string;
  is_mention: boolean;
  permalink: string;
  priority_score: number;
  priority_reason: string;
}

export interface PrioritizedSlackData {
  items: PrioritizedSlackMessage[];
  error?: string;
  stale?: boolean;
}

export interface PrioritizedEmail {
  id: string;
  thread_id: string;
  subject: string;
  snippet: string;
  from_name: string;
  from_email: string;
  date: string;
  is_unread: boolean;
  priority_score: number;
  priority_reason: string;
  message_count?: number;
}

export interface EmailThreadMessage {
  id: string;
  thread_id: string;
  subject: string;
  from_name: string;
  from_email: string;
  to: string;
  date: string;
  snippet: string;
  body: string;
  labels: string[];
  is_unread: boolean;
}

export interface EmailThreadDetail {
  thread_id: string;
  message_count: number;
  messages: EmailThreadMessage[];
}

export interface PrioritizedEmailData {
  items: PrioritizedEmail[];
  error?: string;
  stale?: boolean;
}

export interface PrioritizedNotionPage {
  id: string;
  title: string;
  url: string;
  last_edited_time: string;
  last_edited_by: string;
  snippet: string | null;
  relevance_reason: string | null;
  priority_score: number;
  priority_reason: string;
}

export interface PrioritizedNotionData {
  items: PrioritizedNotionPage[];
  error?: string;
  stale?: boolean;
}

export interface RampTransaction {
  id: string;
  amount: number;
  currency: string;
  merchant_name: string;
  category: string;
  transaction_date: string;
  cardholder_name: string;
  cardholder_email: string;
  memo: string | null;
  status: string;
  ramp_url: string | null;
  priority_score: number;
  priority_reason: string;
}

export interface RampData {
  items: RampTransaction[];
  total_amount: number;
  error?: string;
  stale?: boolean;
}

export interface RampBill {
  id: string;
  vendor_id: string;
  vendor_name: string;
  amount: number;
  currency: string;
  due_at: string | null;
  issued_at: string | null;
  paid_at: string | null;
  invoice_number: string | null;
  memo: string | null;
  status: string;
  approval_status: string;
  payment_status: string;
  payment_method: string | null;
  project_id: number | null;
  project_name: string | null;
  ramp_url: string | null;
}

export interface RampBillsResponse {
  bills: RampBill[];
  total: number;
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  budget_amount: number;
  currency: string;
  status: string;
  vendor_id: string | null;
  notes: string | null;
  committed_amount: number;
  paid_amount: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectsResponse {
  projects: Project[];
}

// --- Longform ---

export interface LongformComment {
  id: number;
  post_id: number;
  text: string;
  is_thought: boolean;
  created_at: string;
  updated_at: string;
}

export interface LongformPost {
  id: number;
  title: string;
  body: string;
  status: 'draft' | 'published';
  tags: string[];
  people: { id: string; name: string }[];
  word_count: number;
  comment_count: number;
  thought_count: number;
  claude_session_id: number | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
}

export interface LongformPostDetail extends LongformPost {
  comments: LongformComment[];
  thoughts: LongformComment[];
}

// --- Longform AI Edit ---

export interface LongformAIEditResponse {
  revised_body: string;
  commentary: string;
  error: string | null;
}

// --- Claude Sessions ---

export interface ClaudeSession {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  preview: string;
  summary: string;
  size_bytes: number;
}

export interface ClaudeSessionContent {
  id: number;
  raw_output: string;
  plain_text: string;
  summary: string;
  metadata: {
    rows: number;
    cols: number;
  };
}

// --- Personas ---

export interface Persona {
  id: number;
  name: string;
  description: string;
  system_prompt: string;
  avatar_filename: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

// --- Profile & Setup ---

export interface UserProfile {
  user_name?: string;
  user_title?: string;
  user_company?: string;
  user_company_description?: string;
  user_email?: string;
  user_email_domain?: string;
  user_location?: string;
  github_repo?: string;
  skip_domains?: string[];
  news_topics?: string[];
  email_calendar_provider?: 'google' | 'microsoft';
  meeting_notes_provider?: string;
  notion_meeting_notes_database_id?: string;
  whatsapp_phone?: string;
  ai_provider?: string;
  ai_model?: string;
  auto_sync_interval_seconds?: number;
}

// --- WhatsApp ---

export interface WhatsAppStatus {
  connected: boolean;
  phone?: string;
  hasQR?: boolean;
  error?: string;
}

export interface WhatsAppQR {
  qr?: string;
  connected?: boolean;
  waiting?: boolean;
  error?: string;
}

export interface SetupStatus {
  setup_complete: boolean;
  has_profile: boolean;
  connected_services: number;
  data_dir: string;
  database_path: string;
}

export interface ConnectorInfo {
  id: string;
  name: string;
  description: string;
  category: 'oauth' | 'token' | 'client_credentials' | 'cli' | 'local' | 'none';
  secret_keys: string[];
  help_steps: string[];
  help_url: string | null;
  default_enabled: boolean;
  enabled: boolean;
  capabilities: string[];
  google_access_mode?: 'readonly' | 'readwrite';
}

export interface SecretStatus {
  configured: boolean;
  masked: string;
}

export type SecretsStatus = Record<string, SecretStatus>;

// --- Memory ---

export interface MemoryEntry {
  id: number;
  trigger: 'sync' | 'claude_session' | 'manual';
  summary: string;
  sources: string[];
  word_count: number;
  claude_session_id: number | null;
  data_hash: string;
  created_at: string;
}

export interface MemorySummary {
  summary_text: string | null;
  last_entry_id: number;
  entry_count: number;
  generated_at: string | null;
}

// --- Briefing ---

export interface WeatherData {
  temp_f: number | null;
  condition: string;
  location: string;
}

export interface OvernightItem {
  id: string;
  source: 'email' | 'slack' | 'notion' | 'drive';
  title: string;
  subtitle: string;
  time: string;
  url?: string;
  permalink?: string;
  is_unread?: boolean;
  is_mention?: boolean;
}

export interface BriefingData {
  greeting: {
    user_name: string;
  };
  summary: string | null;
  weather: WeatherData | null;
  calendar_today: CalendarEvent[];
  calendar_summary: {
    tomorrow_count: number;
    week_count: number;
  };
  attention_items: PriorityItem[];
  pulse: {
    unread_emails: number;
    slack_dms: number;
    pr_reviews: number;
    open_notes: number;
    overdue_bills: number;
  };
  overnight: OvernightItem[];
}

// --- Agent Chat ---

export interface AgentConversation {
  id: number;
  title: string;
  saved: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentToolCall {
  name: string;
  input: Record<string, unknown>;
  result?: string;
}

export interface AgentMessage {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  tool_calls: AgentToolCall[];
  created_at: string;
}
