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
  useCreateLongformFromSession,
  usePersonas,
  useCreatePersona,
  useUpdatePersona,
  useDeletePersona,
  useUploadPersonaAvatar,
} from '../api/hooks';
import { api } from '../api/client';
import type { Issue, LongformPostDetail } from '../api/types';

interface Tab {
  id: string;
  label: string;
  personaId?: number;
  personaName?: string;
  initialPrompt?: string;
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
  const [panelTab, setPanelTab] = useState<'history' | 'personas'>('history');
  const [viewingSessionId, setViewingSessionId] = useState<number | null>(null);
  const [sessionTitle, setSessionTitle] = useState('');

  const { data: sessions } = useClaudeSessions();
  const { data: sessionContent } = useClaudeSessionContent(viewingSessionId);
  const saveSession = useSaveClaudeSession();
  const deleteSession = useDeleteClaudeSession();
  const createNoteFromSession = useCreateNoteFromSession();
  const { data: personas } = usePersonas();
  const createPersona = useCreatePersona();
  const updatePersona = useUpdatePersona();
  const deletePersona = useDeletePersona();
  const uploadAvatar = useUploadPersonaAvatar();
  const [showPersonaPicker, setShowPersonaPicker] = useState(false);
  const [personaCreateForm, setPersonaCreateForm] = useState({ name: '', description: '', system_prompt: '' });
  const [editingPersonaId, setEditingPersonaId] = useState<number | null>(null);
  const [personaEditForm, setPersonaEditForm] = useState({ name: '', description: '', system_prompt: '' });
  const personaPickerRef = useRef<HTMLDivElement>(null);

