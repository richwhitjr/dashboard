import { useEffect, useRef, useState, useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSyncStatus, useCancelSync, useConnectors, useRefreshPriorities, useRefreshPrioritizedEmail, useRefreshPrioritizedSlack, useRefreshPrioritizedNotion, useRefreshPrioritizedNews, useRefreshPrioritizedRamp, useRefreshPrioritizedDrive } from '../api/hooks';

type StepStatus = 'pending' | 'running' | 'done' | 'error';

// Each data source maps to a connector ID (null = always shown)
const ALL_DATA_SOURCES: { key: string; label: string; connector: string | null }[] = [
  { key: 'granola', label: 'Meetings', connector: 'granola' },
  { key: 'gmail', label: 'Gmail', connector: 'google' },
  { key: 'calendar', label: 'Calendar', connector: 'google' },
  { key: 'drive', label: 'Drive', connector: 'google_drive' },
  { key: 'sheets', label: 'Sheets', connector: 'google_drive' },
  { key: 'docs', label: 'Docs', connector: 'google_drive' },
  { key: 'slack', label: 'Slack', connector: 'slack' },
  { key: 'notion', label: 'Notion', connector: 'notion' },
  { key: 'github', label: 'GitHub', connector: 'github' },
  { key: 'ramp', label: 'Ramp transactions', connector: 'ramp' },
  { key: 'ramp_vendors', label: 'Ramp vendors', connector: 'ramp' },
  { key: 'ramp_bills', label: 'Ramp bills', connector: 'ramp' },
  { key: 'news', label: 'News', connector: 'news' },
];

