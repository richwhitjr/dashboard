import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedNotion, useRefreshPrioritizedNotion, useAllNotion, type AllTabSearchParams } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';

export function NotionPage() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = usePrioritizedNotion(days);
  const refresh = useRefreshPrioritizedNotion(days);
  const [allSearchParams, setAllSearchParams] = useState<AllTabSearchParams>({});

  const allQuery = useAllNotion(allSearchParams);
  const allPages = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <PrioritizedSourceList
      title="Notion"
      source="notion"
      items={data?.items ?? []}
      isLoading={isLoading}
      error={data?.error}
      stale={data?.stale}
      refresh={refresh}
      days={days}
      onDaysChange={setDays}
      itemNoun="page"
      getIssueTitle={(page) => page.title}
      errorMessage={<p className="empty-state">Notion is not connected. Add your integration token in <Link to="/settings">Settings</Link> to see your pages.</p>}
      renderItem={(page, expanded) => (
        <a
          className="dashboard-item dashboard-item-link"
          href={page.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
        >
          <div style={{ flexShrink: 0, paddingTop: '2px' }}><ScoreBadge score={page.priority_score} /></div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="dashboard-item-title">{page.title}</span>
            <div className="dashboard-item-meta">
              {page.last_edited_by && <span>{page.last_edited_by} &middot; </span>}
              <TimeAgo date={page.last_edited_time} />
            </div>
            {expanded && page.snippet && <div className="dashboard-item-expanded">{page.snippet}</div>}
            {expanded && page.relevance_reason && <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{page.relevance_reason}</div>}
            {!expanded && page.priority_reason && <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{page.priority_reason}</div>}
          </div>
        </a>
      )}
      allTab={{
        items: allPages,
        total: allTotal,
        isLoading: allQuery.isLoading,
        hasNextPage: !!allQuery.hasNextPage,
        isFetchingNextPage: allQuery.isFetchingNextPage,
        fetchNextPage: allQuery.fetchNextPage,
        search: {
          authorLabel: 'Edited by',
          hasDateFilter: true,
          onParamsChange: setAllSearchParams,
        },
        renderItem: (item) => {
          const page = item as (typeof allPages)[0];
          return (
            <a
              className="dashboard-item dashboard-item-link"
              href={page.url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <span className="dashboard-item-title">{page.title}</span>
                <div className="dashboard-item-meta">
                  {page.last_edited_by && <span>{page.last_edited_by} &middot; </span>}
                  <TimeAgo date={page.last_edited_time} />
                </div>
              </div>
            </a>
          );
        },
      }}
    />
  );
}
