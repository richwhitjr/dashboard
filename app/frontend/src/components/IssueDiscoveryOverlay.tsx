import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  useDiscoverIssues,
  useDiscoveryStatus,
  useDiscoveryProposals,
  useAcceptProposal,
  useRejectProposal,
  useBulkDiscoveryAction,
} from '../api/hooks';
import type { ProposedIssue } from '../api/types';

export type DiscoveryPhase = 'hidden' | 'scanning' | 'ready' | 'reviewing';

interface Props {
  phase: DiscoveryPhase;
  onPhaseChange: (phase: DiscoveryPhase) => void;
}

const STEP_LABELS: Record<string, string> = {
  preparing: 'Preparing...',
  gathering: 'Gathering data from sources',
  analyzing: 'Analyzing with AI',
  saving: 'Saving proposals',
  done: 'Complete',
  error: 'Error',
};

const SIZES = ['s', 'm', 'l', 'xl'] as const;
const PRIORITIES = [0, 1, 2, 3] as const;

export function IssueDiscoveryOverlay({ phase, onPhaseChange }: Props) {
  const [runId, setRunId] = useState<number | null>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editOverrides, setEditOverrides] = useState<Record<number, Record<string, unknown>>>({});
  const listRef = useRef<HTMLDivElement>(null);

  const discoverIssues = useDiscoverIssues();
  const { data: status } = useDiscoveryStatus(phase === 'scanning');
  const { data: proposalsData, refetch: refetchProposals } = useDiscoveryProposals(
    phase === 'reviewing' || phase === 'ready' ? runId : null
  );
  const acceptProposal = useAcceptProposal();
  const rejectProposal = useRejectProposal();
  const bulkAction = useBulkDiscoveryAction();

  const proposals = useMemo(() => proposalsData?.proposals ?? [], [proposalsData]);
  const pendingCount = proposals.filter(p => p.status === 'pending').length;
  const acceptedCount = proposals.filter(p => p.status === 'accepted').length;
  const rejectedCount = proposals.filter(p => p.status === 'rejected').length;
  const reviewedCount = acceptedCount + rejectedCount;

  // Trigger scan when entering scanning phase
  useEffect(() => {
    if (phase === 'scanning' && !discoverIssues.isPending) {
      discoverIssues.mutate(undefined, {
        onSuccess: (data) => {
          if (data.run_id) setRunId(data.run_id);
        },
      });
    }
  }, [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  // Transition from scanning to ready when done
  useEffect(() => {
    if (phase === 'scanning' && status && !status.running && status.current_step === 'done') {
      if (status.run_id) setRunId(status.run_id);
      onPhaseChange('ready');
    }
    if (phase === 'scanning' && status && !status.running && status.current_step === 'error') {
      onPhaseChange('hidden');
    }
  }, [phase, status, onPhaseChange]);

  // Reset state when hidden
  useEffect(() => {
    if (phase === 'hidden') {
      setFocusedIndex(0);
      setEditingId(null);
      setEditOverrides({});
    }
  }, [phase]);

  // Scroll focused item into view
  useEffect(() => {
    if (phase === 'reviewing') {
      const item = listRef.current?.querySelector('.discovery-proposal.focused');
      item?.scrollIntoView({ block: 'nearest' });
    }
  }, [focusedIndex, phase]);

  const handleAccept = useCallback((proposal: ProposedIssue) => {
    const overrides = editOverrides[proposal.id];
    acceptProposal.mutate(
      { proposalId: proposal.id, overrides },
      { onSuccess: () => refetchProposals() },
    );
    setEditingId(null);
  }, [acceptProposal, editOverrides, refetchProposals]);

  const handleReject = useCallback((proposalId: number) => {
    rejectProposal.mutate(proposalId, {
      onSuccess: () => refetchProposals(),
    });
    setEditingId(null);
  }, [rejectProposal, refetchProposals]);

  const handleAcceptAll = useCallback(() => {
    if (runId) {
      bulkAction.mutate(
        { action: 'accept_all', run_id: runId },
        { onSuccess: () => refetchProposals() },
      );
    }
  }, [bulkAction, runId, refetchProposals]);

  const handleRejectAll = useCallback(() => {
    if (runId) {
      bulkAction.mutate(
        { action: 'reject_all', run_id: runId },
        { onSuccess: () => refetchProposals() },
      );
    }
  }, [bulkAction, runId, refetchProposals]);

  const updateOverride = (proposalId: number, key: string, value: unknown) => {
    setEditOverrides(prev => ({
      ...prev,
      [proposalId]: { ...(prev[proposalId] || {}), [key]: value },
    }));
  };

  // Keyboard handler for review modal
  useEffect(() => {
    if (phase !== 'reviewing') return;

    const handler = (e: KeyboardEvent) => {
      // Stop all keyboard events from reaching page-level handlers while modal is open.
      // Using stopImmediatePropagation because all handlers are on `document`;
      // plain stopPropagation only blocks cross-node bubbling, not same-node listeners.
      e.stopImmediatePropagation();

      const tag = (e.target as HTMLElement)?.tagName;
      const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

      if (e.key === 'Escape') {
        e.preventDefault();
        if (editingId !== null) {
          setEditingId(null);
        } else {
          onPhaseChange('hidden');
        }
        return;
      }

      // Skip navigation keys when editing
      if (isInput) return;

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusedIndex(i => Math.min(i + 1, proposals.length - 1));
        return;
      }
      if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusedIndex(i => Math.max(i - 1, 0));
        return;
      }

      const focused = proposals[focusedIndex];
      if (!focused || focused.status !== 'pending') return;

      if (e.key === 'Enter') {
        e.preventDefault();
        handleAccept(focused);
        return;
      }
      if (e.key === 'x') {
        e.preventDefault();
        handleReject(focused.id);
        return;
      }
      if (e.key === 'e') {
        e.preventDefault();
        setEditingId(editingId === focused.id ? null : focused.id);
        return;
      }
    };

    document.addEventListener('keydown', handler, true);
    return () => document.removeEventListener('keydown', handler, true);
  }, [phase, proposals, focusedIndex, editingId, handleAccept, handleReject, onPhaseChange]);

  // --- Phase 1: Scanning toast ---
  if (phase === 'scanning') {
    return (
      <div className="discovery-toast">
        <div className="discovery-toast-content">
          <svg className="sync-step-spinner" width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor"
                    strokeWidth="1.5" strokeDasharray="20 14" />
          </svg>
          <span>
            Scanning for issues...
            {status?.steps_done?.length ? ` (${status.steps_done.length}/3)` : ''}
          </span>
        </div>
        {status?.current_step && (
          <div className="discovery-toast-step">
            {STEP_LABELS[status.current_step] || status.current_step}
          </div>
        )}
        <button className="discovery-toast-close" onClick={() => onPhaseChange('hidden')}>
          &times;
        </button>
      </div>
    );
  }

  // --- Phase 2: Ready toast ---
  if (phase === 'ready') {
    return (
      <div className="discovery-toast discovery-toast-ready" onClick={() => onPhaseChange('reviewing')}>
        <div className="discovery-toast-content">
          <span style={{ color: '#2a7f2a' }}>&#10003;</span>
          <span>Found {proposalsData?.proposals?.length ?? '...'} potential issues</span>
          <button className="discovery-toast-review-btn">Review</button>
        </div>
        <button className="discovery-toast-close" onClick={(e) => { e.stopPropagation(); onPhaseChange('hidden'); }}>
          &times;
        </button>
      </div>
    );
  }

  // --- Phase 3: Review modal ---
  if (phase !== 'reviewing') return null;

  return (
    <div className="discovery-overlay" onClick={() => onPhaseChange('hidden')}>
      <div className="discovery-panel" onClick={e => e.stopPropagation()}>
        <div className="discovery-header">
          <h3>Issue Discovery</h3>
          <span className="discovery-stats">
            {reviewedCount} of {proposals.length} reviewed
            {acceptedCount > 0 && <> &middot; {acceptedCount} accepted</>}
            {rejectedCount > 0 && <> &middot; {rejectedCount} rejected</>}
          </span>
        </div>

        <div className="discovery-proposals" ref={listRef}>
          {proposals.length === 0 && (
            <p style={{ color: 'var(--color-text-light)', fontStyle: 'italic', fontSize: 'var(--text-sm)' }}>
              No issues found. Try syncing your data first (press s).
            </p>
          )}
          {proposals.map((proposal, idx) => (
            <ProposalItem
              key={proposal.id}
              proposal={proposal}
              focused={idx === focusedIndex}
              editing={editingId === proposal.id}
              overrides={editOverrides[proposal.id]}
              onFocus={() => setFocusedIndex(idx)}
              onAccept={() => handleAccept(proposal)}
              onReject={() => handleReject(proposal.id)}
              onToggleEdit={() => setEditingId(editingId === proposal.id ? null : proposal.id)}
              onUpdateOverride={(key, value) => updateOverride(proposal.id, key, value)}
            />
          ))}
        </div>

        <div className="discovery-footer">
          {pendingCount > 0 && (
            <>
              <button onClick={handleAcceptAll}>Accept all ({pendingCount})</button>
              <button onClick={handleRejectAll}>Reject all ({pendingCount})</button>
            </>
          )}
          {pendingCount === 0 && proposals.length > 0 && (
            <button onClick={() => onPhaseChange('hidden')}>Done</button>
          )}
          <span className="discovery-hint">
            j/k navigate &middot; Enter accept &middot; x reject &middot; e edit &middot; Esc close
          </span>
        </div>
      </div>
    </div>
  );
}

