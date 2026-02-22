import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { SerializeAddon } from '@xterm/addon-serialize';
import '@xterm/xterm/css/xterm.css';

const TERM_THEME = {
  background: '#1a1b26',
  foreground: '#c0caf5',
  cursor: '#c0caf5',
  selectionBackground: '#33467c',
  black: '#15161e',
  red: '#f7768e',
  green: '#9ece6a',
  yellow: '#e0af68',
  blue: '#7aa2f7',
  magenta: '#bb9af7',
  cyan: '#7dcfff',
  white: '#a9b1d6',
  brightBlack: '#414868',
  brightRed: '#f7768e',
  brightGreen: '#9ece6a',
  brightYellow: '#e0af68',
  brightBlue: '#7aa2f7',
  brightMagenta: '#bb9af7',
  brightCyan: '#7dcfff',
  brightWhite: '#c0caf5',
};

const TERM_FONT = "'SF Mono', 'Fira Code', 'Cascadia Code', monospace";

function getPlainText(term: Terminal): string {
  const lines: string[] = [];
  const buffer = term.buffer.active;
  for (let i = 0; i < buffer.length; i++) {
    const line = buffer.getLine(i);
    if (line) lines.push(line.translateToString(true));
  }
  return lines.join('\n').trimEnd();
}

function toBase64(str: string): string {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export interface ClaudeTerminalHandle {
  serialize: () => { content: string; plainText: string; rows: number; cols: number } | null;
  focus: () => void;
  fit: () => void;
}

interface ClaudeTerminalProps {
  visible: boolean;
  overlayOpen?: boolean;
  personaId?: number;
  onConnected?: () => void;
  onDisconnected?: () => void;
}

export const ClaudeTerminal = forwardRef<ClaudeTerminalHandle, ClaudeTerminalProps>(
  ({ visible, overlayOpen, personaId, onConnected, onDisconnected }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const termRef = useRef<Terminal | null>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const fitRef = useRef<FitAddon | null>(null);
    const serializeRef = useRef<SerializeAddon | null>(null);
    const [, setConnState] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');

    useImperativeHandle(ref, () => ({
      serialize: () => {
        const term = termRef.current;
        const serialize = serializeRef.current;
        if (!term || !serialize) return null;
        try {
          const raw = serialize.serialize();
          return {
            content: toBase64(raw),
            plainText: getPlainText(term),
            rows: term.rows,
            cols: term.cols,
          };
        } catch {
          return null;
        }
      },
      focus: () => termRef.current?.focus(),
      fit: () => fitRef.current?.fit(),
    }));

    // Connect on mount, cleanup on unmount
    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: TERM_FONT,
        theme: TERM_THEME,
        scrollback: 10000,
      });

      const fitAddon = new FitAddon();
      const webLinksAddon = new WebLinksAddon();
      const serializeAddon = new SerializeAddon();
      term.loadAddon(fitAddon);
      term.loadAddon(webLinksAddon);
      term.loadAddon(serializeAddon);

      // Let Cmd+K pass through for search
      term.attachCustomKeyEventHandler((e: KeyboardEvent) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') return false;
        return true;
      });

      term.open(container);
      fitAddon.fit();

      termRef.current = term;
      fitRef.current = fitAddon;
      serializeRef.current = serializeAddon;

      // WebSocket
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const params = personaId ? `?persona_id=${personaId}` : '';
      const ws = new WebSocket(`${proto}//${location.host}/api/ws/claude${params}`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        setConnState('connected');
        onConnected?.();
        ws.send(JSON.stringify({
          type: 'resize',
          rows: term.rows,
          cols: term.cols,
        }));
      };

      ws.onmessage = (evt) => {
        if (evt.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(evt.data));
        } else {
          term.write(evt.data);
        }
      };

      ws.onclose = (evt) => {
        setConnState('disconnected');
        onDisconnected?.();
        if (evt.code === 4429) {
          term.write('\r\n\x1b[31m--- too many concurrent sessions, close a tab first ---\x1b[0m\r\n');
        } else {
          term.write('\r\n\x1b[90m--- session ended ---\x1b[0m\r\n');
        }
      };

      ws.onerror = () => {
        setConnState('disconnected');
        onDisconnected?.();
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(new TextEncoder().encode(data));
        }
      });

      term.onBinary((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          const buf = new Uint8Array(data.length);
          for (let i = 0; i < data.length; i++) buf[i] = data.charCodeAt(i);
          ws.send(buf);
        }
      });

      term.onResize(({ rows, cols }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'resize', rows, cols }));
        }
      });

      const onResize = () => fitAddon.fit();
      window.addEventListener('resize', onResize);

      term.focus();

      return () => {
        window.removeEventListener('resize', onResize);
        if (wsRef.current) {
          wsRef.current.onclose = null;
          wsRef.current.close();
          wsRef.current = null;
        }
        if (termRef.current) {
          termRef.current.dispose();
          termRef.current = null;
        }
        serializeRef.current = null;
        fitRef.current = null;
        if (container) {
          container.innerHTML = '';
        }
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ResizeObserver for container size changes (e.g. panel toggle)
    useEffect(() => {
      const observer = new ResizeObserver(() => {
        fitRef.current?.fit();
      });
      if (containerRef.current) {
        observer.observe(containerRef.current);
      }
      return () => observer.disconnect();
    }, []);

    // Re-fit and focus when becoming visible
    useEffect(() => {
      if (visible && !overlayOpen) {
        const t = setTimeout(() => {
          fitRef.current?.fit();
          termRef.current?.focus();
        }, 50);
        return () => clearTimeout(t);
      }
    }, [visible, overlayOpen]);

    return (
      <div
        className="claude-terminal"
        ref={containerRef}
        style={{ display: visible ? undefined : 'none' }}
      />
    );
  }
);

ClaudeTerminal.displayName = 'ClaudeTerminal';
