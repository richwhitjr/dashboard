import { useState, useEffect, useCallback } from 'react';
import { useUndoStack } from '../hooks/useUndo';

let triggerUndo: (() => void) | null = null;

// eslint-disable-next-line react-refresh/only-export-components
export function getUndoTrigger() {
  return triggerUndo;
}

export function UndoToast() {
  const { canUndo, label, undo } = useUndoStack();
  const [toast, setToast] = useState<string | null>(null);
  const [fading, setFading] = useState(false);

  const doUndo = useCallback(async () => {
    const result = await undo();
    if (result) {
      setToast(`Undone: ${result}`);
      setFading(false);
    }
  }, [undo]);

  // Expose trigger for keyboard shortcut
  useEffect(() => {
    triggerUndo = canUndo ? doUndo : null;
    return () => { triggerUndo = null; };
  }, [canUndo, doUndo]);

  // Auto-hide toast
  useEffect(() => {
    if (!toast) return;
    const fadeTimer = setTimeout(() => setFading(true), 1800);
    const hideTimer = setTimeout(() => { setToast(null); setFading(false); }, 2400);
    return () => { clearTimeout(fadeTimer); clearTimeout(hideTimer); };
  }, [toast]);

  // Show a hint toast when there's an undoable action
  const [hint, setHint] = useState<string | null>(null);
  const [hintFading, setHintFading] = useState(false);

  useEffect(() => {
    if (canUndo && label && !toast) {
      setHint(label);
      setHintFading(false);
      const fadeTimer = setTimeout(() => setHintFading(true), 2000);
      const hideTimer = setTimeout(() => setHint(null), 2600);
      return () => { clearTimeout(fadeTimer); clearTimeout(hideTimer); };
    } else {
      setHint(null);
    }
  }, [canUndo, label]); // eslint-disable-line react-hooks/exhaustive-deps

  const visible = toast || hint;
  if (!visible) return null;

  return (
    <div className={`undo-toast ${(toast ? fading : hintFading) ? 'fading' : ''}`}>
      {toast ? (
        <span>{toast}</span>
      ) : (
        <span>{hint} — press <kbd>u</kbd> to undo</span>
      )}
    </div>
  );
}
