import { useState } from 'react';
import {
  useAuthStatus,
  useGoogleAuth,
  useGoogleRevoke,
  useTestConnection,
  useSync,
} from '../api/hooks';
import type { ServiceAuthStatus, SyncSourceInfo } from '../api/types';

const SERVICE_INFO: Record<
  string,
  { label: string; description: string; setupHint: string }
> = {
  google: {
    label: 'Google',
    description: 'Gmail, Calendar, Drive, Sheets',
    setupHint:
      'Run: gcloud auth application-default login --scopes="https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/spreadsheets.readonly"',
  },
  slack: {
    label: 'Slack',
    description: 'Direct messages and mentions',
    setupHint: 'Add SLACK_TOKEN to .env (get a token from api.slack.com/apps)',
  },
  notion: {
    label: 'Notion',
    description: 'Recently edited pages',
    setupHint:
      'Add NOTION_TOKEN to .env (create an integration at notion.so/my-integrations)',
  },
  granola: {
    label: 'Granola',
    description: 'Meeting notes (local cache)',
    setupHint: 'Install Granola and record at least one meeting',
  },
  github: {
    label: 'GitHub',
    description: 'Pull requests and code search (osmoai/osmo)',
    setupHint: 'Install gh CLI and run: gh auth login',
  },
  ramp: {
    label: 'Ramp',
    description: 'Corporate card transactions and expenses',
    setupHint: 'Add RAMP_CLIENT_ID and RAMP_CLIENT_SECRET to .env',
  },
};

function StatusBadge({ status }: { status: ServiceAuthStatus }) {
  const hasSyncErrors = Object.values(status.sync || {}).some(
    (s) => s.last_sync_status === 'error'
  );
  const hasSyncSuccess = Object.values(status.sync || {}).some(
    (s) => s.last_sync_status === 'success'
  );

  // Sync success is the strongest signal — if data synced, we're connected
  if (hasSyncSuccess && !hasSyncErrors) {
    return <span className="auth-badge auth-badge-connected">connected</span>;
  }
  if (hasSyncSuccess && hasSyncErrors) {
    return <span className="auth-badge auth-badge-configured">partial</span>;
  }
  if (status.connected) {
    return <span className="auth-badge auth-badge-connected">authenticated</span>;
  }
  if (hasSyncErrors) {
    return <span className="auth-badge auth-badge-error">sync error</span>;
  }
  if (status.configured && status.error) {
    return <span className="auth-badge auth-badge-error">error</span>;
  }
  if (status.configured) {
    return <span className="auth-badge auth-badge-configured">configured</span>;
  }
  return <span className="auth-badge auth-badge-none">not configured</span>;
}

