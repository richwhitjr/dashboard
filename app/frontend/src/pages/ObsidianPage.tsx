import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedObsidian, useRefreshPrioritizedObsidian, useAllObsidian, useObsidianVault, type AllTabSearchParams } from '../api/hooks';
import { openExternal } from '../api/client';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';
import { ObsidianNoteModal } from '../components/ObsidianNoteModal';

function obsidianUri(relativePath: string, vaultName: string): string {
  const file = encodeURIComponent(relativePath.replace(/\.md$/, ''));
  return `obsidian://open?vault=${encodeURIComponent(vaultName)}&file=${file}`;
}

export function ObsidianPage() {
  const [days, setDays] = useState(365);
  const { data, isLoading } = usePrioritizedObsidian(days);
  const { data: vaultConfig } = useObsidianVault();
  const vaultName = vaultConfig?.active_path ? vaultConfig.active_path.split('/').pop() ?? '' : '';
  const refresh = useRefreshPrioritizedObsidian(days);
  const [selectedNote, setSelectedNote] = useState<{
    id: string; title: string; relativePath: string;
    folder?: string | null; modifiedTime?: string; wordCount?: number; contentPreview?: string | null;
  } | null>(null);

  const [allSearchParams, setAllSearchParams] = useState<AllTabSearchParams>({});
  const allQuery = useAllObsidian(allSearchParams);
  const allNotes = useMemo(() => allQuery.data?.pages.flatMap(p => p.items) ?? [], [allQuery.data]);
  const allTotal = allQuery.data?.pages[0]?.total ?? 0;

  return (
    <>
      <PrioritizedSourceList
        title="Obsidian"
        source="obsidian"
        items={data?.items ?? []}
        isLoading={isLoading || (data?.stale === true && (data?.items ?? []).length === 0)}
        error={data?.error}
        stale={data?.stale}
        refresh={refresh}
        days={days}
        onDaysChange={setDays}
        itemNoun="note"
        dayOptions={[30, 90, 365]}
        getIssueTitle={(note) => note.title}
        onOpen={(note) => setSelectedNote({ id: note.id, title: note.title, relativePath: note.relative_path, folder: note.folder, modifiedTime: note.modified_time, wordCount: note.word_count, contentPreview: note.content_preview })}
        errorMessage={<p className="empty-state">Obsidian is not connected. Enable the Obsidian connector in <Link to="/settings">Settings</Link> and sync to see your notes.</p>}
        renderItem={(note, expanded) => (
          <div
            className="dashboard-item dashboard-item-link"
            style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: 'pointer' }}
            onClick={() => setSelectedNote({ id: note.id, title: note.title, relativePath: note.relative_path })}
          >
            <div style={{ flexShrink: 0, paddingTop: '2px' }}><ScoreBadge score={note.priority_score} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="dashboard-item-title" style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                <span>{note.title}</span>
                <a
                  href={obsidianUri(note.relative_path, vaultName)}
                  className="dashboard-item-meta"
                  style={{ fontSize: 'var(--text-xs)', opacity: 0.6, flexShrink: 0 }}
                  onClick={(e) => { e.stopPropagation(); e.preventDefault(); openExternal(obsidianUri(note.relative_path, vaultName)); }}
                  title="Open in Obsidian"
                >
                  open ↗
                </a>
              </div>
              <div className="dashboard-item-meta">
                {note.folder && <span>{note.folder} &middot; </span>}
                <TimeAgo date={note.modified_time} />
                {note.word_count > 0 && <span> &middot; {note.word_count.toLocaleString()} words</span>}
                {note.wiki_links && (
                  <span> &middot; {note.wiki_links.split(', ').length} link{note.wiki_links.split(', ').length !== 1 ? 's' : ''}</span>
                )}
              </div>
              {note.tags && (
                <div className="dashboard-item-meta">
                  {note.tags.split(', ').map(tag => (
                    <span key={tag} style={{ marginRight: '0.4em', opacity: 0.7 }}>#{tag}</span>
                  ))}
                </div>
              )}
              {expanded && note.content_preview && (
                <div className="dashboard-item-expanded">{note.content_preview}</div>
              )}
              {note.priority_reason && (
                <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{note.priority_reason}</div>
              )}
            </div>
          </div>
        )}
        allTab={{
          items: allNotes,
          total: allTotal,
          isLoading: allQuery.isLoading,
          hasNextPage: !!allQuery.hasNextPage,
          isFetchingNextPage: allQuery.isFetchingNextPage,
          fetchNextPage: allQuery.fetchNextPage,
          search: {
            hasDateFilter: true,
            onParamsChange: setAllSearchParams,
          },
          renderItem: (item, expanded) => {
            const note = item as (typeof allNotes)[0];
            return (
              <div
                className="dashboard-item dashboard-item-link"
                style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: 'pointer' }}
                onClick={() => setSelectedNote({ id: note.id, title: note.title, relativePath: note.relative_path, folder: note.folder, modifiedTime: note.modified_time, wordCount: note.word_count, contentPreview: note.content_preview })}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="dashboard-item-title" style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                    <span>{note.title}</span>
                    <a
                      href={obsidianUri(note.relative_path, vaultName)}
                      className="dashboard-item-meta"
                      style={{ fontSize: 'var(--text-xs)', opacity: 0.6, flexShrink: 0 }}
                      onClick={(e) => { e.stopPropagation(); e.preventDefault(); openExternal(obsidianUri(note.relative_path, vaultName)); }}
                      title="Open in Obsidian"
                    >
                      open ↗
                    </a>
                  </div>
                  <div className="dashboard-item-meta">
                    {note.folder && <span>{note.folder} &middot; </span>}
                    <TimeAgo date={note.modified_time} />
                    {note.word_count > 0 && <span> &middot; {note.word_count.toLocaleString()} words</span>}
                  </div>
                  {expanded && note.content_preview && (
                    <div className="dashboard-item-expanded">{note.content_preview}</div>
                  )}
                </div>
              </div>
            );
          },
        }}
      />
      {selectedNote && (
        <ObsidianNoteModal
          noteId={selectedNote.id}
          title={selectedNote.title}
          relativePath={selectedNote.relativePath}
          folder={selectedNote.folder}
          modifiedTime={selectedNote.modifiedTime}
          wordCount={selectedNote.wordCount}
          contentPreview={selectedNote.contentPreview}
          onClose={() => setSelectedNote(null)}
        />
      )}
    </>
  );
}
