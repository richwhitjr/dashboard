import { useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedSlack, useRefreshPrioritizedSlack, useDismissPrioritizedItem, useCreateIssue, useAllSlack } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import { cleanSlackText } from '../utils/cleanSlackText';
import { InfiniteScrollSentinel } from '../components/shared/InfiniteScrollSentinel';

const DAY_OPTIONS = [1, 7, 30] as const;

function scoreBadge(score: number) {
  const cls = score >= 8 ? 'priority-urgency-high'
    : score >= 5 ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

const SCORE_OPTIONS = [0, 3, 5, 6, 7, 8] as const;
const DEFAULT_MIN_SCORE = 6;

export function SlackPage() {
  const [tab, setTab] = useState<'priority' | 'all'>('priority');
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const { data, isLoading } = usePrioritizedSlack(days);
  const refresh = useRefreshPrioritizedSlack(days);
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
    enabled: tab === 'priority',
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source: 'slack', item_id: items[i].id }); },
    onCreateIssue: (i) => { if (items[i]) createIssue.mutate({ title: cleanSlackText(items[i].text).slice(0, 120) }); },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? DEFAULT_MIN_SCORE : 0),
  });

  // All-items tab
  const allQuery = useAllSlack();
  const allMessages = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <div>
      <div className="priorities-header">
        <h1>Slack</h1>
        {tab === 'priority' && (
          <>
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
          </>
        )}
      </div>

      <div className="github-tabs">
        <button className={`github-tab ${tab === 'priority' ? 'active' : ''}`} onClick={() => setTab('priority')}>
          Priority
        </button>
        <button className={`github-tab ${tab === 'all' ? 'active' : ''}`} onClick={() => setTab('all')}>
          All{allTotal > 0 ? ` (${allTotal})` : ''}
        </button>
      </div>

      {tab === 'priority' && (
        <>
          {isLoading && <p className="empty-state">Loading prioritized messages...</p>}
          {data?.error && <p className="empty-state">
            Slack is not connected. Add your Slack token in <Link to="/settings">Settings</Link> to see your messages.
          </p>}
          {!isLoading && !data?.error && items.length === 0 && (
            <p className="empty-state">
              {hiddenCount > 0
                ? `${hiddenCount} message${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
                : `No Slack messages in the last ${days} day${days > 1 ? 's' : ''}`}
            </p>
          )}

          <div ref={containerRef}>
            {items.map((msg) => {
              const cleaned = cleanSlackText(msg.text);
              const isExpanded = expandedIds.has(msg.id);
              const isLong = cleaned.length > 300;
              return (
                <div key={msg.id} className="dashboard-item-row">
                  <a
                    className="dashboard-item dashboard-item-link"
                    href={msg.permalink || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
                  >
                    <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                      {scoreBadge(msg.priority_score)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="dashboard-item-title">
                        {isExpanded ? cleaned : (
                          <>
                            {cleaned.slice(0, 300)}
                            {isLong && '...'}
                          </>
                        )}
                      </div>
                      <div className="dashboard-item-meta">
                        {msg.user_name} in {msg.channel_name || 'DM'}
                        {msg.is_mention && <span> &middot; <strong>@mention</strong></span>}
                        {' '}&middot;{' '}
                        <TimeAgo date={new Date(Number(msg.ts) * 1000).toISOString()} />
                      </div>
                      {msg.priority_reason && (
                        <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>
                          {msg.priority_reason}
                        </div>
                      )}
                    </div>
                  </a>
                  {isLong && (
                    <button
                      className="dashboard-expand-btn"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(msg.id); }}
                      title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                    >
                      {isExpanded ? '\u25BE' : '\u25B8'}
                    </button>
                  )}
                  <button
                    className="dashboard-dismiss-btn"
                    onClick={() => dismiss.mutate({ source: 'slack', item_id: msg.id })}
                    title="Mark as seen"
                  >&times;</button>
                </div>
              );
            })}
          </div>
          {hiddenCount > 0 && items.length > 0 && (
            <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
              {hiddenCount} lower-priority message{hiddenCount !== 1 ? 's' : ''} hidden
              <button
                className="day-filter-btn"
                style={{ marginLeft: 'var(--space-sm)' }}
                onClick={() => setMinScore(0)}
              >
                Show all
              </button>
            </p>
          )}
          {items.length > 0 && (
            <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']} />
          )}
        </>
      )}

      {tab === 'all' && (
        <>
          {allQuery.isLoading && <p className="empty-state">Loading messages...</p>}
          {!allQuery.isLoading && allMessages.length === 0 && (
            <p className="empty-state">No synced Slack messages yet. Run a sync to populate.</p>
          )}
          <div>
            {allMessages.map((msg) => {
              const cleaned = cleanSlackText(msg.text);
              const isExpanded = expandedIds.has(msg.id);
              const isLong = cleaned.length > 300;
              return (
                <div key={msg.id} className="dashboard-item-row">
                  <a
                    className="dashboard-item dashboard-item-link"
                    href={msg.permalink || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="dashboard-item-title">
                        {isExpanded ? cleaned : (
                          <>
                            {cleaned.slice(0, 300)}
                            {isLong && '...'}
                          </>
                        )}
                      </div>
                      <div className="dashboard-item-meta">
                        {msg.user_name} in {msg.channel_name || 'DM'}
                        {msg.is_mention && <span> &middot; <strong>@mention</strong></span>}
                        {' '}&middot;{' '}
                        <TimeAgo date={new Date(Number(msg.ts) * 1000).toISOString()} />
                      </div>
                    </div>
                  </a>
                  {isLong && (
                    <button
                      className="dashboard-expand-btn"
                      onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(msg.id); }}
                      title={isExpanded ? 'Collapse' : 'Expand'}
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
      )}
    </div>
  );
}
