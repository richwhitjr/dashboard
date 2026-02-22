import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  useEmployee,
  useEmployees,
  useUpdateNote,
  useCreateNote,
  useUpdateEmployee,
  useDeleteEmployee,
  useCreateEmployee,
  useCreateOneOnOneNote,
  useUpdateOneOnOneNote,
  useDeleteOneOnOneNote,
  useGroups,
} from '../api/hooks';
import { MarkdownRenderer } from '../components/shared/MarkdownRenderer';
import type { MeetingFile, GranolaMeeting, OneOnOneNote, Note } from '../api/types';
import { useState, useEffect, useRef, useMemo } from 'react';
import { sanitizeHtml } from '../utils/sanitize';

type UnifiedMeeting = {
  date: string;
  title: string;
  summary: string;
  granola_link?: string;
  action_items?: string[];
  content?: string;
  granola_html?: string;
  source: 'file' | 'granola' | 'manual';
  manualNote?: OneOnOneNote;
};

function unifyMeetings(
  files: MeetingFile[],
  granola: GranolaMeeting[],
  manualNotes: OneOnOneNote[]
): UnifiedMeeting[] {
  const meetings: UnifiedMeeting[] = [];

  // Index granola meetings by date for cross-referencing
  const granolaByDate = new Map<string, GranolaMeeting>();
  for (const g of granola) {
    const gDate = g.created_at?.split('T')[0];
    if (gDate) granolaByDate.set(gDate, g);
  }

  for (const f of files) {
    const matchingGranola = granolaByDate.get(f.meeting_date);
    meetings.push({
      date: f.meeting_date,
      title: f.title,
      summary: f.summary,
      granola_link: f.granola_link || undefined,
      action_items: f.action_items_json ? JSON.parse(f.action_items_json) : [],
      content: f.content_markdown,
      granola_html: matchingGranola?.panel_summary_html || undefined,
      source: 'file',
    });
  }

  const usedDates = new Set(files.map((f) => f.meeting_date));

  for (const g of granola) {
    const gDate = g.created_at?.split('T')[0];
    if (gDate && !usedDates.has(gDate)) {
      meetings.push({
        date: gDate,
        title: g.title,
        summary: g.panel_summary_plain || '',
        granola_link: g.granola_link || undefined,
        granola_html: g.panel_summary_html || undefined,
        source: 'granola',
      });
      usedDates.add(gDate);
    }
  }

  for (const n of manualNotes) {
    if (!usedDates.has(n.meeting_date)) {
      meetings.push({
        date: n.meeting_date,
        title: n.title || `1:1 — ${n.meeting_date}`,
        summary: n.content.slice(0, 200),
        source: 'manual',
        manualNote: n,
      });
      usedDates.add(n.meeting_date);
    } else {
      // Attach manual note to existing meeting entry
      const existing = meetings.find((m) => m.date === n.meeting_date);
      if (existing) existing.manualNote = n;
    }
  }

  meetings.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  return meetings;
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return 'today';
  if (diffDays === 1) return 'tomorrow';
  if (diffDays < 7) return `in ${diffDays} days`;
  if (diffDays < 14) return 'next week';
  return `in ${Math.ceil(diffDays / 7)} weeks`;
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

function formatDate(dateStr: string): string {
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
}

function htmlToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  function walk(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    const el = node as Element;
    const tag = el.tagName.toLowerCase();
    const children = Array.from(el.childNodes).map(walk).join('');
    switch (tag) {
      case 'h1': return `# ${children}\n\n`;
      case 'h2': return `## ${children}\n\n`;
      case 'h3': return `### ${children}\n\n`;
      case 'p': return `${children}\n\n`;
      case 'br': return '\n';
      case 'strong': case 'b': return `**${children}**`;
      case 'em': case 'i': return `*${children}*`;
      case 'ul': return `${children}\n`;
      case 'ol': return `${children}\n`;
      case 'li': return `- ${children}\n`;
      case 'a': return `[${children}](${el.getAttribute('href') || ''})`;
      case 'blockquote': return `> ${children.trim()}\n\n`;
      case 'code': return el.parentElement?.tagName === 'PRE' ? `\`\`\`\n${children}\n\`\`\`\n\n` : `\`${children}\``;
      default: return children;
    }
  }
  return walk(doc.body).trim();
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <button className="btn-link copy-btn" onClick={handleCopy}>
      {copied ? 'copied' : (label || 'copy')}
    </button>
  );
}

