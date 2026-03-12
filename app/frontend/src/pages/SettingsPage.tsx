import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useAuthStatus,
  useGoogleAuth,
  useGranolaAuth,
  useGoogleRevoke,
  useTestConnection,
  useSync,
  useSyncStatus,
  useProfile,
  useUpdateProfile,
  useConnectors,
  useMeetingNotesProviders,
  useToggleConnector,
  useSetGoogleAccessMode,
  useSecrets,
  useUpdateSecret,
  useSetupStatus,
  useResetData,
  useWhatsAppStatus,
  useWhatsAppQR,
  useBackupDatabase,
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

function WhatsAppQRSection() {
  const waStatus = useWhatsAppStatus();
  const waQR = useWhatsAppQR(!waStatus.data?.connected);
  const [starting, setStarting] = useState(false);

  const startSidecar = async () => {
    setStarting(true);
    try {
      await fetch('/api/whatsapp/start', { method: 'POST' });
      // Give it a moment then refetch status
      setTimeout(() => {
        waStatus.refetch();
        waQR.refetch();
        setStarting(false);
      }, 3000);
    } catch {
      setStarting(false);
    }
  };

  if (waStatus.data?.connected) {
    return (
      <div style={{ margin: 'var(--space-md) 0', padding: 'var(--space-sm)', background: 'var(--color-bg-subtle, #f8f8f8)', borderRadius: '4px' }}>
        Connected to WhatsApp{waStatus.data.phone ? ` (${waStatus.data.phone})` : ''}
      </div>
    );
  }

  if (waQR.data?.qr) {
    return (
      <div style={{ margin: 'var(--space-md) 0', textAlign: 'center' }}>
        <p style={{ marginBottom: 'var(--space-sm)', fontSize: 'var(--text-sm)' }}>
          Scan with WhatsApp &rarr; Linked Devices &rarr; Link a Device
        </p>
        <img
          src={waQR.data.qr}
          alt="WhatsApp QR Code"
          style={{ width: 200, height: 200, imageRendering: 'pixelated' }}
        />
      </div>
    );
  }

  // Sidecar not running — show Start button
  const needsStart = !waStatus.data?.connected && !waQR.data?.qr;
  if (needsStart) {
    return (
      <div style={{ margin: 'var(--space-md) 0' }}>
        <button className="btn-primary" onClick={startSidecar} disabled={starting}>
          {starting ? 'Starting...' : 'Start WhatsApp'}
        </button>
      </div>
    );
  }

  if (waQR.data?.error || waStatus.data?.error) {
    return (
      <div className="auth-error" style={{ margin: 'var(--space-md) 0' }}>
        {waQR.data?.error || waStatus.data?.error}
      </div>
    );
  }

  return null;
}

