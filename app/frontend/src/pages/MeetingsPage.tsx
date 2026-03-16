import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMeetings, useUpsertMeetingNote, useDeleteMeetingNote, useDismissPrioritizedItem, useProfile, useAllMeetingNotes } from '../api/hooks';
import type { MeetingWithContext } from '../api/types';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import { InfiniteScrollSentinel } from '../components/shared/InfiniteScrollSentinel';
import { sanitizeHtml } from '../utils/sanitize';

const TZ = 'America/New_York';

function getHourInTZ(d: Date): number {
  return parseInt(d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: false, timeZone: TZ }), 10);
}

function getMinuteInTZ(d: Date): number {
  return parseInt(d.toLocaleTimeString('en-US', { minute: '2-digit', timeZone: TZ }), 10);
}

function formatMeetingTime(startTime: string, endTime: string | null): string {
  const start = new Date(startTime);
  const time = start.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: TZ,
  });
  if (!endTime) return time;
  const end = new Date(endTime);
  const endStr = end.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: TZ,
  });
  return `${time} – ${endStr}`;
}

function formatMeetingDate(startTime: string): string {
  const d = new Date(startTime);
  const now = new Date();
  // Compare dates in ET so "Today"/"Tomorrow" labels are correct
  const todayET = now.toLocaleDateString('en-CA', { timeZone: TZ }); // YYYY-MM-DD
  const meetingET = d.toLocaleDateString('en-CA', { timeZone: TZ });
  const diffDays = Math.round((new Date(meetingET).getTime() - new Date(todayET).getTime()) / (1000 * 60 * 60 * 24));

  let relative = '';
  if (diffDays === 0) relative = 'Today';
  else if (diffDays === 1) relative = 'Tomorrow';
  else if (diffDays === -1) relative = 'Yesterday';

  const dateStr = d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZone: TZ,
  });

  return relative ? `${relative}, ${dateStr}` : dateStr;
}

