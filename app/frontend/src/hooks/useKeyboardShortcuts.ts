import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

export type ShortcutCategory = 'navigation' | 'actions' | 'focus' | 'issues' | 'discovery' | 'overlays';

export interface ShortcutDef {
  keys: string;
  description: string;
  category: ShortcutCategory;
}

export const SHORTCUT_DEFINITIONS: ShortcutDef[] = [
  // Navigation (g + key)
  { keys: 'g d', description: 'Go to Dashboard', category: 'navigation' },
  { keys: 'g n', description: 'Go to Notes', category: 'navigation' },
  { keys: 'g t', description: 'Go to Thoughts', category: 'navigation' },
  { keys: 'g i', description: 'Go to Issues', category: 'navigation' },
  { keys: 'g l', description: 'Go to Longform', category: 'navigation' },
  { keys: 'g m', description: 'Go to Meetings', category: 'navigation' },
  { keys: 'g w', description: 'Go to News', category: 'navigation' },
  { keys: 'g p', description: 'Go to Team', category: 'navigation' },
  { keys: 'g h', description: 'Go to GitHub', category: 'navigation' },
  { keys: 'g c', description: 'Go to Claude', category: 'navigation' },
  { keys: 'g x', description: 'Go to Ramp (expenses)', category: 'navigation' },
  { keys: 'g s', description: 'Go to Settings', category: 'navigation' },

  // Actions
  { keys: 'h', description: 'Help / intro', category: 'actions' },
  { keys: 'c', description: 'New note', category: 'actions' },
  { keys: 'r', description: 'Refresh page data', category: 'actions' },
  { keys: 'u', description: 'Undo last action', category: 'actions' },
  { keys: 's', description: 'Sync all data', category: 'actions' },
  { keys: 'D', description: 'Discover issues (AI scan)', category: 'actions' },

  // Focus
  { keys: 'Tab / j / \u2193', description: 'Next item in list', category: 'focus' },
  { keys: 'Shift+Tab / k / \u2191', description: 'Previous item in list', category: 'focus' },
  { keys: 'Enter', description: 'Open focused item', category: 'focus' },
  { keys: 'd', description: 'Dismiss focused item', category: 'focus' },
  { keys: 'e', description: 'Expand / collapse item', category: 'focus' },
  { keys: 'i', description: 'Create issue from item', category: 'focus' },
  { keys: 'f', description: 'Toggle score filter (all / filtered)', category: 'focus' },

  // Issues (on Issues page)
  { keys: 'j / \u2193', description: 'Next issue', category: 'issues' },
  { keys: 'k / \u2191', description: 'Previous issue', category: 'issues' },
  { keys: 'Enter', description: 'Expand / collapse issue', category: 'issues' },
  { keys: 'x', description: 'Toggle done', category: 'issues' },
  { keys: '\u2190 / \u2192', description: 'Change priority', category: 'issues' },
  { keys: 'Shift+\u2190 / Shift+\u2192', description: 'Change size', category: 'issues' },
  { keys: 'Tab', description: 'Edit expanded issue', category: 'issues' },
  { keys: 'Delete', description: 'Delete issue', category: 'issues' },
  { keys: 'i', description: 'New issue', category: 'issues' },

  // Discovery (in review overlay)
  { keys: 'j / \u2193', description: 'Next proposal', category: 'discovery' },
  { keys: 'k / \u2191', description: 'Previous proposal', category: 'discovery' },
  { keys: 'Enter', description: 'Accept proposal', category: 'discovery' },
  { keys: 'x', description: 'Reject proposal', category: 'discovery' },
  { keys: 'e', description: 'Edit proposal', category: 'discovery' },
  { keys: 'Escape', description: 'Close review', category: 'discovery' },

  // Overlays
  { keys: '\u2318K', description: 'Search / command palette', category: 'overlays' },
  { keys: 'Tab (in \u2318K)', description: 'Quick create (issue/thought/note)', category: 'overlays' },
  { keys: '\u2318E (in \u2318K)', description: 'Toggle external search', category: 'overlays' },
  { keys: '?', description: 'Keyboard shortcuts help', category: 'overlays' },
  { keys: 'Escape', description: 'Close overlay', category: 'overlays' },
];

// Route map for g+key navigation shortcuts
const GO_ROUTES: Record<string, string> = {
  d: '/',
  n: '/notes',
  t: '/thoughts',
  i: '/issues',
  l: '/longform',
  m: '/meetings',
  w: '/news',
  p: '/team',
  h: '/github',
  c: '/claude',
  x: '/ramp',
  s: '/settings',
};

interface UseKeyboardShortcutsOptions {
  navigate: (path: string) => void;
  onSearchOpen: () => void;
  onHelpOpen: () => void;
  onRefresh: () => void;
  onUndo: () => void;
  onSync: () => void;
  onDiscoverIssues?: () => void;
  suppressWhen?: boolean;
}

export function useKeyboardShortcuts(opts: UseKeyboardShortcutsOptions) {
  const location = useLocation();
  const pendingPrefix = useRef<string | null>(null);
  const prefixTimer = useRef<number>(0);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const o = optsRef.current;

      // Cmd+K: search — works everywhere including Claude page
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        o.onSearchOpen();
        return;
      }

      // Guard: skip in inputs/textareas/contentEditable
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((e.target as HTMLElement)?.isContentEditable) return;

      // Guard: skip on Claude page (terminal captures keys)
      if (location.pathname === '/claude') return;

      // Guard: skip when overlays are open
      if (o.suppressWhen) return;

      // Shift+D: discover issues (before meta guard since shift is held)
      if (e.key === 'D' && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        o.onDiscoverIssues?.();
        return;
      }

      // Don't process if meta/ctrl/alt held (except Cmd+K above)
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // ? key: help overlay
      if (e.key === '?') {
        e.preventDefault();
        o.onHelpOpen();
        return;
      }

      // Handle pending "g" prefix
      if (pendingPrefix.current === 'g') {
        clearTimeout(prefixTimer.current);
        pendingPrefix.current = null;

        const route = GO_ROUTES[e.key];
        if (route) {
          e.preventDefault();
          o.navigate(route);
        }
        return;
      }

      // "g" starts a sequence
      if (e.key === 'g') {
        pendingPrefix.current = 'g';
        prefixTimer.current = window.setTimeout(() => {
          pendingPrefix.current = null;
        }, 1500);
        return;
      }

      // Single-key shortcuts
      if (e.key === 'c') {
        o.navigate('/notes?focus=1');
        return;
      }
      if (e.key === 'h') {
        o.navigate('/help');
        return;
      }
      if (e.key === 'r') {
        e.preventDefault();
        o.onRefresh();
        return;
      }
      if (e.key === 'u') {
        e.preventDefault();
        o.onUndo();
        return;
      }
      if (e.key === 's') {
        e.preventDefault();
        o.onSync();
        return;
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [location.pathname]);
}
