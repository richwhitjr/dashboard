import { useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePriorities, useRefreshPriorities, useDismissPriority, useConnectors } from '../api/hooks';
import { useFocusNavigation } from '../hooks/useFocusNavigation';

const SOURCE_LABELS: Record<string, string> = {
  slack: 'Slack',
  email: 'Email',
  calendar: 'Calendar',
  note: 'Note',
  ramp: 'Ramp',
};

export function PrioritiesPage() {
  const { data: priorities, isLoading } = usePriorities();
  const refreshPriorities = useRefreshPriorities();
  const dismissPriority = useDismissPriority();
  const { data: connectors } = useConnectors();
  const geminiEnabled = connectors?.some(c => c.id === 'gemini' && c.enabled) ?? false;

  const items = useMemo(() => priorities?.items ?? [], [priorities]);

  const handleDismiss = (title: string, reason: 'done' | 'ignored') => {
    dismissPriority.mutate({ title, reason });
  };

  const onDismiss = useCallback(
    (index: number) => {
      const item = items[index];
      if (item) dismissPriority.mutate({ title: item.title, reason: 'ignored' });
    },
    [items, dismissPriority],
  );

  const { containerRef } = useFocusNavigation({
    selector: '.priority-item',
    enabled: !isLoading && items.length > 0,
    onDismiss,
  });

  const handleRefresh = () => {
    refreshPriorities.mutate();
  };

  return (
    <div ref={containerRef}>
      <div className="priorities-header">
        <h1>Priorities</h1>
        <button
          className="priorities-refresh-btn"
          onClick={handleRefresh}
          disabled={refreshPriorities.isPending}
          title="Refresh priorities"
        >
          {refreshPriorities.isPending ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {isLoading && (
        <p className="empty-state">Analyzing your morning...</p>
      )}
      {priorities?.error && (
        <p className="empty-state">
          Could not load priorities. Check your Gemini API key in{' '}
          <Link to="/settings">Settings</Link>.
        </p>
      )}
      {!isLoading && !priorities?.error && items.length === 0 && (
        <p className="empty-state">
          {geminiEnabled
            ? 'No priorities generated yet. Try refreshing.'
            : <>Enable Gemini AI in <Link to="/settings">Settings</Link> to get AI-powered priorities.</>}
        </p>
      )}
      {items.map((item, i) => (
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
  );
}
