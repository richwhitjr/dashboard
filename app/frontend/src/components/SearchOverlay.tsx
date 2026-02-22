import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSearch, useCreateNote, useCreateIssue, useEmployees } from '../api/hooks';
import { openExternal } from '../api/client';
import { detectEmployees } from '../utils/detectEmployees';
import { parseIssuePrefix } from '../utils/parseIssuePrefix';
import { MarkdownRenderer } from './shared/MarkdownRenderer';
import { SHORTCUT_DEFINITIONS } from '../hooks/useKeyboardShortcuts';
import { sanitizeHtml } from '../utils/sanitize';

type FlatResult = {
  category: string;
  type: string;
  id: string;
  label: string;
  sublabel?: string;
  snippet?: string;
  navigateTo: string;
  externalUrl?: string;
  highlightHtml?: string;
  // Full content for preview panel
  fullText?: string;
  fullHtml?: string;
  date?: string;
  status?: string;
  action?: () => void;
};

// Pages available as quick-nav commands
const PAGE_COMMANDS: { label: string; sublabel: string; route: string; keywords: string[]; externalUrl?: string }[] = [
  { label: 'Dashboard', sublabel: 'Home overview', route: '/', keywords: ['dashboard', 'home', 'overview'] },
  { label: 'Priorities', sublabel: 'AI morning briefing', route: '/priorities', keywords: ['priorities', 'briefing', 'morning', 'today'] },
  { label: 'Notes', sublabel: 'Add and manage notes', route: '/notes?focus=1', keywords: ['notes', 'note', 'todo', 'todos'] },
  { label: 'Thoughts', sublabel: 'Add a thought', route: '/thoughts?focus=1', keywords: ['thoughts', 'thought', 'think'] },
  { label: 'Issues', sublabel: 'Track work items', route: '/issues', keywords: ['issues', 'issue', 'bugs', 'tasks', 'work'] },
  { label: 'Meetings', sublabel: 'Calendar and meeting notes', route: '/meetings', keywords: ['meetings', 'meeting', 'calendar'] },
  { label: 'Email', sublabel: 'Prioritized email', route: '/email', keywords: ['email', 'gmail', 'inbox', 'mail'] },
  { label: 'News', sublabel: 'News feed', route: '/news', keywords: ['news', 'feed'] },
  { label: 'Team', sublabel: 'Org chart', route: '/team', keywords: ['team', 'org', 'people', 'chart'] },
  { label: 'GitHub', sublabel: 'Pull requests and code', route: '/github', keywords: ['github', 'pr', 'pull', 'code'] },
  { label: 'Claude', sublabel: 'Claude Code terminal', route: '/claude', keywords: ['claude', 'terminal', 'ai'] },
  { label: 'Slack', sublabel: 'Slack messages overview', route: '/slack', keywords: ['slack', 'messages', 'dms'] },
  { label: 'Notion', sublabel: 'Notion pages overview', route: '/notion', keywords: ['notion', 'docs', 'wiki'] },
  { label: 'Settings', sublabel: 'Auth and sync', route: '/settings', keywords: ['settings', 'config', 'auth', 'sync'] },
  { label: 'Help', sublabel: 'App intro and guide', route: '/help', keywords: ['help', 'intro', 'guide', 'about'] },
  { label: 'Keyboard Shortcuts', sublabel: 'Show all shortcuts', route: '__help__', keywords: ['keyboard', 'shortcuts', 'keys', 'hotkeys', '?'] },
];

interface SearchOverlayProps {
  isOpen: boolean;
  onClose: () => void;
  onHelpOpen?: () => void;
}

type OverlayMode = 'search' | 'note';