function formatHour(hour: number): string {
  if (hour === 0) return '12 AM';
  if (hour === 12) return '12 PM';
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

function parseAttendees(json?: string): { email: string; name: string; response: string }[] {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
  }
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

function MeetingModal({
  meeting,
  onClose,
}: {
  meeting: MeetingWithContext;
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

  const summaryHtml = meeting.notes_summary_html || meeting.granola_summary_html;
  const summaryPlain = meeting.notes_summary_plain || meeting.granola_summary_plain;
  const notesLink = meeting.notes_link || meeting.granola_link;
  const transcript = meeting.notes_transcript || meeting.granola_transcript;
  const providerName = meeting.notes_provider ? meeting.notes_provider.charAt(0).toUpperCase() + meeting.notes_provider.slice(1) : 'Notes';

  const meetingNotesMarkdown = summaryHtml
    ? htmlToMarkdown(summaryHtml)
    : summaryPlain || '';

  return (
    <div
      className="meeting-modal-overlay"
      ref={overlayRef}
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="meeting-modal">
        <button className="meeting-modal-close" onClick={onClose}>
          &times;
        </button>

        <div className="meeting-modal-header">
          <h2>{meeting.summary}</h2>
          <div
            style={{
              color: 'var(--color-text-light)',
              fontSize: 'var(--text-sm)',
            }}
          >
            {formatMeetingDate(meeting.start_time)}
            {meeting.end_time && `, ${formatMeetingTime(meeting.start_time, meeting.end_time)}`}
            {notesLink && (
              <>
                {' '}&middot;{' '}
                <a
                  href={notesLink}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open in {providerName}
                </a>
              </>
            )}
            {meeting.html_link && (
              <>
                {' '}&middot;{' '}
                <a
                  href={meeting.html_link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google Calendar
                </a>
              </>
            )}
          </div>
        </div>

        {meeting.note_content && (
          <div className="meeting-modal-section">
            <div className="meeting-modal-section-header">
              <h3>My Notes</h3>
              <CopyButton text={meeting.note_content} />
            </div>
            <div style={{ whiteSpace: 'pre-wrap' }}>{meeting.note_content}</div>
          </div>
        )}

        {(summaryHtml || summaryPlain) && (
          <div className="meeting-modal-section">
            <div className="meeting-modal-section-header">
              <h3>Meeting Notes</h3>
              {meetingNotesMarkdown && <CopyButton text={meetingNotesMarkdown} />}
            </div>
            {summaryHtml ? (
              <div
                className="markdown-content"
                dangerouslySetInnerHTML={{ __html: sanitizeHtml(summaryHtml) }}
              />
            ) : (
              <div style={{ whiteSpace: 'pre-wrap' }}>
                {summaryPlain}
              </div>
            )}
          </div>
        )}

        {transcript && (
          <div className="meeting-modal-section">
            <div className="meeting-modal-section-header">
              <h3>Transcript</h3>
              <CopyButton text={transcript} />
            </div>
            <div
              style={{
                whiteSpace: 'pre-wrap',
                fontSize: 'var(--text-sm)',
                maxHeight: '400px',
                overflow: 'auto',
              }}
            >
              {transcript}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MeetingRow({
  meeting,
  onOpenModal,
}: {
  meeting: MeetingWithContext;
  onOpenModal: (m: MeetingWithContext) => void;
}) {
  const upsertNote = useUpsertMeetingNote();
  const deleteNote = useDeleteMeetingNote();
  const { data: profile } = useProfile();
  const [noteText, setNoteText] = useState(meeting.note_content || '');
  const [expanded, setExpanded] = useState(false);

  const refType = meeting.event_id ? 'calendar' : 'external';
  const refId = (meeting.event_id || meeting.notes_id || meeting.granola_id)!;

  const userEmail = profile?.user_email;
  const attendees = parseAttendees(meeting.attendees_json);
  const attendeeNames = attendees
    .filter((a) => !userEmail || !a.email?.includes(userEmail.split('@')[0]))
    .map((a) => a.name || a.email?.split('@')[0] || '')
    .filter(Boolean);

  const hasNotes = !!(meeting.notes_summary_html || meeting.granola_summary_html || meeting.notes_summary_plain || meeting.granola_summary_plain);
  const notesBadgeLink = meeting.notes_link || meeting.granola_link;
  const notesBadgeLabel = meeting.notes_provider ? meeting.notes_provider.charAt(0).toUpperCase() + meeting.notes_provider.slice(1) : 'Notes';

  const handleSave = () => {
    if (!noteText.trim()) return;
    upsertNote.mutate({ refType, refId, content: noteText.trim() });
  };

  const handleDelete = () => {
    if (!confirm('Delete this note?')) return;
    deleteNote.mutate(
      { refType, refId },
      {
        onSuccess: () => {
          setNoteText('');
        },
      }
    );
  };

  const handleHeaderClick = (e: React.MouseEvent) => {
    // Don't toggle expand if clicking a link or button inside the header
    const target = e.target as HTMLElement;
    if (target.closest('a') || target.closest('.meeting-title-link')) return;
    setExpanded(!expanded);
  };

  return (
    <div className="meeting-entry">
      {/* Header: title left, time right */}
      <div className="meeting-row-header" onClick={handleHeaderClick}>
        <div className="meeting-row-title">
          {hasNotes ? (
            <button
              className="btn-link meeting-title-link"
              onClick={(e) => { e.stopPropagation(); onOpenModal(meeting); }}
              style={{ fontWeight: 600 }}
            >
              {meeting.summary}
            </button>
          ) : (
            <span>{meeting.summary}</span>
          )}
          {notesBadgeLink && (
            <a
              href={notesBadgeLink}
              target="_blank"
              rel="noopener noreferrer"
              className="meeting-source-badge"
              onClick={(e) => e.stopPropagation()}
            >
              {notesBadgeLabel}
            </a>
          )}
          {meeting.html_link && (
            <a
              href={meeting.html_link}
              target="_blank"
              rel="noopener noreferrer"
              className="meeting-source-badge"
              onClick={(e) => e.stopPropagation()}
            >
              Calendar
            </a>
          )}
        </div>
        <div className="meeting-row-meta">
          {!expanded && meeting.note_content && (
            <span className="meeting-has-note-indicator">has notes</span>
          )}
          <span className="meeting-row-time">
            {meeting.end_time
              ? formatMeetingTime(meeting.start_time, meeting.end_time)
              : new Date(meeting.start_time).toLocaleTimeString('en-US', {
                  hour: 'numeric',
                  minute: '2-digit',
                  hour12: true,
                  timeZone: TZ,
                })}
          </span>
          <span className={`collapse-icon ${expanded ? 'open' : ''}`}>
            &#x25b6;
          </span>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="meeting-details">
          {meeting.description && (
            <p className="meeting-description">{meeting.description}</p>
          )}

          {attendeeNames.length > 0 && (
            <div className="meeting-details-attendees">
              <span className="meeting-details-label">People</span>
              {attendeeNames.join(', ')}
            </div>
          )}

          {/* Meeting notes summary */}
          {(() => {
            const html = meeting.notes_summary_html || meeting.granola_summary_html;
            const plain = meeting.notes_summary_plain || meeting.granola_summary_plain;
            if (!html && !plain) return null;
            return (
              <div className="meeting-summary">
                {html ? (
                  <div
                    className="markdown-content"
                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
                  />
                ) : (
                  <div style={{ whiteSpace: 'pre-wrap' }}>
                    {plain}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Notes - always visible when expanded */}
          <div className="meeting-inline-notes">
            <textarea
              className="note-input"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Add your notes..."
              rows={3}
              style={{ width: '100%', resize: 'vertical' }}
              onClick={(e) => e.stopPropagation()}
            />
            <div className="meeting-note-actions">
              <button className="btn-primary" onClick={handleSave} disabled={upsertNote.isPending}>
                Save
              </button>
              {meeting.note_content && (
                <button
                  className="btn-link"
                  style={{ color: 'var(--color-text-light)' }}
                  onClick={handleDelete}
                >
                  delete
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Group meetings by date for day headers
function groupByDate(meetings: MeetingWithContext[]): { dateKey: string; dateLabel: string; meetings: MeetingWithContext[] }[] {
  const groups: Map<string, MeetingWithContext[]> = new Map();
  for (const m of meetings) {
    const dateKey = new Date(m.start_time).toDateString();
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    groups.get(dateKey)!.push(m);
  }
  return Array.from(groups.entries()).map(([dateKey, dayMeetings]) => ({
    dateKey,
    dateLabel: formatMeetingDate(dayMeetings[0].start_time),
    meetings: dayMeetings,
  }));
}

// Detect overlapping meetings for side-by-side rendering
function computeOverlapColumns(meetings: MeetingWithContext[]): Map<string, { col: number; totalCols: number }> {
  const result = new Map<string, { col: number; totalCols: number }>();
  if (meetings.length === 0) return result;

  type Block = { id: string; start: number; end: number };
  const blocks: Block[] = meetings.map(m => {
    const s = new Date(m.start_time).getTime();
    const e = m.end_time ? new Date(m.end_time).getTime() : s + 30 * 60000;
    return { id: m.event_id || m.notes_id || m.granola_id || m.start_time, start: s, end: e };
  });

  // Find groups of overlapping meetings
  const sorted = [...blocks].sort((a, b) => a.start - b.start);
  const groups: Block[][] = [];
  let currentGroup: Block[] = [sorted[0]];
  let groupEnd = sorted[0].end;

  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].start < groupEnd) {
      currentGroup.push(sorted[i]);
      groupEnd = Math.max(groupEnd, sorted[i].end);
    } else {
      groups.push(currentGroup);
      currentGroup = [sorted[i]];
      groupEnd = sorted[i].end;
    }
  }
  groups.push(currentGroup);

  for (const group of groups) {
    for (let i = 0; i < group.length; i++) {
      result.set(group[i].id, { col: i, totalCols: group.length });
    }
  }

  return result;
}

function DayCalendarView({
  meetings,
  onOpenModal,
}: {
  meetings: MeetingWithContext[];
  onOpenModal: (m: MeetingWithContext) => void;
}) {
  const now = new Date();
  const todayStr = now.toDateString();
  const todayMeetings = meetings.filter(m =>
    new Date(m.start_time).toDateString() === todayStr
  );

  const allDayMeetings = todayMeetings.filter(m => m.all_day);
  const timedMeetings = todayMeetings.filter(m => !m.all_day);

  // Determine time range
  let startHour = 8;
  let endHour = 18;
  for (const m of timedMeetings) {
    const h = getHourInTZ(new Date(m.start_time));
    const eh = m.end_time ? getHourInTZ(new Date(m.end_time)) : h + 1;
    if (h < startHour) startHour = Math.max(0, h);
    if (eh >= endHour) endHour = Math.min(24, eh + 1);
  }

  const HOUR_HEIGHT = 60;
  const totalHeight = (endHour - startHour) * HOUR_HEIGHT;

  const overlapCols = computeOverlapColumns(timedMeetings);

  const positioned = timedMeetings.map(m => {
    const start = new Date(m.start_time);
    const end = m.end_time ? new Date(m.end_time) : new Date(start.getTime() + 30 * 60000);
    const startMinutes = (getHourInTZ(start) - startHour) * 60 + getMinuteInTZ(start);
    const endMinutes = (getHourInTZ(end) - startHour) * 60 + getMinuteInTZ(end);
    const top = (startMinutes / 60) * HOUR_HEIGHT;
    const height = Math.max(((endMinutes - startMinutes) / 60) * HOUR_HEIGHT, 24);
    const id = m.event_id || m.notes_id || m.granola_id || m.start_time;
    const overlap = overlapCols.get(id) || { col: 0, totalCols: 1 };
    return { meeting: m, top, height, overlap };
  });

  // Now indicator
  const nowMinutes = (getHourInTZ(now) - startHour) * 60 + getMinuteInTZ(now);
  const nowTop = (nowMinutes / 60) * HOUR_HEIGHT;
  const showNow = now.toDateString() === todayStr && nowMinutes >= 0 && nowMinutes <= (endHour - startHour) * 60;

  if (todayMeetings.length === 0) {
    return <p className="empty-state">No meetings today.</p>;
  }

  return (
    <div className="day-calendar">
      <div className="day-calendar-header">
        {formatMeetingDate(now.toISOString())}
        {' '}&middot;{' '}
        {todayMeetings.length} meeting{todayMeetings.length !== 1 ? 's' : ''}
      </div>

      {allDayMeetings.length > 0 && (
        <div className="day-calendar-allday">
          <span className="day-calendar-allday-label">All day</span>
          {allDayMeetings.map(m => m.summary).join(', ')}
        </div>
      )}

      <div className="day-calendar-container" style={{ height: totalHeight, position: 'relative' }}>
        {/* Hour lines */}
        {Array.from({ length: endHour - startHour + 1 }, (_, i) => (
          <div key={i} className="day-calendar-hour" style={{ top: i * HOUR_HEIGHT }}>
            <span className="day-calendar-hour-label">
              {formatHour(startHour + i)}
            </span>
          </div>
        ))}

        {/* Now indicator */}
        {showNow && (
          <div className="day-calendar-now" style={{ top: nowTop }} />
        )}

        {/* Meeting blocks */}
        {positioned.map(({ meeting, top, height, overlap }) => {
          const widthPct = 100 / overlap.totalCols;
          const leftPct = overlap.col * widthPct;
          return (
            <div
              key={meeting.event_id || meeting.granola_id || meeting.start_time}
              className="day-calendar-block"
              style={{
                top,
                height,
                left: `${leftPct}%`,
                width: `${widthPct}%`,
              }}
              onClick={() => onOpenModal(meeting)}
            >
              <span className="day-calendar-block-title">{meeting.summary}</span>
              {height > 32 && (
                <span className="day-calendar-block-time">
                  {formatMeetingTime(meeting.start_time, meeting.end_time)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MeetingList({
  tab,
  viewMode,
}: {
  tab: 'upcoming' | 'past';
  viewMode: 'list' | 'calendar';
}) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useMeetings(tab);

  const observerRef = useRef<HTMLDivElement>(null);
  const [selectedMeeting, setSelectedMeeting] = useState<MeetingWithContext | null>(null);

  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    },
    [fetchNextPage, hasNextPage, isFetchingNextPage]
  );

  useEffect(() => {
    const el = observerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(handleObserver, { threshold: 0.1 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleObserver]);

  const meetings = useMemo(() => data?.pages.flatMap((p) => p.meetings) ?? [], [data]);
  const total = data?.pages[0]?.total ?? 0;
  const dayGroups = useMemo(() => groupByDate(meetings), [meetings]);

  const dismissMeeting = useDismissPrioritizedItem();

  // Keyboard navigation callbacks
  const handleOpenAtIndex = (index: number) => {
    if (meetings[index]) {
      setSelectedMeeting(meetings[index]);
    }
  };

  const handleExpandAtIndex = (index: number) => {
    const entries = document.querySelectorAll('.meeting-entry');
    const entry = entries[index];
    if (entry) {
      const header = entry.querySelector('.meeting-row-header') as HTMLElement;
      header?.click();
    }
  };

  const handleDismissAtIndex = (index: number) => {
    if (meetings[index]) {
      const meeting = meetings[index];
      const meetingId = meeting.event_id || meeting.granola_id;
      if (meetingId) {
        dismissMeeting.mutate({ source: 'meeting', item_id: meetingId });
      }
    }
  };

  const { containerRef } = useFocusNavigation({
    selector: '.meeting-entry',
    enabled: !isLoading && viewMode === 'list',
    onOpen: handleOpenAtIndex,
    onExpand: handleExpandAtIndex,
    onDismiss: handleDismissAtIndex,
  });

  if (isLoading) {
    return <p className="empty-state">Loading meetings...</p>;
  }

  if (meetings.length === 0) {
    return (
      <p className="empty-state">
        {tab === 'upcoming'
          ? 'No upcoming meetings.'
          : 'No past meetings found.'}
      </p>
    );
  }

  // Calendar view
  if (viewMode === 'calendar' && tab === 'upcoming') {
    return (
      <>
        <DayCalendarView meetings={meetings} onOpenModal={setSelectedMeeting} />
        {selectedMeeting && (
          <MeetingModal
            meeting={selectedMeeting}
            onClose={() => setSelectedMeeting(null)}
          />
        )}
      </>
    );
  }

  // List view with day groups
  return (
    <div ref={containerRef}>
      <p style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-md)' }}>
        {total} {tab === 'upcoming' ? 'upcoming' : 'past'} meeting{total !== 1 ? 's' : ''}
      </p>
      {dayGroups.map(({ dateKey, dateLabel, meetings: dayMeetings }) => (
        <div key={dateKey} className="meeting-day-group">
          <div className="meeting-day-header">{dateLabel}</div>
          {dayMeetings.map((m, i) => (
            <MeetingRow
              key={`${m.event_id || m.notes_id || m.granola_id || i}`}
              meeting={m}
              onOpenModal={setSelectedMeeting}
            />
          ))}
        </div>
      ))}
      <div ref={observerRef} style={{ height: 1 }} />
      {isFetchingNextPage && (
        <p style={{ textAlign: 'center', color: 'var(--color-text-light)' }}>
          Loading more...
        </p>
      )}
      {selectedMeeting && (
        <MeetingModal
          meeting={selectedMeeting}
          onClose={() => setSelectedMeeting(null)}
        />
      )}

      {meetings.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open modal', 'e expand/collapse', 'd dismiss', 't toggle tab', 'v toggle view']} />
      )}
    </div>
  );
}

function MeetingNotesList() {
  const allQuery = useAllMeetingNotes();
  const allMeetings = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  return (
    <>
      {allQuery.isLoading && <p className="empty-state">Loading meeting notes...</p>}
      {!allQuery.isLoading && allMeetings.length === 0 && (
        <p className="empty-state">No synced meeting notes yet. Run a sync to populate.</p>
      )}
      {allTotal > 0 && (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-sm)' }}>
          {allTotal} meeting note{allTotal !== 1 ? 's' : ''}
        </p>
      )}
      <div>
        {allMeetings.map((meeting) => {
          const isExpanded = expandedIds.has(meeting.id);
          const html = meeting.summary_html || meeting.panel_summary_html;
          const plain = meeting.summary_plain || meeting.panel_summary_plain;
          const link = meeting.external_link || meeting.granola_link;
          const hasSummary = !!(html || plain);
          const provider = meeting.provider ? meeting.provider.charAt(0).toUpperCase() + meeting.provider.slice(1) : '';
          return (
            <div key={meeting.id} className="dashboard-item-row" onClick={() => { if (hasSummary) toggleExpand(meeting.id); }} style={{ cursor: hasSummary ? 'pointer' : undefined }}>
              <div
                className="dashboard-item"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', flex: 1, minWidth: 0 }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">
                    {link ? (
                      <a href={link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                        {meeting.title}
                      </a>
                    ) : meeting.title}
                    {provider && (
                      <span style={{ marginLeft: 'var(--space-xs)', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
                        {provider}
                      </span>
                    )}
                  </div>
                  <div className="dashboard-item-meta">
                    {formatMeetingDate(meeting.created_at)}
                    {' '}&middot;{' '}
                    {new Date(meeting.created_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: TZ })}
                  </div>
                  {isExpanded && hasSummary && (
                    <div className="dashboard-item-expanded">
                      {html ? (
                        <div
                          className="markdown-content"
                          dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
                        />
                      ) : (
                        <div style={{ whiteSpace: 'pre-wrap' }}>{plain}</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              {hasSummary && (
                <button
                  className="dashboard-expand-btn"
                  onClick={(e) => { e.stopPropagation(); toggleExpand(meeting.id); }}
                  title={isExpanded ? 'Collapse summary' : 'Show summary'}
                >
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
              )}
            </div>
          );
        })}
      </div>
      <InfiniteScrollSentinel
        hasNextPage={!!allQuery.hasNextPage}
        isFetchingNextPage={allQuery.isFetchingNextPage}
        fetchNextPage={allQuery.fetchNextPage}
      />
    </>
  );
}

export function MeetingsPage() {
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const initialTab = (tabParam === 'notes' || tabParam === 'granola') ? 'notes' : 'upcoming';
  const [tab, setTab] = useState<'upcoming' | 'past' | 'notes'>(initialTab);
  const [viewMode, setViewMode] = useState<'list' | 'calendar'>('list');

  // Keyboard handler for tab switching and view toggle
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const tag = target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (target.isContentEditable) return;

      if (e.key === 't' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setTab(prev => prev === 'upcoming' ? 'past' : prev === 'past' ? 'notes' : 'upcoming');
      }
      if (e.key === 'v' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setViewMode(prev => prev === 'list' ? 'calendar' : 'list');
      }
    };

    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <h1>Meetings</h1>
        {tab === 'upcoming' && (
          <div className="issue-view-modes">
            <button
              className={`filter-btn${viewMode === 'list' ? ' active' : ''}`}
              onClick={() => setViewMode('list')}
            >
              List
            </button>
            <button
              className={`filter-btn${viewMode === 'calendar' ? ' active' : ''}`}
              onClick={() => setViewMode('calendar')}
            >
              Day
            </button>
          </div>
        )}
      </div>

      <div className="tab-bar">
        <button
          className={`tab ${tab === 'upcoming' ? 'active' : ''}`}
          onClick={() => setTab('upcoming')}
        >
          Upcoming
        </button>
        <button
          className={`tab ${tab === 'past' ? 'active' : ''}`}
          onClick={() => setTab('past')}
        >
          Past
        </button>
        <button
          className={`tab ${tab === 'notes' ? 'active' : ''}`}
          onClick={() => setTab('notes')}
        >
          Notes
        </button>
      </div>

      {(tab === 'upcoming' || tab === 'past') && <MeetingList tab={tab} viewMode={viewMode} />}
      {tab === 'notes' && <MeetingNotesList />}
    </div>
  );
}
