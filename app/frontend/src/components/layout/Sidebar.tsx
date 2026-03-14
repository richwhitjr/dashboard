import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { usePeople, useSync, useAuthStatus, useConnectors, useCreatePerson, useDeletePerson, useUpdatePerson, usePersonas, useGroups, useRenameGroup } from '../../api/hooks';
import { useSyncProgress } from '../../hooks/useSyncProgress';
import { SyncDetailModal } from '../SyncProgressOverlay';
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
  const { data: employees } = usePeople();
  const { data: groups } = useGroups();
  const { data: connectors } = useConnectors();
  const sync = useSync();
  const syncProgress = useSyncProgress();
  const { data: authStatus } = useAuthStatus();
  const [syncDetailOpen, setSyncDetailOpen] = useState(false);

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


  const createEmployee = useCreatePerson();
  const deleteEmployee = useDeletePerson();
  const updateEmployee = useUpdatePerson();
  const renameGroup = useRenameGroup();

  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [renamingGroup, setRenamingGroup] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [dragOverGroup, setDragOverGroup] = useState<string | null>(null);

  const lastSyncedAt = (() => {
    if (!syncProgress.sources) return null;
    const timestamps = Object.values(syncProgress.sources)
      .map((s) => (s as { last_sync_at?: string }).last_sync_at)
      .filter(Boolean) as string[];
    if (!timestamps.length) return null;
    return timestamps.reduce((a, b) => (a > b ? a : b));
  })();


  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleGroup = (group: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group)) next.delete(group); else next.add(group);
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


  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <NavLink to="/" className="sidebar-title sidebar-title-link">Dashboard</NavLink>

        <div className="sidebar-section-label">work</div>
        <nav>
          <NavLink to="/notes">Notes</NavLink>
          <NavLink to="/issues">Issues</NavLink>
          <NavLink to="/longform">Writing</NavLink>
          {(active.has('google') || active.has('granola')) && <NavLink to="/meetings">Meetings</NavLink>}
        </nav>

        {(active.has('google') || active.has('slack') || active.has('notion') || active.has('github') || active.has('ramp') || active.has('news') || active.has('google_drive')) && (
          <>
            <div className="sidebar-section-label">sources</div>
            <nav>
              {active.has('google') && <NavLink to="/email">Email</NavLink>}
              {active.has('news') && <NavLink to="/news">News</NavLink>}
              {active.has('github') && <NavLink to="/github">GitHub</NavLink>}
              {active.has('slack') && <NavLink to="/slack">Slack</NavLink>}
              {active.has('notion') && <NavLink to="/notion">Notion</NavLink>}
              {active.has('google_drive') && <NavLink to="/drive">Drive</NavLink>}
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
          <NavLink to="/people">People</NavLink>
          {active.has('claude_code') && <>
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
          </>}
        </nav>

        {groupList.map((group) => {
          const members = employeesByGroup.get(group) || [];
          const isTeam = group === 'team';
          if (members.length === 0 && !isTeam) return null;

          return (
            <div
              key={group}
              onDragOver={(e) => { e.preventDefault(); setDragOverGroup(group); }}
              onDragLeave={() => setDragOverGroup(null)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOverGroup(null);
                const empId = e.dataTransfer.getData('text/employee-id');
                const fromGroup = e.dataTransfer.getData('text/from-group');
                if (empId && fromGroup !== group) {
                  updateEmployee.mutate({ id: empId, group_name: group });
                }
              }}
              style={dragOverGroup === group ? { background: 'var(--color-highlight)', borderRadius: 4 } : undefined}
            >
              <div className="sidebar-section-label">
                {renamingGroup === group ? (
                  <form
                    className="sidebar-inline-add"
                    style={{ flex: 1, margin: 0 }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const val = renameValue.trim().toLowerCase();
                      if (val && val !== group) {
                        renameGroup.mutate({ oldName: group, newName: val });
                      }
                      setRenamingGroup(null);
                    }}
                  >
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => setRenamingGroup(null)}
                      style={{ fontSize: 'var(--text-sm)', width: '100%' }}
                    />
                  </form>
                ) : (
                  <span
                    onClick={() => toggleGroup(group)}
                    onDoubleClick={(e) => {
                      if (!isTeam) {
                        e.stopPropagation();
                        setRenamingGroup(group);
                        setRenameValue(group);
                      }
                    }}
                    style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}
                    title={!isTeam ? 'Click to expand/collapse · Double-click to rename' : 'Click to expand/collapse'}
                  >
                    <span style={{ fontSize: '0.6em', opacity: 0.5 }}>{expandedGroups.has(group) ? '\u25BE' : '\u25B8'}</span>
                    {group}
                  </span>
                )}
                <button className="sidebar-add-btn" onClick={() => {
                  if (addingTo === group) {
                    setAddingTo(null);
                  } else {
                    setAddingTo(group);
                    setExpandedGroups(prev => new Set(prev).add(group));
                  }
                  setNewName('');
                }}>+</button>
              </div>
              {expandedGroups.has(group) && (
                <>
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
                            <div
                              className="sidebar-person"
                              draggable
                              onDragStart={(e) => {
                                e.dataTransfer.setData('text/employee-id', emp.id);
                                e.dataTransfer.setData('text/from-group', group);
                                e.dataTransfer.effectAllowed = 'move';
                              }}
                            >
                              <NavLink to={`/people/${emp.id}`}>{emp.name}</NavLink>
                              {subs.length > 0 && (
                                <button className="sidebar-expand-btn" onClick={() => toggleExpand(emp.id)}>
                                  {expanded.has(emp.id) ? '\u25BE' : '\u25B8'}
                                </button>
                              )}
                              <button className="sidebar-remove-btn" onClick={() => handleRemove(emp.id, emp.name)}>&times;</button>
                            </div>
                            {expanded.has(emp.id) && subs.map((sub) => (
                              <div
                                key={sub.id}
                                className="sidebar-person sidebar-sub-report"
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.setData('text/employee-id', sub.id);
                                  e.dataTransfer.setData('text/from-group', group);
                                  e.dataTransfer.effectAllowed = 'move';
                                }}
                              >
                                <NavLink to={`/people/${sub.id}`}>{sub.name}</NavLink>
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
                </>
              )}
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
            <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Group name" onBlur={() => { setAddingTo(null); setNewName(''); }} onKeyDown={(e) => { if (e.key === 'Escape') { setAddingTo(null); setNewName(''); } }} />
          </form>
        ) : (
          <button
            className="btn-link"
            style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 'var(--space-lg)', padding: 0, fontVariant: 'small-caps', letterSpacing: '0.05em' }}
            onClick={() => { setAddingTo('__new_group__'); setNewName(''); }}
          >
            + new group
          </button>
        )}

        {syncProgress.isRunning ? (
          <button
            className="btn-link sync-progress-inline"
            style={{ marginTop: 'var(--space-lg)' }}
            onClick={() => setSyncDetailOpen(true)}
          >
            Syncing {syncProgress.completedCount}/{syncProgress.totalCount}&hellip;
          </button>
        ) : (
          lastSyncedAt && (
            <div
              style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-light)', marginTop: 'var(--space-lg)' }}
              title={syncProgress.autoSync?.enabled
                ? `Auto-sync every ${Math.round((syncProgress.autoSync.interval_seconds || 900) / 60)}m`
                : 'Auto-sync off'}
            >
              synced {formatTimeAgo(lastSyncedAt)}
            </div>
          )
        )}
      </div>

      <div className="sidebar-bottom">
        <div className="sidebar-bottom-row">
          <NavLink to="/settings" className="sidebar-settings-btn">
            <span className="sidebar-settings-icon">&#x2699;</span>
            <span>Settings</span>
            <span className="sidebar-settings-status">
              <span className="count-badge">{connectedCount}/{authServices.length}</span>
            </span>
          </NavLink>
          <button
            className="restart-button"
            disabled={sync.isPending}
            title={syncProgress.isRunning ? 'Click for sync details' : 'Sync all sources'}
            onClick={() => {
              if (syncProgress.isRunning) {
                setSyncDetailOpen(true);
              } else {
                sync.mutate();
              }
            }}
          >
            {syncProgress.isRunning ? (
              <svg className="sync-step-spinner" width="14" height="14" viewBox="0 0 14 14">
                <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
              </svg>
            ) : '\u21BB'}
          </button>
        </div>
        <div className="sidebar-shortcut-hint">
          <NavLink to="/help" className="sidebar-help-icon" title="Help &amp; intro">?</NavLink>
          <kbd>?</kbd> shortcuts &middot; <kbd>&#x2318;K</kbd> search
        </div>
      </div>

      <SyncDetailModal open={syncDetailOpen} onClose={() => setSyncDetailOpen(false)} />
    </aside>
  );
}