export function SearchOverlay({ isOpen, onClose, onHelpOpen }: SearchOverlayProps) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<OverlayMode>('search');
  const [includeExternal, setIncludeExternal] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [preview, setPreview] = useState<FlatResult | null>(null);
  const [addedConfirmation, setAddedConfirmation] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const createNote = useCreateNote();
  const createIssue = useCreateIssue();
  const { data: employees } = useEmployees();

  // Mention autocomplete state (note mode only)
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState(-1);
  const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);

  const mentionMatches = useMemo(() => {
    if (mode !== 'note' || mentionQuery === null || !employees) return [];
    return employees.filter(e =>
      mentionQuery === '' ||
      e.name.toLowerCase().includes(mentionQuery.toLowerCase()) ||
      e.name.toLowerCase().split(' ')[0].startsWith(mentionQuery.toLowerCase())
    );
  }, [mode, mentionQuery, employees]);

  const mentionOpen = mentionQuery !== null && mentionMatches.length > 0;

  const handleMentionChange = useCallback((text: string) => {
    const input = inputRef.current;
    if (!input) return;
    const cursor = input.selectionStart ?? text.length;
    const before = text.slice(0, cursor);
    const atIndex = before.lastIndexOf('@');
    if (atIndex >= 0 && (atIndex === 0 || before[atIndex - 1] === ' ')) {
      const mq = before.slice(atIndex + 1);
      if (!mq.includes(' ') || mq.length <= 20) {
        setMentionQuery(mq);
        setMentionStart(atIndex);
        setMentionSelectedIndex(0);
        return;
      }
    }
    setMentionQuery(null);
    setMentionStart(-1);
  }, []);

  const completeMention = useCallback((emp: { id: string; name: string }) => {
    const firstName = emp.name.split(' ')[0];
    const cursor = inputRef.current?.selectionStart ?? query.length;
    const before = query.slice(0, mentionStart);
    const after = query.slice(cursor);
    const newText = `${before}@${firstName} ${after}`;
    setQuery(newText);
    setMentionQuery(null);
    setMentionStart(-1);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [query, mentionStart]);

  // Note context (derived state for note mode)
  const noteContext = useMemo(() => {
    if (mode !== 'note') return null;
    const trimmed = query.trim();
    if (!trimmed) return null;
    const isThought = trimmed.startsWith('[t]') || trimmed.startsWith('[T]');
    const isOneOnOne = trimmed.startsWith('[1]');
    const detected = employees ? detectEmployees(trimmed, employees) : { employees: [], isOneOnOne: false };
    return {
      isThought,
      isOneOnOne: isOneOnOne || detected.isOneOnOne,
      linkedEmployees: detected.employees,
      noteType: isThought ? 'thought' : (isOneOnOne || detected.isOneOnOne) ? '1:1 topic' : 'note',
    };
  }, [mode, query, employees]);

  // Debounce: only search after 150ms of idle typing
  const [debouncedQuery, setDebouncedQuery] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 150);
    return () => clearTimeout(timer);
  }, [query]);

  const { data: localResults, isLoading: localLoading } = useSearch(
    debouncedQuery,
    { sources: 'all', includeExternal: false, enabled: isOpen && mode === 'search' && debouncedQuery.length > 0 }
  );

  const { data: externalResults, isLoading: externalLoading } = useSearch(
    debouncedQuery,
    { sources: 'all', includeExternal: true, enabled: isOpen && mode === 'search' && includeExternal && debouncedQuery.length > 1 }
  );

  // Match page commands against current query
  const matchedPages = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return PAGE_COMMANDS; // Show all when empty
    return PAGE_COMMANDS.filter(
      (p) =>
        p.label.toLowerCase().includes(q) ||
        p.keywords.some((k) => k.includes(q))
    );
  }, [query]);

  // Flatten all results into a single navigable list
  const flatResults: FlatResult[] = useMemo(() => {
    const flat: FlatResult[] = [];

    // Page commands first
    for (const page of matchedPages) {
      const isSpecial = page.route.startsWith('__');
      flat.push({
        category: 'Go to',
        type: 'page',
        id: page.label,
        label: page.label,
        sublabel: page.sublabel,
        navigateTo: isSpecial ? '/' : page.route,
        externalUrl: page.externalUrl,
        action: page.route === '__help__' ? onHelpOpen : undefined,
      });
    }

    // Keyboard shortcut commands (navigation only, shown when query matches)
    const ql = query.trim().toLowerCase();
    if (ql) {
      for (const s of SHORTCUT_DEFINITIONS) {
        if (s.category !== 'navigation') continue;
        const desc = s.description.toLowerCase();
        if (desc.includes(ql) || s.keys.toLowerCase().includes(ql)) {
          flat.push({
            category: 'Shortcuts',
            type: 'shortcut',
            id: `shortcut-${s.keys}`,
            label: s.description,
            sublabel: s.keys,
            navigateTo: '/',
          });
        }
      }
    }

    // Then search results (only when there's a query with results)
    const data = includeExternal && externalResults ? externalResults : localResults;
    if (!data) return flat;
    const r = data.results;

    // People
    for (const emp of r.employees ?? []) {
      flat.push({
        category: 'People',
        type: 'employee',
        id: emp.id,
        label: emp.name,
        sublabel: emp.title,
        navigateTo: `/employees/${emp.id}`,
        highlightHtml: emp.name_hl,
      });
    }

    // Notes
    for (const note of r.notes ?? []) {
      const isThought = note.text.startsWith('[t]') || note.text.startsWith('[T]');
      const cleanText = note.text.replace(/^\[[tT1]\]\s*/, '');
      const prefix = note.is_one_on_one ? '[1:1] ' : isThought ? '~ ' : '';
      flat.push({
        category: 'Notes',
        type: 'note',
        id: String(note.id),
        label: `${prefix}${cleanText.slice(0, 100)}`,
        sublabel: note.employee_name ?? undefined,
        navigateTo: isThought ? `/thoughts?noteId=${note.id}` : `/notes?noteId=${note.id}`,
        highlightHtml: note.text_hl,
        fullText: note.text,
        date: note.created_at,
        status: note.status,
      });
    }

    // Issues
    for (const iss of r.issues ?? []) {
      const sizeLabel = (iss.tshirt_size || 'm').toUpperCase();
      flat.push({
        category: 'Issues',
        type: 'issue',
        id: String(iss.id),
        label: `[${sizeLabel}] P${iss.priority} ${iss.title}`,
        sublabel: iss.status,
        navigateTo: `/issues?issueId=${iss.id}`,
        highlightHtml: iss.title_hl ? `[${sizeLabel}] P${iss.priority} ${iss.title_hl}` : undefined,
        fullText: iss.description || undefined,
        date: iss.created_at,
        status: iss.status,
      });
    }

    // Granola meetings
    for (const gm of r.granola_meetings ?? []) {
      const meetingDate = gm.created_at?.split('T')[0] || '';
      flat.push({
        category: 'Meetings',
        type: 'granola',
        id: gm.id,
        label: gm.title,
        sublabel: gm.employee_name ?? undefined,
        snippet: gm.summary_snippet ?? undefined,
        navigateTo: gm.employee_id
          ? `/employees/${gm.employee_id}?meetingDate=${meetingDate}&meetingSource=granola`
          : '/',
        externalUrl: gm.employee_id ? undefined : (gm.granola_link ?? undefined),
        highlightHtml: gm.title_hl,
        fullText: gm.summary_snippet ?? undefined,
        date: meetingDate,
      });
    }

    // Meeting files
    for (const mf of r.meeting_files ?? []) {
      flat.push({
        category: 'Meetings',
        type: 'meeting_file',
        id: String(mf.id),
        label: mf.title,
        sublabel: [mf.employee_name, mf.meeting_date].filter(Boolean).join(' \u2014 '),
        snippet: mf.summary_snippet ?? undefined,
        navigateTo: `/employees/${mf.employee_id}?meetingDate=${mf.meeting_date}&meetingSource=file`,
        highlightHtml: mf.title_hl,
        fullText: mf.summary_snippet ?? undefined,
        date: mf.meeting_date,
      });
    }

    // 1:1 notes
    for (const oo of r.one_on_one_notes ?? []) {
      flat.push({
        category: '1:1 Notes',
        type: 'one_on_one',
        id: String(oo.id),
        label: oo.title || `1:1 on ${oo.meeting_date}`,
        sublabel: oo.employee_name ?? undefined,
        snippet: oo.content_snippet ?? undefined,
        navigateTo: `/employees/${oo.employee_id}?meetingDate=${oo.meeting_date}&meetingSource=manual`,
        highlightHtml: oo.title_hl,
        fullText: oo.content_snippet ?? undefined,
        date: oo.meeting_date,
      });
    }

    // Emails (local FTS search)
    for (const em of r.emails ?? []) {
      flat.push({
        category: 'Email',
        type: 'email',
        id: em.id,
        label: em.subject,
        sublabel: em.from_name || em.from_email,
        snippet: em.snippet_hl ?? em.snippet ?? undefined,
        navigateTo: '/email',
        externalUrl: `https://mail.google.com/mail/u/0/#inbox/${em.thread_id || em.id}`,
        highlightHtml: em.subject_hl,
        date: em.date,
      });
    }

    // External results (when toggled on)
    if (includeExternal && externalResults) {
      const ext = externalResults.results;
      for (const item of ext.gmail?.items ?? []) {
        flat.push({
          category: 'Gmail',
          type: 'gmail',
          id: item.id,
          label: item.title,
          sublabel: item.subtitle,
          snippet: item.snippet,
          navigateTo: '/',
          externalUrl: `https://mail.google.com/mail/#inbox/${item.id}`,
        });
      }
      for (const item of ext.calendar?.items ?? []) {
        flat.push({
          category: 'Calendar',
          type: 'calendar',
          id: item.id,
          label: item.title,
          sublabel: item.date,
          navigateTo: '/',
          externalUrl: item.url,
        });
      }
      for (const item of ext.slack?.items ?? []) {
        flat.push({
          category: 'Slack',
          type: 'slack',
          id: item.id,
          label: item.title || item.snippet?.slice(0, 80) || 'Message',
          sublabel: item.subtitle,
          snippet: item.snippet,
          navigateTo: '/',
          externalUrl: item.permalink,
        });
      }
      for (const item of ext.notion?.items ?? []) {
        flat.push({
          category: 'Notion',
          type: 'notion',
          id: item.id,
          label: item.title,
          navigateTo: '/',
          externalUrl: item.url,
        });
      }
    }

    // "Add as note/issue" action — shown whenever there's non-empty input text
    const trimmedQuery = query.trim();
    if (trimmedQuery.length > 0) {
      const isThought = trimmedQuery.startsWith('[t]') || trimmedQuery.startsWith('[T]');
      const isOneOnOne = trimmedQuery.startsWith('[1]');
      const parsedQuery = parseIssuePrefix(trimmedQuery);
      let sublabel = '\u2318Enter';
      if (parsedQuery.isIssue) sublabel += ` \u2014 ${parsedQuery.tshirtSize.toUpperCase()} / P${parsedQuery.priority}`;
      else if (isThought) sublabel += ' \u2014 thought';
      else if (isOneOnOne) sublabel += ' \u2014 1:1 topic';

      const addLabel = parsedQuery.isIssue ? 'Add as issue' : 'Add as note';
      const displayText = parsedQuery.isIssue ? parsedQuery.title : trimmedQuery;
      flat.push({
        category: 'Quick add',
        type: 'add_note',
        id: '__add_note__',
        label: `${addLabel}: ${displayText.length > 80 ? displayText.slice(0, 80) + '\u2026' : displayText}`,
        sublabel,
        navigateTo: parsedQuery.isIssue ? '/issues' : '/notes',
      });
    }

    return flat;
  }, [localResults, externalResults, includeExternal, matchedPages, query, onHelpOpen]);

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0);
  }, [flatResults]);

  // Focus input when opened; clear preview; reset mode
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setDebouncedQuery('');
      setMode('search');
      setSelectedIndex(0);
      setPreview(null);
      setAddedConfirmation(null);
      setMentionQuery(null);
      setMentionStart(-1);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [isOpen]);

  // Scroll selected item into view
  useEffect(() => {
    const item = listRef.current?.querySelector('.search-result-item.selected');
    item?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  // Types that show a preview panel instead of navigating away
  const isPreviewable = (type: string) =>
    type === 'note' || type === 'granola' || type === 'meeting_file' || type === 'one_on_one';

  const handleAddNote = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed || createNote.isPending || createIssue.isPending) return;

    const detected = employees ? detectEmployees(trimmed, employees) : { employees: [], isOneOnOne: false };
    const parsed = parseIssuePrefix(trimmed);

    const onSuccess = () => {
      setAddedConfirmation(parsed.isIssue ? `Issue: ${parsed.title}` : trimmed);
      setQuery('');
      setDebouncedQuery('');
      setTimeout(() => {
        setAddedConfirmation(null);
        onClose();
      }, 1200);
    };

    if (parsed.isIssue) {
      createIssue.mutate(
        {
          title: parsed.title,
          priority: parsed.priority,
          tshirt_size: parsed.tshirtSize,
          employee_ids: detected.employees.map((e) => e.id),
        },
        { onSuccess }
      );
    } else {
      createNote.mutate(
        {
          text: trimmed,
          employee_ids: detected.employees.map((e) => e.id),
          is_one_on_one: detected.isOneOnOne,
        },
        { onSuccess }
      );
    }
  }, [query, employees, createNote, createIssue, onClose]);

  const handleSelect = useCallback((result: FlatResult) => {
    if (result.type === 'add_note') {
      handleAddNote();
      return;
    }
    if (result.action) {
      onClose();
      result.action();
      return;
    }
    if (result.externalUrl) {
      onClose();
      openExternal(result.externalUrl);
    } else if (isPreviewable(result.type)) {
      setPreview(result);
    } else {
      onClose();
      navigate(result.navigateTo);
    }
  }, [navigate, onClose, handleAddNote]);

  const handleNavigate = useCallback((result: FlatResult) => {
    onClose();
    navigate(result.navigateTo);
  }, [navigate, onClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Preview state (unchanged)
    if (preview) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setPreview(null);
        setTimeout(() => inputRef.current?.focus(), 0);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        handleNavigate(preview);
      }
      return;
    }

    // Cmd+E: toggle external search (both modes)
    if ((e.metaKey || e.ctrlKey) && e.key === 'e') {
      e.preventDefault();
      setIncludeExternal(prev => !prev);
      return;
    }

    if (mode === 'note') {
      // --- NOTE MODE ---
      // Mention autocomplete takes priority
      if (mentionOpen) {
        if (e.key === 'ArrowDown') { e.preventDefault(); setMentionSelectedIndex(i => Math.min(i + 1, mentionMatches.length - 1)); return; }
        if (e.key === 'ArrowUp') { e.preventDefault(); setMentionSelectedIndex(i => Math.max(i - 1, 0)); return; }
        if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); completeMention(mentionMatches[mentionSelectedIndex]); return; }
        if (e.key === 'Escape') { e.preventDefault(); setMentionQuery(null); setMentionStart(-1); return; }
      }
      // Tab: exit note mode back to search
      if (e.key === 'Tab') {
        e.preventDefault();
        setMode('search');
        setMentionQuery(null);
        setMentionStart(-1);
        setTimeout(() => inputRef.current?.focus(), 0);
        return;
      }
      // Enter: submit note
      if (e.key === 'Enter' && query.trim()) {
        e.preventDefault();
        handleAddNote();
        return;
      }
      // Escape: back to search mode
      if (e.key === 'Escape') {
        e.preventDefault();
        setMode('search');
        setQuery('');
        setDebouncedQuery('');
        setMentionQuery(null);
        setMentionStart(-1);
        setTimeout(() => inputRef.current?.focus(), 0);
        return;
      }
      return;
    }

    // --- SEARCH MODE ---
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => Math.min(i + 1, flatResults.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && e.metaKey && query.trim()) {
      e.preventDefault();
      handleAddNote();
    } else if (e.key === 'Enter' && flatResults.length > 0) {
      e.preventDefault();
      handleSelect(flatResults[selectedIndex]);
    } else if (e.key === 'Escape') {
      onClose();
    } else if (e.key === 'Tab') {
      e.preventDefault();
      setMode('note');
      setSelectedIndex(0);
    }
  }, [mode, flatResults, selectedIndex, handleSelect, handleNavigate, handleAddNote, onClose, preview, query, mentionOpen, mentionMatches, mentionSelectedIndex, completeMention]);

  if (!isOpen) return null;

  // Group results by category for rendering
  const grouped = new Map<string, { items: FlatResult[]; startIndex: number }>();
  let globalIdx = 0;
  for (const r of flatResults) {
    if (!grouped.has(r.category)) {
      grouped.set(r.category, { items: [], startIndex: globalIdx });
    }
    grouped.get(r.category)!.items.push(r);
    globalIdx++;
  }

  const isLoading = localLoading || (includeExternal && externalLoading);

  return (
    <div className="search-overlay" onClick={onClose}>
      <div className={`search-modal ${mode === 'note' ? 'search-modal--note-mode' : ''}`} onClick={e => e.stopPropagation()}>
        <div className="search-input-row">
          {mode === 'note' && (
            <span className="search-mode-badge">Note</span>
          )}
          <input
            ref={inputRef}
            className="search-input"
            value={query}
            onChange={e => {
              setQuery(e.target.value);
              setPreview(null);
              if (mode === 'note') handleMentionChange(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            placeholder={mode === 'note'
              ? 'Type a note... (@name to link, [1] for 1:1, [t] for thought)'
              : 'Search or jump to...'}
            autoComplete="off"
            spellCheck={mode === 'note'}
          />
          {mode === 'search' && (
            <button
              className={`search-external-toggle ${includeExternal ? 'active' : ''}`}
              onClick={() => setIncludeExternal(prev => !prev)}
              title="Toggle external search (Gmail, Slack, Calendar, Notion) — Cmd+E"
            >
              {includeExternal ? 'External on' : 'External off'}
            </button>
          )}
        </div>

        {mode === 'search' && isLoading && query && (
          <div className="search-loading">Searching...</div>
        )}

        {/* Confirmation after adding a note */}
        {addedConfirmation ? (
          <div className="search-note-added">
            <span className="search-note-added-icon">&#x2713;</span>
            <span>Note added</span>
          </div>
        ) : mode === 'note' ? (
          /* --- NOTE MODE BODY --- */
          <>
            <div className="search-note-compose">
              {query.trim() ? (
                <div className="search-note-context">
                  <span className={`note-type-badge ${noteContext?.isThought ? 'thought' : noteContext?.isOneOnOne ? 'one-on-one' : ''}`}>
                    {noteContext?.noteType}
                  </span>
                  {noteContext && noteContext.linkedEmployees.length > 0 && (
                    <div className="search-note-linked">
                      Linked to: {noteContext.linkedEmployees.map(e => e.name).join(', ')}
                    </div>
                  )}
                </div>
              ) : (
                <div className="search-note-help">
                  <p>Start typing your note.</p>
                  <p className="search-note-help-hint">
                    <code>@name</code> to link to a person &middot; <code>[1]</code> prefix for 1:1 topic &middot; <code>[t]</code> prefix for thought
                  </p>
                </div>
              )}
              {mentionOpen && (
                <div className="search-mention-dropdown">
                  {mentionMatches.map((emp, i) => (
                    <div
                      key={emp.id}
                      className={`mention-option ${i === mentionSelectedIndex ? 'selected' : ''}`}
                      onMouseEnter={() => setMentionSelectedIndex(i)}
                      onClick={() => completeMention(emp)}
                    >
                      <span className="mention-name">{emp.name}</span>
                      <span className="mention-title">{emp.title}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="search-footer">
              <span className="search-hint">
                {query.trim() && (
                  <>
                    <kbd>Enter</kbd> add note
                    &nbsp;&middot;&nbsp;
                  </>
                )}
                <kbd>@name</kbd> link person
                &nbsp;&middot;&nbsp;
                <kbd>Esc</kbd> back to search
              </span>
            </div>
          </>
        ) : preview ? (
          <div className="search-preview">
            <div className="search-preview-header">
              <button
                className="search-preview-back"
                onClick={() => { setPreview(null); setTimeout(() => inputRef.current?.focus(), 0); }}
              >
                &larr; Back
              </button>
              <span className="search-preview-type">{preview.category}</span>
            </div>
            <div className="search-preview-title">{preview.label}</div>
            {preview.sublabel && (
              <div className="search-preview-meta">{preview.sublabel}</div>
            )}
            {preview.date && (
              <div className="search-preview-meta">{preview.date}</div>
            )}
            {preview.status && (
              <div className="search-preview-meta">Status: {preview.status}</div>
            )}
            <div className="search-preview-content">
              {preview.fullHtml ? (
                <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(preview.fullHtml) }} />
              ) : preview.fullText ? (
                <MarkdownRenderer content={preview.fullText} />
              ) : preview.snippet ? (
                <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(preview.snippet) }} />
              ) : (
                <p className="empty-state">No preview available.</p>
              )}
            </div>
            <div className="search-preview-actions">
              <button onClick={() => handleNavigate(preview)}>
                Go to page &rarr;
              </button>
            </div>
            <div className="search-footer">
              <span className="search-hint">
                <kbd>Esc</kbd> back to results
                &nbsp;&middot;&nbsp;
                <kbd>Enter</kbd> go to page
              </span>
            </div>
          </div>
        ) : (
          <>
            <div className="search-results" ref={listRef}>
              {query && !isLoading && flatResults.length === 0 && (
                <div className="search-empty">No results for &ldquo;{query}&rdquo;</div>
              )}

              {[...grouped.entries()].map(([category, { items, startIndex }]) => (
                <div key={category} className="search-category">
                  <div className="search-category-label">{category}</div>
                  {items.map((item, i) => {
                    const idx = startIndex + i;
                    return (
                      <div
                        key={`${item.type}-${item.id}`}
                        className={`search-result-item ${idx === selectedIndex ? 'selected' : ''} ${item.type === 'add_note' ? 'add-note-item' : ''}`}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => handleSelect(item)}
                      >
                        <div className="search-result-main">
                          <span className="search-result-label">
                            {item.highlightHtml ? (
                              <span dangerouslySetInnerHTML={{ __html: sanitizeHtml(item.highlightHtml) }} />
                            ) : (
                              item.label
                            )}
                          </span>
                          {item.sublabel && (
                            <span className="search-result-sublabel">{item.sublabel}</span>
                          )}
                          {item.externalUrl && (
                            <span className="search-result-external-icon" title="Opens externally">&#x2197;</span>
                          )}
                        </div>
                        {item.snippet && (
                          <div
                            className="search-result-snippet"
                            dangerouslySetInnerHTML={{ __html: sanitizeHtml(item.snippet) }}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="search-footer">
              <span className="search-hint">
                <kbd>&uarr;</kbd><kbd>&darr;</kbd> navigate
                &nbsp;&middot;&nbsp;
                <kbd>Enter</kbd> open
                {query.trim() && (
                  <>
                    &nbsp;&middot;&nbsp;
                    <kbd>&#x2318;Enter</kbd> add note
                  </>
                )}
                &nbsp;&middot;&nbsp;
                <kbd>Tab</kbd> note mode
                &nbsp;&middot;&nbsp;
                <kbd>&#x2318;E</kbd> external
                &nbsp;&middot;&nbsp;
                <kbd>Esc</kbd> close
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
