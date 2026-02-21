import { useState, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { usePrioritizedRamp, useRefreshPrioritizedRamp, useDismissPrioritizedItem, useCreateIssue, useRampBills, useAssignBillProject, useProjects, useCreateProject, useUpdateProject, useDeleteProject } from '../api/hooks';
import type { RampBill, Project } from '../api/types';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import { openExternal } from '../api/client';

const DAY_OPTIONS = [7, 30, 90, 180, 365] as const;
const SCORE_OPTIONS = [0, 3, 5, 6, 7, 8] as const;
const DEFAULT_MIN_SCORE = 6;

type TabType = 'expenses' | 'bills' | 'projects';

function scoreBadge(score: number) {
  const cls = score >= 8 ? 'priority-urgency-high'
    : score >= 5 ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

function formatAmount(amount: number, currency: string = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function billStatusBadge(status: string, paymentStatus: string) {
  const s = (paymentStatus || status || '').toUpperCase();
  const cls = s.includes('PAID') || s.includes('COMPLETED')
    ? 'priority-urgency-low'
    : s.includes('ERROR') || s.includes('FAIL')
    ? 'priority-urgency-high'
    : s.includes('PENDING') || s.includes('APPROVAL')
    ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  const label = s.replace(/_/g, ' ') || 'UNKNOWN';
  return <span className={`priority-score-badge ${cls}`} style={{ fontSize: '0.7rem', padding: '1px 5px' }}>{label}</span>;
}

// --- Expenses Tab ---
function ExpensesTab() {
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const [orgOnly, setOrgOnly] = useState(true);
  const { data, isLoading } = usePrioritizedRamp(days, orgOnly);
  const refresh = useRefreshPrioritizedRamp(days, orgOnly);
  const dismiss = useDismissPrioritizedItem();
  const createIssue = useCreateIssue();
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const allItems = data?.items ?? [];
  const items = minScore > 0 ? allItems.filter(m => m.priority_score >= minScore) : allItems;
  const hiddenCount = allItems.length - items.length;
  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    onDismiss: (i) => { if (items[i]) dismiss.mutate({ source: 'ramp', item_id: items[i].id }); },
    onOpen: (i) => {
      if (items[i]?.ramp_url) openExternal(items[i].ramp_url!);
    },
    onCreateIssue: (i) => {
      if (items[i]) {
        createIssue.mutate({
          title: `${items[i].merchant_name} — ${formatAmount(items[i].amount, items[i].currency)}`,
        });
      }
    },
    onExpand: (i) => { if (items[i]) toggleExpand(items[i].id); },
    onToggleFilter: () => setMinScore(prev => prev === 0 ? DEFAULT_MIN_SCORE : 0),
  });

  return (
    <>
      <div className="priorities-header" style={{ marginTop: 0 }}>
        <span className="day-filter">
          <button className={`day-filter-btn${orgOnly ? ' day-filter-active' : ''}`} onClick={() => setOrgOnly(true)} title="Show only transactions from your org">My org</button>
          <button className={`day-filter-btn${!orgOnly ? ' day-filter-active' : ''}`} onClick={() => setOrgOnly(false)} title="Show all transactions">All</button>
        </span>
        <span className="day-filter">
          {DAY_OPTIONS.map((d) => (
            <button key={d} className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`} onClick={() => setDays(d)}>{d}d</button>
          ))}
        </span>
        <span className="day-filter">
          {SCORE_OPTIONS.map((s) => (
            <button key={s} className={`day-filter-btn${minScore === s ? ' day-filter-active' : ''}`} onClick={() => setMinScore(s)} title={s === 0 ? 'Show all (f)' : `Hide scores below ${s} (f)`}>
              {s === 0 ? 'All' : `${s}+`}
            </button>
          ))}
        </span>
        <button className="priorities-refresh-btn" onClick={() => refresh.mutate()} disabled={refresh.isPending} title="Re-rank with Gemini">
          {refresh.isPending ? 'Ranking...' : 'Refresh'}
        </button>
        {data?.total_amount != null && data.total_amount > 0 && (
          <span className="ramp-total">{formatAmount(data.total_amount)} total</span>
        )}
      </div>

      {isLoading && <p className="empty-state">Loading expenses...</p>}
      {data?.error && <p className="empty-state">Error: {data.error}</p>}
      {!isLoading && !data?.error && items.length === 0 && (
        <p className="empty-state">
          {hiddenCount > 0
            ? `${hiddenCount} transaction${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
            : `No Ramp transactions in the last ${days} day${days > 1 ? 's' : ''}`}
        </p>
      )}

      <div ref={containerRef}>
        {items.map((txn) => {
          const isExpanded = expandedIds.has(txn.id);
          const hasExtra = !!(txn.memo && txn.memo.length > 150);
          return (
            <div key={txn.id} className="dashboard-item-row">
              <div
                className="dashboard-item dashboard-item-link"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: txn.ramp_url ? 'pointer' : 'default' }}
                onClick={() => txn.ramp_url && openExternal(txn.ramp_url)}
              >
                <div style={{ flexShrink: 0, paddingTop: '2px' }}>{scoreBadge(txn.priority_score)}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">
                    <strong className="ramp-amount">{formatAmount(txn.amount, txn.currency)}</strong>
                    {' '}{txn.merchant_name || 'Unknown merchant'}
                  </div>
                  <div className="dashboard-item-meta">
                    {txn.cardholder_name && <>{txn.cardholder_name} &middot; </>}
                    {txn.category && <>{txn.category} &middot; </>}
                    <TimeAgo date={txn.transaction_date} />
                  </div>
                  {txn.priority_reason && (
                    <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{txn.priority_reason}</div>
                  )}
                  {txn.memo && (
                    <div className="dashboard-item-meta">
                      {isExpanded ? txn.memo : (
                        <>{txn.memo.slice(0, 150)}{txn.memo.length > 150 && '...'}</>
                      )}
                    </div>
                  )}
                </div>
              </div>
              {hasExtra && (
                <button className="dashboard-expand-btn" onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleExpand(txn.id); }} title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}>
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
              )}
              <button className="dashboard-dismiss-btn" onClick={() => dismiss.mutate({ source: 'ramp', item_id: txn.id })} title="Mark as seen">&times;</button>
            </div>
          );
        })}
      </div>
      {hiddenCount > 0 && items.length > 0 && (
        <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
          {hiddenCount} lower-priority transaction{hiddenCount !== 1 ? 's' : ''} hidden
          <button className="day-filter-btn" style={{ marginLeft: 'var(--space-sm)' }} onClick={() => setMinScore(0)}>Show all</button>
        </p>
      )}
      {items.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']} />
      )}
    </>
  );
}

