import { useState, useRef, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useAgentConversations,
  useAgentMessages,
  useCreateAgentConversation,
  useUpdateAgentConversation,
  useDeleteAgentConversation,
  useSaveAgentConversation,
  useCreateLongformFromAgentConversation,
} from '../api/hooks';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { MarkdownRenderer } from '../components/shared/MarkdownRenderer';
import { TimeAgo } from '../components/shared/TimeAgo';
import type { AgentMessage, AgentToolCall } from '../api/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Tab {
  id: string;
  convId: number | null;
  label: string;
  saved: boolean;
}

interface StreamingToolCall {
  name: string;
  input: Record<string, unknown>;
  result?: string;
}

interface StreamingState {
  text: string;
  toolCalls: StreamingToolCall[];
  isStreaming: boolean;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ToolCallDisplay({ tc, defaultExpanded }: { tc: AgentToolCall | StreamingToolCall; defaultExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);
  return (
    <div className="agent-tool-call">
      <button className="agent-tool-call-toggle" onClick={() => setExpanded(!expanded)}>
        <span className="agent-tool-call-icon">{expanded ? '\u25BE' : '\u25B8'}</span>
        <span className="agent-tool-call-name">{tc.name}</span>
        {tc.result === undefined && <span className="agent-tool-call-spinner" />}
      </button>
      {expanded && (
        <div className="agent-tool-call-detail">
          <pre>{JSON.stringify(tc.input, null, 2)}</pre>
          {tc.result !== undefined && (
            <pre className="agent-tool-call-result-pre">
              {typeof tc.result === 'string' && tc.result.length > 500
                ? tc.result.slice(0, 500) + '...'
                : tc.result}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: AgentMessage }) {
  const isUser = msg.role === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(msg.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className={`agent-message ${isUser ? 'agent-message-user' : 'agent-message-assistant'}`}>
      <div className="agent-message-role">{isUser ? 'You' : 'Agent'}</div>
      {!isUser && msg.tool_calls && msg.tool_calls.length > 0 && (
        <div className="agent-tool-calls">
          {msg.tool_calls.map((tc, i) => (
            <ToolCallDisplay key={i} tc={tc} />
          ))}
        </div>
      )}
      <div className="agent-message-content">
        {isUser ? <p>{msg.content}</p> : <MarkdownRenderer content={msg.content} />}
      </div>
      <button
        className="agent-message-copy"
        onClick={handleCopy}
        title="Copy"
      >
        {copied ? '✓' : '⎘'}
      </button>
    </div>
  );
}

function StreamingBubble({ state }: { state: StreamingState }) {
  return (
    <div className="agent-message agent-message-assistant">
      <div className="agent-message-role">Agent</div>
      {state.toolCalls.length > 0 && (
        <div className="agent-tool-calls">
          {state.toolCalls.map((tc, i) => (
            <ToolCallDisplay key={i} tc={tc} defaultExpanded={i === state.toolCalls.length - 1 && tc.result === undefined} />
          ))}
        </div>
      )}
      {state.text ? (
        <div className="agent-message-content">
          <MarkdownRenderer content={state.text} />
        </div>
      ) : state.toolCalls.length === 0 ? (
        <div className="agent-typing-indicator">
          <span /><span /><span />
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'agent-tabs';

function loadPersistedTabs(): { tabs: Tab[]; activeTabId: string | null; nextId: number } {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const data = JSON.parse(raw);
      return { tabs: data.tabs ?? [], activeTabId: data.activeTabId ?? null, nextId: data.nextId ?? 1 };
    }
  } catch { /* ignore */ }
  return { tabs: [], activeTabId: null, nextId: 1 };
}

function persistTabs(tabs: Tab[], activeTabId: string | null, nextId: number) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ tabs, activeTabId, nextId }));
  } catch { /* ignore */ }
}

let nextTabId = loadPersistedTabs().nextId;

function buildMarkdown(messages: AgentMessage[]): string {
  return messages
    .map((m) => `**${m.role === 'user' ? 'You' : 'Agent'}:** ${m.content}`)
    .join('\n\n---\n\n');
}

export function AgentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: savedConversations } = useAgentConversations();
  const createConversation = useCreateAgentConversation();
  const updateConversation = useUpdateAgentConversation();
  const deleteConversation = useDeleteAgentConversation();
  const saveConversation = useSaveAgentConversation();
  const createLongformFromConv = useCreateLongformFromAgentConversation();
  const [copyLabel, setCopyLabel] = useState<'Copy' | 'Copied!'>('Copy');