  const location = useLocation();
  const navigate = useNavigate();
  const [pendingPersonaId, setPendingPersonaId] = useState<number | null>(null);
  const [pendingIssueId, setPendingIssueId] = useState<number | null>(null);
  const [pendingLongformId, setPendingLongformId] = useState<number | null>(null);
  const createLongformFromSession = useCreateLongformFromSession();

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
      return;
    }

    const issueParam = params.get('issue');
    if (issueParam) {
      const issueId = parseInt(issueParam, 10);
      if (!isNaN(issueId)) {
        setPendingIssueId(issueId);
      }
      navigate('/claude', { replace: true });
      return;
    }

    const longformParam = params.get('longform');
    if (longformParam) {
      const longformId = parseInt(longformParam, 10);
      if (!isNaN(longformId)) {
        setPendingLongformId(longformId);
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

  // Create tab when pending issue is set — fetch issue and build prompt
  useEffect(() => {
    if (pendingIssueId === null) return;
    setPendingIssueId(null);

    api.get<Issue>(`/issues/${pendingIssueId}`).then((issue) => {
      let prompt = `I want to work on this issue:\n\nTitle: ${issue.title}`;
      if (issue.description) prompt += `\nDescription: ${issue.description}`;
      prompt += `\nPriority: P${issue.priority} | Size: ${issue.tshirt_size.toUpperCase()} | Status: ${issue.status}`;
      if (issue.tags?.length) prompt += `\nTags: ${issue.tags.join(', ')}`;
      if (issue.people?.length) prompt += `\nPeople: ${issue.people.map((p) => p.name).join(', ')}`;
      prompt += `\n\nPlease help me think through and work on this issue.`;

      tabCounterRef.current += 1;
      const id = String(nextTabId++);
      const label = `Issue: ${issue.title.slice(0, 30)}`;
      setTabs((prev) => [...prev, { id, label, initialPrompt: prompt }]);
      setActiveTabId(id);
      setTabStatus((prev) => {
        const next = new Map(prev);
        next.set(id, 'connecting');
        return next;
      });
    }).catch((err) => {
      console.error('Failed to fetch issue for Claude:', err);
    });
  }, [pendingIssueId]);

  // Create tab when pending longform post is set — fetch post and build prompt
  useEffect(() => {
    if (pendingLongformId === null) return;
    setPendingLongformId(null);

    api.get<LongformPostDetail>(`/docs/${pendingLongformId}`).then((post) => {
      let prompt = `I have a doc I'd like help with:\n\n# ${post.title}\n\n`;
      if (post.body) {
        const bodyPreview = post.body.length > 3000 ? post.body.slice(0, 3000) + '\n\n...(truncated)' : post.body;
        prompt += bodyPreview;
      }
      prompt += `\n\nStatus: ${post.status} | ${post.word_count} words`;
      if (post.tags?.length) prompt += ` | Tags: ${post.tags.join(', ')}`;
      prompt += `\n\nPlease help me improve and refine this doc.`;

      tabCounterRef.current += 1;
      const id = String(nextTabId++);
      const label = `Post: ${post.title.slice(0, 30)}`;
      setTabs((prev) => [...prev, { id, label, initialPrompt: prompt }]);
      setActiveTabId(id);
      setTabStatus((prev) => {
        const next = new Map(prev);
        next.set(id, 'connecting');
        return next;
      });
    }).catch((err) => {
      console.error('Failed to fetch longform post for Claude:', err);
    });
  }, [pendingLongformId]);

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
      } else {
        // Refocus the active terminal — the close button stole focus
        setTimeout(() => terminalRefs.current.get(activeTabId)?.focus(), 50);
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
        <div className="claude-tab-new-wrapper" ref={personaPickerRef}>
          <button
            className="claude-tab-new"
            onClick={() => setShowPersonaPicker(!showPersonaPicker)}
            title="New session"
          >
            +
          </button>
          {showPersonaPicker && (
            <div className="claude-persona-picker">
              <button
                className="claude-persona-option"
                onClick={() => addTabWithPersona()}
              >
                <span
                  className="persona-avatar-placeholder"
                  style={{ width: 28, height: 28, fontSize: 13 }}
                >
                  +
                </span>
                <span className="claude-persona-info">
                  <span className="claude-persona-name">New Session</span>
                  <span className="claude-persona-desc">Default assistant</span>
                </span>
              </button>
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
            <div className="github-tabs" style={{ marginBottom: 'var(--space-sm)' }}>
              <button className={`github-tab ${panelTab === 'history' ? 'active' : ''}`} onClick={() => setPanelTab('history')}>History</button>
              <button className={`github-tab ${panelTab === 'personas' ? 'active' : ''}`} onClick={() => setPanelTab('personas')}>Personas</button>
            </div>

            {panelTab === 'history' && (
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
                      className="claude-session-note-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        createLongformFromSession.mutate(s.id, {
                          onSuccess: (post) => {
                            navigate(`/docs?postId=${post.id}`);
                          },
                        });
                      }}
                      title="Save as doc"
                      disabled={createLongformFromSession.isPending}
                    >
                      📄
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
            )}

            {panelTab === 'personas' && (
              <div className="claude-sessions-list">
                {personas?.map((persona) => (
                  <div key={persona.id} className="claude-session-item" style={{ cursor: 'default' }}>
                    {editingPersonaId === persona.id ? (
                      <form onSubmit={(e) => {
                        e.preventDefault();
                        updatePersona.mutate({ id: persona.id, ...personaEditForm }, {
                          onSuccess: () => setEditingPersonaId(null),
                        });
                      }}>
                        <input
                          type="text"
                          value={personaEditForm.name}
                          onChange={(e) => setPersonaEditForm({ ...personaEditForm, name: e.target.value })}
                          placeholder="Name"
                          className="note-input"
                          style={{ marginBottom: 'var(--space-xs)', fontSize: 'var(--text-sm)' }}
                          required
                        />
                        <input
                          type="text"
                          value={personaEditForm.description}
                          onChange={(e) => setPersonaEditForm({ ...personaEditForm, description: e.target.value })}
                          placeholder="Description"
                          className="note-input"
                          style={{ marginBottom: 'var(--space-xs)', fontSize: 'var(--text-sm)' }}
                        />
                        <textarea
                          value={personaEditForm.system_prompt}
                          onChange={(e) => setPersonaEditForm({ ...personaEditForm, system_prompt: e.target.value })}
                          placeholder="System prompt..."
                          className="note-input"
                          style={{ minHeight: 80, fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', resize: 'vertical' }}
                        />
                        <div style={{ display: 'flex', gap: 'var(--space-xs)', marginTop: 'var(--space-xs)' }}>
                          <button type="submit" className="auth-action-btn" style={{ fontSize: 'var(--text-xs)' }} disabled={updatePersona.isPending}>Save</button>
                          <button type="button" className="auth-action-btn" style={{ fontSize: 'var(--text-xs)' }} onClick={() => setEditingPersonaId(null)}>Cancel</button>
                        </div>
                      </form>
                    ) : (
                      <>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
                          <label className="persona-avatar-upload" style={{ cursor: 'pointer', position: 'relative' }}>
                            {persona.avatar_filename ? (
                              <img src={`/api/personas/${persona.id}/avatar`} alt="" className="persona-avatar" style={{ width: 32, height: 32 }} />
                            ) : (
                              <span className="persona-avatar-placeholder" style={{ width: 32, height: 32, fontSize: 14 }}>{persona.name.charAt(0).toUpperCase()}</span>
                            )}
                            <input
                              type="file"
                              accept="image/png,image/jpeg,image/webp,image/gif"
                              style={{ display: 'none' }}
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) uploadAvatar.mutate({ id: persona.id, file });
                                e.target.value = '';
                              }}
                            />
                          </label>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="claude-session-item-title">{persona.name}</div>
                            {persona.description && (
                              <div className="claude-session-item-meta">{persona.description}</div>
                            )}
                          </div>
                        </div>
                        {persona.system_prompt && (
                          <div className="claude-session-item-preview" style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                            {persona.system_prompt.slice(0, 150)}{persona.system_prompt.length > 150 ? '...' : ''}
                          </div>
                        )}
                        <div style={{ display: 'flex', gap: 'var(--space-xs)', marginTop: 'var(--space-xs)' }}>
                          <button
                            className="auth-action-btn"
                            style={{ fontSize: 'var(--text-xs)' }}
                            onClick={() => {
                              setEditingPersonaId(persona.id);
                              setPersonaEditForm({ name: persona.name, description: persona.description, system_prompt: persona.system_prompt });
                            }}
                          >
                            Edit
                          </button>
                          {!persona.is_default && (
                            <button
                              className="auth-action-btn"
                              style={{ fontSize: 'var(--text-xs)', color: 'var(--color-accent)' }}
                              onClick={() => deletePersona.mutate(persona.id)}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}

                {/* Create new persona form */}
                <div className="claude-session-item" style={{ cursor: 'default' }}>
                  <form onSubmit={(e) => {
                    e.preventDefault();
                    if (!personaCreateForm.name.trim()) return;
                    createPersona.mutate(personaCreateForm, {
                      onSuccess: () => setPersonaCreateForm({ name: '', description: '', system_prompt: '' }),
                    });
                  }}>
                    <input
                      type="text"
                      value={personaCreateForm.name}
                      onChange={(e) => setPersonaCreateForm({ ...personaCreateForm, name: e.target.value })}
                      placeholder="New persona name..."
                      className="note-input"
                      style={{ marginBottom: 'var(--space-xs)', fontSize: 'var(--text-sm)' }}
                      required
                    />
                    {personaCreateForm.name && (
                      <>
                        <input
                          type="text"
                          value={personaCreateForm.description}
                          onChange={(e) => setPersonaCreateForm({ ...personaCreateForm, description: e.target.value })}
                          placeholder="Short description"
                          className="note-input"
                          style={{ marginBottom: 'var(--space-xs)', fontSize: 'var(--text-sm)' }}
                        />
                        <textarea
                          value={personaCreateForm.system_prompt}
                          onChange={(e) => setPersonaCreateForm({ ...personaCreateForm, system_prompt: e.target.value })}
                          placeholder="System prompt..."
                          className="note-input"
                          style={{ minHeight: 80, fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', resize: 'vertical' }}
                        />
                        <button type="submit" className="auth-action-btn" style={{ fontSize: 'var(--text-xs)', marginTop: 'var(--space-xs)' }} disabled={createPersona.isPending}>
                          {createPersona.isPending ? 'Creating...' : 'Create'}
                        </button>
                      </>
                    )}
                  </form>
                </div>
              </div>
            )}
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
              initialPrompt={tab.initialPrompt}
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
