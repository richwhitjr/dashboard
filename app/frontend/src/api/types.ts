export interface Employee {
  id: string;
  name: string;
  title: string;
  reports_to: string | null;
  depth: number;
  has_meetings_dir: boolean;
  is_executive: boolean;
  group_name: 'exec' | 'team' | 'external';
  email?: string;
  dir_path?: string;
}

export interface OneOnOneNote {
  id: number;
  employee_id: string;
  meeting_date: string;
  title: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeDetail extends Employee {
  role_content: string;
  direct_reports: { id: string; name: string; title: string }[];
  meeting_files: MeetingFile[];
  granola_meetings: GranolaMeeting[];
  linked_notes: Note[];
  one_on_one_notes: OneOnOneNote[];
  linked_issues: Issue[];
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
    source: 'file' | 'granola';
  }[];
}

export interface Note {
  id: number;
  text: string;
  priority: number;
  status: 'open' | 'done' | 'archived';
  employee_id: string | null;
  employee_name: string | null;
  employees: { id: string; name: string }[];
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
  employees: { id: string; name: string }[];
  meetings: { ref_type: 'calendar' | 'granola'; ref_id: string; summary: string; start_time: string | null }[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  _type?: 'issue';
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
  snippet?: string;
  relevance_score?: number;
  relevance_reason?: string;
}

export interface GranolaMeeting {
  id: string;
  title: string;
  created_at: string;
  attendees_json?: string;
  panel_summary_html?: string;
  panel_summary_plain?: string;
  transcript_text?: string;
  granola_link?: string;
  employee_id?: string;
}

export interface MeetingFile {
  id: number;
  employee_id: string;
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
  current_source?: string | null;
  sources: Record<
    string,
    {
      source: string;
      last_sync_at: string;
      last_sync_status: string;
      last_error: string | null;
      items_synced: number;
    }
  >;
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
  source: 'slack' | 'email' | 'calendar' | 'note';
  urgency: 'high' | 'medium' | 'low';
}

export interface PrioritiesData {
  items: PriorityItem[];
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
    employees?: {
      id: string;
      name: string;
      title: string;
      email?: string;
      group_name: string;
      name_hl?: string;
      title_hl?: string;
    }[];
    notes?: {
      id: number;
      text: string;
      status: string;
      employee_id: string | null;
      employee_name: string | null;
      is_one_on_one: boolean;
      text_hl?: string;
      created_at: string;
    }[];
    granola_meetings?: {
      id: string;
      title: string;
      created_at: string;
      employee_id: string | null;
      employee_name: string | null;
      granola_link: string | null;
      title_hl?: string;
      summary_snippet?: string;
    }[];
    meeting_files?: {
      id: number;
      title: string;
      meeting_date: string;
      employee_id: string;
      employee_name: string | null;
      title_hl?: string;
      summary_snippet?: string;
    }[];
    one_on_one_notes?: {
      id: number;
      title: string | null;
      meeting_date: string;
      employee_id: string;
      employee_name: string | null;
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
    gmail?: SearchExternalResults;
    slack?: SearchExternalResults;
    calendar?: SearchExternalResults;
    notion?: SearchExternalResults;
    github?: SearchExternalResults;
  };
}

export interface MeetingWithContext {
  event_id: string | null;
  granola_id: string | null;
  source_type: 'calendar' | 'granola';
  summary: string;
  start_time: string;
  end_time: string | null;
  all_day: boolean;
  attendees_json?: string;
  html_link?: string;
  description?: string;
  granola_title?: string;
  granola_summary_html?: string;
  granola_summary_plain?: string;
  granola_link?: string;
  granola_transcript?: string;
  note_id?: number;
  note_content?: string;
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
  notes_open_count: number;
  sync_status: Record<string, unknown>;
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
