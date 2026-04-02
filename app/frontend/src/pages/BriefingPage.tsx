import { useState, useCallback, useMemo, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import {
  useBriefing,
  useRefreshPriorities,
  useDismissPriority,
  useDismissDashboardItem,
  useSetupStatus,
  useConnectors,
} from '../api/hooks';
import { EmailThreadModal } from '../components/EmailThreadModal';
import { cleanSlackText } from '../utils/cleanSlackText';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import type { PriorityItem, OvernightItem } from '../api/types';

const GCAL_COLORS: Record<string, string> = {
  '1': '#7986CB', '2': '#33B679', '3': '#8E24AA', '4': '#E67C73',
  '5': '#F6BF26', '6': '#F4511E', '7': '#039BE5', '8': '#616161',
  '9': '#3F51B5', '10': '#0B8043', '11': '#D50000',
};

const SOURCE_LABELS: Record<string, string> = {
  slack: 'Slack',
  email: 'Email',
  calendar: 'Calendar',
  note: 'Thought',
  ramp: 'Ramp',
  drive: 'Drive',
  github: 'GitHub',
  notion: 'Notion',
  granola: 'Granola',
  news: 'News',
  obsidian: 'Obsidian',
};

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function formatDate(): string {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}

function formatEventTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
  });
}

function isWithin30Min(iso: string): boolean {
  const diff = new Date(iso).getTime() - Date.now();
  return diff >= 0 && diff <= 30 * 60 * 1000;
}

function isHappeningNow(start: string, end: string): boolean {
  const now = Date.now();
  return new Date(start).getTime() <= now && new Date(end).getTime() > now;
}

function isOneOnOne(attendeesJson?: string): boolean {
  if (!attendeesJson) return false;
  try {
    const attendees = JSON.parse(attendeesJson);
    return Array.isArray(attendees) && attendees.length === 2;
  } catch {
    return false;
  }
}

