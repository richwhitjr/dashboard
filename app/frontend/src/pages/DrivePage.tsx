import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  usePrioritizedDrive,
  useRefreshPrioritizedDrive,
  useDismissPrioritizedItem,
  useCreateIssue,
  useDocs,
  useSheets,
  useSheetValues,
  useAllDriveFiles,
  type AllTabSearchParams,
} from '../api/hooks';
import type { GoogleSheet } from '../api/types';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';
import { InfiniteScrollSentinel } from '../components/shared/InfiniteScrollSentinel';
import { openExternal } from '../api/client';

const TABS = ['Files', 'Docs', 'Sheets'] as const;
type Tab = (typeof TABS)[number];

const DAY_OPTIONS = [7, 30, 90] as const;
const SCORE_OPTIONS = [0, 3, 5, 6, 7, 8] as const;
const DEFAULT_MIN_SCORE = 5;

// --- SVG icons for file types (16x16, Google-style colors) ---

function DocIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="2" y="1" width="12" height="14" rx="1.5" fill="#4285F4" />
      <rect x="4.5" y="4" width="7" height="1" rx=".5" fill="#fff" />
      <rect x="4.5" y="6.5" width="7" height="1" rx=".5" fill="#fff" />
      <rect x="4.5" y="9" width="5" height="1" rx=".5" fill="#fff" />
    </svg>
  );
}

function SheetIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="2" y="1" width="12" height="14" rx="1.5" fill="#0F9D58" />
      <rect x="4" y="4" width="8" height="1" fill="#fff" />
      <rect x="4" y="6" width="8" height="1" fill="#fff" />
      <rect x="4" y="8" width="8" height="1" fill="#fff" />
      <rect x="4" y="10" width="8" height="1" fill="#fff" />
      <rect x="7.5" y="4" width="1" height="7" fill="#fff" opacity=".5" />
    </svg>
  );
}

function SlidesIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="2" y="1" width="12" height="14" rx="1.5" fill="#F4B400" />
      <rect x="4" y="4" width="8" height="6" rx="1" fill="#fff" />
    </svg>
  );
}

function PdfIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="2" y="1" width="12" height="14" rx="1.5" fill="#DB4437" />
      <text x="8" y="10.5" textAnchor="middle" fill="#fff" fontSize="6" fontWeight="bold" fontFamily="sans-serif">
        PDF
      </text>
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <path d="M2 4.5A1.5 1.5 0 013.5 3H6l1.5 1.5h5A1.5 1.5 0 0114 6v6a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12V4.5z" fill="#5F6368" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="2" y="2" width="12" height="12" rx="1.5" fill="#5F6368" />
      <circle cx="5.5" cy="5.5" r="1.5" fill="#fff" />
      <path d="M2 11l3-3 2 2 3-4 4 5H2z" fill="#fff" opacity=".8" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <path d="M3.5 1A1.5 1.5 0 002 2.5v11A1.5 1.5 0 003.5 15h9a1.5 1.5 0 001.5-1.5V5.5L10 1H3.5z" fill="#5F6368" />
      <path d="M10 1v3.5a1 1 0 001 1H14" fill="#9AA0A6" />
    </svg>
  );
}

function MimeIcon({ mime }: { mime: string }) {
  if (mime.includes('document')) return <DocIcon />;
  if (mime.includes('spreadsheet')) return <SheetIcon />;
  if (mime.includes('presentation')) return <SlidesIcon />;
  if (mime.includes('pdf')) return <PdfIcon />;
  if (mime.includes('folder')) return <FolderIcon />;
  if (mime.includes('image')) return <ImageIcon />;
  return <FileIcon />;
}

function scoreBadge(score: number) {
  const cls =
    score >= 8
      ? 'priority-urgency-high'
      : score >= 5
        ? 'priority-urgency-medium'
        : 'priority-urgency-low';
  return <span className={`priority-score-badge ${cls}`}>{score}</span>;
}

// --- Files Tab ---

