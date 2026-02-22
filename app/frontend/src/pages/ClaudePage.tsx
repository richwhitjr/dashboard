import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { TimeAgo } from '../components/shared/TimeAgo';
import { MarkdownRenderer } from '../components/shared/MarkdownRenderer';
import { ClaudeTerminal } from '../components/ClaudeTerminal';
import type { ClaudeTerminalHandle } from '../components/ClaudeTerminal';
import {
  useClaudeSessions,
  useClaudeSessionContent,
  useSaveClaudeSession,
  useDeleteClaudeSession,
  useCreateNoteFromSession,
  usePersonas,
} from '../api/hooks';

interface Tab {
  id: string;
  label: string;
  personaId?: number;
  personaName?: string;
}

function generateTitle(plainText: string): string {
  const lines = plainText.split('\n').filter((l) => l.trim());
  for (const line of lines) {
    const trimmed = line.trim();
    if ((trimmed.startsWith('> ') || trimmed.startsWith('\u276F ')) && trimmed.length > 3) {
      return trimmed.slice(2).slice(0, 60);
    }
  }
  return `Session ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

let nextTabId = 2;

export function ClaudePage({ visible, overlayOpen }: { visible: boolean; overlayOpen?: boolean }) {
  const [tabs, setTabs] = useState<Tab[]>([{ id: '1', label: 'Session 1' }]);
  const [activeTabId, setActiveTabId] = useState('1');
  const [tabStatus, setTabStatus] = useState<Map<string, string>>(new Map([['1', 'connecting']]));
  const terminalRefs = useRef<Map<string, ClaudeTerminalHandle>>(new Map());
  const tabCounterRef = useRef(1);

  const [panelOpen, setPanelOpen] = useState(false);
  const [viewingSessionId, setViewingSessionId] = useState<number | null>(null);
  const [sessionTitle, setSessionTitle] = useState('');

  const { data: sessions } = useClaudeSessions();
  const { data: sessionContent } = useClaudeSessionContent(viewingSessionId);
  const saveSession = useSaveClaudeSession();
  const deleteSession = useDeleteClaudeSession();
  const createNoteFromSession = useCreateNoteFromSession();
  const { data: personas } = usePersonas();
  const [showPersonaPicker, setShowPersonaPicker] = useState(false);
  const personaPickerRef = useRef<HTMLDivElement>(null);

  const location = useLocation();
  const navigate = useNavigate();
  const [pendingPersonaId, setPendingPersonaId] = useState<number | null>(null);

  // Parse query params reactively (ClaudePage is always mounted, so mount-only won't work)
  useEffect(() => {
    const params = new URLSearchParams(location.search);

    const sessionParam = params.get('session');
    if (sessionParam) {
      const sessionId = parseInt(sessionParam, 10);
      if (!isNaN(sessionId)) {
        setViewingSessionId(sessionId);
        setPanelOpen(true);
      }
      navigate('/claude', { replace: true });
      return;
    }

    const personaParam = params.get('persona');
    if (personaParam) {
      const personaId = parseInt(personaParam, 10);
      if (!isNaN(personaId)) {
        setPendingPersonaId(personaId);
      }
      navigate('/claude', { replace: true });
    }
  }, [location.search, navigate]);

  // Create tab when pending persona resolves with loaded persona data
  useEffect(() => {
    if (pendingPersonaId === null) return;
    if (!personas) return;

    const persona = personas.find((p) => p.id === pendingPersonaId);
    setPendingPersonaId(null);

    const isDefault = !persona || persona.name === 'Default';
    const pId = isDefault ? undefined : persona.id;
    const pName = isDefault ? undefined : persona.name;

    tabCounterRef.current += 1;
    const id = String(nextTabId++);
    const label = pName ? `${pName} ${tabCounterRef.current}` : `Session ${tabCounterRef.current}`;
    setTabs((prev) => [...prev, { id, label, personaId: pId, personaName: pName }]);
    setActiveTabId(id);
    setTabStatus((prev) => {
      const next = new Map(prev);
      next.set(id, 'connecting');
      return next;
    });
  }, [pendingPersonaId, personas]);

  const updateTabStatus = useCallback((tabId: string, status: string) => {
    setTabStatus((prev) => {
      const next = new Map(prev);
      next.set(tabId, status);
      return next;
    });
  }, []);

  // Close persona picker on click outside
  useEffect(() => {
    if (!showPersonaPicker) return;
    function handleClickOutside(e: MouseEvent) {
      if (personaPickerRef.current && !personaPickerRef.current.contains(e.target as Node)) {
        setShowPersonaPicker(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showPersonaPicker]);

  function addTabWithPersona(personaId?: number, personaName?: string) {
    tabCounterRef.current += 1;
    const id = String(nextTabId++);
    const label = personaName
      ? `${personaName} ${tabCounterRef.current}`
      : `Session ${tabCounterRef.current}`;
    setTabs((prev) => [...prev, { id, label, personaId, personaName }]);
    setActiveTabId(id);
    setTabStatus((prev) => {
      const next = new Map(prev);
      next.set(id, 'connecting');
      return next;
    });
    setShowPersonaPicker(false);
  }

  function closeTab(tabId: string) {
    setTabs((prev) => {
      if (prev.length <= 1) {
        // Last tab — create a new one, then remove the old
        tabCounterRef.current += 1;
        const newId = String(nextTabId++);
        const newLabel = `Session ${tabCounterRef.current}`;
        setActiveTabId(newId);
        setTabStatus((s) => {
          const next = new Map(s);
          next.delete(tabId);
          next.set(newId, 'connecting');
          return next;
        });
        return [{ id: newId, label: newLabel }];
      }

      const idx = prev.findIndex((t) => t.id === tabId);
      const next = prev.filter((t) => t.id !== tabId);

      if (tabId === activeTabId) {
        // Switch to nearest neighbor
        const newIdx = Math.min(idx, next.length - 1);
        setActiveTabId(next[newIdx].id);
        setTimeout(() => terminalRefs.current.get(next[newIdx].id)?.focus(), 50);
      }

      setTabStatus((s) => {
        const updated = new Map(s);
        updated.delete(tabId);
        return updated;
      });

      return next;
    });

    // Cleanup ref
    terminalRefs.current.delete(tabId);
  }

  function switchTab(tabId: string) {
    setActiveTabId(tabId);
    setViewingSessionId(null);
    setTimeout(() => terminalRefs.current.get(tabId)?.focus(), 50);
  }

  function handleSave() {
    const handle = terminalRefs.current.get(activeTabId);
    if (!handle) return;

    const data = handle.serialize();
    if (!data) {
      console.warn('Cannot save: terminal not available');
      return;
    }

    const title = sessionTitle || generateTitle(data.plainText);

    saveSession.mutate({
      title,
      content: data.content,
      plain_text: data.plainText,
      rows: data.rows,
      cols: data.cols,
    }, {
      onSuccess: () => {
        setSessionTitle('');
      },
    });
  }

  function handleViewSession(id: number) {
    setViewingSessionId(id);
  }

  function handleBackToTerminal() {
    setViewingSessionId(null);
    setTimeout(() => {
      terminalRefs.current.get(activeTabId)?.fit();
      terminalRefs.current.get(activeTabId)?.focus();
    }, 50);
  }

  function handleDeleteSession(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    deleteSession.mutate(id);
    if (viewingSessionId === id) {
      handleBackToTerminal();
    }
  }

  function handleCreateNote(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    createNoteFromSession.mutate(id, {
      onError: (error: Error) => {
        if (error?.message?.includes('already exists')) return;
        console.error('Failed to create note:', error);
      },
    });
  }

  const activeStatus = tabStatus.get(activeTabId);

  return (
    <div className="claude-page">
      <div className="claude-header">
        <div className="claude-header-left">
          <button
            className="claude-panel-toggle"
            onClick={() => setPanelOpen(!panelOpen)}
            title="Toggle session history"
          >
            {panelOpen ? '\u2039' : '\u203A'}
          </button>
          {viewingSessionId ? (
            <span className="claude-viewing-label">
              {sessions?.find((s) => s.id === viewingSessionId)?.title || 'Saved session'}
            </span>
          ) : (
            <input
              className="claude-session-title-input"
              placeholder="Session title..."
              value={sessionTitle}
              onChange={(e) => setSessionTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.currentTarget.blur();
                  terminalRefs.current.get(activeTabId)?.focus();
                }
              }}
            />
          )}
        </div>
        <div className="claude-status">
          {viewingSessionId ? (
            <button className="auth-action-btn" onClick={handleBackToTerminal}>
              Back to Terminal
            </button>
          ) : (
            <>
              {activeStatus === 'connected' && <span className="status-ok">connected</span>}
              <button
                className="auth-action-btn"
                onClick={handleSave}
                disabled={saveSession.isPending}
              >
                {saveSession.isPending ? 'Saving...' : 'Save'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="claude-tab-bar">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`claude-tab${tab.id === activeTabId ? ' active' : ''}`}
            onClick={() => switchTab(tab.id)}
          >
            {tab.personaId && (() => {
              const p = personas?.find((p) => p.id === tab.personaId);
              return p?.avatar_filename ? (
                <img
                  src={`/api/personas/${p.id}/avatar`}
                  alt=""
                  className="persona-avatar-sm"
                />
              ) : p ? (
                <span className="persona-avatar-placeholder-sm">
                  {p.name.charAt(0).toUpperCase()}
                </span>
              ) : null;
            })()}
            <span className="claude-tab-label">{tab.label}</span>
            <button
              className="claude-tab-close"
              onClick={(e) => { e.stopPropagation(); closeTab(tab.id); }}
              title="Close tab"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          className="claude-tab-new"
          onClick={() => addTabWithPersona()}
          title="New session"
        >
          +
        </button>
        <div className="claude-tab-new-wrapper" ref={personaPickerRef}>
          <button
            className="claude-tab-persona-trigger"
            onClick={() => setShowPersonaPicker(!showPersonaPicker)}
            title="New session with persona"
          >
            &#9662;
          </button>
          {showPersonaPicker && (
            <div className="claude-persona-picker">
              {personas?.filter((p) => p.name !== 'Default').map((p) => (
                <button
                  key={p.id}
                  className="claude-persona-option"
                  onClick={() => addTabWithPersona(p.id, p.name)}
                >
                  {p.avatar_filename ? (
                    <img
                      src={`/api/personas/${p.id}/avatar`}
                      alt=""
                      className="persona-avatar"
                      style={{ width: 28, height: 28 }}
                    />
                  ) : (
                    <span
                      className="persona-avatar-placeholder"
                      style={{ width: 28, height: 28, fontSize: 13 }}
                    >
                      {p.name.charAt(0).toUpperCase()}
                    </span>
                  )}
                  <span className="claude-persona-info">
                    <span className="claude-persona-name">{p.name}</span>
                    {p.description && (
                      <span className="claude-persona-desc">{p.description}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="claude-body">
        {panelOpen && (
          <div className="claude-sessions-panel">
            <h3>History</h3>
            <div className="claude-sessions-list">
              {sessions?.map((s) => (
                <div
                  key={s.id}
                  className={`claude-session-item${viewingSessionId === s.id ? ' active' : ''}`}
                  onClick={() => handleViewSession(s.id)}
                >
                  <div className="claude-session-item-title">{s.title}</div>
                  <div className="claude-session-item-meta">
                    <TimeAgo date={s.created_at} />
                  </div>
                  {s.preview && (
                    <div className="claude-session-item-preview">{s.preview}</div>
                  )}
                  <button
                    className="claude-session-note-btn"
                    onClick={(e) => handleCreateNote(s.id, e)}
                    title="Create note from session"
                    disabled={createNoteFromSession.isPending}
                  >
                    📝
                  </button>
                  <button
                    className="claude-session-delete"
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    title="Delete session"
                  >
                    &times;
                  </button>
                </div>
              ))}
              {(!sessions || sessions.length === 0) && (
                <div className="claude-sessions-empty">No saved sessions</div>
              )}
            </div>
          </div>
        )}

        <div className="claude-main-area">
          {/* All terminals mounted, only active visible */}
          {tabs.map((tab) => (
            <ClaudeTerminal
              key={tab.id}
              ref={(handle) => {
                if (handle) terminalRefs.current.set(tab.id, handle);
                else terminalRefs.current.delete(tab.id);
              }}
              visible={tab.id === activeTabId && !viewingSessionId && visible}
              overlayOpen={overlayOpen}
              personaId={tab.personaId}
              onConnected={() => updateTabStatus(tab.id, 'connected')}
              onDisconnected={() => updateTabStatus(tab.id, 'disconnected')}
            />
          ))}

          {/* Session viewer — shown when viewing a saved session */}
          {viewingSessionId && sessionContent && (
            <div className="claude-session-viewer">
              <MarkdownRenderer content={sessionContent.summary || sessionContent.plain_text || 'No content available.'} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
