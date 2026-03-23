import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

const MAX_HISTORY = 20;

// Module-level history so it persists across re-renders
let pageHistory: string[] = ['/'];

// Route path → human-readable label
const ROUTE_LABELS: Record<string, string> = {
  '/': 'Today',
  '/notes': 'Notes',
  '/issues': 'Issues',
  '/docs': 'Docs',
  '/longform': 'Docs',
  '/meetings': 'Meetings',
  '/news': 'News',
  '/people': 'People',
  '/github': 'GitHub',
  '/claude': 'Claude',
  '/email': 'Email',
  '/slack': 'Slack',
  '/notion': 'Notion',
  '/drive': 'Drive',
  '/ramp': 'Expenses',
  '/ramp/bills': 'Bills',
  '/ramp/projects': 'Projects',
  '/settings': 'Settings',
  '/help': 'Help',
};

export function getPageLabel(path: string): string {
  // Exact match
  if (ROUTE_LABELS[path]) return ROUTE_LABELS[path];
  // Person pages: /people/123
  if (path.startsWith('/people/') || path.startsWith('/employees/')) return 'Person';
  return path;
}

export function usePageHistory() {
  const location = useLocation();
  const lastPath = useRef(location.pathname);

  useEffect(() => {
    const path = location.pathname;
    // Skip setup page and duplicate consecutive visits
    if (path === '/setup' || path === lastPath.current) return;
    lastPath.current = path;

    // Move to front, deduplicate
    pageHistory = [path, ...pageHistory.filter(p => p !== path)].slice(0, MAX_HISTORY);
  }, [location.pathname]);

  return pageHistory;
}
