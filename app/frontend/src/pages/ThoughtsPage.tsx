import { useState, useRef, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  useNotes,
  useCreateNote,
  useUpdateNote,
  useDeleteNote,
  useCreateIssue,
} from '../api/hooks';
import type { Note } from '../api/types';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';

function isThought(note: Note): boolean {
  return note.text.startsWith('[t]') || note.text.startsWith('[T]');
}

function ThoughtItem({
  note,
  onToggle,
  onDelete,
  onUpdate,
}: {
  note: Note;
  onToggle: () => void;
  onDelete: () => void;
  onUpdate: (text: string) => void;
}) {
  // Strip the [t] prefix for display
  const displayText = note.text.replace(/^\[[tT]\]\s*/, '');
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(displayText);
  const editRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing && editRef.current) {
      editRef.current.focus();
      editRef.current.selectionStart = editRef.current.value.length;
    }
  }, [editing]);

  const saveEdit = () => {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== displayText) {
      // Re-add [t] prefix when saving
      onUpdate(`[t] ${trimmed}`);
    }
    setEditing(false);
  };

  return (
    <div
      id={`note-${note.id}`}
      className={`note-item dashboard-item-row ${note.status === 'done' ? 'done' : ''}`}
    >
      <input
        type="checkbox"
        checked={note.status === 'done'}
        onChange={onToggle}
      />
      <div className="note-text">
        {editing ? (
          <textarea
            ref={editRef}
            className="note-input"
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(); }
              if (e.key === 'Escape') { setEditText(displayText); setEditing(false); }
            }}
            onBlur={saveEdit}
            rows={2}
            style={{
              width: '100%',
              fontSize: 'inherit',
              padding: '2px 4px',
              fontFamily: 'var(--font-body)',
              resize: 'vertical',
            }}
          />
        ) : (
          <div onDoubleClick={() => { setEditText(displayText); setEditing(true); }} style={{ cursor: 'text' }}>
            {displayText}
          </div>
        )}
        <div className="note-meta">
          {note.employee_name && (
            <a href={`/employees/${note.employee_id}`}>{note.employee_name}</a>
          )}
          <span style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
            {new Date(note.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>
      <button
        onClick={onDelete}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--color-text-light)',
          cursor: 'pointer',
          fontSize: 'var(--text-xs)',
        }}
      >
        &times;
      </button>
    </div>
  );
}

export function ThoughtsPage() {
  const [text, setText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('open');
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: notes, isLoading } = useNotes({ status: statusFilter || undefined });
  const createNote = useCreateNote();
  const updateNote = useUpdateNote();
  const deleteNote = useDeleteNote();
  const createIssue = useCreateIssue();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const thoughts = useMemo(() => notes?.filter(isThought) ?? [], [notes]);

  // Keyboard navigation callbacks
  const handleToggleAtIndex = (index: number) => {
    const thought = thoughts[index];
    if (thought) {
      updateNote.mutate({
        id: thought.id,
        status: thought.status === 'done' ? 'open' : 'done',
      });
    }
  };

  const handleEditAtIndex = (index: number) => {
    const thought = thoughts[index];
    if (thought) {
      // Trigger double-click behavior to start editing
      const el = document.getElementById(`note-${thought.id}`);
      const textDiv = el?.querySelector('.note-text > div');
      if (textDiv) {
        (textDiv as HTMLElement).dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      }
    }
  };

  const handleCreateIssueAtIndex = (index: number) => {
    const thought = thoughts[index];
    if (thought) {
      const strippedText = thought.text.replace(/^\[[tT]\]\s*/, '');
      createIssue.mutate({
        title: strippedText,
        employee_ids: thought.employee_id ? [thought.employee_id] : undefined,
      });
    }
  };

  const { containerRef } = useFocusNavigation({
    selector: '.dashboard-item-row',
    enabled: !isLoading,
    onDismiss: handleToggleAtIndex,
    onOpen: handleEditAtIndex,
    onExpand: handleEditAtIndex,
    onCreateIssue: handleCreateIssueAtIndex,
  });

  // Deep-link: scroll to and highlight a specific thought from search
  useEffect(() => {
    const noteId = searchParams.get('noteId');
    if (noteId && thoughts.length > 0) {
      const thoughtInView = thoughts.find((n) => String(n.id) === noteId);
      if (!thoughtInView && statusFilter !== '') {
        setStatusFilter('');
        return;
      }
      setTimeout(() => {
        const el = document.getElementById(`note-${noteId}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('search-highlight');
          setTimeout(() => el.classList.remove('search-highlight'), 3000);
          setSearchParams({}, { replace: true });
        }
      }, 100);
    }
  }, [searchParams, thoughts, statusFilter, setSearchParams]);

  // Auto-focus input when arriving via search (focus=1 param)
  useEffect(() => {
    if (searchParams.get('focus')) {
      setSearchParams({}, { replace: true });
      setTimeout(() => inputRef.current?.focus(), 100);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    // Auto-prefix with [t] so it's tagged as a thought
    const noteText = `[t] ${text.trim()}`;
    createNote.mutate({ text: noteText });
    setText('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div ref={containerRef}>
      <h1>Thoughts</h1>

      <div className="filters" style={{ marginBottom: 'var(--space-lg)' }}>
        {['open', 'done', ''].map((s) => (
          <button
            key={s}
            className={`filter-btn ${statusFilter === s ? 'active' : ''}`}
            onClick={() => setStatusFilter(s)}
          >
            {s || 'all'}
          </button>
        ))}
      </div>

      {isLoading && <p className="empty-state">Loading...</p>}

      {thoughts.map((note) => (
        <ThoughtItem
          key={note.id}
          note={note}
          onToggle={() =>
            updateNote.mutate({
              id: note.id,
              status: note.status === 'done' ? 'open' : 'done',
            })
          }
          onDelete={() => deleteNote.mutate(note.id)}
          onUpdate={(text) => updateNote.mutate({ id: note.id, text })}
        />
      ))}

      {thoughts.length === 0 && !isLoading && (
        <p className="empty-state">
          {statusFilter === 'open' ? 'No open thoughts.' : 'No thoughts found.'}
        </p>
      )}

      <div style={{ marginTop: 'var(--space-xl)' }}>
        <h2>Add a thought</h2>
        <form onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            className="note-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What's on your mind?"
            rows={3}
            style={{
              width: '100%',
              resize: 'vertical',
              fontFamily: 'var(--font-body)',
              fontSize: 'var(--text-base)',
              padding: 'var(--space-sm) var(--space-md)',
              border: '1px solid var(--color-border)',
              borderRadius: '4px',
              background: 'var(--color-bg)',
            }}
          />
          <button
            type="submit"
            disabled={!text.trim() || createNote.isPending}
            style={{
              marginTop: 'var(--space-sm)',
              padding: 'var(--space-xs) var(--space-md)',
              fontSize: 'var(--text-sm)',
            }}
          >
            {createNote.isPending ? 'Saving...' : 'Save thought'}
          </button>
        </form>
      </div>

      {thoughts.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter edit', 'e edit', 'd done', 'i create issue']} />
      )}
    </div>
  );
}
