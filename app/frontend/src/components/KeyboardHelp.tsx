import { useEffect } from 'react';
import { SHORTCUT_DEFINITIONS, type ShortcutCategory } from '../hooks/useKeyboardShortcuts';

interface KeyboardHelpProps {
  isOpen: boolean;
  onClose: () => void;
}

const CATEGORY_LABELS: Record<ShortcutCategory, string> = {
  navigation: 'Navigation',
  actions: 'Actions',
  focus: 'Focus',
  issues: 'Issues',
  discovery: 'Issue Discovery',
  overlays: 'Overlays',
};

const CATEGORY_ORDER: ShortcutCategory[] = ['overlays', 'navigation', 'actions', 'focus', 'issues', 'discovery'];

export function KeyboardHelp({ isOpen, onClose }: KeyboardHelpProps) {
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '?') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Group by category
  const grouped = new Map<ShortcutCategory, typeof SHORTCUT_DEFINITIONS>();
  for (const s of SHORTCUT_DEFINITIONS) {
    const list = grouped.get(s.category) || [];
    list.push(s);
    grouped.set(s.category, list);
  }

  return (
    <div className="keyboard-help-overlay" onClick={onClose}>
      <div className="keyboard-help-modal" onClick={e => e.stopPropagation()}>
        <h2>Keyboard Shortcuts</h2>
        {CATEGORY_ORDER.map(cat => {
          const shortcuts = grouped.get(cat);
          if (!shortcuts) return null;
          return (
            <div key={cat} className="keyboard-help-section">
              <h3>{CATEGORY_LABELS[cat]}</h3>
              <div className="keyboard-help-list">
                {shortcuts.map(s => (
                  <div key={s.keys} className="keyboard-help-row">
                    <span className="keyboard-help-desc">{s.description}</span>
                    <span className="keyboard-help-keys">
                      {renderKeys(s.keys)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
        <div className="keyboard-help-footer">
          Press <kbd>Esc</kbd> to close
        </div>
      </div>
    </div>
  );
}

function renderKeys(keys: string) {
  // Handle " / " separator (e.g. "j / ↓")
  if (keys.includes(' / ')) {
    const parts = keys.split(' / ');
    return parts.map((part, i) => (
      <span key={i}>
        {i > 0 && <span className="keyboard-help-sep"> / </span>}
        <kbd>{part}</kbd>
      </span>
    ));
  }

  // Handle sequence keys (e.g. "g d")
  const parts = keys.split(' ');
  if (parts.length > 1) {
    return parts.map((part, i) => (
      <span key={i}>
        {i > 0 && <span className="keyboard-help-then">then</span>}
        <kbd>{part}</kbd>
      </span>
    ));
  }

  return <kbd>{keys}</kbd>;
}
