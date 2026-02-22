import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useAuthStatus,
  useGoogleAuth,
  useGoogleRevoke,
  useTestConnection,
  useSync,
  useProfile,
  useUpdateProfile,
  useConnectors,
  useToggleConnector,
  useSecrets,
  useUpdateSecret,
  useSetupStatus,
  useResetData,
} from '../api/hooks';
import type { ServiceAuthStatus, SyncSourceInfo, ConnectorInfo, UserProfile } from '../api/types';

function StatusBadge({ status }: { status: ServiceAuthStatus }) {
  const hasSyncErrors = Object.values(status.sync || {}).some(
    (s) => s.last_sync_status === 'error'
  );
  const hasSyncSuccess = Object.values(status.sync || {}).some(
    (s) => s.last_sync_status === 'success'
  );

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
  connector,
  status,
}: {
  connector: ConnectorInfo;
  status: ServiceAuthStatus | undefined;
}) {
  const googleAuth = useGoogleAuth();
  const googleRevoke = useGoogleRevoke();
  const testConnection = useTestConnection();
  const toggle = useToggleConnector();
  const secrets = useSecrets();
  const updateSecret = useUpdateSecret();
  const [showDetail, setShowDetail] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [tokenInputs, setTokenInputs] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const syncEntries = Object.entries(status?.sync || {});
  const hasSyncSuccess = syncEntries.some(([, s]) => s.last_sync_status === 'success');
  const secretsData = secrets.data ?? {};

  const handleSaveToken = (key: string) => {
    const val = tokenInputs[key];
    if (val) {
      updateSecret.mutate({ key, value: val }, {
        onSuccess: () => {
          setTokenInputs((prev) => ({ ...prev, [key]: '' }));
          setSaveSuccess(key);
          setTimeout(() => setSaveSuccess(null), 3000);
        },
      });
    }
  };

  const handleTest = () => {
    setTestResult(null);
    testConnection.mutate(connector.id, {
      onSuccess: (data) => {
        if (data.connected) {
          setTestResult({ ok: true, message: data.detail || 'Connected successfully' });
        } else {
          setTestResult({ ok: false, message: data.error || 'Connection failed' });
        }
      },
      onError: (err) => {
        setTestResult({ ok: false, message: err instanceof Error ? err.message : 'Connection test failed' });
      },
    });
  };

  return (
    <div className="auth-card">
      <div className="auth-card-header">
        <div>
          <div className="auth-card-title">
            {connector.name}
            <label className="setup-toggle" style={{ marginLeft: 'var(--space-sm)', verticalAlign: 'middle' }}>
              <input
                type="checkbox"
                checked={connector.enabled}
                onChange={() => toggle.mutate({ id: connector.id, enabled: !connector.enabled })}
              />
              <span className="setup-toggle-slider" />
            </label>
          </div>
          <div className="auth-card-description">{connector.description}</div>
        </div>
        {status && <StatusBadge status={status} />}
      </div>

      {connector.enabled && (
        <>
          {/* Auth-level error */}
          {status?.error && !hasSyncSuccess && (
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

          {/* Sync errors */}
          {syncEntries.map(([name, syncInfo]) => (
            <SyncErrorBlock key={name} name={name} info={syncInfo} />
          ))}

          {/* Sync successes */}
          {syncEntries.some(([, s]) => s.last_sync_status === 'success') && (
            <div className="auth-sync-summary">
              {syncEntries.map(([name, syncInfo]) => (
                <SyncSuccessBlock key={name} name={name} info={syncInfo} />
              ))}
            </div>
          )}

          {/* Inline token inputs */}
          {connector.secret_keys.map((key) => (
            <div key={key} className="setup-secret-row" style={{ margin: 'var(--space-md) 0' }}>
              <div className="setup-secret-label">
                {key}
                {secretsData[key]?.configured && (
                  <span className="setup-secret-configured"> {secretsData[key].masked}</span>
                )}
              </div>
              <div className="setup-secret-input">
                <input
                  type="password"
                  value={tokenInputs[key] ?? ''}
                  onChange={(e) => setTokenInputs({ ...tokenInputs, [key]: e.target.value })}
                  placeholder={secretsData[key]?.configured ? 'Replace existing token...' : 'Paste token here'}
                />
                <button
                  className="btn-primary"
                  onClick={() => handleSaveToken(key)}
                  disabled={!tokenInputs[key] || updateSecret.isPending}
                >
                  Save
                </button>
              </div>
              {saveSuccess === key && (
                <div className="setup-feedback setup-feedback-ok">Token saved.</div>
              )}
            </div>
          ))}

          {status?.connected && status?.detail && !status?.error && (
            <div className="auth-detail-info">{status.detail}</div>
          )}

          <div className="auth-card-actions">
            {connector.category === 'oauth' && !status?.connected && (
              <button
                className="auth-action-btn"
                onClick={() => googleAuth.mutate()}
                disabled={googleAuth.isPending}
              >
                {googleAuth.isPending ? 'Authenticating...' : 'Authenticate'}
              </button>
            )}
            {connector.category === 'oauth' && status?.connected && (
              <button
                className="auth-action-btn auth-action-btn-secondary"
                onClick={() => googleRevoke.mutate()}
                disabled={googleRevoke.isPending}
              >
                {googleRevoke.isPending ? 'Revoking...' : 'Disconnect'}
              </button>
            )}
            <button
              className="auth-action-btn auth-action-btn-secondary"
              onClick={handleTest}
              disabled={testConnection.isPending}
            >
              {testConnection.isPending ? 'Testing...' : 'Test Connection'}
            </button>
            {testResult && (
              <span className={`setup-feedback ${testResult.ok ? 'setup-feedback-ok' : 'setup-feedback-err'}`}>
                {testResult.message}
              </span>
            )}
          </div>

          {/* Help steps */}
          <button className="setup-help-toggle" onClick={() => setShowHelp(!showHelp)}>
            {showHelp ? 'Hide setup guide' : 'How to set up'}
          </button>
          {showHelp && (
            <ol className="setup-help-steps">
              {connector.help_steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
              {connector.help_url && (
                <li>
                  <a href={connector.help_url} target="_blank" rel="noopener noreferrer">
                    Open developer portal &rarr;
                  </a>
                </li>
              )}
            </ol>
          )}

          {googleAuth.data?.error && (
            <div className="auth-error" style={{ marginTop: 'var(--space-md)' }}>
              <div className="auth-error-label">OAuth Error</div>
              <div className="auth-error-message">{googleAuth.data.error}</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProfileSection() {
  const { data: profile } = useProfile();
  const update = useUpdateProfile();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Partial<UserProfile>>({});

  const val = (key: keyof UserProfile) =>
    (form[key] as string) ?? (profile?.[key] as string) ?? '';

  const save = () => {
    const updates: Partial<UserProfile> = {};
    for (const key of ['user_name', 'user_title', 'user_company', 'user_company_description', 'user_email', 'user_email_domain', 'github_repo'] as const) {
      if (form[key] !== undefined) updates[key] = form[key];
    }
    if (Object.keys(updates).length > 0) {
      update.mutate(updates, { onSuccess: () => setEditing(false) });
    } else {
      setEditing(false);
    }
  };

  if (!editing) {
    const name = profile?.user_name;
    return (
      <div style={{ marginBottom: 'var(--space-lg)' }}>
        <h2>Profile</h2>
        {name ? (
          <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
            {name}
            {profile?.user_title && ` — ${profile.user_title}`}
            {profile?.user_company && ` at ${profile.user_company}`}
            <button
              className="btn-secondary"
              onClick={() => { setForm({}); setEditing(true); }}
              style={{ marginLeft: 'var(--space-sm)' }}
            >
              Edit
            </button>
          </div>
        ) : (
          <button className="btn-primary" onClick={() => setEditing(true)}>
            Set up profile
          </button>
        )}
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 'var(--space-lg)' }}>
      <h2>Profile</h2>
      <div className="setup-form" style={{ maxWidth: '400px' }}>
        <label>Name <input type="text" value={val('user_name')} onChange={(e) => setForm({ ...form, user_name: e.target.value })} /></label>
        <label>Title <input type="text" value={val('user_title')} onChange={(e) => setForm({ ...form, user_title: e.target.value })} /></label>
        <label>Company <input type="text" value={val('user_company')} onChange={(e) => setForm({ ...form, user_company: e.target.value })} /></label>
        <label>Company Description <input type="text" value={val('user_company_description')} onChange={(e) => setForm({ ...form, user_company_description: e.target.value })} /></label>
        <label>Email <input type="email" value={val('user_email')} onChange={(e) => setForm({ ...form, user_email: e.target.value })} /></label>
        <label>Email Domain <input type="text" value={val('user_email_domain')} onChange={(e) => setForm({ ...form, user_email_domain: e.target.value })} /></label>
        <label>GitHub Repo <input type="text" value={val('github_repo')} onChange={(e) => setForm({ ...form, github_repo: e.target.value })} placeholder="e.g. myorg/myrepo" /></label>
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
        <button className="btn-primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? 'Saving...' : 'Save'}
        </button>
        <button className="btn-secondary" onClick={() => setEditing(false)}>Cancel</button>
      </div>
    </div>
  );
}

function ResetSection() {
  const navigate = useNavigate();
  const resetData = useResetData();
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState('');

  const handleReset = () => {
    resetData.mutate(undefined, {
      onSuccess: () => navigate('/setup'),
    });
  };

  return (
    <div style={{ marginTop: 'var(--space-xl)', paddingTop: 'var(--space-lg)', borderTop: '1px solid var(--color-border)' }}>
      <h2>Reset</h2>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
        Delete all data, settings, and connections. Returns the app to its initial setup state.
      </p>
      {!confirming ? (
        <button className="btn-danger" onClick={() => setConfirming(true)}>
          Start Over
        </button>
      ) : (
        <div>
          <p style={{ fontSize: 'var(--text-sm)', marginBottom: 'var(--space-sm)' }}>
            This will permanently delete your database, config, sessions, and avatars.
            Type <strong>reset</strong> to confirm.
          </p>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type 'reset'"
              style={{ width: 140, fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-xs) var(--space-sm)' }}
            />
            <button
              className="btn-danger"
              onClick={handleReset}
              disabled={confirmText !== 'reset' || resetData.isPending}
            >
              {resetData.isPending ? 'Resetting...' : 'Confirm Reset'}
            </button>
            <button
              className="auth-action-btn"
              onClick={() => { setConfirming(false); setConfirmText(''); }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function SettingsPage() {
  const { data: authData, isLoading: authLoading, refetch } = useAuthStatus();
  const { data: connectors, isLoading: connectorsLoading } = useConnectors();
  const { data: setupStatus } = useSetupStatus();
  const triggerSync = useSync();

  if (authLoading || connectorsLoading) return <p className="empty-state">Loading...</p>;

  const authMap = authData ?? {};

  return (
    <div>
      <h1>Settings</h1>

      <ProfileSection />

      <h2>Connections</h2>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
        Enable connectors and configure credentials. Toggle services on/off as needed.
      </p>

      <div className="auth-grid">
        {(connectors ?? []).map((connector) => (
          <ServiceCard
            key={connector.id}
            connector={connector}
            status={authMap[connector.id as keyof typeof authMap]}
          />
        ))}
      </div>

      <div className="auth-page-actions">
        <button className="sync-button" onClick={() => refetch()}>
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

      {setupStatus && (
        <div style={{ marginTop: 'var(--space-lg)', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
          <h2>Data</h2>
          <div>Data directory: <code>{setupStatus.data_dir}</code></div>
          <div>Database: <code>{setupStatus.database_path}</code></div>
        </div>
      )}

      <ResetSection />
    </div>
  );
}
