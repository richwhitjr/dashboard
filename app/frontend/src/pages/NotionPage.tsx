import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedNotion, useRefreshPrioritizedNotion, useDismissPrioritizedItem, useCreateIssue } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';

const DAY_OPTIONS = [1, 7, 30] as const;
const SCORE_OPTIONS = [0, 3, 5, 6, 7, 8] as const;
const DEFAULT_MIN_SCORE = 6;

function scoreBadge(score: number) {
  const cls = score >= 8 ? 'priority-urgency-high'
    : score >= 5 ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

export function NotionPage() {
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const { data, isLoading } = usePrioritizedNotion(days);
  const refresh = useRefreshPrioritizedNotion(days);
  const dismiss = useDismissPrioritizedItem();
  const createIssue = useCreateIssue();
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
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source: 'notion', item_id: items[i].id }); },
    onCreateIssue: (i) => { if (items[i]) createIssue.mutate({ title: items[i].title }); },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? DEFAULT_MIN_SCORE : 0),
  });

  return (
    <div>
      <div className="priorities-header">
        <h1>Notion</h1>
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

      {isLoading && <p className="empty-state">Loading prioritized pages...</p>}
      {data?.error && <p className="empty-state">
        Notion is not connected. Add your integration token in <Link to="/settings">Settings</Link> to see your pages.
      </p>}
      {!isLoading && !data?.error && items.length === 0 && (
        <p className="empty-state">
          {hiddenCount > 0
            ? `${hiddenCount} page${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
            : `No Notion pages in the last ${days} day${days > 1 ? 's' : ''}`}
        </p>
      )}

      <div ref={containerRef}>
        {items.map((page) => {
          const isExpanded = expandedIds.has(page.id);
          const hasExtra = !!(page.snippet || page.relevance_reason);
          return (
            <div key={page.id} className="dashboard-item-row">
              <a
                className="dashboard-item dashboard-item-link"
                href={page.url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
              >
                <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                  {scoreBadge(page.priority_score)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span className="dashboard-item-title">{page.title}</span>
                  <div className="dashboard-item-meta">
                    {page.last_edited_by && <span>{page.last_edited_by} &middot; </span>}
                    <TimeAgo date={page.last_edited_time} />
                  </div>
                  {isExpanded && page.snippet && (
                    <div className="dashboard-item-expanded">
                      {page.snippet}
                    </div>
                  )}
                  {isExpanded && page.relevance_reason && (
                    <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>
                      {page.relevance_reason}
                    </div>
                  )}
                  {!isExpanded && page.priority_reason && (
                    <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>
                      {page.priority_reason}
                    </div>
                  )}
                </div>
              </a>
              {hasExtra && (
                <button
                  className="dashboard-expand-btn"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(page.id); }}
                  title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                >
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
              )}
              <button
                className="dashboard-dismiss-btn"
                onClick={() => dismiss.mutate({ source: 'notion', item_id: page.id })}
                title="Mark as seen"
              >&times;</button>
            </div>
          );
        })}
      </div>
      {hiddenCount > 0 && items.length > 0 && (
        <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
          {hiddenCount} lower-priority page{hiddenCount !== 1 ? 's' : ''} hidden
          <button className="day-filter-btn" style={{ marginLeft: 'var(--space-sm)' }} onClick={() => setMinScore(0)}>Show all</button>
        </p>
      )}

      {items.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']} />
      )}
    </div>
  );
}
