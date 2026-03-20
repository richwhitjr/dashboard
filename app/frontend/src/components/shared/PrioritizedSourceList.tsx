import { useState, useCallback, useRef, useEffect, type ReactNode } from 'react';
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

interface AllTabSearch {
  authorLabel?: string;     // e.g. "From", "User", "Edited by"
  hasDateFilter?: boolean;  // show from/to date inputs
  onParamsChange: (params: { q?: string; author?: string; from_date?: string; to_date?: string }) => void;
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
    search?: AllTabSearch;
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

  // All-tab search state (local UI state; debounced before notifying parent)
  const [localQuery, setLocalQuery] = useState('');
  const [localAuthor, setLocalAuthor] = useState('');
  const [localDateFrom, setLocalDateFrom] = useState('');
  const [localDateTo, setLocalDateTo] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const items = minScore > 0 ? allItems.filter(m => m.priority_score >= minScore) : allItems;
  const hiddenCount = allItems.length - items.length;

  // Priority tab keyboard navigation
  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: tab === 'priority',
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source, item_id: getItemId(items[i]) }); },
    onOpen: onOpen ? (i) => { if (items[i]) onOpen(items[i]); } : undefined,
    onCreateIssue: (i) => { if (items[i]) createIssue.mutate({ title: getIssueTitle(items[i]) }); },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? defaultMinScore : 0),
  });

  // All tab keyboard navigation
  const { containerRef: allContainerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: tab === 'all',
    onExpand: (i) => {
      const item = allTab?.items[i] as PrioritizedItem | undefined;
      if (item?.id) toggleExpand(item.id);
    },
  });

  // Tab switching: p/[ = priority, a/] = all; / = focus search
  useEffect(() => {
    if (!allTab) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((e.target as HTMLElement)?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'p' || e.key === '[') { e.preventDefault(); setTab('priority'); }
      else if (e.key === 'a' || e.key === ']') { e.preventDefault(); setTab('all'); }
      else if (e.key === '/' && tab === 'all' && allTab.search) {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [allTab, tab]);

  // Debounce: notify parent of search param changes 350ms after user stops typing
  useEffect(() => {
    if (!allTab?.search?.onParamsChange) return;
    const timer = setTimeout(() => {
      allTab.search!.onParamsChange({
        q: localQuery || undefined,
        author: localAuthor || undefined,
        from_date: localDateFrom || undefined,
        to_date: localDateTo || undefined,
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [localQuery, localAuthor, localDateFrom, localDateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset search state when leaving all tab
  useEffect(() => {
    if (tab !== 'all') {
      setLocalQuery('');
      setLocalAuthor('');
      setLocalDateFrom('');
      setLocalDateTo('');
      setShowFilters(false);
      allTab?.search?.onParamsChange({});
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasActiveSearch = localQuery || localAuthor || localDateFrom || localDateTo;

  const clearSearch = () => {
    setLocalQuery('');
    setLocalAuthor('');
    setLocalDateFrom('');
    setLocalDateTo('');
  };

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
            <KeyboardHints hints={[
              'j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter',
              ...(allTab ? ['a/] all tab'] : []),
            ]} />
          )}
        </>
      )}

      {tab === 'all' && allTab && (
        <>
          {allTab.search && (
            <div className="all-search-bar">
              <input
                ref={searchInputRef}
                type="search"
                value={localQuery}
                onChange={e => setLocalQuery(e.target.value)}
                placeholder={`Search ${itemNoun}s...`}
                className="all-search-input"
                onKeyDown={e => {
                  if (e.key === 'Escape') {
                    if (localQuery) setLocalQuery('');
                    else searchInputRef.current?.blur();
                  }
                }}
              />
              {(allTab.search.authorLabel || allTab.search.hasDateFilter) && (
                <button
                  className={`day-filter-btn${showFilters ? ' day-filter-active' : ''}`}
                  onClick={() => setShowFilters(f => !f)}
                >
                  Filters
                </button>
              )}
              {hasActiveSearch && (
                <button className="day-filter-btn" onClick={clearSearch}>Clear</button>
              )}
            </div>
          )}

          {showFilters && allTab.search && (
            <div className="all-search-filters">
              {allTab.search.authorLabel && (
                <label>
                  {allTab.search.authorLabel}
                  <input
                    type="text"
                    value={localAuthor}
                    onChange={e => setLocalAuthor(e.target.value)}
                    className="all-search-filter-input"
                    placeholder={`Filter by ${allTab.search.authorLabel.toLowerCase()}...`}
                  />
                </label>
              )}
              {allTab.search.hasDateFilter && (
                <>
                  <label>
                    From
                    <input
                      type="date"
                      value={localDateFrom}
                      onChange={e => setLocalDateFrom(e.target.value)}
                      className="all-search-filter-input"
                    />
                  </label>
                  <label>
                    To
                    <input
                      type="date"
                      value={localDateTo}
                      onChange={e => setLocalDateTo(e.target.value)}
                      className="all-search-filter-input"
                    />
                  </label>
                </>
              )}
            </div>
          )}

          {allTab.isLoading && <p className="empty-state">Loading {itemNoun}s...</p>}
          {!allTab.isLoading && allTab.items.length === 0 && (
            <p className="empty-state">
              {hasActiveSearch
                ? `No ${itemNoun}s match your search`
                : `No synced ${itemNoun}s yet. Run a sync to populate.`}
            </p>
          )}

          <div ref={allContainerRef}>
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

          {allTab.items.length > 0 && (
            <KeyboardHints hints={[
              'j/k navigate',
              ...(allTab.search ? ['/ search', 'Esc clear'] : []),
              'p/[ priority',
            ]} />
          )}
        </>
      )}
    </div>
  );
}
