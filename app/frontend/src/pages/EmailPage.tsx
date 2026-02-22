import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedEmail, useRefreshPrioritizedEmail, useDismissPrioritizedItem, useCreateIssue } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import { EmailThreadModal } from '../components/EmailThreadModal';

const DAY_OPTIONS = [1, 7, 30] as const;
const SCORE_OPTIONS = [0, 3, 5, 6, 7, 8] as const;
const DEFAULT_MIN_SCORE = 6;

function scoreBadge(score: number) {
  const cls = score >= 8 ? 'priority-urgency-high'
    : score >= 5 ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

export function EmailPage() {
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const { data, isLoading } = usePrioritizedEmail(days);
  const refresh = useRefreshPrioritizedEmail(days);
  const dismiss = useDismissPrioritizedItem();
  const createIssue = useCreateIssue();
  const [selectedThread, setSelectedThread] = useState<{ threadId: string; subject: string } | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const allItems = data?.items ?? [];
  const items = minScore > 0 ? allItems.filter(m => m.priority_score >= minScore) : allItems;
  const hiddenCount = allItems.length - items.length;
  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source: 'email', item_id: items[i].thread_id || items[i].id }); },
    onOpen: (i) => {
      if (items[i]) {
        setSelectedThread({
          threadId: items[i].thread_id || items[i].id,
          subject: items[i].subject,
        });
      }
    },
    onCreateIssue: (i) => { if (items[i]) createIssue.mutate({ title: items[i].subject }); },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? DEFAULT_MIN_SCORE : 0),
  });

  return (
    <div>
      <div className="priorities-header">
        <h1>Email</h1>
        <span className="day-filter">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </span>
        <span className="day-filter">
          {SCORE_OPTIONS.map((s) => (
            <button
              key={s}
              className={`day-filter-btn${minScore === s ? ' day-filter-active' : ''}`}
              onClick={() => setMinScore(s)}
              title={s === 0 ? 'Show all (f)' : `Hide scores below ${s} (f)`}
            >
              {s === 0 ? 'All' : `${s}+`}
            </button>
          ))}
        </span>
        <button
          className="priorities-refresh-btn"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          title="Re-rank with Gemini"
        >
          {refresh.isPending ? 'Ranking...' : 'Refresh'}
        </button>
      </div>

      {isLoading && <p className="empty-state">Loading prioritized emails...</p>}
      {data?.error && <p className="empty-state">
        Gmail is not connected. Set up Google in <Link to="/settings">Settings</Link> to see your email.
      </p>}
      {!isLoading && !data?.error && items.length === 0 && (
        <p className="empty-state">
          {hiddenCount > 0
            ? `${hiddenCount} email${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
            : `No emails in the last ${days} day${days > 1 ? 's' : ''}`}
        </p>
      )}

      <div ref={containerRef}>
        {items.map((email) => {
          const isExpanded = expandedIds.has(email.id);
          const hasSnippet = !!email.snippet;
          return (
            <div key={email.id} className="dashboard-item-row">
              <div
                className="dashboard-item dashboard-item-link"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: 'pointer' }}
                onClick={() => setSelectedThread({
                  threadId: email.thread_id || email.id,
                  subject: email.subject,
                })}
              >
                <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                  {scoreBadge(email.priority_score)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">
                    {email.is_unread && <strong>{'\u2022'} </strong>}
                    {email.subject}
                    {(email.message_count ?? 0) > 1 && (
                      <span className="email-thread-count">({email.message_count})</span>
                    )}
                  </div>
                  <div className="dashboard-item-meta">
                    {email.from_name || email.from_email}
                    {' '}&middot;{' '}
                    <TimeAgo date={email.date} />
                  </div>
                  {isExpanded && hasSnippet && (
                    <div className="dashboard-item-expanded">
                      {email.snippet}
                    </div>
                  )}
                  {email.priority_reason && (
                    <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>
                      {email.priority_reason}
                    </div>
                  )}
                </div>
              </div>
              {hasSnippet && (
                <button
                  className="dashboard-expand-btn"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(email.id); }}
                  title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                >
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
              )}
              <button
                className="dashboard-dismiss-btn"
                onClick={() => dismiss.mutate({ source: 'email', item_id: email.thread_id || email.id })}
                title="Mark as seen"
              >&times;</button>
            </div>
          );
        })}
      </div>
      {hiddenCount > 0 && items.length > 0 && (
        <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
          {hiddenCount} lower-priority email{hiddenCount !== 1 ? 's' : ''} hidden
          <button className="day-filter-btn" style={{ marginLeft: 'var(--space-sm)' }} onClick={() => setMinScore(0)}>Show all</button>
        </p>
      )}

      {selectedThread && (
        <EmailThreadModal
          threadId={selectedThread.threadId}
          subject={selectedThread.subject}
          onClose={() => setSelectedThread(null)}
        />
      )}

      {items.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']} />
      )}
    </div>
  );
}