// --- Proposal Item sub-component ---

interface ProposalItemProps {
  proposal: ProposedIssue;
  focused: boolean;
  editing: boolean;
  overrides?: Record<string, unknown>;
  onFocus: () => void;
  onAccept: () => void;
  onReject: () => void;
  onToggleEdit: () => void;
  onUpdateOverride: (key: string, value: unknown) => void;
}

function ProposalItem({
  proposal,
  focused,
  editing,
  overrides,
  onFocus,
  onAccept,
  onReject,
  onToggleEdit,
  onUpdateOverride,
}: ProposalItemProps) {
  const title = (overrides?.title as string) ?? proposal.title;
  const description = (overrides?.description as string) ?? proposal.description;
  const priority = (overrides?.priority as number) ?? proposal.priority;
  const tshirtSize = (overrides?.tshirt_size as string) ?? proposal.tshirt_size;

  const classNames = [
    'discovery-proposal',
    focused && 'focused',
    proposal.status !== 'pending' && proposal.status,
  ].filter(Boolean).join(' ');

  return (
    <div className={classNames} onClick={onFocus}>
      <div className="discovery-proposal-header">
        <span className={`issue-size-badge size-${tshirtSize}`}>
          {tshirtSize.toUpperCase()}
        </span>
        {editing ? (
          <span className="discovery-proposal-title">
            <input
              value={title}
              onChange={e => onUpdateOverride('title', e.target.value)}
              autoFocus
            />
          </span>
        ) : (
          <span className="discovery-proposal-title">{title}</span>
        )}
        <span className="issue-priority-label">P{priority}</span>
        <span className="discovery-source-badge">{proposal.source}</span>
      </div>

      {editing ? (
        <div className="discovery-proposal-desc">
          <textarea
            value={description}
            onChange={e => onUpdateOverride('description', e.target.value)}
            rows={2}
          />
        </div>
      ) : description ? (
        <p className="discovery-proposal-desc">{description}</p>
      ) : null}

      {proposal.source_context && (
        <blockquote className="discovery-context">{proposal.source_context}</blockquote>
      )}

      <div className="discovery-proposal-meta">
        {proposal.suggested_tags.map(t => (
          <span key={t} className="issue-tag-badge">{t}</span>
        ))}
        {proposal.suggested_people.map(p => (
          <span key={p} className="discovery-person-badge">{p}</span>
        ))}
      </div>

      {editing && (
        <div className="discovery-edit-row">
          <label>Size:</label>
          <select
            value={tshirtSize}
            onChange={e => onUpdateOverride('tshirt_size', e.target.value)}
          >
            {SIZES.map(s => <option key={s} value={s}>{s.toUpperCase()}</option>)}
          </select>
          <label>Priority:</label>
          <select
            value={priority}
            onChange={e => onUpdateOverride('priority', parseInt(e.target.value))}
          >
            {PRIORITIES.map(p => <option key={p} value={p}>P{p}</option>)}
          </select>
        </div>
      )}

      {proposal.status === 'pending' && (
        <div className="discovery-proposal-actions">
          <button className="discovery-btn-accept" onClick={e => { e.stopPropagation(); onAccept(); }}>
            Accept
          </button>
          <button className="discovery-btn-edit" onClick={e => { e.stopPropagation(); onToggleEdit(); }}>
            {editing ? 'Done editing' : 'Edit'}
          </button>
          <button className="discovery-btn-reject" onClick={e => { e.stopPropagation(); onReject(); }}>
            Reject
          </button>
        </div>
      )}

      {proposal.status !== 'pending' && (
        <div className={`discovery-proposal-status ${proposal.status}`}>
          {proposal.status === 'accepted' ? '✓ accepted' : '✗ rejected'}
        </div>
      )}
    </div>
  );
}