  const persisted = loadPersistedTabs();
  const [tabs, setTabs] = useState<Tab[]>(persisted.tabs);
  const [activeTabId, setActiveTabId] = useState<string | null>(persisted.activeTabId);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [titleValue, setTitleValue] = useState('');

  // Persist tabs on change
  useEffect(() => {
    persistTabs(tabs, activeTabId, nextTabId);
  }, [tabs, activeTabId]);

  const activeTab = tabs.find(t => t.id === activeTabId) ?? null;
  const activeConvId = activeTab?.convId ?? null;

  const { data: messages } = useAgentMessages(activeConvId);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streaming]);

  // Focus textarea
  useEffect(() => {
    if (activeTabId && !streaming) {
      textareaRef.current?.focus();
    }
  }, [activeTabId, streaming]);

  // Sync title input with active tab label
  useEffect(() => {
    setTitleValue(activeTab?.label ?? '');
  }, [activeTab?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Tab management
  // ---------------------------------------------------------------------------

  const [searchParams, setSearchParams] = useSearchParams();

  const addTab = useCallback((convId: number | null = null, label = 'New chat', saved = false) => {
    // If resuming, check if tab already open for this convId
    if (convId !== null) {
      const existing = tabs.find(t => t.convId === convId);
      if (existing) {
        setActiveTabId(existing.id);
        return;
      }
    }
    const id = String(nextTabId++);
    setTabs(prev => [...prev, { id, convId, label, saved }]);
    setActiveTabId(id);
  }, [tabs]);

  // Auto-open a new tab when navigated here with ?new=1
  const newParam = searchParams.get('new');
  useEffect(() => {
    if (newParam === '1') {
      addTab();
      setSearchParams({}, { replace: true });
    }
  }, [newParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const closeTab = useCallback((tabId: string) => {
    const tab = tabs.find(t => t.id === tabId);
    if (!tab) return;

    // Clean up unsaved DB data
    if (!tab.saved && tab.convId !== null) {
      deleteConversation.mutate(tab.convId);
    }

    setTabs(prev => {
      const remaining = prev.filter(t => t.id !== tabId);
      if (activeTabId === tabId) {
        // Switch to nearest neighbor
        const idx = prev.findIndex(t => t.id === tabId);
        const next = remaining[Math.min(idx, remaining.length - 1)];
        setActiveTabId(next?.id ?? null);
      }
      return remaining;
    });
  }, [tabs, activeTabId, deleteConversation]);

  const updateTab = useCallback((tabId: string, updates: Partial<Tab>) => {
    setTabs(prev => prev.map(t => t.id === tabId ? { ...t, ...updates } : t));
  }, []);

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = useCallback(async () => {
    if (!activeTab || !activeTab.convId || activeTab.saved) return;
    const title = titleValue.trim() || activeTab.label;
    await saveConversation.mutateAsync({ id: activeTab.convId, title });
    updateTab(activeTab.id, { saved: true, label: title });
  }, [activeTab, titleValue, saveConversation, updateTab]);

  // ---------------------------------------------------------------------------
  // Title editing
  // ---------------------------------------------------------------------------

  const handleTitleBlur = useCallback(() => {
    if (!activeTab || !activeTab.convId) return;
    const newTitle = titleValue.trim();
    if (newTitle && newTitle !== activeTab.label) {
      updateTab(activeTab.id, { label: newTitle });
      if (activeTab.saved) {
        updateConversation.mutate({ id: activeTab.convId, title: newTitle });
      }
    }
  }, [activeTab, titleValue, updateTab, updateConversation]);

  // ---------------------------------------------------------------------------
  // Copy / Download / Save as draft
  // ---------------------------------------------------------------------------

  const handleCopy = useCallback(() => {
    if (!messages?.length) return;
    const text = buildMarkdown(messages);
    navigator.clipboard.writeText(text).then(() => {
      setCopyLabel('Copied!');
      setTimeout(() => setCopyLabel('Copy'), 2000);
    });
  }, [messages]);

  const handleDownload = useCallback(() => {
    if (!messages?.length) return;
    const text = buildMarkdown(messages);
    const filename = `${(activeTab?.label ?? 'chat').replace(/[^a-z0-9]/gi, '-').toLowerCase()}.md`;
    const blob = new Blob([text], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, [messages, activeTab]);

  const handleSaveAsDraft = useCallback(async () => {
    if (!activeConvId) return;
    const post = await createLongformFromConv.mutateAsync(activeConvId);
    navigate(`/docs?postId=${post.id}`);
  }, [activeConvId, createLongformFromConv, navigate]);

  // ---------------------------------------------------------------------------
  // Send message
  // ---------------------------------------------------------------------------

  const handleSend = useCallback(async () => {
    if (!input.trim() || !activeTab || streaming) return;

    const message = input.trim();
    setInput('');

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    // Create DB conversation on first message
    let convId = activeTab.convId;
    if (convId === null) {
      const conv = await createConversation.mutateAsync(titleValue.trim() || undefined);
      convId = conv.id;
      updateTab(activeTab.id, { convId });
    }

    const streamState: StreamingState = { text: '', toolCalls: [], isStreaming: true };
    setStreaming(streamState);

    // Optimistic user message
    queryClient.setQueryData<AgentMessage[]>(['agent-messages', convId], (old) => [
      ...(old ?? []),
      {
        id: -Date.now(),
        conversation_id: convId!,
        role: 'user' as const,
        content: message,
        tool_calls: [],
        created_at: new Date().toISOString(),
      },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`/api/agent/conversations/${convId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ') && eventType) {
            try {
              const data = JSON.parse(line.slice(6));
              if (eventType === 'text') {
                streamState.text = data.text;
              } else if (eventType === 'tool_call') {
                streamState.toolCalls.push({ name: data.name, input: data.input });
              } else if (eventType === 'tool_result') {
                for (let i = streamState.toolCalls.length - 1; i >= 0; i--) {
                  if (streamState.toolCalls[i].name === data.name && streamState.toolCalls[i].result === undefined) {
                    streamState.toolCalls[i].result = typeof data.result === 'string' && data.result.length > 2000
                      ? data.result.slice(0, 2000) + '...'
                      : data.result;
                    break;
                  }
                }
              } else if (eventType === 'done') {
                queryClient.invalidateQueries({ queryKey: ['agent-messages', convId] });
              } else if (eventType === 'error') {
                streamState.text = `Error: ${data.error}`;
              }
              setStreaming({ ...streamState });
            } catch {
              // Ignore parse errors
            }
            eventType = '';
          } else if (line === '') {
            eventType = '';
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        const errorText = `Error: ${(err as Error).message}`;
        // Add error as a persistent message in the cache so it survives setStreaming(null)
        queryClient.setQueryData<AgentMessage[]>(['agent-messages', convId], (old) => [
          ...(old ?? []),
          {
            id: -Date.now() - 1,
            conversation_id: convId!,
            role: 'assistant' as const,
            content: errorText,
            tool_calls: [],
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } finally {
      setStreaming(null);
      abortRef.current = null;
      queryClient.invalidateQueries({ queryKey: ['agent-messages', convId] });
    }
  }, [input, activeTab, streaming, queryClient, createConversation, titleValue, updateTab]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextareaInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };

  return (
    <div className="agent-page">
      {/* Header: toggle + title + save */}
      <div className="agent-header">
        <div className="agent-header-left">
          <button
            className="claude-panel-toggle"
            onClick={() => setPanelOpen(!panelOpen)}
            title="Toggle history"
          >
            {panelOpen ? '\u2039' : '\u203A'}
          </button>
          {activeTab && (
            <input
              className="claude-session-title-input"
              placeholder="Session title..."
              value={titleValue}
              onChange={(e) => setTitleValue(e.target.value)}
              onBlur={handleTitleBlur}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.currentTarget.blur(); }
                if (e.key === 'Escape') { setTitleValue(activeTab.label); e.currentTarget.blur(); }
              }}
            />
          )}
        </div>
        {messages && messages.length > 0 && (
          <div style={{ display: 'flex', gap: 'var(--space-xs)' }}>
            <button
              className="auth-action-btn"
              onClick={handleCopy}
              title="Copy conversation as markdown"
            >
              {copyLabel}
            </button>
            <button
              className="auth-action-btn"
              onClick={handleDownload}
              title="Download as markdown file"
            >
              Download
            </button>
            <button
              className="auth-action-btn"
              onClick={handleSaveAsDraft}
              disabled={!activeConvId || createLongformFromConv.isPending}
              title="Summarize and save as doc"
            >
              {createLongformFromConv.isPending ? 'Saving...' : 'Save as Doc'}
            </button>
          </div>
        )}
        {activeTab && activeTab.convId !== null && !activeTab.saved && (
          <button
            className="auth-action-btn"
            onClick={handleSave}
            disabled={saveConversation.isPending}
          >
            {saveConversation.isPending ? 'Saving...' : 'Save'}
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="claude-tab-bar">
        {tabs.map(tab => (
          <div
            key={tab.id}
            className={`claude-tab${tab.id === activeTabId ? ' active' : ''}`}
            onClick={() => setActiveTabId(tab.id)}
          >
            <span className="claude-tab-label">{tab.label}</span>
            <button
              className="claude-tab-close"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              title="Close"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          className="claude-tab-new"
          onClick={() => addTab()}
          title="New conversation"
        >
          +
        </button>
      </div>

      {/* Body: panel + chat */}
      <div className="agent-body">
        {panelOpen && (
          <div className="agent-panel">
            <h3>Saved</h3>
            <div className="agent-panel-list">
              {savedConversations?.map(conv => (
                <div
                  key={conv.id}
                  className={`agent-conv-item${activeConvId === conv.id ? ' active' : ''}`}
                  onClick={() => addTab(conv.id, conv.title, true)}
                >
                  <div className="agent-conv-item-title">{conv.title}</div>
                  <div className="agent-conv-item-meta">
                    <TimeAgo date={conv.updated_at} />
                  </div>
                  <button
                    className="agent-conv-delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm('Delete this conversation?')) {
                        // Close any tab with this convId
                        const openTab = tabs.find(t => t.convId === conv.id);
                        if (openTab) {
                          setTabs(prev => prev.filter(t => t.id !== openTab.id));
                          if (activeTabId === openTab.id) {
                            const remaining = tabs.filter(t => t.id !== openTab.id);
                            setActiveTabId(remaining[0]?.id ?? null);
                          }
                        }
                        deleteConversation.mutate(conv.id);
                      }
                    }}
                  >
                    &times;
                  </button>
                </div>
              ))}
              {(!savedConversations || savedConversations.length === 0) && (
                <div className="agent-panel-empty">No saved conversations</div>
              )}
            </div>
          </div>
        )}

        {/* Chat */}
        <div className="agent-chat">
          {activeTab ? (
            <>
              <div className="agent-chat-messages">
                {(!messages || messages.length === 0) && !streaming && (
                  <div className="agent-chat-welcome">
                    Ask anything about your dashboard &mdash; calendar, email, Slack, notes, issues, and more.
                  </div>
                )}
                {messages?.map(msg => (
                  <MessageBubble key={msg.id} msg={msg} />
                ))}
                {streaming && <StreamingBubble state={streaming} />}
                <div ref={messagesEndRef} />
              </div>
              <div className="agent-input-area">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={handleTextareaInput}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask the agent..."
                  rows={1}
                  disabled={!!streaming}
                />
                <button
                  className="agent-send-btn"
                  onClick={handleSend}
                  disabled={!input.trim() || !!streaming}
                  title="Send (Enter)"
                >
                  &uarr;
                </button>
              </div>
            </>
          ) : (
            <div className="agent-chat-welcome">
              Press <strong>+</strong> to start a conversation.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
