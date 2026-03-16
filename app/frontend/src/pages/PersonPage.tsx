import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  usePerson,
  usePeople,
  useUpdateNote,
  useCreateNote,
  useUpdatePerson,
  useDeletePerson,
  useCreatePerson,
  useCreateOneOnOneNote,
  useUpdateOneOnOneNote,
  useDeleteOneOnOneNote,
  useGroups,
  useCreatePersonLink,
  useDeletePersonLink,
  useCreatePersonAttribute,
  useDeletePersonAttribute,
  useCreatePersonConnection,
  useDeletePersonConnection,
} from '../api/hooks';
import { MarkdownRenderer } from '../components/shared/MarkdownRenderer';
import type { MeetingFile, MeetingNote, OneOnOneNote, Note, PersonLink, PersonAttribute, PersonConnection } from '../api/types';
import { useState, useEffect, useRef, useMemo } from 'react';
import { sanitizeHtml } from '../utils/sanitize';

type UnifiedMeeting = {
  date: string;
  title: string;
  summary: string;
  external_link?: string;
  notes_provider?: string;
  action_items?: string[];
  content?: string;
  summary_html?: string;
  source: string;
  manualNote?: OneOnOneNote;
};

function unifyMeetings(
  files: MeetingFile[],
  meetingNotes: MeetingNote[],
  manualNotes: OneOnOneNote[]
): UnifiedMeeting[] {
  const meetings: UnifiedMeeting[] = [];

  // Index meeting notes by date for cross-referencing
  const notesByDate = new Map<string, MeetingNote>();
  for (const n of meetingNotes) {
    const nDate = n.created_at?.split('T')[0];
    if (nDate) notesByDate.set(nDate, n);
  }

  for (const f of files) {
    const matchingNote = notesByDate.get(f.meeting_date);
    meetings.push({
      date: f.meeting_date,
      title: f.title,
      summary: f.summary,
      external_link: matchingNote?.external_link || matchingNote?.granola_link || undefined,
      notes_provider: matchingNote?.provider,
      action_items: f.action_items_json ? JSON.parse(f.action_items_json) : [],
      content: f.content_markdown,
      summary_html: matchingNote?.summary_html || matchingNote?.panel_summary_html || undefined,
      source: 'file',
    });
  }

  const usedDates = new Set(files.map((f) => f.meeting_date));

  for (const n of meetingNotes) {
    const nDate = n.created_at?.split('T')[0];
    if (nDate && !usedDates.has(nDate)) {
      meetings.push({
        date: nDate,
        title: n.title,
        summary: n.summary_plain || n.panel_summary_plain || '',
        external_link: n.external_link || n.granola_link || undefined,
        notes_provider: n.provider,
        summary_html: n.summary_html || n.panel_summary_html || undefined,
        source: n.provider || 'notes',
      });
      usedDates.add(nDate);
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
    timeZone: 'America/New_York',
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

  const meetingNotesMarkdown = meeting.summary_html
    ? htmlToMarkdown(meeting.summary_html)
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
            {meeting.external_link && (
              <>
                {' '}&middot;{' '}
                <a href={meeting.external_link} target="_blank" rel="noopener noreferrer">
                  Open in {meeting.notes_provider ? meeting.notes_provider.charAt(0).toUpperCase() + meeting.notes_provider.slice(1) : 'Notes'}
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

        {(meeting.summary_html || meeting.content || meeting.summary) && (
          <div className="meeting-modal-section">
            <div className="meeting-modal-section-header">
              <h3>Meeting Notes</h3>
              {meetingNotesMarkdown && <CopyButton text={meetingNotesMarkdown} />}
            </div>
            {meeting.summary_html ? (
              <div
                className="markdown-content"
                dangerouslySetInnerHTML={{ __html: sanitizeHtml(meeting.summary_html) }}
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

export function PersonPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: person, isLoading } = usePerson(id!);
  const { data: allPeople } = usePeople();
  const { data: groups } = useGroups();
  const updateNote = useUpdateNote();
  const createNote = useCreateNote();
  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();
  const createPerson = useCreatePerson();
  const createOneOnOneNote = useCreateOneOnOneNote();
  const updateOneOnOneNote = useUpdateOneOnOneNote();
  const deleteOneOnOneNote = useDeleteOneOnOneNote();
  const createLink = useCreatePersonLink();
  const deleteLink = useDeletePersonLink();
  const createAttribute = useCreatePersonAttribute();
  const deleteAttribute = useDeletePersonAttribute();
  const createConnection = useCreatePersonConnection();
  const deleteConnection = useDeletePersonConnection();

  const [activeTab, setActiveTab] = useState<'overview' | 'one-on-ones' | 'team' | 'role' | 'connections'>('overview');
  const [expandedMeeting, setExpandedMeeting] = useState<string | null>(null);
  const [oneOnOneText, setOneOnOneText] = useState('');
  const [asyncText, setAsyncText] = useState('');

  // Edit mode state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editTitle, setEditTitle] = useState('');
  const [editReportsTo, setEditReportsTo] = useState('');
  const [editGroup, setEditGroup] = useState('');
  const [editCompany, setEditCompany] = useState('');
  const [editPhone, setEditPhone] = useState('');
  const [editBio, setEditBio] = useState('');
  const [editLinkedin, setEditLinkedin] = useState('');
  const [editIsCoworker, setEditIsCoworker] = useState(true);

  // Add link form
  const [showAddLink, setShowAddLink] = useState(false);
  const [newLinkType, setNewLinkType] = useState('linkedin');
  const [newLinkUrl, setNewLinkUrl] = useState('');
  const [newLinkLabel, setNewLinkLabel] = useState('');

  // Add attribute form
  const [showAddAttr, setShowAddAttr] = useState(false);
  const [newAttrKey, setNewAttrKey] = useState('');
  const [newAttrValue, setNewAttrValue] = useState('');

  // Add connection form
  const [showAddConn, setShowAddConn] = useState(false);
  const [newConnPersonId, setNewConnPersonId] = useState('');
  const [newConnRelationship, setNewConnRelationship] = useState('');

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
        person?.meeting_files || [],
        person?.meeting_notes || person?.granola_meetings || [],
        person?.one_on_one_notes || []
      ),
    [person?.meeting_files, person?.meeting_notes, person?.granola_meetings, person?.one_on_one_notes]
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
  if (!person) return <p className="empty-state">Person not found.</p>;

  const oneOnOneNotes = person.linked_notes?.filter((t) => t.is_one_on_one) ?? [];
  const otherNotes = person.linked_notes?.filter((t) => !t.is_one_on_one) ?? [];

  const handleAddOneOnOne = (e: React.FormEvent) => {
    e.preventDefault();
    if (!oneOnOneText.trim()) return;
    createNote.mutate({
      text: oneOnOneText.trim(),
      person_id: person.id,
      is_one_on_one: true,
    });
    setOneOnOneText('');
  };

  const handleAddAsync = (e: React.FormEvent) => {
    e.preventDefault();
    if (!asyncText.trim()) return;
    createNote.mutate({
      text: asyncText.trim(),
      person_id: person.id,
      is_one_on_one: false,
    });
    setAsyncText('');
  };

  const startEditing = () => {
    setEditName(person.name);
    setEditTitle(person.title || '');
    setEditReportsTo(person.reports_to || '');
    setEditGroup(person.group_name || 'team');
    setEditCompany(person.company || '');
    setEditPhone(person.phone || '');
    setEditBio(person.bio || '');
    setEditLinkedin(person.linkedin_url || '');
    setEditIsCoworker(person.is_coworker ?? true);
    setEditing(true);
  };

  const saveEdits = () => {
    updatePerson.mutate({
      id: person.id,
      name: editName,
      title: editTitle || undefined,
      reports_to: editReportsTo || null,
      group_name: editGroup,
      company: editCompany || undefined,
      phone: editPhone || undefined,
      bio: editBio || undefined,
      linkedin_url: editLinkedin || undefined,
      is_coworker: editIsCoworker,
    });
    setEditing(false);
  };

  const handleDelete = () => {
    if (!confirm(`Delete ${person.name}? This will unlink their notes and remove all meeting data.`)) return;
    deletePerson.mutate(person.id, {
      onSuccess: () => navigate('/people'),
    });
  };

  const handleAddMeetingNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNoteDate) return;
    createOneOnOneNote.mutate({
      personId: person.id,
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
      personId: person.id,
      id: noteId,
      content: editNoteContent,
    });
    setEditingNoteId(null);
  };

  const otherPeople = allPeople?.filter((p) => p.id !== person.id) ?? [];

  return (
    <div>
      <div className="breadcrumb">
        <Link to="/people">People</Link>
        {person.reports_to && (
          <>
            {' / '}
            <Link to={`/people/${person.reports_to}`}>
              {person.reports_to.replace(/_/g, ' ')}
            </Link>
          </>
        )}
        {' / '}
        {person.name}
      </div>

      {/* Header */}
      {editing ? (
        <div className="person-edit-form">
          {/* Type toggle */}
          <div className="person-edit-type-row">
            <button
              className={`person-type-toggle ${editIsCoworker ? 'active' : ''}`}
              onClick={() => setEditIsCoworker(true)}
              type="button"
            >
              Coworker
            </button>
            <button
              className={`person-type-toggle ${!editIsCoworker ? 'active' : ''}`}
              onClick={() => setEditIsCoworker(false)}
              type="button"
            >
              Contact
            </button>
          </div>

          {/* Name — full width, prominent */}
          <input
            className="note-input person-edit-name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            placeholder="Full name"
            autoFocus
          />

          {/* Two-column fields */}
          <div className="person-edit-grid">
            <label className="person-edit-field">
              <span className="person-edit-label">Title</span>
              <input
                className="note-input"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                placeholder="Job title"
              />
            </label>
            <label className="person-edit-field">
              <span className="person-edit-label">Company</span>
              <input
                className="note-input"
                value={editCompany}
                onChange={(e) => setEditCompany(e.target.value)}
                placeholder="Company name"
              />
            </label>
            <label className="person-edit-field">
              <span className="person-edit-label">Phone</span>
              <input
                className="note-input"
                type="tel"
                value={editPhone}
                onChange={(e) => setEditPhone(e.target.value)}
                placeholder="+1 (555) 000-0000"
              />
            </label>
            <label className="person-edit-field">
              <span className="person-edit-label">LinkedIn</span>
              <input
                className="note-input"
                value={editLinkedin}
                onChange={(e) => setEditLinkedin(e.target.value)}
                placeholder="https://linkedin.com/in/..."
              />
            </label>
          </div>

          {/* Bio — full width */}
          <label className="person-edit-field" style={{ marginTop: 'var(--space-sm)' }}>
            <span className="person-edit-label">Bio</span>
            <textarea
              className="note-input"
              value={editBio}
              onChange={(e) => setEditBio(e.target.value)}
              placeholder="How you know this person, background, context..."
              rows={2}
              style={{ resize: 'vertical' }}
            />
          </label>

          {/* Org fields — contextual on coworker */}
          <div className="person-edit-org-row">
            <label className="person-edit-field" style={{ flex: 1 }}>
              <span className="person-edit-label">Group</span>
              <input
                list="edit-group-options"
                className="note-input"
                value={editGroup}
                onChange={(e) => setEditGroup(e.target.value)}
                placeholder={editIsCoworker ? 'team' : 'advisors, investors...'}
              />
              <datalist id="edit-group-options">
                {(groups ?? ['team']).map(g => <option key={g} value={g} />)}
              </datalist>
            </label>
            {editIsCoworker && (
              <label className="person-edit-field" style={{ flex: 1 }}>
                <span className="person-edit-label">Reports to</span>
                <select
                  className="note-input"
                  value={editReportsTo}
                  onChange={(e) => setEditReportsTo(e.target.value)}
                >
                  <option value="">No one</option>
                  {otherPeople.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {/* Actions */}
          <div className="person-edit-actions">
            <button className="btn-primary" onClick={saveEdits}>Save</button>
            <button className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn-danger" onClick={handleDelete} style={{ marginLeft: 'auto' }}>Delete</button>
          </div>
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-md)' }}>
            <h1 style={{ marginBottom: 0 }}>{person.name}</h1>
            <span className="note-badge" style={{ fontSize: 'var(--text-xs)' }}>
              {person.is_coworker ? 'coworker' : 'contact'}
            </span>
            <button
              className="btn-link"
              onClick={startEditing}
              style={{ fontSize: 'var(--text-sm)' }}
            >
              edit
            </button>
          </div>
          <p style={{ color: 'var(--color-text-muted)', marginTop: '4px', marginBottom: 'var(--space-xs)' }}>
            {[person.title, person.company].filter(Boolean).join(' \u2014 ')}
          </p>
          {/* Contact info row */}
          {(person.email || person.phone || person.linkedin_url) && (
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', display: 'flex', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
              {person.email && <span>{person.email}</span>}
              {person.phone && <span>{person.phone}</span>}
              {person.linkedin_url && (
                <a href={person.linkedin_url} target="_blank" rel="noopener noreferrer">LinkedIn</a>
              )}
            </div>
          )}
          {/* Bio */}
          {person.bio && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', marginTop: 'var(--space-sm)', fontStyle: 'italic' }}>
              {person.bio}
            </p>
          )}
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
        {person.is_coworker && (
          <button
            className={`tab ${activeTab === 'one-on-ones' ? 'active' : ''}`}
            onClick={() => setActiveTab('one-on-ones')}
          >
            1:1 Notes
          </button>
        )}
        {person.is_coworker && (
          <button
            className={`tab ${activeTab === 'team' ? 'active' : ''}`}
            onClick={() => setActiveTab('team')}
          >
            Team{person.direct_reports?.length > 0 && ` (${person.direct_reports.length})`}
          </button>
        )}
        {person.role_content && person.is_coworker && (
          <button
            className={`tab ${activeTab === 'role' ? 'active' : ''}`}
            onClick={() => setActiveTab('role')}
          >
            Role
          </button>
        )}
        <button
          className={`tab ${activeTab === 'connections' ? 'active' : ''}`}
          onClick={() => setActiveTab('connections')}
        >
          Connections{(person.connections?.length ?? 0) > 0 && ` (${person.connections.length})`}
        </button>
      </div>

      {/* === OVERVIEW TAB === */}
      {activeTab === 'overview' && (
        <>
          {/* Dashboard cards */}
          <div className="employee-dashboard">
            <div className="emp-card">
              <div className="emp-card-label">next meeting</div>
              {person.next_meeting ? (
                <div>
                  <div className="emp-card-value">
                    {formatRelativeDate(person.next_meeting.start_time)}
                  </div>
                  <div className="emp-card-detail">
                    {formatTime(person.next_meeting.start_time)}
                    {' \u2014 '}
                    {person.next_meeting.summary}
                  </div>
                  {person.next_meeting.html_link && (
                    <a
                      href={person.next_meeting.html_link}
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
              {(person.recent_meeting_summaries || []).length > 0 ? (
                (person.recent_meeting_summaries || []).map((m, i) => (
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
              {(oneOnOneNotes.length > 0 || otherNotes.length > 0) ? (
                <div className="emp-card-stats">
                  {person.is_coworker && (
                    <div>
                      <span className="emp-card-stat-number">{oneOnOneNotes.length}</span>
                      <span className="emp-card-stat-label">1:1 topics</span>
                    </div>
                  )}
                  <div>
                    <span className="emp-card-stat-number">{otherNotes.length}</span>
                    <span className="emp-card-stat-label">notes</span>
                  </div>
                </div>
              ) : (
                <div style={{ color: 'var(--color-text-light)', fontStyle: 'italic' }}>
                  None yet
                </div>
              )}
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
          {(person.linked_issues?.length ?? 0) > 0 && (
            <div className="employee-section">
              <h2>Issues</h2>
              {person.linked_issues.map((issue) => (
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

          {/* Linked longform posts */}
          {(person.linked_longform_posts?.length ?? 0) > 0 && (
            <div className="employee-section">
              <h2>Writing</h2>
              {person.linked_longform_posts.map((lp) => (
                <div key={lp.id} className="note-item">
                  <Link to={`/longform?postId=${lp.id}`} className="issue-title">
                    {lp.title}
                  </Link>
                  <span className={`longform-status-badge ${lp.status}`} style={{ marginLeft: '0.5em' }}>
                    {lp.status}
                  </span>
                  <span
                    style={{
                      color: 'var(--color-text-light)',
                      marginLeft: '0.5em',
                      fontSize: 'var(--text-xs)',
                    }}
                  >
                    {lp.word_count} words
                  </span>
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

          {/* Links */}
          <div className="employee-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h2>Links</h2>
              <button className="btn-link" onClick={() => setShowAddLink(!showAddLink)}>
                {showAddLink ? 'cancel' : '+ add link'}
              </button>
            </div>
            {showAddLink && (
              <form
                className="one-on-one-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!newLinkUrl.trim()) return;
                  createLink.mutate(
                    { personId: person.id, link_type: newLinkType, url: newLinkUrl.trim(), label: newLinkLabel.trim() || undefined },
                    { onSuccess: () => { setNewLinkUrl(''); setNewLinkLabel(''); setShowAddLink(false); } }
                  );
                }}
              >
                <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'end' }}>
                  <select
                    value={newLinkType}
                    onChange={(e) => setNewLinkType(e.target.value)}
                    style={{ width: 'auto' }}
                  >
                    <option value="linkedin">LinkedIn</option>
                    <option value="twitter">Twitter / X</option>
                    <option value="github">GitHub</option>
                    <option value="website">Website</option>
                    <option value="other">Other</option>
                  </select>
                  <input
                    className="note-input"
                    value={newLinkUrl}
                    onChange={(e) => setNewLinkUrl(e.target.value)}
                    placeholder="https://..."
                    style={{ flex: 1 }}
                    required
                  />
                  <input
                    className="note-input"
                    value={newLinkLabel}
                    onChange={(e) => setNewLinkLabel(e.target.value)}
                    placeholder="Label (optional)"
                    style={{ width: '150px' }}
                  />
                  <button className="btn-primary" type="submit">Add</button>
                </div>
              </form>
            )}
            {(person.links?.length ?? 0) > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-sm)' }}>
                {person.links.map((link: PersonLink) => (
                  <span key={link.id} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 'var(--space-xs)',
                    padding: '2px var(--space-sm)', border: '1px solid var(--color-border)',
                    fontSize: 'var(--text-sm)',
                  }}>
                    <a href={link.url} target="_blank" rel="noopener noreferrer">
                      {link.label || link.link_type}
                    </a>
                    <button
                      className="btn-link"
                      style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}
                      onClick={() => deleteLink.mutate({ personId: person.id, linkId: link.id })}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              !showAddLink && <p className="empty-state" style={{ padding: 'var(--space-sm) 0' }}>No links yet.</p>
            )}
          </div>

          {/* Attributes */}
          <div className="employee-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h2>Attributes</h2>
              <button className="btn-link" onClick={() => setShowAddAttr(!showAddAttr)}>
                {showAddAttr ? 'cancel' : '+ add attribute'}
              </button>
            </div>
            {showAddAttr && (
              <form
                className="one-on-one-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!newAttrKey.trim() || !newAttrValue.trim()) return;
                  createAttribute.mutate(
                    { personId: person.id, key: newAttrKey.trim(), value: newAttrValue.trim() },
                    { onSuccess: () => { setNewAttrKey(''); setNewAttrValue(''); setShowAddAttr(false); } }
                  );
                }}
              >
                <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'end' }}>
                  <input
                    className="note-input"
                    value={newAttrKey}
                    onChange={(e) => setNewAttrKey(e.target.value)}
                    placeholder="Key (e.g. Met at)"
                    style={{ width: '200px' }}
                    required
                  />
                  <input
                    className="note-input"
                    value={newAttrValue}
                    onChange={(e) => setNewAttrValue(e.target.value)}
                    placeholder="Value (e.g. SXSW 2025)"
                    style={{ flex: 1 }}
                    required
                  />
                  <button className="btn-primary" type="submit">Add</button>
                </div>
              </form>
            )}
            {(person.attributes?.length ?? 0) > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-sm)' }}>
                {person.attributes.map((attr: PersonAttribute) => (
                  <span key={attr.id} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 'var(--space-xs)',
                    padding: '2px var(--space-sm)', background: 'var(--color-bg-highlight, #fefaec)',
                    border: '1px solid var(--color-border)', fontSize: 'var(--text-sm)',
                  }}>
                    <strong>{attr.key}:</strong> {attr.value}
                    <button
                      className="btn-link"
                      style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}
                      onClick={() => deleteAttribute.mutate({ personId: person.id, attrId: attr.id })}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              !showAddAttr && <p className="empty-state" style={{ padding: 'var(--space-sm) 0' }}>No attributes yet.</p>
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
                  {m.external_link && (
                    <>
                      {' '}
                      &middot;{' '}
                      <a href={m.external_link} target="_blank" rel="noopener noreferrer">
                        {m.notes_provider ? m.notes_provider.charAt(0).toUpperCase() + m.notes_provider.slice(1) : 'Notes'}
                      </a>
                    </>
                  )}
                  {m.source !== 'file' && m.source !== 'manual' && !m.external_link && (
                    <span style={{ color: 'var(--color-text-light)' }}> ({m.notes_provider ? m.notes_provider.charAt(0).toUpperCase() + m.notes_provider.slice(1) : m.source})</span>
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
                                deleteOneOnOneNote.mutate({ personId: person.id, id: m.manualNote!.id });
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
            <h2>Reports to {person.name}</h2>
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
                createPerson.mutate(
                  {
                    name: newReportName.trim(),
                    group_name: person.group_name || 'team',
                    reports_to: person.id,
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

          {person.direct_reports?.length > 0 ? (
            <ul className="org-tree-list">
              {person.direct_reports.map((dr: { id: string; name: string; title?: string }) => (
                <li key={dr.id} className="org-tree-item">
                  <Link to={`/people/${dr.id}`} className="org-tree-name">
                    {dr.name}
                  </Link>
                  {dr.title && <span className="org-tree-title">{dr.title}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty-state">No one reports to {person.name} yet.</p>
          )}
        </div>
      )}

      {/* === ROLE TAB === */}
      {activeTab === 'role' && person.role_content && (
        <div className="employee-section">
          <h2>Role</h2>
          <MarkdownRenderer content={person.role_content} />
        </div>
      )}

      {/* === CONNECTIONS TAB === */}
      {activeTab === 'connections' && (
        <div className="employee-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <h2>Connections</h2>
            <button className="btn-link" onClick={() => setShowAddConn(!showAddConn)}>
              {showAddConn ? 'cancel' : '+ add connection'}
            </button>
          </div>

          {showAddConn && (
            <form
              className="one-on-one-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (!newConnPersonId) return;
                createConnection.mutate(
                  { personId: person.id, person_id: newConnPersonId, relationship: newConnRelationship.trim() || undefined },
                  { onSuccess: () => { setNewConnPersonId(''); setNewConnRelationship(''); setShowAddConn(false); } }
                );
              }}
            >
              <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'end' }}>
                <select
                  value={newConnPersonId}
                  onChange={(e) => setNewConnPersonId(e.target.value)}
                  required
                  style={{ flex: 1 }}
                >
                  <option value="">Select a person...</option>
                  {otherPeople
                    .filter(p => !person.connections?.some((c: PersonConnection) => c.person_id === p.id))
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.company ? ` (${p.company})` : ''}
                      </option>
                    ))}
                </select>
                <input
                  className="note-input"
                  value={newConnRelationship}
                  onChange={(e) => setNewConnRelationship(e.target.value)}
                  placeholder="Relationship (e.g. introduced by)"
                  style={{ flex: 1 }}
                />
                <button className="btn-primary" type="submit">Add</button>
              </div>
            </form>
          )}

          {(person.connections?.length ?? 0) > 0 ? (
            person.connections.map((conn: PersonConnection) => (
              <div key={conn.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: 'var(--space-sm) 0', borderBottom: '1px solid var(--color-border)',
              }}>
                <div>
                  <Link to={`/people/${conn.person_id}`} style={{ fontWeight: 500 }}>
                    {conn.person_name}
                  </Link>
                  {conn.relationship && (
                    <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginLeft: 'var(--space-sm)' }}>
                      {conn.relationship}
                    </span>
                  )}
                </div>
                <button
                  className="btn-link"
                  style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}
                  onClick={() => {
                    if (confirm(`Remove connection with ${conn.person_name}?`)) {
                      deleteConnection.mutate({ personId: person.id, connectionId: conn.id });
                    }
                  }}
                >
                  remove
                </button>
              </div>
            ))
          ) : (
            !showAddConn && <p className="empty-state">No connections yet.</p>
          )}
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

// Backward compat alias
export { PersonPage as EmployeePage };
