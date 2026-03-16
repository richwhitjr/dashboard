import { useState, useCallback, type ReactNode } from 'react';
import { useDismissPrioritizedItem, useCreateIssue } from '../../api/hooks';
import { useFocusNavigation } from '../../hooks/useFocusNavigation';
import { KeyboardHints } from './KeyboardHints';
import { InfiniteScrollSentinel } from './InfiniteScrollSentinel';

export function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 8 ? 'priority-urgency-high'
    : score >= 5 ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

export interface PrioritizedItem {
  id: string;
  priority_score: number;
  priority_reason?: string;
}

interface Props<T extends PrioritizedItem> {
  title: string;
  source: string;
  items: T[];
  isLoading: boolean;
  error?: string;
  refresh: { mutate: () => void; isPending: boolean };
  renderItem: (item: T, expanded: boolean) => ReactNode;
  getItemId?: (item: T) => string;
  getIssueTitle: (item: T) => string;
  onOpen?: (item: T) => void;
  // Day filter
  days: number;
  onDaysChange: (days: number) => void;
  dayOptions?: readonly number[];
  // Score filter
  scoreOptions?: readonly number[];
  defaultMinScore?: number;
  // "All" tab
  allTab?: {
    items: unknown[];
    total: number;
    isLoading: boolean;
    hasNextPage: boolean;
    isFetchingNextPage: boolean;
    fetchNextPage: () => void;
    renderItem: (item: unknown, expanded: boolean) => ReactNode;
  };
  // Config
  errorMessage?: ReactNode;
  itemNoun?: string;
  stale?: boolean;
}

export function PrioritizedSourceList<T extends PrioritizedItem>({
  title,
  source,
  items: allItems,
  isLoading,
  error,
  refresh,
  renderItem,
  getItemId = (item) => item.id,
  getIssueTitle,
  onOpen,
  days,
  onDaysChange,
  dayOptions = [1, 7, 30],
  scoreOptions = [0, 3, 5, 6, 7, 8],
  defaultMinScore = 6,
  allTab,
  errorMessage,
  itemNoun = 'item',
  stale = false,
}: Props<T>) {
  const [tab, setTab] = useState<'priority' | 'all'>('priority');
  const [minScore, setMinScore] = useState(defaultMinScore);
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

  const items = minScore > 0 ? allItems.filter(m => m.priority_score >= minScore) : allItems;
  const hiddenCount = allItems.length - items.length;

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: tab === 'priority',
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source, item_id: getItemId(items[i]) }); },
    onOpen: onOpen ? (i) => { if (items[i]) onOpen(items[i]); } : undefined,
    onCreateIssue: (i) => { if (items[i]) createIssue.mutate({ title: getIssueTitle(items[i]) }); },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? defaultMinScore : 0),
  });

  return (
    <div>
      <div className="priorities-header">
        <h1>{title}</h1>
        {tab === 'priority' && (
          <>
            <span className="day-filter">
              {dayOptions.map((d) => (
                <button
                  key={d}
                  className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`}
                  onClick={() => onDaysChange(d)}
                >
                  {d}d
                </button>
              ))}
            </span>
            <span className="day-filter">
              {scoreOptions.map((s) => (
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
              disabled={refresh.isPending || stale}
              title="Re-rank with AI"
            >
              {stale ? 'Updating...' : refresh.isPending ? 'Ranking...' : 'Refresh'}
            </button>
          </>
        )}
      </div>

      {allTab && (
        <div className="github-tabs">
          <button className={`github-tab ${tab === 'priority' ? 'active' : ''}`} onClick={() => setTab('priority')}>Priority</button>
          <button className={`github-tab ${tab === 'all' ? 'active' : ''}`} onClick={() => setTab('all')}>
            All{allTab.total > 0 ? ` (${allTab.total})` : ''}
          </button>
        </div>
      )}

      {tab === 'priority' && (
        <>
          {isLoading && <p className="empty-state">Loading prioritized {itemNoun}s...</p>}
          {error && (errorMessage || <p className="empty-state">{error}</p>)}
          {!isLoading && !error && items.length === 0 && (
            <p className="empty-state">
              {hiddenCount > 0
                ? `${hiddenCount} ${itemNoun}${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
                : `No ${itemNoun}s in the last ${days} day${days > 1 ? 's' : ''}`}
            </p>
          )}

          <div ref={containerRef}>
            {items.map((item) => (
              <div key={item.id} className="dashboard-item-row">
                {renderItem(item, expandedIds.has(item.id))}
                <button
                  className="dashboard-dismiss-btn"
                  onClick={() => dismiss.mutate({ source, item_id: getItemId(item) })}
                  title="Mark as seen"
                >&times;</button>
              </div>
            ))}
          </div>
          {hiddenCount > 0 && items.length > 0 && (
            <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
              {hiddenCount} lower-priority {itemNoun}{hiddenCount !== 1 ? 's' : ''} hidden
              <button className="day-filter-btn" style={{ marginLeft: 'var(--space-sm)' }} onClick={() => setMinScore(0)}>Show all</button>
            </p>
          )}
          {items.length > 0 && (
            <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']} />
          )}
        </>
      )}

      {tab === 'all' && allTab && (
        <>
          {allTab.isLoading && <p className="empty-state">Loading {itemNoun}s...</p>}
          {!allTab.isLoading && allTab.items.length === 0 && (
            <p className="empty-state">No synced {itemNoun}s yet. Run a sync to populate.</p>
          )}
          <div>
            {allTab.items.map((item, i) => (
              <div key={(item as PrioritizedItem).id ?? i} className="dashboard-item-row">
                {allTab.renderItem(item, expandedIds.has((item as PrioritizedItem).id))}
              </div>
            ))}
          </div>
          <InfiniteScrollSentinel
            hasNextPage={allTab.hasNextPage}
            isFetchingNextPage={allTab.isFetchingNextPage}
            fetchNextPage={allTab.fetchNextPage}
          />
        </>
      )}
    </div>
  );
}