function SyncErrorBlock({ name, info }: { name: string; info: SyncSourceInfo }) {
  const [showDetail, setShowDetail] = useState(false);

  if (info.last_sync_status !== 'error') return null;

  return (
    <div className="auth-error">
      <div className="auth-error-label">Sync error — {name}</div>
      <div className="auth-error-message">
        {info.last_error?.split('\n').pop()?.trim() || 'Unknown error'}
      </div>
      {info.last_error && (
        <>
          <button
            className="auth-detail-toggle"
            onClick={() => setShowDetail(!showDetail)}
          >
            {showDetail ? 'Hide traceback' : 'Show traceback'}
          </button>
          {showDetail && (
            <pre className="auth-error-detail">{info.last_error}</pre>
          )}
        </>
      )}
      {info.last_sync_at && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 'var(--space-xs)' }}>
          Last attempted: {new Date(info.last_sync_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}

function SyncSuccessBlock({ name, info }: { name: string; info: SyncSourceInfo }) {
  if (info.last_sync_status !== 'success') return null;

  return (
    <div className="auth-sync-ok">
      <span className="status-ok">{name}</span>: {info.items_synced} items synced
      {info.last_sync_at && (
        <span style={{ color: 'var(--color-text-light)' }}>
          {' '}— {new Date(info.last_sync_at).toLocaleString()}
        </span>
      )}
    </div>
  );
}

function ServiceCard({
  service,
  status,
}: {
  service: string;
  status: ServiceAuthStatus;
}) {
  const info = SERVICE_INFO[service];
  const googleAuth = useGoogleAuth();
  const googleRevoke = useGoogleRevoke();
  const testConnection = useTestConnection();
  const [showDetail, setShowDetail] = useState(false);

  const syncEntries = Object.entries(status.sync || {});
  const hasSyncData = syncEntries.length > 0;
  const hasSyncSuccess = syncEntries.some(([, s]) => s.last_sync_status === 'success');

  return (
    <div className="auth-card">
      <div className="auth-card-header">
        <div>
          <div className="auth-card-title">{info.label}</div>
          <div className="auth-card-description">{info.description}</div>
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Auth-level error — hide if sync is working (auth check may be a false alarm) */}
      {status.error && !hasSyncSuccess && (
        <div className="auth-error">
          <div className="auth-error-label">Auth error</div>
          <div className="auth-error-message">{status.error}</div>
          {status.detail && (
            <>
              <button
                className="auth-detail-toggle"
                onClick={() => setShowDetail(!showDetail)}
              >
                {showDetail ? 'Hide details' : 'Show details'}
              </button>
              {showDetail && (
                <pre className="auth-error-detail">{status.detail}</pre>
              )}
            </>
          )}
        </div>
      )}

      {/* Sync errors per source (e.g. gmail, calendar separately) */}
      {syncEntries.map(([name, syncInfo]) => (
        <SyncErrorBlock key={name} name={name} info={syncInfo} />
      ))}

      {/* Sync successes */}
      {hasSyncData && syncEntries.some(([, s]) => s.last_sync_status === 'success') && (
        <div className="auth-sync-summary">
          {syncEntries.map(([name, syncInfo]) => (
            <SyncSuccessBlock key={name} name={name} info={syncInfo} />
          ))}
        </div>
      )}

      {!status.configured && !status.error && (
        <div className="auth-setup-hint">
          <div className="auth-error-label">Setup</div>
          <code>{info.setupHint}</code>
        </div>
      )}

      {status.connected && status.detail && !status.error && (
        <div className="auth-detail-info">{status.detail}</div>
      )}

      <div className="auth-card-actions">
        {service === 'google' && !status.connected && (
          <button
            className="auth-action-btn"
            onClick={() => googleAuth.mutate()}
            disabled={googleAuth.isPending}
          >
            {googleAuth.isPending ? 'Authenticating...' : 'Authenticate'}
          </button>
        )}
        {service === 'google' && status.connected && (
          <button
            className="auth-action-btn auth-action-btn-secondary"
            onClick={() => googleRevoke.mutate()}
            disabled={googleRevoke.isPending}
          >
            {googleRevoke.isPending ? 'Revoking...' : 'Disconnect'}
          </button>
        )}
        {status.configured && (
          <button
            className="auth-action-btn auth-action-btn-secondary"
            onClick={() => testConnection.mutate(service)}
            disabled={testConnection.isPending}
          >
            {testConnection.isPending ? 'Testing...' : 'Test Connection'}
          </button>
        )}
      </div>

      {googleAuth.data?.error && (
        <div className="auth-error" style={{ marginTop: 'var(--space-sm)' }}>
          <div className="auth-error-label">OAuth Error</div>
          <div className="auth-error-message">
            {googleAuth.data.error}
          </div>
        </div>
      )}
    </div>
  );
}

export function SettingsPage() {
  const { data, isLoading, error, refetch } = useAuthStatus();
  const triggerSync = useSync();

  if (isLoading) return <p className="empty-state">Checking connections...</p>;
  if (error)
    return <p className="empty-state">Failed to load auth status: {String(error)}</p>;

  return (
    <div>
      <h1>Settings</h1>

      <h2>Connections</h2>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
        Manage authentication for external services. Test connections to diagnose
        issues.
      </p>

      <div className="auth-grid">
        {data &&
          Object.entries(data).map(([service, status]) => (
            <ServiceCard key={service} service={service} status={status} />
          ))}
      </div>

      <div className="auth-page-actions">
        <button
          className="sync-button"
          onClick={() => refetch()}
        >
          Re-check All
        </button>
        <button
          className={`sync-button ${triggerSync.isPending ? 'syncing' : ''}`}
          onClick={() => {
            triggerSync.mutate();
            setTimeout(() => refetch(), 5000);
          }}
          disabled={triggerSync.isPending}
        >
          <span className={`sync-icon ${triggerSync.isPending ? 'syncing' : ''}`}>
            &#x21bb;
          </span>
          {triggerSync.isPending ? 'Syncing...' : 'Sync All Sources'}
        </button>
      </div>
    </div>
  );
}