function ServiceCard({
  connector,
  status,
}: {
  connector: ConnectorInfo;
  status: ServiceAuthStatus | undefined;
}) {
  const googleAuth = useGoogleAuth();
  const granolaAuth = useGranolaAuth();
  const googleRevoke = useGoogleRevoke();
  const testConnection = useTestConnection();
  const toggle = useToggleConnector();
  const setAccessMode = useSetGoogleAccessMode();
  const secrets = useSecrets();
  const updateSecret = useUpdateSecret();
  const [showDetail, setShowDetail] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [tokenInputs, setTokenInputs] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [accessModeChanged, setAccessModeChanged] = useState(false);

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

      {connector.enabled && connector.google_access_mode && (
        <div style={{ margin: 'var(--space-sm) 0', fontSize: 'var(--text-sm)' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
            Access:
            <select
              value={connector.google_access_mode}
              onChange={(e) => {
                const mode = e.target.value as 'readonly' | 'readwrite';
                setAccessMode.mutate(mode, {
                  onSuccess: (data) => {
                    if (data.needs_reauth) setAccessModeChanged(true);
                  },
                });
              }}
              disabled={setAccessMode.isPending}
            >
              <option value="readonly">Read Only</option>
              <option value="readwrite">Read &amp; Write</option>
            </select>
          </label>
          {accessModeChanged && (
            <div className="auth-error" style={{ marginTop: 'var(--space-xs)', padding: 'var(--space-xs) var(--space-sm)' }}>
              Access mode changed — click Authenticate below to re-authorize with new permissions.
            </div>
          )}
        </div>
      )}

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
                onClick={() => connector.id === 'granola' ? granolaAuth.mutate() : googleAuth.mutate()}
                disabled={connector.id === 'granola' ? granolaAuth.isPending : googleAuth.isPending}
              >
                {(connector.id === 'granola' ? granolaAuth.isPending : googleAuth.isPending) ? 'Authenticating...' : 'Authenticate'}
              </button>
            )}
            {connector.category === 'oauth' && status?.connected && connector.id === 'granola' && (
              <button
                className="auth-action-btn"
                onClick={() => granolaAuth.mutate()}
                disabled={granolaAuth.isPending}
              >
                {granolaAuth.isPending ? 'Authenticating...' : 'Reauthenticate'}
              </button>
            )}
            {connector.category === 'oauth' && status?.connected && connector.id !== 'granola' && (
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

          {/* WhatsApp QR code pairing */}
          {connector.id === 'whatsapp' && <WhatsAppQRSection />}

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

          {(googleAuth.data?.error || granolaAuth.data?.error) && (
            <div className="auth-error" style={{ marginTop: 'var(--space-md)' }}>
              <div className="auth-error-label">OAuth Error</div>
              <div className="auth-error-message">{googleAuth.data?.error || granolaAuth.data?.error}</div>
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
    for (const key of ['user_name', 'user_title', 'user_company', 'user_company_description', 'user_email', 'user_email_domain', 'user_location', 'github_repo', 'whatsapp_phone'] as const) {
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
        <label>Location <input type="text" value={val('user_location')} onChange={(e) => setForm({ ...form, user_location: e.target.value })} placeholder="e.g. San Francisco, CA" /></label>
        <label>GitHub Repo <input type="text" value={val('github_repo')} onChange={(e) => setForm({ ...form, github_repo: e.target.value })} placeholder="e.g. myorg/myrepo" /></label>
        <label>WhatsApp Phone <input type="tel" value={val('whatsapp_phone')} onChange={(e) => setForm({ ...form, whatsapp_phone: e.target.value })} placeholder="e.g. 15551234567 (country code + number)" /></label>
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

const AI_PROVIDER_MAP: Record<string, string> = { gemini: 'gemini', anthropic: 'anthropic', openai: 'openai' };

function AISection({
  connectors,
  authMap,
}: {
  connectors: ConnectorInfo[];
  authMap: Record<string, ServiceAuthStatus>;
}) {
  const { data: profile } = useProfile();
  const update = useUpdateProfile();
  const currentProvider = profile?.ai_provider || 'gemini';
  const currentModel = profile?.ai_model || '';

  const handleProviderChange = (provider: string) => {
    update.mutate({ ai_provider: provider, ai_model: '' });
  };

  const handleModelChange = (model: string) => {
    update.mutate({ ai_model: model });
  };

  const matchingConnector = connectors.find(c => c.id === AI_PROVIDER_MAP[currentProvider]);

  const placeholder =
    currentProvider === 'gemini' ? 'gemini-2.0-flash' :
    currentProvider === 'anthropic' ? 'claude-sonnet-4-20250514' :
    'gpt-4o-mini';

  return (
    <section className="settings-group">
      <h3>AI</h3>
      <p className="settings-group-desc">
        Powers priority ranking, issue discovery, and news scoring. Pick a provider and add your API key.
      </p>
      <div className="setup-form" style={{ maxWidth: '400px', marginBottom: 'var(--space-md)' }}>
        <label>Provider
          <select
            value={currentProvider}
            onChange={(e) => handleProviderChange(e.target.value)}
            disabled={update.isPending}
          >
            <option value="gemini">Gemini (Google)</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai">OpenAI (GPT)</option>
          </select>
        </label>
        <label>Model
          <input
            type="text"
            value={currentModel}
            onChange={(e) => handleModelChange(e.target.value)}
            placeholder={placeholder}
          />
        </label>
      </div>
      {matchingConnector && (
        <div className="auth-grid">
          <ServiceCard
            connector={matchingConnector}
            status={authMap[matchingConnector.id as keyof typeof authMap]}
          />
        </div>
      )}
    </section>
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

function DataSection({ setupStatus }: { setupStatus: { data_dir: string; database_path: string } }) {
  const backup = useBackupDatabase();
  const [backupResult, setBackupResult] = useState<string | null>(null);

  const handleBackup = () => {
    setBackupResult(null);
    backup.mutate(undefined, {
      onSuccess: (data) => {
        const sizeMb = (data.size_bytes / (1024 * 1024)).toFixed(1);
        setBackupResult(`Saved to ${data.backup_path} (${sizeMb} MB)`);
      },
      onError: () => setBackupResult('Backup failed'),
    });
  };

  return (
    <div style={{ marginTop: 'var(--space-lg)', fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>
      <h2>Data</h2>
      <div>Data directory: <code>{setupStatus.data_dir}</code></div>
      <div>Database: <code>{setupStatus.database_path}</code></div>
      <div style={{ marginTop: 'var(--space-sm)' }}>
        <button
          className="btn-secondary"
          onClick={handleBackup}
          disabled={backup.isPending}
        >
          {backup.isPending ? 'Backing up...' : 'Backup Database'}
        </button>
        {backupResult && (
          <div style={{ marginTop: 'var(--space-xs)', fontSize: 'var(--text-xs)' }}>
            {backupResult}
          </div>
        )}
      </div>
    </div>
  );
}

function MeetingNotesSection() {
  const { data: profile } = useProfile();
  const updateProfile = useUpdateProfile();
  const { data: providers } = useMeetingNotesProviders();
  const toggle = useToggleConnector();

  const currentProvider = profile?.meeting_notes_provider || null;

  const handleSelect = (providerId: string | null) => {
    updateProfile.mutate(
      { meeting_notes_provider: providerId || '' },
      {
        onSuccess: () => {
          if (providerId) {
            toggle.mutate({ id: providerId, enabled: true });
          }
        },
      }
    );
  };

  if (!providers || providers.length === 0) return null;

  return (
    <div style={{ marginBottom: 'var(--space-lg)' }}>
      <h2>Meeting Notes</h2>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
        Select which app you use for meeting notes. Notes will be synced and matched to your calendar events.
      </p>
      <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', marginTop: 'var(--space-sm)' }}>
        {providers.map((p) => (
          <button
            key={p.id}
            className={`filter-btn ${currentProvider === p.id ? 'active' : ''}`}
            onClick={() => handleSelect(currentProvider === p.id ? null : p.id)}
            disabled={updateProfile.isPending}
          >
            {p.name}
          </button>
        ))}
      </div>
      {currentProvider && (
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', marginTop: 'var(--space-xs)' }}>
          Using <strong>{providers.find(p => p.id === currentProvider)?.name || currentProvider}</strong> as your meeting notes source.
        </div>
      )}
    </div>
  );
}

function SyncStatusSummary() {
  const { data: syncStatus } = useSyncStatus();
  const { data: connectors } = useConnectors();
  const { data: authStatus } = useAuthStatus();

  const enabled = new Set(connectors?.filter(c => c.enabled).map(c => c.id));
  const noAuthCheck = new Set(['news', 'gemini', 'anthropic', 'openai', 'whatsapp']);
  const active = new Set(
    [...enabled].filter(id => {
      if (noAuthCheck.has(id)) return true;
      const status = authStatus?.[id as keyof typeof authStatus];
      if (!status) return true;
      return status.connected;
    })
  );

  const syncSourceToConnector: Record<string, string> = {
    gmail: 'google', calendar: 'google',
    slack: 'slack', notion: 'notion', github: 'github',
    granola: 'granola', ramp: 'ramp', ramp_vendors: 'ramp', ramp_bills: 'ramp',
    drive: 'google_drive', sheets: 'google_drive', docs: 'google_drive',
    news: 'news',
  };

  const sources = syncStatus?.sources;
  if (!sources || Object.keys(sources).length === 0) return null;

  const entries = Object.entries(sources).filter(([source]) => {
    const connectorId = syncSourceToConnector[source] ?? source;
    return active.has(connectorId);
  });

  if (entries.length === 0) return null;

  const successCount = entries.filter(([, info]) => info.last_sync_status === 'success').length;
  const errorCount = entries.filter(([, info]) => info.last_sync_status === 'error').length;

  const lastSyncedAt = entries
    .map(([, info]) => info.last_sync_at)
    .filter(Boolean)
    .reduce((a, b) => (a > b ? a : b), '');

  return (
    <div className="sync-status" style={{ marginBottom: 'var(--space-md)' }}>
      {entries.map(([source, info]) => (
        <div key={source} className="sync-source">
          <span>{source}</span>
          {syncStatus?.running ? (
            <svg className="sync-icon syncing" width="10" height="10" viewBox="0 0 14 14" style={{ display: 'inline-block' }}>
              <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
            </svg>
          ) : (
            <span className={info.last_sync_status === 'success' ? 'status-ok' : 'status-error'}>
              {info.last_sync_status === 'success' ? '\u2713' : '\u2717'}
            </span>
          )}
        </div>
      ))}
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 'var(--space-xs)' }}>
        {successCount}/{entries.length} synced
        {errorCount > 0 && <span className="status-error"> · {errorCount} error{errorCount > 1 ? 's' : ''}</span>}
        {lastSyncedAt && <span> · last {new Date(lastSyncedAt).toLocaleString()}</span>}
      </div>
    </div>
  );
}

const AUTO_SYNC_OPTIONS = [
  { value: 0, label: 'Off' },
  { value: 60, label: '1 minute' },
  { value: 180, label: '3 minutes' },
  { value: 300, label: '5 minutes' },
  { value: 600, label: '10 minutes' },
  { value: 900, label: '15 minutes' },
  { value: 1800, label: '30 minutes' },
];

function AutoSyncSetting() {
  const { data: profile } = useProfile();
  const updateProfile = useUpdateProfile();
  const currentInterval = profile?.auto_sync_interval_seconds ?? 900;

  return (
    <div style={{ marginBottom: 'var(--space-md)' }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', fontSize: 'var(--text-sm)' }}>
        Auto-sync every
        <select
          value={currentInterval}
          onChange={(e) => {
            updateProfile.mutate({ auto_sync_interval_seconds: parseInt(e.target.value) });
          }}
        >
          {AUTO_SYNC_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

const CONNECTOR_GROUPS: { label: string; description: string; ids: string[] }[] = [
  { label: 'Google Services', description: 'Gmail, Calendar, and Drive. Authenticate once to enable all Google services.', ids: ['google', 'google_drive'] },
  { label: 'Communication', description: 'Search and sync messages from your team tools.', ids: ['slack', 'notion'] },
  { label: 'Meeting Transcripts', description: 'Import meeting notes and transcripts.', ids: ['granola'] },
  { label: 'Development', description: 'Pull requests, issues, and AI-assisted coding.', ids: ['github', 'claude_code'] },
  { label: 'Finance', description: 'Transactions, bills, and vendor data from Ramp.', ids: ['ramp'] },
  { label: 'Experimental', description: 'Features still in development.', ids: ['whatsapp', 'news'] },
];

const AI_CONNECTOR_IDS = new Set(['gemini', 'anthropic', 'openai']);

export function SettingsPage() {
  const { data: authData, isLoading: authLoading, refetch } = useAuthStatus();
  const { data: connectors, isLoading: connectorsLoading } = useConnectors();
  const { data: setupStatus } = useSetupStatus();
  const triggerSync = useSync();

  if (authLoading || connectorsLoading) return <p className="empty-state">Loading...</p>;

  const authMap = (authData ?? {}) as Record<string, ServiceAuthStatus>;
  const allConnectors = connectors ?? [];

  return (
    <div>
      <h1>Settings</h1>

      <ProfileSection />

      {/* Grouped connector sections */}
      {CONNECTOR_GROUPS.map((group) => {
        const groupConnectors = allConnectors.filter(c => group.ids.includes(c.id));
        if (groupConnectors.length === 0) return null;
        return (
          <section key={group.label} className="settings-group">
            <h3>{group.label}</h3>
            <p className="settings-group-desc">{group.description}</p>
            <div className="auth-grid">
              {groupConnectors.map((connector) => (
                <ServiceCard
                  key={connector.id}
                  connector={connector}
                  status={authMap[connector.id]}
                />
              ))}
            </div>
          </section>
        );
      })}

      {/* Meeting notes provider picker — after Communication & Granola are visible */}
      <MeetingNotesSection />

      {/* AI provider + API key — separate section */}
      <AISection connectors={allConnectors.filter(c => AI_CONNECTOR_IDS.has(c.id))} authMap={authMap} />

      {/* Sync status + actions */}
      <section className="settings-group">
        <h3>Sync</h3>
        <SyncStatusSummary />
        <AutoSyncSetting />
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
      </section>

      {setupStatus && (
        <DataSection setupStatus={setupStatus} />
      )}

      <ResetSection />

      <section className="settings-group" style={{ borderTop: '1px solid var(--color-border)', paddingTop: 'var(--space-md)', marginTop: 'var(--space-xl)' }}>
        <a href="/help" style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-light)' }}>? Help &amp; feature guide</a>
      </section>
    </div>
  );
}