function MeetingModal({ meeting, linkedNotes, onClose }: {
  meeting: UnifiedMeeting;
  linkedNotes: Note[];
  onClose: () => void;
}) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const myNotesMarkdown = meeting.manualNote?.content || '';

  const meetingNotesMarkdown = meeting.granola_html
    ? htmlToMarkdown(meeting.granola_html)
    : meeting.content || meeting.summary || '';

  return (
    <div
      className="meeting-modal-overlay"
      ref={overlayRef}
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div className="meeting-modal">
        <button className="meeting-modal-close" onClick={onClose}>&times;</button>

        <div className="meeting-modal-header">
          <h2>{meeting.title}</h2>
          <div style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)' }}>
            {formatDate(meeting.date)}
            {meeting.granola_link && (
              <>
                {' '}&middot;{' '}
                <a href={meeting.granola_link} target="_blank" rel="noopener noreferrer">
                  Open in Granola
                </a>
              </>
            )}
          </div>
        </div>

        <div className="meeting-modal-section">
          <div className="meeting-modal-section-header">
            <h3>My Notes</h3>
            {myNotesMarkdown && <CopyButton text={myNotesMarkdown} />}
          </div>
          {meeting.manualNote ? (
            <div style={{ whiteSpace: 'pre-wrap' }}>{meeting.manualNote.content}</div>
          ) : (
            <p className="empty-state" style={{ margin: 0 }}>No notes for this meeting.</p>
          )}
          {linkedNotes.length > 0 && (
            <div style={{ marginTop: 'var(--space-sm)' }}>
              {linkedNotes.map((note) => (
                <div key={note.id} className="note-item" style={{ fontSize: 'var(--text-sm)' }}>
                  <span className="note-text">{note.text}</span>
                  {note.is_one_on_one && (
                    <span style={{ color: 'var(--color-text-light)', marginLeft: 'var(--space-xs)' }}>(1:1)</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {(meeting.granola_html || meeting.content || meeting.summary) && (
          <div className="meeting-modal-section">
            <div className="meeting-modal-section-header">
              <h3>Meeting Notes</h3>
              {meetingNotesMarkdown && <CopyButton text={meetingNotesMarkdown} />}
            </div>
            {meeting.granola_html ? (
              <div
                className="markdown-content"
                dangerouslySetInnerHTML={{ __html: sanitizeHtml(meeting.granola_html) }}
              />
            ) : meeting.content ? (
              <MarkdownRenderer content={meeting.content} />
            ) : (
              <div style={{ whiteSpace: 'pre-wrap' }}>{meeting.summary}</div>
            )}
          </div>
        )}

        {meeting.action_items && meeting.action_items.length > 0 && (
          <div className="meeting-modal-section">
            <h3>Action Items</h3>
            <ul>
              {meeting.action_items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function EmployeePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: emp, isLoading } = useEmployee(id!);
  const { data: allEmployees } = useEmployees();
  const { data: groups } = useGroups();
  const updateNote = useUpdateNote();
  const createNote = useCreateNote();
  const updateEmployee = useUpdateEmployee();
  const deleteEmployee = useDeleteEmployee();
  const createEmployee = useCreateEmployee();
  const createOneOnOneNote = useCreateOneOnOneNote();
  const updateOneOnOneNote = useUpdateOneOnOneNote();
  const deleteOneOnOneNote = useDeleteOneOnOneNote();

  const [activeTab, setActiveTab] = useState<'overview' | 'one-on-ones' | 'team' | 'role'>('overview');
  const [expandedMeeting, setExpandedMeeting] = useState<string | null>(null);
  const [oneOnOneText, setOneOnOneText] = useState('');
  const [asyncText, setAsyncText] = useState('');

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [editReportsTo, setEditReportsTo] = useState('');
  const [editGroup, setEditGroup] = useState('');

  // Add report
  const [addingReport, setAddingReport] = useState(false);
  const [newReportName, setNewReportName] = useState('');

  // New 1:1 note form
  const [showNewNote, setShowNewNote] = useState(false);
  const [newNoteDate, setNewNoteDate] = useState('');
  const [newNoteTitle, setNewNoteTitle] = useState('');
  const [newNoteContent, setNewNoteContent] = useState('');

  // Editing a 1:1 note
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [editNoteContent, setEditNoteContent] = useState('');

  // Meeting modal
  const [selectedMeeting, setSelectedMeeting] = useState<UnifiedMeeting | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();


  const meetings = useMemo(
    () =>
      unifyMeetings(
        emp?.meeting_files || [],
        emp?.granola_meetings || [],
        emp?.one_on_one_notes || []
      ),
    [emp?.meeting_files, emp?.granola_meetings, emp?.one_on_one_notes]
  );

  // Deep-link: auto-open meeting modal from URL params (e.g. from search)
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current) return;
    const meetingDate = searchParams.get('meetingDate');
    const meetingSource = searchParams.get('meetingSource');
    if (!meetingDate || meetings.length === 0) return;

    const match =
      meetings.find(
        (m) => m.date === meetingDate && (!meetingSource || m.source === meetingSource)
      ) || meetings.find((m) => m.date === meetingDate);
    if (match) {
      deepLinked.current = true;
      setSelectedMeeting(match);
      setActiveTab('one-on-ones');
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, meetings, setSearchParams]);

  if (isLoading) return <p className="empty-state">Loading...</p>;
  if (!emp) return <p className="empty-state">Employee not found.</p>;

  const oneOnOneNotes = emp.linked_notes?.filter((t) => t.is_one_on_one) ?? [];
  const otherNotes = emp.linked_notes?.filter((t) => !t.is_one_on_one) ?? [];

  const handleAddOneOnOne = (e: React.FormEvent) => {
    e.preventDefault();
    if (!oneOnOneText.trim()) return;
    createNote.mutate({
      text: oneOnOneText.trim(),
      employee_id: emp.id,
      is_one_on_one: true,
    });
    setOneOnOneText('');
  };

  const handleAddAsync = (e: React.FormEvent) => {
    e.preventDefault();
    if (!asyncText.trim()) return;
    createNote.mutate({
      text: asyncText.trim(),
      employee_id: emp.id,
      is_one_on_one: false,
    });
    setAsyncText('');
  };

  const startEditing = () => {
    setEditName(emp.name);
    setEditTitle(emp.title || '');
    setEditReportsTo(emp.reports_to || '');
    setEditGroup(emp.group_name || 'team');
    setEditing(true);
  };

  const saveEdits = () => {
    updateEmployee.mutate({
      id: emp.id,
      name: editName,
      title: editTitle || undefined,
      reports_to: editReportsTo || null,
      group_name: editGroup,
    });
    setEditing(false);
  };

  const handleDelete = () => {
    if (!confirm(`Delete ${emp.name}? This will unlink their notes and remove all meeting data.`)) return;
    deleteEmployee.mutate(emp.id, {
      onSuccess: () => navigate('/team'),
    });
  };

  const handleAddMeetingNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNoteDate) return;
    createOneOnOneNote.mutate({
      employeeId: emp.id,
      meeting_date: newNoteDate,
      title: newNoteTitle || undefined,
      content: newNoteContent,
    });
    setNewNoteDate('');
    setNewNoteTitle('');
    setNewNoteContent('');
    setShowNewNote(false);
  };

  const handleSaveNoteEdit = (noteId: number) => {
    updateOneOnOneNote.mutate({
      employeeId: emp.id,
      id: noteId,
      content: editNoteContent,
    });
    setEditingNoteId(null);
  };

  const otherEmployees = allEmployees?.filter((e) => e.id !== emp.id) ?? [];

  return (
    <div>
      <div className="breadcrumb">
        <Link to="/team">Team</Link>
        {emp.reports_to && (
          <>
            {' / '}
            <Link to={`/employees/${emp.reports_to}`}>
              {emp.reports_to.replace(/_/g, ' ')}
            </Link>
          </>
        )}
        {' / '}
        {emp.name}
      </div>

      {/* Header */}
      {editing ? (
        <div className="employee-edit-form">
          <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'baseline' }}>
            <input
              className="note-input"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder="Name"
              style={{ fontSize: 'var(--text-xl)', fontWeight: 'bold' }}
            />
          </div>
          <input
            className="note-input"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            placeholder="Title"
          />
          <div style={{ display: 'flex', gap: 'var(--space-md)', alignItems: 'center', marginTop: 'var(--space-xs)' }}>
            <label style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
              Reports to:
              <select
                value={editReportsTo}
                onChange={(e) => setEditReportsTo(e.target.value)}
                style={{ marginLeft: 'var(--space-xs)' }}
              >
                <option value="">None</option>
                {otherEmployees.map((e) => (
                  <option key={e.id} value={e.id}>{e.name}</option>
                ))}
              </select>
            </label>
            <label style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>
              Group:
              <input
                list="edit-group-options"
                value={editGroup}
                onChange={(e) => setEditGroup(e.target.value)}
                placeholder="team"
                style={{ marginLeft: 'var(--space-xs)', width: '120px' }}
              />
              <datalist id="edit-group-options">
                {(groups ?? ['team']).map(g => <option key={g} value={g} />)}
              </datalist>
            </label>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
            <button className="btn-primary" onClick={saveEdits}>Save</button>
            <button className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn-danger" onClick={handleDelete} style={{ marginLeft: 'auto' }}>Delete</button>
          </div>
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)' }}>
            <h1 style={{ marginBottom: 0 }}>{emp.name}</h1>
            <button
              className="btn-link"
              onClick={startEditing}
              style={{ fontSize: 'var(--text-sm)' }}
            >
              edit
            </button>
          </div>
          <p style={{ color: 'var(--color-text-muted)', marginTop: '4px' }}>
            {emp.title}
          </p>
        </div>
      )}

      {/* Tab bar */}
      <div className="tab-bar">
        <button
          className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          Overview
        </button>
        <button
          className={`tab ${activeTab === 'one-on-ones' ? 'active' : ''}`}
          onClick={() => setActiveTab('one-on-ones')}
        >
          1:1 Notes
        </button>
        {(emp.direct_reports?.length > 0 || true) && (
          <button
            className={`tab ${activeTab === 'team' ? 'active' : ''}`}
            onClick={() => setActiveTab('team')}
          >
            Team{emp.direct_reports?.length > 0 && ` (${emp.direct_reports.length})`}
          </button>
        )}
        {emp.role_content && (
          <button
            className={`tab ${activeTab === 'role' ? 'active' : ''}`}
            onClick={() => setActiveTab('role')}
          >
            Role
          </button>
        )}
      </div>

      {/* === OVERVIEW TAB === */}
      {activeTab === 'overview' && (
        <>
          {/* Dashboard cards */}
          <div className="employee-dashboard">
            <div className="emp-card">
              <div className="emp-card-label">next meeting</div>
              {emp.next_meeting ? (
                <div>
                  <div className="emp-card-value">
                    {formatRelativeDate(emp.next_meeting.start_time)}
                  </div>
                  <div className="emp-card-detail">
                    {formatTime(emp.next_meeting.start_time)}
                    {' \u2014 '}
                    {emp.next_meeting.summary}
                  </div>
                  {emp.next_meeting.html_link && (
                    <a
                      href={emp.next_meeting.html_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 'var(--text-xs)' }}
                    >
                      Open in Calendar
                    </a>
                  )}
                </div>
              ) : (
                <div className="emp-card-value" style={{ color: 'var(--color-text-light)' }}>
                  No upcoming meeting
                </div>
              )}
            </div>

            <div className="emp-card">
              <div className="emp-card-label">recent discussions</div>
              {(emp.recent_meeting_summaries || []).length > 0 ? (
                (emp.recent_meeting_summaries || []).map((m, i) => (
                  <div key={i} className="emp-card-meeting">
                    <span className="emp-card-meeting-date">{formatDate(m.date)}</span>
                    {' '}
                    {m.summary
                      ? m.summary.slice(0, 80) + (m.summary.length > 80 ? '...' : '')
                      : m.title}
                  </div>
                ))
              ) : (
                <div style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>
                  No meetings recorded
                </div>
              )}
            </div>

            <div className="emp-card">
              <div className="emp-card-label">open items</div>
              <div className="emp-card-stats">
                <div>
                  <span className="emp-card-stat-number">{oneOnOneNotes.length}</span>
                  <span className="emp-card-stat-label">1:1 topics</span>
                </div>
                <div>
                  <span className="emp-card-stat-number">{otherNotes.length}</span>
                  <span className="emp-card-stat-label">notes</span>
                </div>
              </div>
            </div>
          </div>

          {/* 1:1 Topics with quick-add */}
          <div className="employee-section">
            <h2>1:1 Topics</h2>
            <form onSubmit={handleAddOneOnOne}>
              <input
                className="note-input"
                value={oneOnOneText}
                onChange={(e) => setOneOnOneText(e.target.value)}
                placeholder="Add a topic for next 1:1..."
              />
            </form>
            {oneOnOneNotes.length > 0 ? (
              oneOnOneNotes.map((note) => (
                <div key={note.id} className="note-item">
                  <input
                    type="checkbox"
                    checked={note.status === 'done'}
                    onChange={() =>
                      updateNote.mutate({
                        id: note.id,
                        status: note.status === 'done' ? 'open' : 'done',
                      })
                    }
                  />
                  <span className="note-text">{note.text}</span>
                </div>
              ))
            ) : (
              <p className="empty-state" style={{ padding: 'var(--space-sm) 0' }}>
                No 1:1 topics yet.
              </p>
            )}
          </div>

          {/* Linked issues */}
          {(emp.linked_issues?.length ?? 0) > 0 && (
            <div className="employee-section">
              <h2>Issues</h2>
              {emp.linked_issues.map((issue) => (
                <div key={issue.id} className={`issue-item priority-p${issue.priority}`}>
                  <span className={`issue-size-badge size-${issue.tshirt_size}`}>
                    {(issue.tshirt_size || 'm').toUpperCase()}
                  </span>
                  <Link to={`/issues?issueId=${issue.id}`} className="issue-title">{issue.title}</Link>
                  <span className="issue-priority-label">P{issue.priority}</span>
                </div>
              ))}
            </div>
          )}

          {/* Async notes with quick-add */}
          <div className="employee-section">
            <h2>Notes &amp; Follow-ups</h2>
            <form onSubmit={handleAddAsync}>
              <input
                className="note-input"
                value={asyncText}
                onChange={(e) => setAsyncText(e.target.value)}
                placeholder="Add a note or async follow-up..."
              />
            </form>
            {otherNotes.length > 0 ? (
              otherNotes.map((note) => (
                <div key={note.id} className="note-item">
                  <input
                    type="checkbox"
                    checked={note.status === 'done'}
                    onChange={() =>
                      updateNote.mutate({
                        id: note.id,
                        status: note.status === 'done' ? 'open' : 'done',
                      })
                    }
                  />
                  <span className="note-text">{note.text}</span>
                </div>
              ))
            ) : (
              <p className="empty-state" style={{ padding: 'var(--space-sm) 0' }}>
                No notes yet.
              </p>
            )}
          </div>

        </>
      )}

      {/* === 1:1 NOTES TAB === */}
      {activeTab === 'one-on-ones' && (
        <>
          <div className="employee-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h2>Meeting Notes</h2>
              <button
                className="btn-link"
                onClick={() => setShowNewNote(!showNewNote)}
              >
                {showNewNote ? 'cancel' : '+ new entry'}
              </button>
            </div>

            {showNewNote && (
              <form onSubmit={handleAddMeetingNote} className="one-on-one-form">
                <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
                  <input
                    type="date"
                    value={newNoteDate}
                    onChange={(e) => setNewNoteDate(e.target.value)}
                    required
                  />
                  <input
                    className="note-input"
                    value={newNoteTitle}
                    onChange={(e) => setNewNoteTitle(e.target.value)}
                    placeholder="Title (optional)"
                    style={{ flex: 1 }}
                  />
                </div>
                <textarea
                  className="note-input"
                  value={newNoteContent}
                  onChange={(e) => setNewNoteContent(e.target.value)}
                  placeholder="Meeting notes..."
                  rows={4}
                  style={{ width: '100%', resize: 'vertical' }}
                />
                <button className="btn-primary" type="submit">Add Entry</button>
              </form>
            )}

            {meetings.length === 0 && (
              <p className="empty-state">No meetings recorded.</p>
            )}
            {meetings.map((m) => (
              <div key={m.date + m.source} className="meeting-entry">
                <div className="meeting-date">
                  <button
                    className="btn-link meeting-title-link"
                    onClick={() => setSelectedMeeting(m)}
                  >
                    {m.date} &mdash; {m.title}
                  </button>
                  {m.granola_link && (
                    <>
                      {' '}
                      &middot;{' '}
                      <a href={m.granola_link} target="_blank" rel="noopener noreferrer">
                        Granola
                      </a>
                    </>
                  )}
                  {m.source === 'granola' && !m.granola_link && (
                    <span style={{ color: 'var(--color-text-light)' }}> (Granola)</span>
                  )}
                </div>

                {m.summary && (
                  <div className="meeting-summary">
                    {m.summary.slice(0, 300)}
                    {m.summary.length > 300 && '...'}
                  </div>
                )}

                {m.action_items && m.action_items.length > 0 && (
                  <div className="meeting-actions">
                    <strong>Action items:</strong>{' '}
                    {m.action_items.length} items
                  </div>
                )}

                {/* Manual note for this meeting */}
                {m.manualNote && (
                  <div className="one-on-one-note-content">
                    {editingNoteId === m.manualNote.id ? (
                      <div>
                        <textarea
                          className="note-input"
                          value={editNoteContent}
                          onChange={(e) => setEditNoteContent(e.target.value)}
                          rows={4}
                          style={{ width: '100%', resize: 'vertical' }}
                        />
                        <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-xs)' }}>
                          <button className="btn-primary" onClick={() => handleSaveNoteEdit(m.manualNote!.id)}>Save</button>
                          <button className="btn-secondary" onClick={() => setEditingNoteId(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{m.manualNote.content}</div>
                        <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-xs)' }}>
                          <button
                            className="btn-link"
                            onClick={() => {
                              setEditingNoteId(m.manualNote!.id);
                              setEditNoteContent(m.manualNote!.content);
                            }}
                          >
                            edit
                          </button>
                          <button
                            className="btn-link"
                            style={{ color: 'var(--color-text-light)' }}
                            onClick={() => {
                              if (confirm('Delete this note?')) {
                                deleteOneOnOneNote.mutate({ employeeId: emp.id, id: m.manualNote!.id });
                              }
                            }}
                          >
                            delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* If no manual note exists yet for this date, show "add note" link */}
                {!m.manualNote && m.source !== 'manual' && (
                  <button
                    className="btn-link"
                    style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--space-xs)' }}
                    onClick={() => {
                      setNewNoteDate(m.date);
                      setNewNoteTitle('');
                      setNewNoteContent('');
                      setShowNewNote(true);
                      window.scrollTo({ top: 0, behavior: 'smooth' });
                    }}
                  >
                    + add notes
                  </button>
                )}

                {m.content && (
                  <div>
                    <button
                      className="collapsible-header"
                      onClick={() =>
                        setExpandedMeeting(
                          expandedMeeting === m.date ? null : m.date
                        )
                      }
                      style={{
                        background: 'none',
                        border: 'none',
                        fontFamily: 'var(--font-body)',
                        fontSize: 'var(--text-sm)',
                        color: 'var(--color-accent)',
                        cursor: 'pointer',
                        padding: 'var(--space-xs) 0',
                      }}
                    >
                      <span
                        className={`collapse-icon ${expandedMeeting === m.date ? 'open' : ''}`}
                      >
                        &#x25b6;
                      </span>{' '}
                      {expandedMeeting === m.date ? 'Hide' : 'Show'} full notes
                    </button>
                    {expandedMeeting === m.date && (
                      <div style={{ marginTop: 'var(--space-sm)' }}>
                        <MarkdownRenderer content={m.content} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* === TEAM TAB === */}
      {activeTab === 'team' && (
        <div className="employee-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <h2>Reports to {emp.name}</h2>
            <button
              className="btn-link"
              onClick={() => setAddingReport(!addingReport)}
            >
              {addingReport ? 'cancel' : '+ add person'}
            </button>
          </div>

          {addingReport && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!newReportName.trim()) return;
                createEmployee.mutate(
                  {
                    name: newReportName.trim(),
                    group_name: emp.group_name || 'team',
                    reports_to: emp.id,
                  },
                  {
                    onSuccess: () => {
                      setNewReportName('');
                      setAddingReport(false);
                    },
                  }
                );
              }}
              style={{ marginBottom: 'var(--space-md)' }}
            >
              <input
                className="note-input"
                autoFocus
                value={newReportName}
                onChange={(e) => setNewReportName(e.target.value)}
                placeholder="Name"
              />
            </form>
          )}

          {emp.direct_reports?.length > 0 ? (
            <ul className="org-tree-list">
              {emp.direct_reports.map((dr: { id: string; name: string; title?: string }) => (
                <li key={dr.id} className="org-tree-item">
                  <Link to={`/employees/${dr.id}`} className="org-tree-name">
                    {dr.name}
                  </Link>
                  {dr.title && <span className="org-tree-title">{dr.title}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">No one reports to {emp.name} yet.</p>
          )}
        </div>
      )}

      {/* === ROLE TAB === */}
      {activeTab === 'role' && emp.role_content && (
        <div className="employee-section">
          <h2>Role</h2>
          <MarkdownRenderer content={emp.role_content} />
        </div>
      )}

      {selectedMeeting && (
        <MeetingModal
          meeting={selectedMeeting}
          linkedNotes={[...oneOnOneNotes, ...otherNotes]}
          onClose={() => setSelectedMeeting(null)}
        />
      )}
    </div>
  );
}
