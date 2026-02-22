import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useProfile,
  useUpdateProfile,
  useConnectors,
  useToggleConnector,
  useSecrets,
  useUpdateSecret,
  useCompleteSetup,
  useTestConnection,
  useGoogleAuth,
  useAuthStatus,
} from '../api/hooks';
import type { ConnectorInfo, UserProfile } from '../api/types';

type Step = 'welcome' | 'profile' | 'connectors' | 'done';

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="setup-step">
      <h1>Welcome to Personal Dashboard</h1>
      <p className="setup-subtitle">
        Your personal command center &mdash; email, Slack, calendar, team, and
        your own thoughts, all in one quiet place.
      </p>
      <ul className="setup-features">
        <li>AI-powered morning priorities from your email, Slack, and calendar</li>
        <li>Team management with 1:1 prep, meeting notes, and context</li>
        <li>Quick capture notes with @mentions and keyboard shortcuts</li>
        <li>Unified search across all your connected services</li>
      </ul>
      <button className="btn-primary setup-cta" onClick={onNext}>
        Get Started
      </button>
    </div>
  );
}

function ProfileStep({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const { data: existing } = useProfile();
  const updateProfile = useUpdateProfile();
  const [form, setForm] = useState<Partial<UserProfile>>({});

  const val = (key: keyof UserProfile) =>
    (form[key] as string) ?? (existing?.[key] as string) ?? '';

  const handleSave = () => {
    const updates: Partial<UserProfile> = {};
    for (const key of ['user_name', 'user_title', 'user_company', 'user_company_description', 'user_email', 'user_email_domain'] as const) {
      if (form[key] !== undefined) updates[key] = form[key];
    }
    if (Object.keys(updates).length > 0) {
      updateProfile.mutate(updates, { onSuccess: onNext });
    } else {
      onNext();
    }
  };

  return (
    <div className="setup-step">
      <h2>About You</h2>
      <p className="setup-hint">
        This personalizes AI-generated priorities and team matching.
        All fields are optional.
      </p>
      <div className="setup-form">
        <label>
          Name
          <input
            type="text"
            value={val('user_name')}
            onChange={(e) => setForm({ ...form, user_name: e.target.value })}
            placeholder="e.g. Alex Johnson"
          />
        </label>
        <label>
          Title
          <input
            type="text"
            value={val('user_title')}
            onChange={(e) => setForm({ ...form, user_title: e.target.value })}
            placeholder="e.g. VP of Engineering"
          />
        </label>
        <label>
          Company
          <input
            type="text"
            value={val('user_company')}
            onChange={(e) => setForm({ ...form, user_company: e.target.value })}
            placeholder="e.g. Acme Corp"
          />
        </label>
        <label>
          Company Description
          <input
            type="text"
            value={val('user_company_description')}
            onChange={(e) => setForm({ ...form, user_company_description: e.target.value })}
            placeholder="e.g. a B2B SaaS platform for logistics"
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={val('user_email')}
            onChange={(e) => setForm({ ...form, user_email: e.target.value })}
            placeholder="e.g. alex@acme.com"
          />
        </label>
        <label>
          Email Domain
          <input
            type="text"
            value={val('user_email_domain')}
            onChange={(e) => setForm({ ...form, user_email_domain: e.target.value })}
            placeholder="e.g. acme.com"
          />
        </label>
      </div>
      <div className="setup-actions">
        <button className="btn-primary" onClick={handleSave} disabled={updateProfile.isPending}>
          {updateProfile.isPending ? 'Saving...' : 'Continue'}
        </button>
        <button className="btn-secondary" onClick={onSkip}>Skip for now</button>
      </div>
    </div>
  );
}

function ConnectorCard({ connector }: { connector: ConnectorInfo }) {
  const toggle = useToggleConnector();
  const secrets = useSecrets();
  const updateSecret = useUpdateSecret();
  const testConn = useTestConnection();
  const googleAuth = useGoogleAuth();
  const { data: authData } = useAuthStatus();
  const [expanded, setExpanded] = useState(false);
  const [tokenInputs, setTokenInputs] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const secretsData = secrets.data ?? {};
  const status = authData?.[connector.id as keyof typeof authData];

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
    testConn.mutate(connector.id, {
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

  const isConnected = status?.connected;

  return (
    <div className={`setup-connector-card ${connector.enabled ? 'enabled' : ''}`}>
      <div className="setup-connector-header">
        <div className="setup-connector-info">
          <div className="setup-connector-name">
            <strong>{connector.name}</strong>
            {connector.enabled && isConnected && (
              <span className="setup-status-badge setup-status-connected">connected</span>
            )}
            {connector.enabled && !isConnected && status?.configured && (
              <span className="setup-status-badge setup-status-configured">configured</span>
            )}
          </div>
          <span className="setup-connector-desc">{connector.description}</span>
        </div>
        <label className="setup-toggle">
          <input
            type="checkbox"
            checked={connector.enabled}
            onChange={() => toggle.mutate({ id: connector.id, enabled: !connector.enabled })}
          />
          <span className="setup-toggle-slider" />
        </label>
      </div>

      {connector.enabled && (
        <div className="setup-connector-body">
          {/* OAuth connectors */}
          {connector.category === 'oauth' && !isConnected && (
            <button
              className="btn-primary"
              onClick={() => googleAuth.mutate()}
              disabled={googleAuth.isPending}
            >
              {googleAuth.isPending ? 'Authenticating...' : 'Sign in with Google'}
            </button>
          )}
          {connector.category === 'oauth' && isConnected && (
            <div className="setup-connection-ok">
              Authenticated with Google. Calendar, Gmail, and Drive access is active.
            </div>
          )}

          {/* Token/credential connectors */}
          {connector.secret_keys.map((key) => (
            <div key={key} className="setup-secret-row">
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

          {/* CLI connectors */}
          {connector.category === 'cli' && (
            <p className="setup-hint" style={{ margin: 0 }}>
              {isConnected
                ? 'Authenticated via gh CLI.'
                : 'Authenticate with the GitHub CLI, then test the connection below.'}
            </p>
          )}

          {/* Local file connectors */}
          {connector.category === 'local' && (
            <p className="setup-hint" style={{ margin: 0 }}>
              {isConnected
                ? 'Local cache file found.'
                : 'Install and use the app. Its local cache will be detected automatically.'}
            </p>
          )}

          {/* Test connection */}
          {connector.category !== 'none' && (
            <div className="setup-test-row">
              <button
                className="btn-secondary"
                onClick={handleTest}
                disabled={testConn.isPending}
              >
                {testConn.isPending ? 'Testing...' : 'Test Connection'}
              </button>
              {testResult && (
                <span className={`setup-feedback ${testResult.ok ? 'setup-feedback-ok' : 'setup-feedback-err'}`}>
                  {testResult.message}
                </span>
              )}
            </div>
          )}

          {/* Help steps */}
          <button
            className="setup-help-toggle"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Hide setup guide' : 'How to set up'}
          </button>
          {expanded && (
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
        </div>
      )}
    </div>
  );
}

function ConnectorsStep({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const { data: connectors } = useConnectors();
  const all = connectors ?? [];
  const core = all.filter((c) => c.default_enabled);
  const optional = all.filter((c) => !c.default_enabled);

  return (
    <div className="setup-step">
      <h2>Connect Your Services</h2>
      <p className="setup-hint">
        Enable the services you use. You can always change these later in Settings.
      </p>

      {core.length > 0 && (
        <div className="setup-connector-group">
          <h3>Recommended</h3>
          {core.map((c) => <ConnectorCard key={c.id} connector={c} />)}
        </div>
      )}

      {optional.length > 0 && (
        <div className="setup-connector-group">
          <h3>Optional</h3>
          {optional.map((c) => <ConnectorCard key={c.id} connector={c} />)}
        </div>
      )}

      <div className="setup-actions">
        <button className="btn-primary" onClick={onNext}>Continue</button>
        <button className="btn-secondary" onClick={onSkip}>Skip for now</button>
      </div>
    </div>
  );
}

function DoneStep({ onFinish }: { onFinish: () => void }) {
  return (
    <div className="setup-step">
      <h2>You&rsquo;re all set.</h2>
      <p className="setup-subtitle">
        Your dashboard is ready. You can always update your profile and
        connections in Settings.
      </p>
      <ul className="setup-features">
        <li>Press <kbd>?</kbd> to see all keyboard shortcuts</li>
        <li>Press <kbd>&#x2318;K</kbd> to search across everything</li>
        <li>Press <kbd>c</kbd> to capture a quick note</li>
      </ul>
      <button className="btn-primary setup-cta" onClick={onFinish}>
        Go to Dashboard
      </button>
    </div>
  );
}

const STEPS: Step[] = ['welcome', 'profile', 'connectors', 'done'];

export function SetupPage() {
  const navigate = useNavigate();
  const completeSetup = useCompleteSetup();
  const [step, setStep] = useState<Step>('welcome');

  const currentIdx = STEPS.indexOf(step);
  const next = () => setStep(STEPS[currentIdx + 1] || 'done');

  const finish = () => {
    completeSetup.mutate(undefined, {
      onSuccess: () => navigate('/'),
    });
  };

  return (
    <div className="setup-page">
      <div className="setup-progress">
        {STEPS.map((s, i) => (
          <div
            key={s}
            className={`setup-progress-dot ${i <= currentIdx ? 'active' : ''} ${i === currentIdx ? 'current' : ''}`}
          />
        ))}
      </div>

      {step === 'welcome' && <WelcomeStep onNext={next} />}
      {step === 'profile' && <ProfileStep onNext={next} onSkip={next} />}
      {step === 'connectors' && <ConnectorsStep onNext={next} onSkip={next} />}
      {step === 'done' && <DoneStep onFinish={finish} />}
    </div>
  );
}
