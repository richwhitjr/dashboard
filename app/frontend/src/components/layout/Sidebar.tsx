import { useState, useEffect, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useEmployees, useSync, useSyncStatus, useAuthStatus, useConnectors, useCreateEmployee, useDeleteEmployee, usePersonas, useGroups } from '../../api/hooks';
import type { SyncSourceInfo } from '../../api/types';

function formatTimeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function Sidebar() {
  const { pathname } = useLocation();
  const onRampPage = pathname.startsWith('/ramp');
  const onClaudePage = pathname.startsWith('/claude');
  const { data: personas } = usePersonas();
  const { data: employees } = useEmployees();
  const { data: groups } = useGroups();
  const { data: connectors } = useConnectors();
  const sync = useSync();
  const { data: syncStatus } = useSyncStatus();
  const { data: authStatus } = useAuthStatus();

  const enabled = new Set(connectors?.filter(c => c.enabled).map(c => c.id));

  // "active" = enabled AND (connected or no auth check needed)
  // Connectors without auth checks (news, gemini) are active when enabled
  const noAuthCheck = new Set(['news', 'gemini']);
  const active = new Set(
    [...enabled].filter(id => {
      if (noAuthCheck.has(id)) return true;
      const status = authStatus?.[id as keyof typeof authStatus];
      if (!status) return true; // no auth data yet, show optimistically
      return status.connected;
    })
  );

  // Connectors that are enabled but not connected — need setup help
  const needsSetup = [...enabled].filter(id => !noAuthCheck.has(id) && !active.has(id));

  const createEmployee = useCreateEmployee();
  const deleteEmployee = useDeleteEmployee();

  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [syncStartedAt, setSyncStartedAt] = useState<string | null>(null);
  const prevRunningRef = useRef(false);

  useEffect(() => {
    const isRunning = syncStatus?.running ?? false;
    if (!prevRunningRef.current && isRunning) {
      setSyncStartedAt(new Date().toISOString());
    } else if (prevRunningRef.current && !isRunning) {
      setSyncStartedAt(null);
    }
    prevRunningRef.current = isRunning;
  }, [syncStatus?.running]);

  const lastSyncedAt = (() => {
    if (!syncStatus?.sources) return null;
    const timestamps = Object.values(syncStatus.sources)
      .map((s) => s.last_sync_at)
      .filter(Boolean);
    if (!timestamps.length) return null;
    return timestamps.reduce((a, b) => (a > b ? a : b));
  })();

  function getSourceStatus(info: { last_sync_at: string; last_sync_status: string }) {
    if (syncStatus?.running) {
      if (syncStartedAt && info.last_sync_at > syncStartedAt) {
        return info.last_sync_status === 'success' ? 'done' : 'error';
      }
      return 'running';
    }
    return info.last_sync_status === 'success' ? 'done' : 'error';
  }

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const all = employees ?? [];
  const groupList = groups ?? ['team'];
  const employeesByGroup = new Map<string, typeof all>();
  for (const group of groupList) {
    employeesByGroup.set(group, all.filter(e => e.group_name === group));
  }

  // Build lookup: manager ID → their reports (within same group)
  const reportsByManager = new Map<string, typeof all>();
  for (const e of all) {
    if (e.reports_to) {
      const list = reportsByManager.get(e.reports_to) || [];
      list.push(e);
      reportsByManager.set(e.reports_to, list);
    }
  }

  const handleQuickAdd = (group: string) => {
    if (!newName.trim()) return;
    createEmployee.mutate(
      { name: newName.trim(), group_name: group },
      { onSuccess: () => { setNewName(''); setAddingTo(null); } }
    );
  };

  const handleRemove = (id: string, name: string) => {
    if (!confirm(`Remove ${name}?`)) return;
    deleteEmployee.mutate(id);
  };

  // Only count auth status for enabled connectors
  const authServices = authStatus
    ? Object.entries(authStatus).filter(([id]) => enabled.has(id))
    : [];
  const connectedCount = authServices.filter(([, s]) => {
    const syncVals: SyncSourceInfo[] = Object.values(s.sync || {});
    const hasSyncSuccess = syncVals.some((sv) => sv.last_sync_status === 'success');
    if (hasSyncSuccess) return true;
    if (!s.connected) return false;
    if (syncVals.length === 0) return s.connected;
    return false;
  }).length;

  // Map sync source names back to connector IDs for filtering
  const syncSourceToConnector: Record<string, string> = {
    gmail: 'google', calendar: 'google',
    slack: 'slack', notion: 'notion', github: 'github',
    granola: 'granola', ramp: 'ramp', ramp_vendors: 'ramp', ramp_bills: 'ramp',
    news: 'news',
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <NavLink to="/help" className="sidebar-title sidebar-title-link">Dashboard</NavLink>

        <nav>
          <NavLink to="/" end>Overview</NavLink>
          {active.has('gemini') && <NavLink to="/priorities">Priorities</NavLink>}
        </nav>

        <div className="sidebar-section-label">work</div>
        <nav>
          <NavLink to="/notes">Notes</NavLink>
          <NavLink to="/thoughts">Thoughts</NavLink>
          <NavLink to="/issues">Issues</NavLink>
          {(active.has('google') || active.has('granola')) && <NavLink to="/meetings">Meetings</NavLink>}
        </nav>

        {(active.has('google') || active.has('slack') || active.has('notion') || active.has('github') || active.has('ramp') || active.has('news')) && (
          <>
            <div className="sidebar-section-label">sources</div>
            <nav>
              {active.has('google') && <NavLink to="/email">Email</NavLink>}
              {active.has('news') && <NavLink to="/news">News</NavLink>}
              {active.has('github') && <NavLink to="/github">GitHub</NavLink>}
              {active.has('slack') && <NavLink to="/slack">Slack</NavLink>}
              {active.has('notion') && <NavLink to="/notion">Notion</NavLink>}
              {active.has('ramp') && <>
                <NavLink to="/ramp" end>Ramp</NavLink>
                {onRampPage && <>
                  <NavLink to="/ramp/bills" className="sidebar-sub-link">Bills</NavLink>
                  <NavLink to="/ramp/projects" className="sidebar-sub-link">Projects</NavLink>
                </>}
              </>}
            </nav>
          </>
        )}

        <div className="sidebar-section-label">tools</div>
        <nav>
          <NavLink to="/team">Team</NavLink>
          <NavLink to="/claude" end>Claude</NavLink>
          {onClaudePage && personas?.filter(p => !p.is_default).map(p => (
            <NavLink
              key={p.id}
              to={`/claude?persona=${p.id}`}
              className="sidebar-sub-link sidebar-persona-link"
            >
              {p.avatar_filename ? (
                <img
                  src={`/api/personas/${p.id}/avatar`}
                  alt=""
                  className="persona-avatar-sidebar"
                />
              ) : (
                <span className="persona-avatar-placeholder-sidebar">
                  {p.name.charAt(0).toUpperCase()}
                </span>
              )}
              {p.name}
            </NavLink>
          ))}
          <NavLink to="/personas">Personas</NavLink>
        </nav>

        {groupList.map((group) => {
          const members = employeesByGroup.get(group) || [];
          const isTeam = group === 'team';
          if (members.length === 0 && !isTeam) return null;

          return (
            <div key={group}>
              <div className="sidebar-section-label">
                {group}
                <button className="sidebar-add-btn" onClick={() => { setAddingTo(addingTo === group ? null : group); setNewName(''); }}>+</button>
              </div>
              {addingTo === group && (
                <form className="sidebar-inline-add" onSubmit={(e) => { e.preventDefault(); handleQuickAdd(group); }}>
                  <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name" />
                </form>
              )}
              <nav className="org-tree">
                {members.length > 0 ? (
                  members.filter(e => !e.reports_to || !members.some(m => m.id === e.reports_to)).map((emp) => {
                    const subs = reportsByManager.get(emp.id) || [];
                    return (
                      <div key={emp.id}>
                        <div className="sidebar-person">
                          <NavLink to={`/employees/${emp.id}`}>{emp.name}</NavLink>
                          {subs.length > 0 && (
                            <button className="sidebar-expand-btn" onClick={() => toggleExpand(emp.id)}>
                              {expanded.has(emp.id) ? '\u25BE' : '\u25B8'}
                            </button>
                          )}
                          <button className="sidebar-remove-btn" onClick={() => handleRemove(emp.id, emp.name)}>&times;</button>
                        </div>
                        {expanded.has(emp.id) && subs.map((sub) => (
                          <div key={sub.id} className="sidebar-person sidebar-sub-report">
                            <NavLink to={`/employees/${sub.id}`}>{sub.name}</NavLink>
                            <button className="sidebar-remove-btn" onClick={() => handleRemove(sub.id, sub.name)}>&times;</button>
                          </div>
                        ))}
                      </div>
                    );
                  })
                ) : (
                  isTeam && <span className="sidebar-empty-hint">no entries yet</span>
                )}
              </nav>
            </div>
          );
        })}

        {addingTo && addingTo !== '__new_group__' && !groupList.includes(addingTo) && (
          <div>
            <div className="sidebar-section-label">
              {addingTo}
              <button className="sidebar-add-btn" onClick={() => { setAddingTo(null); setNewName(''); }}>×</button>
            </div>
            <form className="sidebar-inline-add" onSubmit={(e) => { e.preventDefault(); handleQuickAdd(addingTo); }}>
              <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name" />
            </form>
          </div>
        )}

        {addingTo === '__new_group__' ? (
          <form className="sidebar-inline-add" onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) {
              setAddingTo(newName.trim().toLowerCase());
              setNewName('');
            }
          }}>
            <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Group name" />
          </form>
        ) : (
          <button
            className="btn-link"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 'var(--space-xs)', padding: 0 }}
            onClick={() => { setAddingTo('__new_group__'); setNewName(''); }}
          >
            + new group
          </button>
        )}

        <div style={{ marginTop: 'var(--space-xl)' }}>
          <button
            className={`sync-button ${sync.isPending ? 'syncing' : ''}`}
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            <span className={`sync-icon ${sync.isPending ? 'syncing' : ''}`}>
              &#x21bb;
            </span>
            {sync.isPending ? 'Syncing...' : <><span>Refresh</span><kbd style={{ marginLeft: 6, opacity: 0.5 }}>s</kbd></>}
          </button>
          {!sync.isPending && lastSyncedAt && (
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 4 }}>
              synced {formatTimeAgo(lastSyncedAt)}
            </div>
          )}
        </div>

        {syncStatus?.sources && Object.keys(syncStatus.sources).length > 0 && (
          <div className="sync-status">
            {Object.entries(syncStatus.sources)
              .filter(([source]) => {
                const connectorId = syncSourceToConnector[source] ?? source;
                return active.has(connectorId);
              })
              .map(([source, info]) => {
              const status = getSourceStatus(info);
              return (
                <div key={source} className="sync-source">
                  <span>{source}</span>
                  {status === 'running' ? (
                    <svg className="sync-icon syncing" width="10" height="10" viewBox="0 0 14 14" style={{ display: 'inline-block' }}>
                      <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
                    </svg>
                  ) : (
                    <span className={status === 'done' ? 'status-ok' : 'status-error'}>
                      {status === 'done' ? '\u2713' : '\u2717'}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {needsSetup.length > 0 && (
          <div className="sync-status">
            {needsSetup.map(id => {
              const c = connectors?.find(c => c.id === id);
              return (
                <div key={id} className="sync-source">
                  <span>{c?.name ?? id}</span>
                  <NavLink to="/settings" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)' }}>
                    set up
                  </NavLink>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="sidebar-bottom">
        <div className="sidebar-bottom-row">
          <NavLink to="/settings" className="sidebar-settings-btn">
            <span className="sidebar-settings-icon">&#x2699;</span>
            <span>Connections</span>
            <span className="sidebar-settings-status">
              <span className="count-badge">{connectedCount}/{authServices.length}</span>
            </span>
          </NavLink>
          <button
            className="restart-button"
            disabled={sync.isPending}
            title="Re-check connections"
            onClick={() => {
              sync.mutate();
            }}
          >
            {sync.isPending ? '\u2026' : '\u21BB'}
          </button>
        </div>
        <div className="sidebar-shortcut-hint">
          <NavLink to="/help" className="sidebar-help-icon" title="Help &amp; intro">?</NavLink>
          <kbd>?</kbd> shortcuts &middot; <kbd>&#x2318;K</kbd> search
        </div>
      </div>
    </aside>
  );
}