function FilesTab() {
  const [mode, setMode] = useState<'priority' | 'all'>('priority');
  const [days, setDays] = useState(7);
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const { data, isLoading } = usePrioritizedDrive(days);
  const refresh = useRefreshPrioritizedDrive(days);
  const dismiss = useDismissPrioritizedItem();
  const createIssue = useCreateIssue();
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // All-mode search state
  const [allSearchParams, setAllSearchParams] = useState<AllTabSearchParams>({});
  const [allLocalQuery, setAllLocalQuery] = useState('');
  const [allLocalOwner, setAllLocalOwner] = useState('');
  const [allLocalDateFrom, setAllLocalDateFrom] = useState('');
  const [allLocalDateTo, setAllLocalDateTo] = useState('');
  const [showAllFilters, setShowAllFilters] = useState(false);
  const allSearchRef = useRef<HTMLInputElement>(null);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const allItems = data?.items ?? [];
  const items = minScore > 0 ? allItems.filter((f) => f.priority_score >= minScore) : allItems;
  const hiddenCount = allItems.length - items.length;

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: mode === 'priority',
    onDismiss: (i) => {
      if (items[i]) dismiss.mutate({ source: 'drive', item_id: items[i].id });
    },
    onOpen: (i) => {
      if (items[i]?.web_view_link) openExternal(items[i].web_view_link);
    },
    onCreateIssue: (i) => {
      if (items[i]) createIssue.mutate({ title: items[i].name });
    },
    onExpand: (i) => {
      if (items[i]) toggleExpand(items[i].id);
    },
    onToggleFilter: () => setMinScore((prev) => (prev === 0 ? DEFAULT_MIN_SCORE : 0)),
  });

  // Debounce all-mode search params
  useEffect(() => {
    const timer = setTimeout(() => {
      setAllSearchParams({
        q: allLocalQuery || undefined,
        author: allLocalOwner || undefined,
        from_date: allLocalDateFrom || undefined,
        to_date: allLocalDateTo || undefined,
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [allLocalQuery, allLocalOwner, allLocalDateFrom, allLocalDateTo]);

  // Clear search when switching away from all mode
  useEffect(() => {
    if (mode !== 'all') {
      setAllLocalQuery('');
      setAllLocalOwner('');
      setAllLocalDateFrom('');
      setAllLocalDateTo('');
      setShowAllFilters(false);
      setAllSearchParams({});
    }
  }, [mode]);

  // '/' to focus search when in all mode
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((e.target as HTMLElement)?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === '/' && mode === 'all') {
        e.preventDefault();
        allSearchRef.current?.focus();
        allSearchRef.current?.select();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [mode]);

  // All-files query
  const allQuery = useAllDriveFiles(allSearchParams);
  const allFiles = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <>
      <div className="github-tabs" style={{ marginBottom: 'var(--space-sm)' }}>
        <button className={`github-tab ${mode === 'priority' ? 'active' : ''}`} onClick={() => setMode('priority')}>
          Priority
        </button>
        <button className={`github-tab ${mode === 'all' ? 'active' : ''}`} onClick={() => setMode('all')}>
          All{allTotal > 0 ? ` (${allTotal})` : ''}
        </button>
      </div>

      {mode === 'priority' && (
        <>
          <div className="priorities-header" style={{ marginBottom: 'var(--space-sm)' }}>
            <span className="day-filter">
              {DAY_OPTIONS.map((d) => (
                <button
                  key={d}
                  className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`}
                  onClick={() => setDays(d)}
                >
                  {d}d
                </button>
              ))}
            </span>
            <span className="day-filter">
              {SCORE_OPTIONS.map((s) => (
                <button
                  key={s}
                  className={`day-filter-btn${minScore === s ? ' day-filter-active' : ''}`}
                  onClick={() => setMinScore(s)}
                  title={s === 0 ? 'Show all (f)' : `Hide scores below ${s} (f)`}
                >
                  {s === 0 ? 'All' : `${s}+`}
                </button>
              ))}
            </span>
            <button
              className="priorities-refresh-btn"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || !!data?.stale}
              title="Re-rank with AI"
            >
              {data?.stale ? 'Updating...' : refresh.isPending ? 'Ranking...' : 'Refresh'}
            </button>
          </div>

          {isLoading && <p className="empty-state">Loading prioritized files...</p>}
          {data?.error && (
            <p className="empty-state">
              Google Drive is not connected. Set up Google Drive in <Link to="/settings">Settings</Link>{' '}
              to see your files.
            </p>
          )}
          {!isLoading && !data?.error && items.length === 0 && (
            <p className="empty-state">
              {hiddenCount > 0
                ? `${hiddenCount} file${hiddenCount !== 1 ? 's' : ''} hidden below score ${minScore}`
                : `No files in the last ${days} day${days > 1 ? 's' : ''}`}
            </p>
          )}

          <div ref={containerRef}>
            {items.map((file) => {
              const isExpanded = expandedIds.has(file.id);
              const hasPreview = !!file.content_preview || !!file.description;
              return (
                <div key={file.id} className="dashboard-item-row">
                  <div
                    className="dashboard-item dashboard-item-link"
                    style={{
                      display: 'flex',
                      gap: 'var(--space-sm)',
                      alignItems: 'flex-start',
                      cursor: 'pointer',
                    }}
                    onClick={() => openExternal(file.web_view_link)}
                  >
                    <div style={{ flexShrink: 0, paddingTop: '2px', display: 'flex', gap: 6, alignItems: 'center' }}>
                      {scoreBadge(file.priority_score)}
                      <MimeIcon mime={file.mime_type} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="dashboard-item-title">
                        {file.name}
                      </div>
                      <div className="dashboard-item-meta">
                        {file.owner_name || 'Unknown'}
                        {file.modified_by_name &&
                          file.modified_by_name !== file.owner_name &&
                          ` (edited by ${file.modified_by_name})`}
                        {' '}&middot;{' '}
                        <TimeAgo date={file.modified_time} />
                        {file.shared && ' \u00B7 Shared'}
                      </div>
                      {isExpanded && hasPreview && (
                        <div className="dashboard-item-expanded">
                          {file.content_preview || file.description}
                        </div>
                      )}
                      {file.priority_reason && (
                        <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>
                          {file.priority_reason}
                        </div>
                      )}
                    </div>
                  </div>
                  {hasPreview && (
                    <button
                      className="dashboard-expand-btn"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleExpand(file.id);
                      }}
                      title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                    >
                      {isExpanded ? '\u25BE' : '\u25B8'}
                    </button>
                  )}
                  <button
                    className="dashboard-dismiss-btn"
                    onClick={() => dismiss.mutate({ source: 'drive', item_id: file.id })}
                    title="Mark as seen"
                  >
                    &times;
                  </button>
                </div>
              );
            })}
          </div>
          {hiddenCount > 0 && items.length > 0 && (
            <p className="empty-state" style={{ marginTop: 'var(--space-md)' }}>
              {hiddenCount} lower-priority file{hiddenCount !== 1 ? 's' : ''} hidden
              <button
                className="day-filter-btn"
                style={{ marginLeft: 'var(--space-sm)' }}
                onClick={() => setMinScore(0)}
              >
                Show all
              </button>
            </p>
          )}
          {items.length > 0 && (
            <KeyboardHints
              hints={['j/k navigate', 'Enter open', 'e expand', 'd dismiss', 'i create issue', 'f filter']}
            />
          )}
        </>
      )}

      {mode === 'all' && (
        <>
          <div className="all-search-bar">
            <input
              ref={allSearchRef}
              type="search"
              value={allLocalQuery}
              onChange={e => setAllLocalQuery(e.target.value)}
              placeholder="Search files..."
              className="all-search-input"
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  if (allLocalQuery) setAllLocalQuery('');
                  else allSearchRef.current?.blur();
                }
              }}
            />
            <button
              className={`day-filter-btn${showAllFilters ? ' day-filter-active' : ''}`}
              onClick={() => setShowAllFilters(f => !f)}
            >
              Filters
            </button>
            {(allLocalQuery || allLocalOwner || allLocalDateFrom || allLocalDateTo) && (
              <button className="day-filter-btn" onClick={() => { setAllLocalQuery(''); setAllLocalOwner(''); setAllLocalDateFrom(''); setAllLocalDateTo(''); }}>
                Clear
              </button>
            )}
          </div>
          {showAllFilters && (
            <div className="all-search-filters">
              <label>
                Owner
                <input type="text" value={allLocalOwner} onChange={e => setAllLocalOwner(e.target.value)} className="all-search-filter-input" placeholder="Filter by owner..." />
              </label>
              <label>
                From
                <input type="date" value={allLocalDateFrom} onChange={e => setAllLocalDateFrom(e.target.value)} className="all-search-filter-input" />
              </label>
              <label>
                To
                <input type="date" value={allLocalDateTo} onChange={e => setAllLocalDateTo(e.target.value)} className="all-search-filter-input" />
              </label>
            </div>
          )}
          {allQuery.isLoading && <p className="empty-state">Loading files...</p>}
          {!allQuery.isLoading && allFiles.length === 0 && (
            <p className="empty-state">
              {(allLocalQuery || allLocalOwner || allLocalDateFrom || allLocalDateTo)
                ? 'No files match your search'
                : 'No synced Drive files yet. Run a sync to populate.'}
            </p>
          )}
          <div>
            {allFiles.map((file) => {
              const isExpanded = expandedIds.has(file.id);
              const hasPreview = !!file.content_preview || !!file.description;
              return (
                <div key={file.id} className="dashboard-item-row">
                  <div
                    className="dashboard-item dashboard-item-link"
                    style={{
                      display: 'flex',
                      gap: 'var(--space-sm)',
                      alignItems: 'flex-start',
                      cursor: 'pointer',
                    }}
                    onClick={() => openExternal(file.web_view_link)}
                  >
                    <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                      <MimeIcon mime={file.mime_type} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="dashboard-item-title">{file.name}</div>
                      <div className="dashboard-item-meta">
                        {file.owner_name || 'Unknown'}
                        {file.modified_by_name &&
                          file.modified_by_name !== file.owner_name &&
                          ` (edited by ${file.modified_by_name})`}
                        {' '}&middot;{' '}
                        <TimeAgo date={file.modified_time} />
                        {file.shared && ' \u00B7 Shared'}
                      </div>
                      {isExpanded && hasPreview && (
                        <div className="dashboard-item-expanded">
                          {file.content_preview || file.description}
                        </div>
                      )}
                    </div>
                  </div>
                  {hasPreview && (
                    <button
                      className="dashboard-expand-btn"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        toggleExpand(file.id);
                      }}
                      title={isExpanded ? 'Collapse' : 'Expand'}
                    >
                      {isExpanded ? '\u25BE' : '\u25B8'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <InfiniteScrollSentinel
            hasNextPage={!!allQuery.hasNextPage}
            isFetchingNextPage={allQuery.isFetchingNextPage}
            fetchNextPage={allQuery.fetchNextPage}
          />
        </>
      )}
    </>
  );
}

// --- Docs Tab ---

function DocsTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useDocs(days);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const docs = data?.docs ?? [];

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    onOpen: (i) => {
      if (docs[i]?.web_view_link) openExternal(docs[i].web_view_link);
    },
    onExpand: (i) => {
      if (docs[i]) toggleExpand(docs[i].id);
    },
  });

  return (
    <>
      <div className="priorities-header" style={{ marginBottom: 'var(--space-sm)' }}>
        <span className="day-filter">
          {([7, 30, 90] as const).map((d) => (
            <button
              key={d}
              className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </span>
      </div>

      {isLoading && <p className="empty-state">Loading docs...</p>}
      {!isLoading && docs.length === 0 && (
        <p className="empty-state">No Google Docs in the last {days} days</p>
      )}

      <div ref={containerRef}>
        {docs.map((doc) => {
          const isExpanded = expandedIds.has(doc.id);
          const hasPreview = !!doc.content_preview;
          return (
            <div key={doc.id} className="dashboard-item-row">
              <div
                className="dashboard-item dashboard-item-link"
                style={{
                  display: 'flex',
                  gap: 'var(--space-sm)',
                  alignItems: 'flex-start',
                  cursor: 'pointer',
                }}
                onClick={() => openExternal(doc.web_view_link)}
              >
                <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                  <DocIcon />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">{doc.title}</div>
                  <div className="dashboard-item-meta">
                    {doc.owner_name || 'Unknown'}
                    {' '}&middot;{' '}
                    <TimeAgo date={doc.modified_time} />
                    {doc.word_count != null && ` \u00B7 ${doc.word_count.toLocaleString()} words`}
                  </div>
                  {isExpanded && hasPreview && (
                    <div className="dashboard-item-expanded">{doc.content_preview}</div>
                  )}
                </div>
              </div>
              {hasPreview && (
                <button
                  className="dashboard-expand-btn"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    toggleExpand(doc.id);
                  }}
                  title={isExpanded ? 'Collapse (e)' : 'Expand (e)'}
                >
                  {isExpanded ? '\u25BE' : '\u25B8'}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {docs.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open', 'e expand']} />
      )}
    </>
  );
}

// --- Sheets Tab ---

function SheetDetailModal({
  sheet,
  onClose,
}: {
  sheet: GoogleSheet;
  onClose: () => void;
}) {
  const [selectedTab, setSelectedTab] = useState(sheet.sheet_tabs[0]?.title || '');
  const { data: valuesData, isLoading } = useSheetValues(
    sheet.id,
    undefined,
    selectedTab || undefined
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content"
        style={{ maxWidth: 800, maxHeight: '80vh', overflow: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2 style={{ margin: 0 }}>{sheet.title}</h2>
            <div className="dashboard-item-meta" style={{ marginTop: 4 }}>
              {sheet.owner_name || 'Unknown'}
              {' '}&middot;{' '}
              <TimeAgo date={sheet.modified_time} />
              {sheet.sheet_tabs.length > 0 && ` \u00B7 ${sheet.sheet_tabs.length} tab${sheet.sheet_tabs.length !== 1 ? 's' : ''}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
            <a
              href={sheet.web_view_link}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-link"
            >
              Open in Sheets
            </a>
            <button onClick={onClose} className="btn-link">
              Close
            </button>
          </div>
        </div>

        {sheet.sheet_tabs.length > 1 && (
          <div className="day-filter" style={{ marginTop: 'var(--space-md)' }}>
            {sheet.sheet_tabs.map((t) => (
              <button
                key={t.title}
                className={`day-filter-btn${selectedTab === t.title ? ' day-filter-active' : ''}`}
                onClick={() => setSelectedTab(t.title)}
              >
                {t.title}
              </button>
            ))}
          </div>
        )}

        <div style={{ marginTop: 'var(--space-md)' }}>
          {isLoading && <p className="empty-state">Loading values...</p>}
          {valuesData?.values && valuesData.values.length > 0 ? (
            <div style={{ overflow: 'auto' }}>
              <table>
                <tbody>
                  {valuesData.values.slice(0, 20).map((row, ri) => (
                    <tr key={ri}>
                      {row.map((cell, ci) => {
                        const Tag = ri === 0 ? 'th' : 'td';
                        return <Tag key={ci}>{cell ?? ''}</Tag>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              {valuesData.values.length > 20 && (
                <p className="empty-state">
                  Showing first 20 of {valuesData.values.length} rows
                </p>
              )}
            </div>
          ) : (
            !isLoading && <p className="empty-state">No data in this tab</p>
          )}
        </div>
      </div>
    </div>
  );
}

function SheetsTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useSheets(days);
  const [selectedSheet, setSelectedSheet] = useState<GoogleSheet | null>(null);

  const sheets = data?.sheets ?? [];

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    onOpen: (i) => {
      if (sheets[i]) setSelectedSheet(sheets[i]);
    },
  });

  return (
    <>
      <div className="priorities-header" style={{ marginBottom: 'var(--space-sm)' }}>
        <span className="day-filter">
          {([7, 30, 90] as const).map((d) => (
            <button
              key={d}
              className={`day-filter-btn${days === d ? ' day-filter-active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </span>
      </div>

      {isLoading && <p className="empty-state">Loading sheets...</p>}
      {!isLoading && sheets.length === 0 && (
        <p className="empty-state">No Google Sheets in the last {days} days</p>
      )}

      <div ref={containerRef}>
        {sheets.map((sheet) => {
          const tabCount = sheet.sheet_tabs.length;
          const totalRows = sheet.sheet_tabs.reduce((sum, t) => sum + t.row_count, 0);
          return (
            <div key={sheet.id} className="dashboard-item-row">
              <div
                className="dashboard-item dashboard-item-link"
                style={{
                  display: 'flex',
                  gap: 'var(--space-sm)',
                  alignItems: 'flex-start',
                  cursor: 'pointer',
                }}
                onClick={() => setSelectedSheet(sheet)}
              >
                <div style={{ flexShrink: 0, paddingTop: '2px' }}>
                  <SheetIcon />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title">{sheet.title}</div>
                  <div className="dashboard-item-meta">
                    {sheet.owner_name || 'Unknown'}
                    {' '}&middot;{' '}
                    <TimeAgo date={sheet.modified_time} />
                    {tabCount > 0 && ` \u00B7 ${tabCount} tab${tabCount !== 1 ? 's' : ''}`}
                    {totalRows > 0 && ` \u00B7 ${totalRows.toLocaleString()} rows`}
                  </div>
                </div>
              </div>
              <a
                href={sheet.web_view_link}
                target="_blank"
                rel="noopener noreferrer"
                className="dashboard-expand-btn"
                title="Open in Sheets"
                onClick={(e) => e.stopPropagation()}
              >
                &#x2197;
              </a>
            </div>
          );
        })}
      </div>

      {sheets.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter preview']} />
      )}

      {selectedSheet && (
        <SheetDetailModal sheet={selectedSheet} onClose={() => setSelectedSheet(null)} />
      )}
    </>
  );
}

// --- Main Page ---

export function DrivePage() {
  const [tab, setTab] = useState<Tab>('Files');

  return (
    <div>
      <div className="priorities-header">
        <h1>Drive</h1>
        <div className="day-filter">
          {TABS.map((t, i) => (
            <button
              key={t}
              className={`day-filter-btn${tab === t ? ' day-filter-active' : ''}`}
              onClick={() => setTab(t)}
              title={`${t} (${i + 1})`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {tab === 'Files' && <FilesTab />}
      {tab === 'Docs' && <DocsTab />}
      {tab === 'Sheets' && <SheetsTab />}
    </div>
  );
}