// --- Bills Tab ---
function BillsTab({ projects }: { projects: Project[] }) {
  const [days, setDays] = useState(90);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const { data, isLoading } = useRampBills({ days, status: statusFilter || undefined });
  const assignBillProject = useAssignBillProject();
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  const bills: RampBill[] = data?.bills ?? [];

  const statusOptions = ['', 'PAID', 'APPROVED', 'PENDING', 'VOID'];

  return (
    <>
      <div className="priorities-header" style={{ marginTop: 0 }}>
        <span className="day-filter">
          {DAY_OPTIONS.map((d) => (
            <button key={d} className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`} onClick={() => setDays(d)}>{d}d</button>
          ))}
        </span>
        <span className="day-filter">
          {statusOptions.map((s) => (
            <button key={s} className={`day-filter-btn${statusFilter === s ? ' day-filter-active' : ''}`} onClick={() => setStatusFilter(s)}>
              {s || 'All'}
            </button>
          ))}
        </span>
        <span style={{ color: 'var(--color-text-muted)', fontSize: '0.85rem', marginLeft: 'auto' }}>
          {bills.length} bill{bills.length !== 1 ? 's' : ''}
          {bills.length > 0 && ` · ${formatAmount(bills.reduce((s, b) => s + (b.amount || 0), 0))} total`}
        </span>
      </div>

      {isLoading && <p className="empty-state">Loading bills...</p>}
      {!isLoading && bills.length === 0 && (
        <p className="empty-state">No bills found — sync Ramp vendors and bills first</p>
      )}

      <div>
        {bills.map((bill) => (
          <div key={bill.id} className="dashboard-item-row">
            <div
              className="dashboard-item"
              style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: bill.ramp_url ? 'pointer' : 'default', flex: 1 }}
              onClick={() => bill.ramp_url && openExternal(bill.ramp_url)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="dashboard-item-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <strong className="ramp-amount">{formatAmount(bill.amount, bill.currency)}</strong>
                  <span>{bill.vendor_name || 'Unknown vendor'}</span>
                  {billStatusBadge(bill.status, bill.payment_status)}
                </div>
                <div className="dashboard-item-meta">
                  {bill.invoice_number && <>#{bill.invoice_number} &middot; </>}
                  {bill.due_at && <>Due <TimeAgo date={bill.due_at} /> &middot; </>}
                  {bill.issued_at && <>Issued <TimeAgo date={bill.issued_at} /></>}
                </div>
                {bill.memo && (
                  <div className="dashboard-item-meta">{bill.memo.slice(0, 120)}{bill.memo.length > 120 && '...'}</div>
                )}
              </div>
              {/* Project tag / assignment */}
              <div style={{ position: 'relative', flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
                <button
                  className="day-filter-btn"
                  style={{ fontSize: '0.75rem', padding: '2px 6px', opacity: 0.8 }}
                  onClick={() => setOpenDropdown(prev => prev === bill.id ? null : bill.id)}
                  title="Assign to project"
                >
                  {bill.project_name || 'No project'}
                </button>
                {openDropdown === bill.id && (
                  <div style={{
                    position: 'absolute', right: 0, top: '100%', zIndex: 100,
                    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
                    borderRadius: '4px', minWidth: '160px', maxHeight: '200px', overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
                  }}>
                    <button
                      style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px', border: 'none', background: 'none', cursor: 'pointer', fontSize: '0.8rem' }}
                      onClick={() => { assignBillProject.mutate({ billId: bill.id, projectId: null }); setOpenDropdown(null); }}
                    >
                      — No project
                    </button>
                    {projects.map(p => (
                      <button
                        key={p.id}
                        style={{ display: 'block', width: '100%', textAlign: 'left', padding: '6px 10px', border: 'none', background: p.id === bill.project_id ? 'var(--color-bg-hover)' : 'none', cursor: 'pointer', fontSize: '0.8rem' }}
                        onClick={() => { assignBillProject.mutate({ billId: bill.id, projectId: p.id }); setOpenDropdown(null); }}
                      >
                        {p.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

// --- Projects Tab ---
function ProjectsTab() {
  const { data, isLoading } = useProjects();
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();
  const [editingBudget, setEditingBudget] = useState<{ id: number; value: string } | null>(null);
  const [editingName, setEditingName] = useState<{ id: number; value: string } | null>(null);
  const [newName, setNewName] = useState('');
  const budgetInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  const projects: Project[] = data?.projects ?? [];
  const activeProjects = projects.filter(p => p.status !== 'archived');

  const handleBudgetCommit = (project: Project) => {
    if (!editingBudget) return;
    const val = parseFloat(editingBudget.value.replace(/[^0-9.]/g, ''));
    if (!isNaN(val)) {
      updateProject.mutate({ id: project.id, budget_amount: val });
    }
    setEditingBudget(null);
  };

  const handleNameCommit = (project: Project) => {
    if (!editingName) return;
    const val = editingName.value.trim();
    if (val && val !== project.name) {
      updateProject.mutate({ id: project.id, name: val });
    }
    setEditingName(null);
  };

  return (
    <>
      <div className="priorities-header" style={{ marginTop: 0 }}>
        <span style={{ color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
          {activeProjects.length} project{activeProjects.length !== 1 ? 's' : ''}
          {activeProjects.length > 0 && ` · ${formatAmount(activeProjects.reduce((s, p) => s + (p.budget_amount || 0), 0))} budgeted`}
        </span>
      </div>

      {isLoading && <p className="empty-state">Loading projects...</p>}

      <div>
        {activeProjects.map((project) => {
          const remaining = project.budget_amount - project.committed_amount;
          const overBudget = project.budget_amount > 0 && remaining < 0;
          const pct = project.budget_amount > 0 ? Math.min(100, (project.committed_amount / project.budget_amount) * 100) : 0;

          return (
            <div key={project.id} className="dashboard-item-row">
              <div className="dashboard-item" style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                  {/* Name — click to edit */}
                  {editingName?.id === project.id ? (
                    <input
                      ref={nameInputRef}
                      value={editingName.value}
                      onChange={(e) => setEditingName({ id: project.id, value: e.target.value })}
                      onBlur={() => handleNameCommit(project)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleNameCommit(project); if (e.key === 'Escape') setEditingName(null); }}
                      style={{ fontSize: '1rem', fontWeight: 600, border: '1px solid var(--color-border)', borderRadius: '3px', padding: '1px 4px', background: 'var(--color-bg)', color: 'var(--color-text)', width: '200px' }}
                      autoFocus
                    />
                  ) : (
                    <strong
                      className="dashboard-item-title"
                      style={{ cursor: 'text' }}
                      onDoubleClick={() => setEditingName({ id: project.id, value: project.name })}
                      title="Double-click to rename"
                    >
                      {project.name}
                    </strong>
                  )}
                  <span className="dashboard-item-meta">
                    {formatAmount(project.paid_amount)} paid · {formatAmount(project.committed_amount)} committed
                  </span>
                  {/* Budget — click to edit */}
                  <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    {editingBudget?.id === project.id ? (
                      <input
                        ref={budgetInputRef}
                        value={editingBudget.value}
                        onChange={(e) => setEditingBudget({ id: project.id, value: e.target.value })}
                        onBlur={() => handleBudgetCommit(project)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleBudgetCommit(project); if (e.key === 'Escape') setEditingBudget(null); }}
                        style={{ width: '100px', textAlign: 'right', border: '1px solid var(--color-border)', borderRadius: '3px', padding: '1px 4px', background: 'var(--color-bg)', color: 'var(--color-text)' }}
                        autoFocus
                      />
                    ) : (
                      <span
                        style={{ cursor: 'pointer', color: project.budget_amount > 0 ? 'var(--color-text)' : 'var(--color-text-muted)', textDecoration: 'underline dotted' }}
                        onClick={() => setEditingBudget({ id: project.id, value: String(project.budget_amount) })}
                        title="Click to set budget"
                      >
                        {project.budget_amount > 0 ? formatAmount(project.budget_amount) : 'Set budget'}
                      </span>
                    )}
                  </span>
                </div>
                {/* Progress bar */}
                {project.budget_amount > 0 && (
                  <div style={{ marginTop: '4px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{ flex: 1, height: '4px', background: 'var(--color-border)', borderRadius: '2px', overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: overBudget ? 'var(--color-red, #c0392b)' : 'var(--color-green, #27ae60)', borderRadius: '2px', transition: 'width 0.3s' }} />
                    </div>
                    <span className="dashboard-item-meta" style={{ color: overBudget ? 'var(--color-red, #c0392b)' : undefined, whiteSpace: 'nowrap' }}>
                      {overBudget ? `${formatAmount(Math.abs(remaining))} over` : `${formatAmount(remaining)} left`}
                    </span>
                  </div>
                )}
              </div>
              <button
                className="dashboard-dismiss-btn"
                onClick={() => { if (confirm(`Delete project "${project.name}"?`)) deleteProject.mutate(project.id); }}
                title="Delete project"
              >&times;</button>
            </div>
          );
        })}
      </div>

      {/* Add new project */}
      <div style={{ marginTop: 'var(--space-md)', display: 'flex', gap: '8px' }}>
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New project name..."
          onKeyDown={(e) => {
            if (e.key === 'Enter' && newName.trim()) {
              createProject.mutate({ name: newName.trim() });
              setNewName('');
            }
          }}
          style={{ flex: 1, padding: '4px 8px', border: '1px solid var(--color-border)', borderRadius: '3px', background: 'var(--color-bg)', color: 'var(--color-text)', fontSize: '0.9rem' }}
        />
        <button
          className="priorities-refresh-btn"
          disabled={!newName.trim() || createProject.isPending}
          onClick={() => { if (newName.trim()) { createProject.mutate({ name: newName.trim() }); setNewName(''); } }}
        >
          Add project
        </button>
      </div>
    </>
  );
}

// --- Main RampPage ---
export function RampPage() {
  const { pathname } = useLocation();
  const tab: TabType = pathname === '/ramp/bills' ? 'bills' : pathname === '/ramp/projects' ? 'projects' : 'expenses';
  const { data: projectsData } = useProjects();
  const projects: Project[] = projectsData?.projects ?? [];

  return (
    <div>
      <div className="priorities-header">
        <h1>Ramp</h1>
      </div>

      {tab === 'expenses' && <ExpensesTab />}
      {tab === 'bills' && <BillsTab projects={projects} />}
      {tab === 'projects' && <ProjectsTab />}
    </div>
  );
}
