import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedEmail, useRefreshPrioritizedEmail, useAllEmails, type AllTabSearchParams } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';
import { EmailThreadModal } from '../components/EmailThreadModal';

export function EmailPage() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = usePrioritizedEmail(days);
  const refresh = useRefreshPrioritizedEmail(days);
  const [selectedThread, setSelectedThread] = useState<{ threadId: string; subject: string } | null>(null);
  const [allSearchParams, setAllSearchParams] = useState<AllTabSearchParams>({});

  const allQuery = useAllEmails(allSearchParams);
  const allEmails = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <>
      <PrioritizedSourceList
        title="Email"
        source="email"
        items={data?.items ?? []}
        isLoading={isLoading}
        error={data?.error}
        stale={data?.stale}
        refresh={refresh}
        days={days}
        onDaysChange={setDays}
        itemNoun="email"
        getItemId={(e) => e.thread_id || e.id}
        getIssueTitle={(e) => e.subject}
        onOpen={(e) => setSelectedThread({ threadId: e.thread_id || e.id, subject: e.subject })}
        errorMessage={<p className="empty-state">Gmail is not connected. Set up Google in <Link to="/settings">Settings</Link> to see your email.</p>}
        renderItem={(email, expanded) => (
          <div
            className="dashboard-item dashboard-item-link"
            style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: 'pointer' }}
            onClick={() => setSelectedThread({ threadId: email.thread_id || email.id, subject: email.subject })}
          >
            <div style={{ flexShrink: 0, paddingTop: '2px' }}><ScoreBadge score={email.priority_score} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="dashboard-item-title">
                {email.is_unread && <strong>{'\u2022'} </strong>}
                {email.subject}
                {(email.message_count ?? 0) > 1 && <span className="email-thread-count">({email.message_count})</span>}
              </div>
              <div className="dashboard-item-meta">
                {email.from_name || email.from_email} &middot; <TimeAgo date={email.date} />
              </div>
              {expanded && email.snippet && <div className="dashboard-item-expanded">{email.snippet}</div>}
              {email.priority_reason && <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{email.priority_reason}</div>}
            </div>
          </div>
        )}
        allTab={{
          items: allEmails,
          total: allTotal,
          isLoading: allQuery.isLoading,
          hasNextPage: !!allQuery.hasNextPage,
          isFetchingNextPage: allQuery.isFetchingNextPage,
          fetchNextPage: allQuery.fetchNextPage,
          search: {
            authorLabel: 'From',
            hasDateFilter: true,
            onParamsChange: setAllSearchParams,
          },
          renderItem: (item, expanded) => {
            const email = item as (typeof allEmails)[0];
            return (
              <div
                className="dashboard-item dashboard-item-link"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: 'pointer' }}
                onClick={() => setSelectedThread({ threadId: email.thread_id || email.id, subject: email.subject })}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">
                    {email.is_unread && <strong>{'\u2022'} </strong>}
                    {email.subject}
                    {(email.message_count ?? 0) > 1 && <span className="email-thread-count">({email.message_count})</span>}
                  </div>
                  <div className="dashboard-item-meta">
                    {email.from_name || email.from_email} &middot; <TimeAgo date={email.date} />
                  </div>
                  {expanded && email.snippet && <div className="dashboard-item-expanded">{email.snippet}</div>}
                </div>
              </div>
            );
          },
        }}
      />
      {selectedThread && (
        <EmailThreadModal
          threadId={selectedThread.threadId}
          subject={selectedThread.subject}
          onClose={() => setSelectedThread(null)}
        />
      )}
    </>
  );
}
