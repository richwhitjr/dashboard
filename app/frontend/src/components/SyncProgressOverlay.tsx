import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSyncStatus, useRefreshPriorities, useRefreshPrioritizedEmail, useRefreshPrioritizedSlack, useRefreshPrioritizedNotion, useRefreshPrioritizedNews, useRefreshPrioritizedRamp } from '../api/hooks';

type StepStatus = 'pending' | 'running' | 'done' | 'error';

const DATA_SOURCES: { key: string; label: string }[] = [
  { key: 'markdown', label: 'Team files' },
  { key: 'granola', label: 'Meetings' },
  { key: 'gmail', label: 'Gmail' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'slack', label: 'Slack' },
  { key: 'notion', label: 'Notion' },
  { key: 'github', label: 'GitHub' },
  { key: 'ramp', label: 'Ramp' },
  { key: 'news', label: 'News' },
];

const LLM_STEPS: { key: string; label: string }[] = [
  { key: 'priorities', label: 'Action items' },
  { key: 'email', label: 'Email insights' },
  { key: 'slack', label: 'Slack highlights' },
  { key: 'notion', label: 'Notion pages' },
  { key: 'news', label: 'News digest' },
  { key: 'ramp', label: 'Expenses' },
];

type Phase = 'hidden' | 'syncing' | 'llm' | 'done';

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'running') {
    return (
      <svg className="sync-step-spinner" width="14" height="14" viewBox="0 0 14 14">
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
      </svg>
    );
  }
  if (status === 'done') {
    return <span className="sync-step-check">✓</span>;
  }
  if (status === 'error') {
    return <span className="sync-step-error-icon">✗</span>;
  }
  return <span className="sync-step-pending-icon">○</span>;
}

export function SyncProgressOverlay() {
  const qc = useQueryClient();
  const syncStatus = useSyncStatus();
  const refreshPriorities = useRefreshPriorities();
  const refreshEmail = useRefreshPrioritizedEmail();
  const refreshSlack = useRefreshPrioritizedSlack();
  const refreshNotion = useRefreshPrioritizedNotion();
  const refreshNews = useRefreshPrioritizedNews();
  const refreshRamp = useRefreshPrioritizedRamp();

  const [phase, setPhase] = useState<Phase>('hidden');
  const [syncStartedAt, setSyncStartedAt] = useState<string | null>(null);
  const [llmStatuses, setLlmStatuses] = useState<Record<string, StepStatus>>({});
  const prevRunningRef = useRef(false);
  const llmStartedRef = useRef(false);

  // Detect sync start/end
  useEffect(() => {
    const isRunning = syncStatus.data?.running ?? false;

    if (!prevRunningRef.current && isRunning) {
      // Sync just started
      setPhase('syncing');
      setSyncStartedAt(new Date().toISOString());
      setLlmStatuses({});
      llmStartedRef.current = false;
    } else if (prevRunningRef.current && !isRunning && phase === 'syncing') {
      // Sync just completed — move to LLM phase
      setPhase('llm');
    }

    prevRunningRef.current = isRunning;
  }, [syncStatus.data?.running, phase]);

  // Start LLM refreshes when phase transitions to 'llm'
  useEffect(() => {
    if (phase !== 'llm' || llmStartedRef.current) return;
    llmStartedRef.current = true;

    const initialStatuses: Record<string, StepStatus> = {};
    for (const step of LLM_STEPS) {
      initialStatuses[step.key] = 'running';
    }
    setLlmStatuses(initialStatuses);

    const setStatus = (key: string, status: StepStatus) =>
      setLlmStatuses((prev) => ({ ...prev, [key]: status }));

    const run = async (key: string, fn: () => Promise<unknown>) => {
      try {
        await fn();
        setStatus(key, 'done');
      } catch {
        setStatus(key, 'error');
      }
    };

    Promise.all([
      run('priorities', () => refreshPriorities.mutateAsync()),
      run('email', () => refreshEmail.mutateAsync()),
      run('slack', () => refreshSlack.mutateAsync()),
      run('notion', () => refreshNotion.mutateAsync()),
      run('news', () => refreshNews.mutateAsync()),
      run('ramp', () => refreshRamp.mutateAsync()),
    ]).then(() => {
      setPhase('done');
      setTimeout(() => {
        setPhase('hidden');
        setSyncStartedAt(null);
        setLlmStatuses({});
        llmStartedRef.current = false;
        qc.invalidateQueries();
      }, 1500);
    });
  }, [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  if (phase === 'hidden') return null;

  const sources = syncStatus.data?.sources ?? {};
  const currentSource = syncStatus.data?.current_source;

  function getSourceStatus(key: string): StepStatus {
    if (currentSource === key) return 'running';
    const src = sources[key];
    if (!src || !syncStartedAt) return 'pending';
    if (src.last_sync_at > syncStartedAt) {
      return src.last_sync_status === 'success' ? 'done' : 'error';
    }
    return 'pending';
  }

  const allLlmDone =
    LLM_STEPS.length > 0 &&
    LLM_STEPS.every((s) => llmStatuses[s.key] === 'done' || llmStatuses[s.key] === 'error');

  return (
    <div className="sync-progress-overlay">
      <div className="sync-progress-panel">
        <div className="sync-progress-title">
          {phase === 'done' ? (
            <span className="sync-progress-done">Done ✓</span>
          ) : (
            'Refreshing Dashboard'
          )}
        </div>

        <div className="sync-progress-section">
          <div className="sync-progress-section-label">Data sources</div>
          {DATA_SOURCES.map(({ key, label }) => {
            const status = phase === 'syncing' || phase === 'llm' || phase === 'done'
              ? getSourceStatus(key)
              : 'pending';
            const src = sources[key];
            const showCount = status === 'done' && src?.items_synced != null;
            return (
              <div key={key} className={`sync-step sync-step-${status}`}>
                <StepIcon status={status} />
                <span className="sync-step-label">{label}</span>
                {showCount && (
                  <span className="sync-step-count">{src.items_synced} items</span>
                )}
                {status === 'running' && (
                  <span className="sync-step-hint">syncing…</span>
                )}
              </div>
            );
          })}
        </div>

        <div className="sync-progress-section">
          <div className="sync-progress-section-label">AI rankings</div>
          {LLM_STEPS.map(({ key, label }) => {
            const status: StepStatus =
              phase === 'syncing'
                ? 'pending'
                : llmStatuses[key] ?? 'pending';
            return (
              <div key={key} className={`sync-step sync-step-${status}`}>
                <StepIcon status={status} />
                <span className="sync-step-label">{label}</span>
                {status === 'running' && (
                  <span className="sync-step-hint">ranking…</span>
                )}
              </div>
            );
          })}
        </div>

        {phase === 'done' && allLlmDone && (
          <div className="sync-progress-footer">All sources refreshed</div>
        )}
      </div>
    </div>
  );
}
