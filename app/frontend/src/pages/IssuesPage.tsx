import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  useIssues,
  useCreateIssue,
  useUpdateIssue,
  useDeleteIssue,
  useEmployees,
  useSearchMeetings,
} from '../api/hooks';
import type { Employee, Issue, MeetingSearchResult } from '../api/types';
import { parseIssuePrefix } from '../utils/parseIssuePrefix';
import { detectEmployees } from '../utils/detectEmployees';
import { useMentionAutocomplete } from '../hooks/useMentionAutocomplete';

const SIZE_LABELS: Record<string, string> = { s: 'S', m: 'M', l: 'L', xl: 'XL' };
const SIZES = ['s', 'm', 'l', 'xl'] as const;
const PRIORITIES = [0, 1, 2, 3] as const;
const STATUSES = [
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'done', label: 'Done' },
] as const;

function IssueItem({
  issue,
  isExpanded,
  isFocused,
  onToggleExpand,
  onUpdate,
  onDelete,
  employees,
  itemRef,
  titleInputRef,
}: {
  issue: Issue;
  isExpanded: boolean;
  isFocused: boolean;
  onToggleExpand: () => void;
  onUpdate: (update: Partial<Issue> & { employee_ids?: string[]; meeting_ids?: { ref_type: string; ref_id: string }[] }) => void;
  onDelete: () => void;
  employees: Employee[] | undefined;
  itemRef?: (el: HTMLDivElement | null) => void;
  titleInputRef?: (el: HTMLInputElement | null) => void;
}) {
  const [editTitle, setEditTitle] = useState(issue.title);
  const [editDesc, setEditDesc] = useState(issue.description);
  const [meetingQuery, setMeetingQuery] = useState('');
  const { data: meetingResults } = useSearchMeetings(meetingQuery);

  // Sync title/desc when issue prop changes (from server refetch)
  useEffect(() => {
    setEditTitle(issue.title);
    setEditDesc(issue.description);
  }, [issue.title, issue.description]);

  // Mention autocomplete for adding people
  const mention = useMentionAutocomplete(employees);
  const [addPersonText, setAddPersonText] = useState('');
  const addPersonDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mention.isOpen) return;
    const handler = (e: MouseEvent) => {
      if (addPersonDropdownRef.current && !addPersonDropdownRef.current.contains(e.target as Node)) {
        mention.dismiss();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mention.isOpen, mention.dismiss]);

  // Auto-save title on blur
  const handleTitleBlur = () => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== issue.title) {
      onUpdate({ title: trimmed });
    } else {
      setEditTitle(issue.title);
    }
  };

  // Auto-save description on blur
  const handleDescBlur = () => {
    if (editDesc !== issue.description) {
      onUpdate({ description: editDesc });
    }
  };

  // Immediate-save property changes
  const handleSizeClick = (s: Issue['tshirt_size']) => onUpdate({ tshirt_size: s });
  const handlePriorityClick = (p: number) => onUpdate({ priority: p });
  const handleStatusClick = (status: Issue['status']) => onUpdate({ status });

  const handleAddPerson = (empId: string) => {
    const currentIds = issue.employees.map((e) => e.id);
    if (!currentIds.includes(empId)) {
      onUpdate({ employee_ids: [...currentIds, empId] });
    }
    setAddPersonText('');
    mention.dismiss();
  };

  const handleRemovePerson = (empId: string) => {
    onUpdate({ employee_ids: issue.employees.filter((e) => e.id !== empId).map((e) => e.id) });
  };

  const handleAddMeeting = (meeting: MeetingSearchResult) => {
    const existing = issue.meetings.map((m) => ({ ref_type: m.ref_type, ref_id: m.ref_id }));
    const alreadyLinked = existing.some((m) => m.ref_type === meeting.ref_type && m.ref_id === meeting.ref_id);
    if (!alreadyLinked) {
      onUpdate({ meeting_ids: [...existing, { ref_type: meeting.ref_type, ref_id: meeting.ref_id }] });
    }
    setMeetingQuery('');
  };

  const handleRemoveMeeting = (refType: string, refId: string) => {
    onUpdate({
      meeting_ids: issue.meetings
        .filter((m) => !(m.ref_type === refType && m.ref_id === refId))
        .map((m) => ({ ref_type: m.ref_type, ref_id: m.ref_id })),
    });
  };

  return (
    <div ref={itemRef}>
      <div
        className={`issue-item ${issue.status === 'done' ? 'done' : ''} priority-p${issue.priority}${isFocused ? ' focused' : ''}`}
        onClick={onToggleExpand}
        style={{ cursor: 'pointer' }}
      >
        <input
          type="checkbox"
          checked={issue.status === 'done'}
          onClick={(e) => e.stopPropagation()}
          onChange={() => onUpdate({ status: issue.status === 'done' ? 'open' : 'done' })}
        />
        <span className={`issue-size-badge size-${issue.tshirt_size}`}>
          {SIZE_LABELS[issue.tshirt_size] || 'M'}
        </span>
        <div className="issue-title-row">
          <span className={`issue-title ${issue.status === 'done' ? 'done' : ''}`}>{issue.title}</span>
          <div className="note-meta">
            {issue.employees.map((emp, i) => (
              <span key={emp.id}>
                {i > 0 && ', '}
                <Link to={`/employees/${emp.id}`} onClick={(e) => e.stopPropagation()}>{emp.name}</Link>
              </span>
            ))}
            {issue.status === 'in_progress' && <span className="issue-status-badge status-in-progress">in progress</span>}
          </div>
        </div>
        <span className="issue-priority-label">P{issue.priority}</span>
      </div>

      {isExpanded && (
        <div className="issue-detail" onClick={(e) => e.stopPropagation()}>
          <div className="issue-detail-field">
            <input
              ref={titleInputRef}
              className="note-input issue-title-input"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onBlur={handleTitleBlur}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              placeholder="Issue title"
            />
          </div>

          <div className="issue-detail-field">
            <textarea
              value={editDesc}
              onChange={(e) => setEditDesc(e.target.value)}
              onBlur={handleDescBlur}
              placeholder="Description..."
              rows={3}
            />
          </div>

          <div className="issue-selectors">
            <div>
              <label className="issue-field-label">Size</label>
              <div className="size-selector">
                {SIZES.map((s) => (
                  <button key={s} type="button" className={issue.tshirt_size === s ? 'active' : ''} onClick={() => handleSizeClick(s)}>
                    {s.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="issue-field-label">Priority</label>
              <div className="priority-selector">
                {PRIORITIES.map((p) => (
                  <button key={p} type="button" className={issue.priority === p ? 'active' : ''} onClick={() => handlePriorityClick(p)}>
                    P{p}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="issue-field-label">Status</label>
              <div className="status-selector">
                {STATUSES.map((s) => (
                  <button key={s.value} type="button" className={issue.status === s.value ? 'active' : ''} onClick={() => handleStatusClick(s.value)}>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* People */}
          <div className="issue-detail-field">
            <label className="issue-field-label">People</label>
            <div className="issue-tag-list">
              {issue.employees.map((emp) => (
                <span key={emp.id} className="issue-person-tag">
                  <Link to={`/employees/${emp.id}`}>{emp.name}</Link>
                  <button type="button" onClick={() => handleRemovePerson(emp.id)}>&times;</button>
                </span>
              ))}
            </div>
            <div className="note-input-wrapper">
              <input
                ref={mention.inputRef}
                className="note-input issue-detail-input"
                value={addPersonText}
                onChange={(e) => { setAddPersonText(e.target.value); mention.handleChange(e.target.value); }}
                onKeyDown={(e) => mention.handleKeyDown(e, addPersonText, (t) => { setAddPersonText(t); mention.handleChange(t); })}
                placeholder="@ to add person..."
              />
              {mention.isOpen && (
                <div className="mention-dropdown" ref={addPersonDropdownRef}>
                  {mention.matches.map((emp, i) => (
                    <div
                      key={emp.id}
                      className={`mention-option ${i === mention.selectedIndex ? 'selected' : ''}`}
                      onMouseDown={(e) => { e.preventDefault(); handleAddPerson(emp.id); }}
                    >
                      <span className="mention-name">{emp.name}</span>
                      {emp.title && <span className="mention-title">{emp.title}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Meetings */}
          <div className="issue-detail-field">
            <label className="issue-field-label">Meetings</label>
            <div className="issue-tag-list">
              {issue.meetings.map((m) => (
                <span key={`${m.ref_type}-${m.ref_id}`} className="issue-meeting-tag">
                  {m.summary || 'Meeting'}
                  {m.start_time && ` (${new Date(m.start_time).toLocaleDateString()})`}
                  <button type="button" onClick={() => handleRemoveMeeting(m.ref_type, m.ref_id)}>&times;</button>
                </span>
              ))}
            </div>
            <div className="note-input-wrapper">
              <input
                className="note-input issue-detail-input"
                value={meetingQuery}
                onChange={(e) => setMeetingQuery(e.target.value)}
                placeholder="Search meetings to link..."
              />
              {meetingQuery && meetingResults && meetingResults.length > 0 && (
                <div className="mention-dropdown">
                  {meetingResults.map((m) => (
                    <div
                      key={`${m.ref_type}-${m.ref_id}`}
                      className="mention-option"
                      onMouseDown={(e) => { e.preventDefault(); handleAddMeeting(m); }}
                    >
                      <span className="mention-name">{m.summary}</span>
                      {m.start_time && <span className="mention-title">{new Date(m.start_time).toLocaleDateString()}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="issue-detail-actions">
            <div className="issue-detail-actions-left">
              <button type="button" className="btn-link" onClick={onToggleExpand}>Close</button>
            </div>
            <button type="button" className="btn-link issue-delete-btn" onClick={() => { if (confirm('Delete this issue?')) onDelete(); }}>
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function IssuesPage() {
  const [text, setText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('open');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: issues, isLoading } = useIssues({ status: statusFilter || undefined });
  const { data: employees } = useEmployees();
  const createIssue = useCreateIssue();
  const updateIssue = useUpdateIssue();
  const deleteIssue = useDeleteIssue();
  const dropdownRef = useRef<HTMLDivElement>(null);
  const createInputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());
  const titleInputRefs = useRef<Map<number, HTMLInputElement | null>>(new Map());

  const mention = useMentionAutocomplete(employees);
  const detected = employees ? detectEmployees(text, employees) : { employees: [], isOneOnOne: false };
  const parsed = useMemo(() => parseIssuePrefix(text.trim()), [text]);

  const allIssues = useMemo(() => issues ?? [], [issues]);

  // Keep focusedIndex in bounds when list changes
  useEffect(() => {
    if (allIssues.length === 0) {
      setFocusedIndex(-1);
    } else if (focusedIndex >= allIssues.length) {
      setFocusedIndex(allIssues.length - 1);
    }
  }, [allIssues.length, focusedIndex]);

  // Scroll focused item into view
  useEffect(() => {
    if (focusedIndex >= 0 && focusedIndex < allIssues.length) {
      const issue = allIssues[focusedIndex];
      const el = itemRefs.current.get(issue.id);
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [focusedIndex, allIssues]);

  // Deep-link: expand a specific issue from search
  useEffect(() => {
    const issueId = searchParams.get('issueId');
    if (issueId && issues) {
      const id = parseInt(issueId);
      const found = issues.find((i) => i.id === id);
      if (found) {
        setExpandedId(id);
        const idx = issues.indexOf(found);
        setFocusedIndex(idx);
        setSearchParams({}, { replace: true });
        setTimeout(() => {
          document.getElementById(`issue-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
      } else if (statusFilter !== '') {
        setStatusFilter('');
      }
    }
  }, [searchParams, issues, statusFilter, setSearchParams]);

  // Dismiss mention on outside click
  useEffect(() => {
    if (!mention.isOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        mention.dismiss();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mention.isOpen, mention.dismiss]);

  // Keyboard shortcuts for issues
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target as HTMLElement)?.isContentEditable;

      // Tab when expanded: focus the detail panel's title input instead of default tab order
      if (e.key === 'Tab' && !e.shiftKey && expandedId !== null && !inInput) {
        const titleEl = titleInputRefs.current.get(expandedId);
        if (titleEl) {
          e.preventDefault();
          titleEl.focus();
          return;
        }
      }

      // Escape always works — collapse detail panel even from inputs
      if (e.key === 'Escape') {
        if (expandedId !== null) {
          e.preventDefault();
          (e.target as HTMLElement)?.blur();
          setExpandedId(null);
          return;
        } else if (!inInput && focusedIndex >= 0) {
          e.preventDefault();
          setFocusedIndex(-1);
          return;
        }
      }

      // All other shortcuts skip when in inputs
      if (inInput) return;

      // Skip if meta/ctrl/alt (except shift for size shortcuts)
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const len = allIssues.length;
      if (!len) return;

      const getFocused = () => focusedIndex >= 0 && focusedIndex < len ? allIssues[focusedIndex] : null;

      switch (e.key) {
        case 'j':
        case 'ArrowDown': {
          e.preventDefault();
          e.stopImmediatePropagation();
          setFocusedIndex((i) => Math.min(i + 1, len - 1));
          break;
        }
        case 'k':
        case 'ArrowUp': {
          e.preventDefault();
          e.stopImmediatePropagation();
          setFocusedIndex((i) => (i <= 0 ? 0 : i - 1));
          break;
        }
        case 'Enter': {
          const issue = getFocused();
          if (issue) {
            e.preventDefault();
            setExpandedId((prev) => (prev === issue.id ? null : issue.id));
          }
          break;
        }
        // Escape handled above (works from inputs too)
        case 'x': {
          const issue = getFocused();
          if (issue) {
            e.preventDefault();
            updateIssue.mutate({ id: issue.id, status: issue.status === 'done' ? 'open' : 'done' });
          }
          break;
        }
        case 'Backspace':
        case 'Delete': {
          const issue = getFocused();
          if (issue) {
            e.preventDefault();
            if (confirm('Delete this issue?')) {
              deleteIssue.mutate(issue.id);
              if (expandedId === issue.id) setExpandedId(null);
            }
          }
          break;
        }
        case 'ArrowLeft': {
          const issue = getFocused();
          if (!issue) break;
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+Left: smaller size
            const idx = SIZES.indexOf(issue.tshirt_size);
            if (idx > 0) {
              updateIssue.mutate({ id: issue.id, tshirt_size: SIZES[idx - 1] });
            }
          } else {
            // Left: higher priority (lower P number)
            if (issue.priority > 0) {
              updateIssue.mutate({ id: issue.id, priority: issue.priority - 1 });
            }
          }
          break;
        }
        case 'ArrowRight': {
          const issue = getFocused();
          if (!issue) break;
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+Right: larger size
            const idx = SIZES.indexOf(issue.tshirt_size);
            if (idx < SIZES.length - 1) {
              updateIssue.mutate({ id: issue.id, tshirt_size: SIZES[idx + 1] });
            }
          } else {
            // Right: lower priority (higher P number)
            if (issue.priority < 3) {
              updateIssue.mutate({ id: issue.id, priority: issue.priority + 1 });
            }
          }
          break;
        }
        case '/':
        case 'i': {
          e.preventDefault();
          createInputRef.current?.focus();
          break;
        }
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [focusedIndex, expandedId, allIssues, updateIssue, deleteIssue]);

  const handleTextChange = (value: string) => {
    setText(value);
    mention.handleChange(value);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    if (mention.isOpen) return;

    const p = parseIssuePrefix(text.trim());
    const title = p.isIssue ? p.title : text.trim();
    const priority = p.isIssue ? p.priority : 1;
    const tshirtSize = p.isIssue ? p.tshirtSize : 'm';

    createIssue.mutate({
      title,
      priority,
      tshirt_size: tshirtSize,
      employee_ids: detected.employees.map((e) => e.id),
    });
    setText('');
  };

  // Callback ref for mention input that also stores in createInputRef
  const setInputRef = useCallback((el: HTMLInputElement | null) => {
    createInputRef.current = el;
    (mention.inputRef as React.MutableRefObject<HTMLInputElement | null>).current = el;
  }, [mention.inputRef]);

  return (
    <div>
      <h1>Issues</h1>

      <form onSubmit={handleSubmit}>
        <div className="note-input-wrapper">
          <input
            ref={setInputRef}
            className="note-input"
            value={text}
            onChange={(e) => handleTextChange(e.target.value)}
            onKeyDown={(e) => {
              // Arrow down/up from create input → navigate issue list
              if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !mention.isOpen && allIssues.length > 0) {
                e.preventDefault();
                createInputRef.current?.blur();
                setFocusedIndex(e.key === 'ArrowDown' ? 0 : allIssues.length - 1);
                return;
              }
              mention.handleKeyDown(e, text, (t) => { setText(t); mention.handleChange(t); });
            }}
            placeholder="Add an issue... (@ to mention, [s/m/l/xl] size, [p0-p3] priority)"
            autoFocus
          />
          {mention.isOpen && (
            <div className="mention-dropdown" ref={dropdownRef}>
              {mention.matches.map((emp, i) => (
                <div
                  key={emp.id}
                  className={`mention-option ${i === mention.selectedIndex ? 'selected' : ''}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    const newText = mention.selectEmployee(text, emp);
                    setText(newText);
                    mention.handleChange(newText);
                    createInputRef.current?.focus();
                  }}
                >
                  <span className="mention-name">{emp.name}</span>
                  {emp.title && <span className="mention-title">{emp.title}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
        {!mention.isOpen && (parsed.isIssue || detected.employees.length > 0) && (
          <span className="note-link-hint">
            {parsed.isIssue
              ? `Size: ${parsed.tshirtSize.toUpperCase()} / P${parsed.priority}`
              : ''}
            {detected.employees.length > 0 && (
              parsed.isIssue
                ? ` — tagged: ${detected.employees.map((e) => e.name).join(', ')}`
                : `Tagged: ${detected.employees.map((e) => e.name).join(', ')}`
            )}
          </span>
        )}
      </form>

      <div className="filters" style={{ marginTop: 'var(--space-lg)' }}>
        {[
          { value: 'open', label: 'open' },
          { value: 'in_progress', label: 'in progress' },
          { value: 'done', label: 'done' },
          { value: '', label: 'all' },
        ].map((s) => (
          <button
            key={s.value}
            className={`filter-btn ${statusFilter === s.value ? 'active' : ''}`}
            onClick={() => setStatusFilter(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {isLoading && <p className="empty-state">Loading...</p>}

      <div style={{ marginTop: 'var(--space-md)' }}>
        {allIssues.map((issue, idx) => (
          <div key={issue.id} id={`issue-${issue.id}`}>
            <IssueItem
              issue={issue}
              isExpanded={expandedId === issue.id}
              isFocused={focusedIndex === idx}
              onToggleExpand={() => {
                setFocusedIndex(idx);
                setExpandedId(expandedId === issue.id ? null : issue.id);
              }}
              onUpdate={(update) => updateIssue.mutate({ id: issue.id, ...update })}
              onDelete={() => { deleteIssue.mutate(issue.id); setExpandedId(null); }}
              employees={employees}
              itemRef={(el) => { itemRefs.current.set(issue.id, el); }}
              titleInputRef={(el) => { titleInputRefs.current.set(issue.id, el); }}
            />
          </div>
        ))}
        {allIssues.length === 0 && !isLoading && (
          <p className="empty-state">
            {statusFilter === 'open' ? 'No open issues.' : 'No issues found.'}
          </p>
        )}
      </div>

      <div className="issue-shortcuts-hint">
        <kbd>j</kbd><kbd>k</kbd> navigate &middot; <kbd>Enter</kbd> expand &middot; <kbd>Tab</kbd> edit &middot; <kbd>x</kbd> done &middot; <kbd>&larr;</kbd><kbd>&rarr;</kbd> priority &middot; <kbd>Shift+&larr;</kbd><kbd>Shift+&rarr;</kbd> size &middot; <kbd>i</kbd> new issue
      </div>
    </div>
  );
}
