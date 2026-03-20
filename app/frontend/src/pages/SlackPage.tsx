import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedSlack, useRefreshPrioritizedSlack, useAllSlack, type AllTabSearchParams } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';
import { cleanSlackText } from '../utils/cleanSlackText';

export function SlackPage() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = usePrioritizedSlack(days);
  const refresh = useRefreshPrioritizedSlack(days);
  const [allSearchParams, setAllSearchParams] = useState<AllTabSearchParams>({});

  const allQuery = useAllSlack(allSearchParams);
  const allMessages = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <PrioritizedSourceList
      title="Slack"
      source="slack"
      items={data?.items ?? []}
      isLoading={isLoading}
      error={data?.error}
      stale={data?.stale}
      refresh={refresh}
      days={days}
      onDaysChange={setDays}
      itemNoun="message"
      getIssueTitle={(msg) => cleanSlackText(msg.text).slice(0, 120)}
      errorMessage={<p className="empty-state">Slack is not connected. Add your Slack token in <Link to="/settings">Settings</Link> to see your messages.</p>}
      renderItem={(msg, expanded) => {
        const cleaned = cleanSlackText(msg.text);
        const isLong = cleaned.length > 300;
        return (
          <a
            className="dashboard-item dashboard-item-link"
            href={msg.permalink || '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
          >
            <div style={{ flexShrink: 0, paddingTop: '2px' }}><ScoreBadge score={msg.priority_score} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="dashboard-item-title">
                {expanded ? cleaned : <>{cleaned.slice(0, 300)}{isLong && '...'}</>}
              </div>
              <div className="dashboard-item-meta">
                {msg.user_name} in {msg.channel_name || 'DM'}
                {msg.is_mention && <span> &middot; <strong>@mention</strong></span>}
                {' '}&middot;{' '}
                <TimeAgo date={new Date(Number(msg.ts) * 1000).toISOString()} />
              </div>
              {msg.priority_reason && <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{msg.priority_reason}</div>}
            </div>
          </a>
        );
      }}
      allTab={{
        items: allMessages,
        total: allTotal,
        isLoading: allQuery.isLoading,
        hasNextPage: !!allQuery.hasNextPage,
        isFetchingNextPage: allQuery.isFetchingNextPage,
        fetchNextPage: allQuery.fetchNextPage,
        search: {
          authorLabel: 'User',
          hasDateFilter: true,
          onParamsChange: setAllSearchParams,
        },
        renderItem: (item) => {
          const msg = item as (typeof allMessages)[0];
          const cleaned = cleanSlackText(msg.text);
          return (
            <a
              className="dashboard-item dashboard-item-link"
              href={msg.permalink || '#'}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="dashboard-item-title">{cleaned.slice(0, 300)}{cleaned.length > 300 && '...'}</div>
                <div className="dashboard-item-meta">
                  {msg.user_name} in {msg.channel_name || 'DM'}
                  {msg.is_mention && <span> &middot; <strong>@mention</strong></span>}
                  {' '}&middot;{' '}
                  <TimeAgo date={new Date(Number(msg.ts) * 1000).toISOString()} />
                </div>
              </div>
            </a>
          );
        },
      }}
    />
  );
}