// Each LLM step maps to a connector ID (null = always shown)
const ALL_LLM_STEPS: { key: string; label: string; connector: string | null }[] = [
  { key: 'priorities', label: 'Action items', connector: null },
  { key: 'email', label: 'Email insights', connector: 'google' },
  { key: 'slack', label: 'Slack highlights', connector: 'slack' },
  { key: 'notion', label: 'Notion pages', connector: 'notion' },
  { key: 'drive', label: 'Drive files', connector: 'google_drive' },
  { key: 'news', label: 'News digest', connector: 'news' },
  { key: 'ramp', label: 'Expenses', connector: 'ramp' },
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

/** Extract a short, human-readable message from a Python traceback or error string. */
function shortError(raw: string | null | undefined): string {
  if (!raw) return '';
  // Grab the last line of a traceback (the actual exception)
  const lines = raw.trim().split('\n');
  const last = lines[lines.length - 1].trim();
  // Strip common Python exception prefixes for brevity
  const cleaned = last
    .replace(/^[\w.]+Error:\s*/, '')
    .replace(/^[\w.]+Exception:\s*/, '');
  // Truncate if still very long
  return cleaned.length > 120 ? cleaned.slice(0, 117) + '...' : cleaned;
}

export function SyncProgressOverlay() {
  const qc = useQueryClient();
  const syncStatus = useSyncStatus();
  const { data: connectors } = useConnectors();
  const refreshPriorities = useRefreshPriorities();
  const refreshEmail = useRefreshPrioritizedEmail();
  const refreshSlack = useRefreshPrioritizedSlack();
  const refreshNotion = useRefreshPrioritizedNotion();
  const refreshNews = useRefreshPrioritizedNews();
  const refreshRamp = useRefreshPrioritizedRamp();
  const refreshDrive = useRefreshPrioritizedDrive();

  const cancelSync = useCancelSync();

  const [phase, setPhase] = useState<Phase>('hidden');
  const [syncStartedAt, setSyncStartedAt] = useState<string | null>(null);
  const [llmStatuses, setLlmStatuses] = useState<Record<string, StepStatus>>({});
  const [llmErrors, setLlmErrors] = useState<Record<string, string>>({});
  const prevRunningRef = useRef(false);
  const llmStartedRef = useRef(false);

  // Escape dismisses overlay and cancels any running sync
  useEffect(() => {
    if (phase === 'hidden') return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        cancelSync.mutate();
        setPhase('hidden');
        setSyncStartedAt(null);
        setLlmStatuses({});
        setLlmErrors({});
        llmStartedRef.current = false;
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [phase, cancelSync]);

  // Build set of enabled connector IDs
  const enabledSet = useMemo(
    () => new Set(connectors?.filter(c => c.enabled).map(c => c.id)),
    [connectors],
  );

  const dataSources = useMemo(
    () => ALL_DATA_SOURCES.filter(s => s.connector === null || enabledSet.has(s.connector)),
    [enabledSet],
  );

  const llmSteps = useMemo(
    () => ALL_LLM_STEPS.filter(s => s.connector === null || enabledSet.has(s.connector)),
    [enabledSet],
  );

  // Map of LLM step key → refresh function
  const llmRefreshMap: Record<string, () => Promise<unknown>> = useMemo(() => ({
    priorities: () => refreshPriorities.mutateAsync(),
    email: () => refreshEmail.mutateAsync(),
    slack: () => refreshSlack.mutateAsync(),
    notion: () => refreshNotion.mutateAsync(),
    drive: () => refreshDrive.mutateAsync(),
    news: () => refreshNews.mutateAsync(),
    ramp: () => refreshRamp.mutateAsync(),
  }), [refreshPriorities, refreshEmail, refreshSlack, refreshNotion, refreshDrive, refreshNews, refreshRamp]);

  // Detect sync start/end
  useEffect(() => {
    const isRunning = syncStatus.data?.running ?? false;

    if (!prevRunningRef.current && isRunning) {
      // Sync just started
      setPhase('syncing');
      // Use local ISO to match server's datetime.now().isoformat() format.
      // Subtract 5s buffer — fast sources (granola ~0.2s) may finish before
      // the frontend detects running=true via polling.
      const now = new Date();
      const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000 - 5000);
      setSyncStartedAt(local.toISOString().replace('Z', ''));
      setLlmStatuses({});
      setLlmErrors({});
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
    for (const step of llmSteps) {
      initialStatuses[step.key] = 'running';
    }
    setLlmStatuses(initialStatuses);

    const setStatus = (key: string, status: StepStatus) =>
      setLlmStatuses((prev) => ({ ...prev, [key]: status }));

    const run = async (key: string, fn: () => Promise<unknown>) => {
      try {
        await fn();
        setStatus(key, 'done');
      } catch (err) {
        setStatus(key, 'error');
        const msg = err instanceof Error ? err.message : String(err);
        setLlmErrors((prev) => ({ ...prev, [key]: msg }));
      }
    };

    Promise.all(
      llmSteps.map(step => {
        const fn = llmRefreshMap[step.key];
        return fn ? run(step.key, fn) : Promise.resolve();
      }),
    ).then(() => {
      setPhase('done');
      setTimeout(() => {
        setPhase('hidden');
        setSyncStartedAt(null);
        setLlmStatuses({});
        setLlmErrors({});
        llmStartedRef.current = false;
        qc.invalidateQueries();
      }, 1500);
    });
  }, [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  if (phase === 'hidden') return null;

  const sources = syncStatus.data?.sources ?? {};
  const activeSources = new Set(syncStatus.data?.active_sources ?? []);

  function getSourceStatus(key: string): StepStatus {
    if (activeSources.has(key)) return 'running';
    const src = sources[key];
    if (!src || !syncStartedAt) return 'pending';
    if (src.last_sync_at > syncStartedAt) {
      return src.last_sync_status === 'success' ? 'done' : 'error';
    }
    return 'pending';
  }

  const allLlmDone =
    llmSteps.length > 0 &&
    llmSteps.every((s) => llmStatuses[s.key] === 'done' || llmStatuses[s.key] === 'error');

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
          {dataSources.map(({ key, label }) => {
            const status = phase === 'syncing' || phase === 'llm' || phase === 'done'
              ? getSourceStatus(key)
              : 'pending';
            const src = sources[key];
            const showCount = status === 'done' && src?.items_synced != null;
            const duration = src?.duration_seconds;
            const errorMsg = status === 'error' ? shortError(src?.last_error) : '';
            return (
              <div key={key}>
                <div className={`sync-step sync-step-${status}`}>
                  <StepIcon status={status} />
                  <span className="sync-step-label">{label}</span>
                  {showCount && (
                    <span className="sync-step-count">
                      {src.items_synced} items
                      {duration != null && <span className="sync-step-duration"> · {duration}s</span>}
                    </span>
                  )}
                  {status === 'running' && (
                    <span className="sync-step-hint">syncing…</span>
                  )}
                </div>
                {errorMsg && (
                  <div className="sync-step-error-msg" title={src?.last_error ?? ''}>{errorMsg}</div>
                )}
              </div>
            );
          })}
        </div>

        {llmSteps.length > 0 && (
          <div className="sync-progress-section">
            <div className="sync-progress-section-label">AI rankings</div>
            {llmSteps.map(({ key, label }) => {
              const status: StepStatus =
                phase === 'syncing'
                  ? 'pending'
                  : llmStatuses[key] ?? 'pending';
              const errorMsg = status === 'error' ? shortError(llmErrors[key]) : '';
              return (
                <div key={key}>
                  <div className={`sync-step sync-step-${status}`}>
                    <StepIcon status={status} />
                    <span className="sync-step-label">{label}</span>
                    {status === 'running' && (
                      <span className="sync-step-hint">ranking…</span>
                    )}
                  </div>
                  {errorMsg && (
                    <div className="sync-step-error-msg" title={llmErrors[key] ?? ''}>{errorMsg}</div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {phase === 'done' && allLlmDone && (
          <div className="sync-progress-footer">All sources refreshed</div>
        )}

        {phase !== 'done' && (
          <div className="sync-progress-footer sync-progress-hint">Press Esc to dismiss</div>
        )}
      </div>
    </div>
  );
}