function formatOvernightTime(time: string): string {
  // Slack timestamps are unix epoch strings
  const ts = parseFloat(time);
  const date = !isNaN(ts) && ts > 1e9 ? new Date(ts * 1000) : new Date(time);
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function BriefingPage() {
  const { data, isLoading } = useBriefing();
  const refreshPriorities = useRefreshPriorities();
  const dismissPriority = useDismissPriority();
  const dismissItem = useDismissDashboardItem();
  const { data: setupStatus } = useSetupStatus();
  const { data: connectors } = useConnectors();
  const [selectedThread, setSelectedThread] = useState<{ threadId: string; subject: string } | null>(null);
  const [overnightCollapsed, setOvernightCollapsed] = useState(() => new Date().getHours() >= 14);
  const [showAllAttention, setShowAllAttention] = useState(false);

  const enabled = new Set(connectors?.filter(c => c.enabled).map(c => c.id));

  // Unified navigable items: attention + overnight
  type NavItem =
    | { type: 'priority'; index: number; data: PriorityItem }
    | { type: 'overnight'; index: number; data: OvernightItem };

  const navItems = useMemo<NavItem[]>(() => {
    const items: NavItem[] = [];
    data?.attention_items?.forEach((item, i) =>
      items.push({ type: 'priority', index: i, data: item })
    );
    if (!overnightCollapsed) {
      data?.overnight?.forEach((item, i) =>
        items.push({ type: 'overnight', index: i, data: item })
      );
    }
    return items;
  }, [data?.attention_items, data?.overnight, overnightCollapsed]);

  const handleDismissAtIndex = useCallback((idx: number) => {
    const item = navItems[idx];
    if (!item) return;
    if (item.type === 'priority') {
      dismissPriority.mutate({ title: item.data.title, reason: 'ignored' });
    } else {
      const o = item.data as OvernightItem;
      dismissItem.mutate({ source: o.source, item_id: o.id });
    }
  }, [navItems, dismissPriority, dismissItem]);

  const handleOpenAtIndex = useCallback((idx: number) => {
    const item = navItems[idx];
    if (!item) return;
    if (item.type === 'overnight') {
      const o = item.data as OvernightItem;
      if (o.source === 'email') {
        setSelectedThread({ threadId: o.id, subject: o.title });
      } else if (o.permalink || o.url) {
        window.open(o.permalink || o.url, '_blank');
      }
    }
  }, [navItems]);

  const { containerRef } = useFocusNavigation({
    selector: '.briefing-nav-item',
    enabled: !isLoading,
    onDismiss: handleDismissAtIndex,
    onOpen: handleOpenAtIndex,
  });

  if (isLoading) return <p className="empty-state">Loading...</p>;

  const connectedCount = setupStatus?.connected_services ?? 0;
  if (connectedCount === 0 && !data?.calendar_today?.length) {
    return (
      <div>
        <h1>{getGreeting()}.</h1>
        <div className="dashboard-empty-state">
          <h2>Welcome to your dashboard</h2>
          <p>
            Connect your services to get your morning briefing.
            Head to <Link to="/settings">Settings</Link> to get started.
          </p>
          <Link to="/settings" className="btn-primary" style={{ display: 'inline-block', textDecoration: 'none' }}>
            Connect Services
          </Link>
        </div>
      </div>
    );
  }

  const userName = data?.greeting?.user_name;
  const summary = data?.summary;
  const weather = data?.weather;
  const calendar = data?.calendar_today ?? [];
  const calendarSummary = data?.calendar_summary;
  const attention = data?.attention_items ?? [];
  const pulse = data?.pulse;
  const overnight = data?.overnight ?? [];

  return (
    <div ref={containerRef}>
      {/* --- Banner: gradient + greeting + summary --- */}
      <div className="briefing-banner">
        <div className="briefing-header">
          <h1>{getGreeting()}{userName ? `, ${userName}` : ''}.</h1>
          <div className="briefing-date-weather">
            <div>{formatDate()}</div>
            {weather && weather.temp_f !== null && (
              <div>{weather.temp_f}&deg;F, {weather.condition}</div>
            )}
          </div>
        </div>
        {summary && (
          <section className="briefing-summary">
            <p>{summary}</p>
          </section>
        )}
      </div>

      {/* --- Inbox Pulse (compact horizontal) --- */}
      {pulse && (
        <section className="briefing-pulse-compact">
          {pulse.unread_emails > 0 && (
            <Link to="/email" className="briefing-pulse-item">
              <span className="briefing-pulse-count">{pulse.unread_emails}</span>
              unread email{pulse.unread_emails !== 1 ? 's' : ''}
            </Link>
          )}
          {pulse.slack_dms > 0 && (
            <Link to="/slack" className="briefing-pulse-item">
              <span className="briefing-pulse-count">{pulse.slack_dms}</span>
              Slack DM{pulse.slack_dms !== 1 ? 's' : ''}
            </Link>
          )}
          {pulse.pr_reviews > 0 && (
            <Link to="/github" className="briefing-pulse-item">
              <span className="briefing-pulse-count">{pulse.pr_reviews}</span>
              PR review{pulse.pr_reviews !== 1 ? 's' : ''}
            </Link>
          )}
          {pulse.open_notes > 0 && (
            <Link to="/notes" className="briefing-pulse-item">
              <span className="briefing-pulse-count">{pulse.open_notes}</span>
              open task{pulse.open_notes !== 1 ? 's' : ''}
            </Link>
          )}
          {pulse.overdue_bills > 0 && (
            <Link to="/ramp" className="briefing-pulse-item">
              <span className="briefing-pulse-count">{pulse.overdue_bills}</span>
              overdue bill{pulse.overdue_bills !== 1 ? 's' : ''}
            </Link>
          )}
        </section>
      )}

      {/* --- Content Grid: calendar + priorities side by side --- */}
      <div className="briefing-content-grid">
        {/* Column 1: Your Day */}
        <section className="briefing-section">
          <h2>Your day</h2>
          {calendar.length === 0 ? (
            <p className="empty-state">No meetings today</p>
          ) : (
            <>
              <div className="briefing-timeline">
                {calendar.map((event) => {
                  const soon = isWithin30Min(event.start_time);
                  const now = isHappeningNow(event.start_time, event.end_time);
                  const oneOnOne = isOneOnOne(event.attendees_json);
                  const eventColor = event.color_id ? GCAL_COLORS[event.color_id] : undefined;
                  return (
                    <div
                      key={event.id}
                      className={`briefing-timeline-item${now || soon ? ' briefing-timeline-soon' : ''}`}
                      style={eventColor ? { '--event-color': eventColor } as CSSProperties : undefined}
                    >
                      <span className="briefing-timeline-time">
                        {event.all_day ? 'All day' : formatEventTime(event.start_time)}
                      </span>
                      <span className={oneOnOne ? 'briefing-timeline-1on1' : ''}>
                        {event.summary}
                        {now && <span className="briefing-now-badge">now</span>}
                      </span>
                    </div>
                  );
                })}
              </div>
              {calendarSummary && (calendarSummary.tomorrow_count > 0 || calendarSummary.week_count > 0) && (
                <div className="briefing-calendar-summary">
                  {calendarSummary.tomorrow_count > 0 && (
                    <span>{calendarSummary.tomorrow_count} meeting{calendarSummary.tomorrow_count !== 1 ? 's' : ''} tomorrow</span>
                  )}
                  {calendarSummary.tomorrow_count > 0 && calendarSummary.week_count > 0 && (
                    <span> &middot; </span>
                  )}
                  {calendarSummary.week_count > 0 && (
                    <span>{calendarSummary.week_count} this week</span>
                  )}
                </div>
              )}
            </>
          )}
        </section>

        {/* Column 2: Needs Your Attention */}
        <section className="briefing-section">
          <div className="briefing-section-header">
            <h2>Needs your attention</h2>
            {(attention.length > 0 || enabled.has('gemini')) && (
              <button
                className="priorities-refresh-btn"
                onClick={() => refreshPriorities.mutate()}
                disabled={refreshPriorities.isPending}
              >
                {refreshPriorities.isPending ? 'Refreshing...' : 'Refresh'}
              </button>
            )}
          </div>
          {attention.length === 0 && (
            <p className="empty-state">
              {enabled.has('gemini')
                ? 'Nothing urgent right now.'
                : <>Enable Gemini AI in <Link to="/settings">Settings</Link> for priorities.</>
              }
            </p>
          )}
          {(showAllAttention ? attention : attention.slice(0, 5)).map((item, i) => (
            <div
              key={i}
              className={`priority-item priority-urgency-${item.urgency} briefing-nav-item`}
            >
              <div className="priority-item-header">
                <span className="priority-item-title">{item.title}</span>
                <div className="priority-item-actions">
                  <button
                    className="priority-dismiss-btn priority-done-btn"
                    onClick={() => dismissPriority.mutate({ title: item.title, reason: 'done' })}
                    title="Done"
                  >
                    Done
                  </button>
                  <button
                    className="priority-dismiss-btn priority-ignore-btn"
                    onClick={() => dismissPriority.mutate({ title: item.title, reason: 'ignored' })}
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
          {attention.length > 5 && (
            <button
              className="priorities-refresh-btn"
              onClick={() => setShowAllAttention(!showAllAttention)}
              style={{ marginTop: 'var(--space-xs)' }}
            >
              {showAllAttention ? 'Show less' : `Show all (${attention.length})`}
            </button>
          )}
        </section>
      </div>

      {/* --- Overnight Digest (2-column) --- */}
      {overnight.length > 0 && (
        <section className="briefing-section">
          <div className="briefing-section-header">
            <h2>Overnight</h2>
            <button
              className="priorities-refresh-btn"
              onClick={() => setOvernightCollapsed(!overnightCollapsed)}
            >
              {overnightCollapsed ? 'Show' : 'Hide'}
            </button>
          </div>
          {!overnightCollapsed && (
            <div className="briefing-overnight-grid">
              {overnight.map((item) => (
                <div key={`${item.source}-${item.id}`} className="briefing-overnight-item briefing-nav-item">
                  <div className="briefing-overnight-content">
                    <span className={`priority-source-badge priority-source-${item.source}`}>
                      {SOURCE_LABELS[item.source] || item.source}
                    </span>
                    {item.source === 'email' ? (
                      <span
                        className="briefing-overnight-title briefing-overnight-clickable"
                        onClick={() => setSelectedThread({ threadId: item.id, subject: item.title })}
                      >
                        {item.title}
                      </span>
                    ) : item.url || item.permalink ? (
                      <a
                        className="briefing-overnight-title briefing-overnight-clickable"
                        href={item.permalink || item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {item.source === 'slack' ? cleanSlackText(item.title) : item.title}
                      </a>
                    ) : (
                      <span className="briefing-overnight-title">
                        {item.source === 'slack' ? cleanSlackText(item.title) : item.title}
                      </span>
                    )}
                  </div>
                  <div className="briefing-overnight-meta">
                    <span>{item.subtitle}</span>
                    <span> &middot; {formatOvernightTime(item.time)}</span>
                  </div>
                  <button
                    className="dashboard-dismiss-btn"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      dismissItem.mutate({ source: item.source, item_id: item.id });
                    }}
                    title="Dismiss"
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {selectedThread && (
        <EmailThreadModal
          threadId={selectedThread.threadId}
          subject={selectedThread.subject}
          onClose={() => setSelectedThread(null)}
        />
      )}

      {navItems.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'd dismiss']} />
      )}
    </div>
  );
}
