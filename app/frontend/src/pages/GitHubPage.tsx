import { useState, useMemo, useCallback } from 'react';
import { useGitHubPulls, useGitHubSearch, useGitHubCodeSearch, useDismissPrioritizedItem, useCreateIssue } from '../api/hooks';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';

type Tab = 'reviews' | 'open' | 'search';
type SearchMode = 'prs' | 'code';

export function GitHubPage() {
  const [tab, setTab] = useState<Tab>('reviews');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMode, setSearchMode] = useState<SearchMode>('prs');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const dismiss = useDismissPrioritizedItem();
  const createIssue = useCreateIssue();
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpand = useCallback((id: number) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const reviewPulls = useGitHubPulls({ review_requested: true });
  const openPulls = useGitHubPulls({ state: 'open' });
  const searchResults = useGitHubSearch(submittedQuery, searchMode === 'prs' ? 'pr' : undefined);
  const codeResults = useGitHubCodeSearch(searchMode === 'code' ? submittedQuery : '');

  const activePulls = useMemo(() => {
    if (tab === 'reviews') return reviewPulls.data?.pulls ?? [];
    if (tab === 'open') return openPulls.data?.pulls ?? [];
    return [];
  }, [tab, reviewPulls.data, openPulls.data]);

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: tab !== 'search',
    onDismiss: (i) => { if (activePulls[i]) dismiss.mutate({ source: 'github', item_id: String(activePulls[i].number) }); },
    onCreateIssue: (i) => { if (activePulls[i]) createIssue.mutate({ title: activePulls[i].title }); },
    onExpand: (i) => { if (activePulls[i]) toggleExpand(activePulls[i].number); },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittedQuery(searchQuery.trim());
  };

  return (
    <div ref={containerRef}>
      <h1>GitHub</h1>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-md)' }}>
        Pull Requests &amp; Code Search
      </p>

      <div className="github-tabs">
        <button
          className={`github-tab ${tab === 'reviews' ? 'active' : ''}`}
          onClick={() => setTab('reviews')}
        >
          Review Requests
          {reviewPulls.data?.count ? (
            <span className="github-tab-count">({reviewPulls.data.count})</span>
          ) : null}
        </button>
        <button
          className={`github-tab ${tab === 'open' ? 'active' : ''}`}
          onClick={() => setTab('open')}
        >
          Open PRs
          {openPulls.data?.count ? (
            <span className="github-tab-count">({openPulls.data.count})</span>
          ) : null}
        </button>
        <button
          className={`github-tab ${tab === 'search' ? 'active' : ''}`}
          onClick={() => setTab('search')}
        >
          Search
        </button>
      </div>

      {tab === 'reviews' && (
        <div className="github-pr-list">
          {reviewPulls.isLoading && <p className="empty-state">Loading...</p>}
          {!reviewPulls.isLoading && reviewPulls.data?.pulls.length === 0 && (
            <p className="empty-state">No pending review requests</p>
          )}
          {reviewPulls.data?.pulls.map((pr) => (
            <PullRequestRow key={pr.number} pr={pr} expanded={expandedIds.has(pr.number)} onToggleExpand={() => toggleExpand(pr.number)} onDismiss={() => dismiss.mutate({ source: 'github', item_id: String(pr.number) })} />
          ))}
        </div>
      )}

      {tab === 'open' && (
        <div className="github-pr-list">
          {openPulls.isLoading && <p className="empty-state">Loading...</p>}
          {!openPulls.isLoading && openPulls.data?.pulls.length === 0 && (
            <p className="empty-state">No open PRs</p>
          )}
          {openPulls.data?.pulls.map((pr) => (
            <PullRequestRow key={pr.number} pr={pr} expanded={expandedIds.has(pr.number)} onToggleExpand={() => toggleExpand(pr.number)} onDismiss={() => dismiss.mutate({ source: 'github', item_id: String(pr.number) })} />
          ))}
        </div>
      )}

      {tab === 'search' && (
        <div>
          <form onSubmit={handleSearch} className="github-search-form">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search PRs, issues, or code..."
              className="github-search-input"
            />
            <div className="github-search-mode">
              <button
                type="button"
                className={`github-tab ${searchMode === 'prs' ? 'active' : ''}`}
                onClick={() => setSearchMode('prs')}
              >
                Issues & PRs
              </button>
              <button
                type="button"
                className={`github-tab ${searchMode === 'code' ? 'active' : ''}`}
                onClick={() => setSearchMode('code')}
              >
                Code
              </button>
            </div>
          </form>

          {searchMode === 'prs' && submittedQuery && (
            <div className="github-pr-list">
              {searchResults.isLoading && <p className="empty-state">Searching...</p>}
              {searchResults.data && (
                <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-sm)' }}>
                  {searchResults.data.total} results
                </p>
              )}
              {searchResults.data?.items.map((item) => (
                <a
                  key={item.number}
                  className="dashboard-item dashboard-item-link"
                  href={item.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="dashboard-item-title">
                    <span className="github-pr-number">#{item.number}</span>{' '}
                    {item.title}
                    {item.type === 'issue' && <span className="github-badge github-badge-issue">issue</span>}
                  </div>
                  <div className="dashboard-item-meta">
                    {item.author} &middot; {item.state} &middot;{' '}
                    <TimeAgo date={item.updated_at} />
                  </div>
                </a>
              ))}
            </div>
          )}

          {searchMode === 'code' && submittedQuery && (
            <div className="github-pr-list">
              {codeResults.isLoading && <p className="empty-state">Searching code...</p>}
              {codeResults.data && (
                <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-sm)' }}>
                  {codeResults.data.total} results
                </p>
              )}
              {codeResults.data?.items.map((item, i) => (
                <a
                  key={i}
                  className="dashboard-item dashboard-item-link"
                  href={item.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="dashboard-item-title">{item.path}</div>
                  {item.text_matches?.map((tm, j) => (
                    <div key={j} className="github-code-fragment">
                      {tm.fragment}
                    </div>
                  ))}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {(tab === 'reviews' && reviewPulls.data?.pulls.length || tab === 'open' && openPulls.data?.pulls.length) ? (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue']} />
      ) : null}
    </div>
  );
}

function PullRequestRow({ pr, expanded, onToggleExpand, onDismiss }: {
  pr: { number: number; title: string; state: string; draft: boolean; author: string; html_url: string; updated_at: string; head_ref: string; base_ref: string; labels: string[]; requested_reviewers: string[] };
  expanded: boolean;
  onToggleExpand: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="dashboard-item-row">
      <a
        className="dashboard-item dashboard-item-link"
        href={pr.html_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        <div className="dashboard-item-title">
          <span className="github-pr-number">#{pr.number}</span>{' '}
          {pr.title}
          {pr.draft && <span className="github-badge github-badge-draft">draft</span>}
          {pr.state === 'merged' && <span className="github-badge github-badge-merged">merged</span>}
          {pr.labels.map((l) => (
            <span key={l} className="github-badge">{l}</span>
          ))}
        </div>
        <div className="dashboard-item-meta">
          {pr.author} &middot; {pr.head_ref} &middot;{' '}
          <TimeAgo date={pr.updated_at} />
        </div>
        {expanded && (
          <div className="dashboard-item-expanded">
            {pr.head_ref} &rarr; {pr.base_ref}
            {pr.requested_reviewers.length > 0 && (
              <span> &middot; reviewers: {pr.requested_reviewers.join(', ')}</span>
            )}
          </div>
        )}
      </a>
      <button
        className="dashboard-expand-btn"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggleExpand(); }}
        title={expanded ? 'Collapse (e)' : 'Expand (e)'}
      >
        {expanded ? '\u25BE' : '\u25B8'}
      </button>
      <button
        className="dashboard-dismiss-btn"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); onDismiss(); }}
        title="Mark as seen"
      >&times;</button>
    </div>
  );
}
