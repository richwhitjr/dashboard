import { useState, useCallback } from 'react';
import { useDashboard, usePriorities, useRefreshPriorities, useDismissPriority, useDismissDashboardItem, useSyncStatus } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { NewsFeed } from '../components/NewsFeed';
import { EmailThreadModal } from '../components/EmailThreadModal';
import { cleanSlackText } from '../utils/cleanSlackText';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import type { Email, SlackMessage, GitHubPullRequest, NotionPage } from '../api/types';

const SOURCE_LABELS: Record<string, string> = {
  slack: 'Slack',
  email: 'Email',
  calendar: 'Calendar',
  note: 'Note',
};

const DAY_OPTIONS = [1, 7, 30] as const;

function formatTimeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function DayFilter({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  return (
    <span className="day-filter">
      {DAY_OPTIONS.map((d) => (
        <button
          key={d}
          className={`day-filter-btn${value === d ? ' day-filter-active' : ''}`}
          onClick={() => onChange(d)}
        >
          {d}d
        </button>
      ))}
    </span>
  );
}

function DismissBtn({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="dashboard-dismiss-btn"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick(); }}
      title="Mark as seen"
    >
      &times;
    </button>
  );
}

export function DashboardPage() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = useDashboard(days);
  const { data: syncStatus } = useSyncStatus();

  const lastSyncedAt = (() => {
    if (!syncStatus?.sources) return null;
    const timestamps = Object.values(syncStatus.sources)
      .map((s) => s.last_sync_at)
      .filter(Boolean);
    if (!timestamps.length) return null;
    return timestamps.reduce((a, b) => (a > b ? a : b));
  })();

  const { data: priorities, isLoading: prioritiesLoading } = usePriorities();
  const refreshPriorities = useRefreshPriorities();
  const dismissPriority = useDismissPriority();
  const dismissItem = useDismissDashboardItem();
  const [selectedThread, setSelectedThread] = useState<{ threadId: string; subject: string } | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleDismiss = (title: string, reason: 'done' | 'ignored') => {
    dismissPriority.mutate({ title, reason });
  };

  const handleRefresh = () => {
    refreshPriorities.mutate();
  };

  // Create unified item list for keyboard navigation
  type DashboardItem =
    | { type: 'email'; id: string; data: Email }
    | { type: 'slack'; id: string; data: SlackMessage }
    | { type: 'github'; id: string; data: GitHubPullRequest }
    | { type: 'notion'; id: string; data: NotionPage };

  const allItems: DashboardItem[] = [];
  if (data) {
    data.emails_recent?.forEach(email => allItems.push({ type: 'email', id: `email-${email.id}`, data: email }));
    data.slack_recent?.forEach(msg => allItems.push({ type: 'slack', id: `slack-${msg.id}`, data: msg }));
    data.github_review_requests?.forEach(pr => allItems.push({ type: 'github', id: `gh-${pr.number}`, data: pr }));
    data.notion_recent?.forEach(page => allItems.push({ type: 'notion', id: `notion-${page.id}`, data: page }));
  }

  const handleExpandAtIndex = (index: number) => {
    const item = allItems[index];
    if (item) toggleExpand(item.id);
  };

  const handleDismissAtIndex = (index: number) => {
    const item = allItems[index];
    if (!item) return;

    if (item.type === 'email') {
      dismissItem.mutate({ source: 'email', item_id: item.data.thread_id || item.data.id });
    } else if (item.type === 'slack') {
      dismissItem.mutate({ source: 'slack', item_id: item.data.id });
    } else if (item.type === 'github') {
      dismissItem.mutate({ source: 'github', item_id: String(item.data.number) });
    } else if (item.type === 'notion') {
      dismissItem.mutate({ source: 'notion', item_id: item.data.id });
    }
  };

  const handleOpenAtIndex = (index: number) => {
    const item = allItems[index];
    if (!item) return;

    if (item.type === 'email') {
      setSelectedThread({
        threadId: item.data.thread_id || item.data.id,
        subject: item.data.subject,
      });
    }
    // For other types (slack, github, notion), the default click behavior will work (links)
  };

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: !isLoading,
    onExpand: handleExpandAtIndex,
    onDismiss: handleDismissAtIndex,
    onOpen: handleOpenAtIndex,
  });

  if (isLoading) return <p className="empty-state">Loading...</p>;

  return (
    <div ref={containerRef}>
      <h1>Today</h1>

      <div id="priorities" className="priorities-section">
        <div className="priorities-header">
          <h2>Priorities</h2>
          <button
            className="priorities-refresh-btn"
            onClick={handleRefresh}
            disabled={refreshPriorities.isPending}
            title="Refresh priorities"
          >
            {refreshPriorities.isPending ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        {prioritiesLoading && (
          <p className="empty-state">Analyzing your morning...</p>
        )}
        {priorities?.error && (
          <p className="empty-state">Could not load priorities: {priorities.error}</p>
        )}
        {!prioritiesLoading && !priorities?.error && priorities?.items.length === 0 && (
          <p className="empty-state">No priorities — add a GEMINI_API_KEY to enable</p>
        )}
        {priorities?.items.map((item, i) => (
          <div key={i} className={`priority-item priority-urgency-${item.urgency}`}>
            <div className="priority-item-header">
              <span className="priority-item-title">{item.title}</span>
              <div className="priority-item-actions">
                <button
                  className="priority-dismiss-btn priority-done-btn"
                  onClick={() => handleDismiss(item.title, 'done')}
                  title="Mark as done"
                >
                  Done
                </button>
                <button
                  className="priority-dismiss-btn priority-ignore-btn"
                  onClick={() => handleDismiss(item.title, 'ignored')}
                  title="Ignore"
                >
                  Ignore
                </button>
                <span className={`priority-source-badge priority-source-${item.source}`}>
                  {SOURCE_LABELS[item.source] || item.source}
                </span>
              </div>
            </div>
            <div className="priority-item-reason">{item.reason}</div>
          </div>
        ))}
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-card">
          <h3>Calendar</h3>
          {data?.calendar_today.length === 0 && (
            <p className="empty-state">No events today</p>
          )}
          {data?.calendar_today.map((event) => (
            <div key={event.id} className="dashboard-item">
              <span className="dashboard-item-time">
                {new Date(event.start_time).toLocaleTimeString('en-US', {
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </span>{' '}
              <span className="dashboard-item-title">{event.summary}</span>
            </div>
          ))}
        </div>

        <div className="dashboard-card">
          <h3>Upcoming Meetings</h3>
          {data?.meetings_upcoming.length === 0 && (
            <p className="empty-state">No upcoming meetings</p>
          )}
          {data?.meetings_upcoming.map((event) => (
            <div key={event.id} className="dashboard-item">
              <span className="dashboard-item-time">
                {new Date(event.start_time).toLocaleDateString('en-US', {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </span>{' '}
              <span className="dashboard-item-title">{event.summary}</span>
            </div>
          ))}
        </div>

        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>Recent Email</h3>
            <DayFilter value={days} onChange={setDays} />
          </div>
          {data?.emails_recent.length === 0 && (
            <p className="empty-state">No recent emails</p>
          )}
          {data?.emails_recent.map((email) => {
            const isExpanded = expandedIds.has(`email-${email.id}`);
            const hasSnippet = !!email.snippet;
            return (
              <div key={email.id} className="dashboard-item-row">
                <div
                  className="dashboard-item dashboard-item-link"
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelectedThread({
                    threadId: email.thread_id || email.id,
                    subject: email.subject,
                  })}
                >
                  <div>
                    <span className="dashboard-item-title">
                      {email.is_unread && <strong>{'\u2022'} </strong>}
                      {email.subject}
                      {(email.message_count ?? 0) > 1 && (
                        <span className="email-thread-count">({email.message_count})</span>
                      )}
                    </span>
                  </div>
                  <div className="dashboard-item-meta">
                    {email.from_name || email.from_email} &middot;{' '}
                    <TimeAgo date={email.date} />
                  </div>
                  {isExpanded && hasSnippet && (
                    <div className="dashboard-item-expanded">{email.snippet}</div>
                  )}
                </div>
                {hasSnippet && (
                  <button
                    className="dashboard-expand-btn"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(`email-${email.id}`); }}
                    title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                  >
                    {isExpanded ? '\u25BE' : '\u25B8'}
                  </button>
                )}
                <DismissBtn onClick={() => dismissItem.mutate({ source: 'email', item_id: email.thread_id || email.id })} />
              </div>
            );
          })}
        </div>

        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>Slack</h3>
            <DayFilter value={days} onChange={setDays} />
          </div>
          {data?.slack_recent.length === 0 && (
            <p className="empty-state">No recent Slack messages</p>
          )}
          {data?.slack_recent.map((msg) => {
            const cleaned = cleanSlackText(msg.text);
            const isExpanded = expandedIds.has(`slack-${msg.id}`);
            const isLong = cleaned.length > 120;
            const inner = (
              <>
                <div className="dashboard-item-title">
                  {isExpanded ? cleaned : (
                    <>
                      {cleaned.slice(0, 120)}
                      {isLong && '...'}
                    </>
                  )}
                </div>
                <div className="dashboard-item-meta">
                  {msg.user_name} in {msg.channel_name || 'DM'}
                </div>
              </>
            );
            return (
              <div key={msg.id} className="dashboard-item-row">
                {msg.permalink ? (
                  <a
                    className="dashboard-item dashboard-item-link"
                    href={msg.permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {inner}
                  </a>
                ) : (
                  <div className="dashboard-item">
                    {inner}
                  </div>
                )}
                {isLong && (
                  <button
                    className="dashboard-expand-btn"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(`slack-${msg.id}`); }}
                    title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                  >
                    {isExpanded ? '\u25BE' : '\u25B8'}
                  </button>
                )}
                <DismissBtn onClick={() => dismissItem.mutate({ source: 'slack', item_id: msg.id })} />
              </div>
            );
          })}
        </div>

        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>GitHub Reviews</h3>
            <DayFilter value={days} onChange={setDays} />
          </div>
          {(!data?.github_review_requests || data.github_review_requests.length === 0) && (
            <p className="empty-state">No pending review requests</p>
          )}
          {data?.github_review_requests?.map((pr) => {
            const isExpanded = expandedIds.has(`gh-${pr.number}`);
            return (
              <div key={pr.number} className="dashboard-item-row">
                <a
                  className="dashboard-item dashboard-item-link"
                  href={pr.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="dashboard-item-title">
                    <span className="github-pr-number">#{pr.number}</span>{' '}
                    {pr.title}
                  </div>
                  <div className="dashboard-item-meta">
                    {pr.author} &middot; <TimeAgo date={pr.updated_at} />
                  </div>
                  {isExpanded && (
                    <div className="dashboard-item-expanded">
                      {pr.head_ref} &rarr; {pr.base_ref}
                      {pr.labels.length > 0 && <span> &middot; {pr.labels.join(', ')}</span>}
                    </div>
                  )}
                </a>
                <button
                  className="dashboard-expand-btn"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(`gh-${pr.number}`); }}
                  title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                >
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
                <DismissBtn onClick={() => dismissItem.mutate({ source: 'github', item_id: String(pr.number) })} />
              </div>
            );
          })}
        </div>

        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>Notion</h3>
            <DayFilter value={days} onChange={setDays} />
          </div>
          {data?.notion_recent.length === 0 && (
            <p className="empty-state">No recent Notion pages</p>
          )}
          {data?.notion_recent.map((page) => {
            const isExpanded = expandedIds.has(`notion-${page.id}`);
            const hasExtra = !!(page.snippet || page.relevance_reason);
            return (
              <div key={page.id} className="dashboard-item-row">
                <a
                  className="dashboard-item dashboard-item-link"
                  href={page.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="dashboard-item-title">{page.title}</span>
                  <div className="dashboard-item-meta">
                    {!isExpanded && page.relevance_reason && (
                      <span>{page.relevance_reason} &middot; </span>
                    )}
                    <TimeAgo date={page.last_edited_time} />
                  </div>
                  {isExpanded && (
                    <div className="dashboard-item-expanded">
                      {page.snippet && <div>{page.snippet}</div>}
                      {page.relevance_reason && <div style={{ fontStyle: 'italic' }}>{page.relevance_reason}</div>}
                    </div>
                  )}
                </a>
                {hasExtra && (
                  <button
                    className="dashboard-expand-btn"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(`notion-${page.id}`); }}
                    title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                  >
                    {isExpanded ? '\u25BE' : '\u25B8'}
                  </button>
                )}
                <DismissBtn onClick={() => dismissItem.mutate({ source: 'notion', item_id: page.id })} />
              </div>
            );
          })}
        </div>

        <div className="dashboard-card">
          <h3>Status</h3>
          <div className="dashboard-item">
            <span className="dashboard-item-title">
              {data?.notes_open_count ?? 0} open notes
            </span>
          </div>
        </div>
      </div>

      <h2>News</h2>
      <NewsFeed />

      {selectedThread && (
        <EmailThreadModal
          threadId={selectedThread.threadId}
          subject={selectedThread.subject}
          onClose={() => setSelectedThread(null)}
        />
      )}

      {allItems.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss']} />
      )}

      {lastSyncedAt && (
        <div style={{
          position: 'fixed',
          bottom: 16,
          left: 'calc(var(--sidebar-width) + 16px)',
          fontSize: 'var(--text-xs)',
          color: 'var(--color-text-light)',
          pointerEvents: 'none',
        }}>
          synced {formatTimeAgo(lastSyncedAt)}
        </div>
      )}
    </div>
  );
}
