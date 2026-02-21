import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { addError } from './api/errorLog';
import { openExternal } from './api/client';

// Capture console.error
const originalConsoleError = console.error;
console.error = (...args: unknown[]) => {
  originalConsoleError.apply(console, args);
  const message = args
    .map((a) => (a instanceof Error ? a.message : String(a)))
    .join(' ');
  addError('console', message);
};

// Capture unhandled promise rejections
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  const message = reason instanceof Error ? reason.message : String(reason);
  const detail = reason instanceof Error ? reason.stack : undefined;
  addError('unhandled', message, detail);
});

// Capture uncaught errors
window.addEventListener('error', (event) => {
  addError('unhandled', event.message, `${event.filename}:${event.lineno}`);
});

// In pywebview (native app), intercept <a target="_blank"> clicks and open via system browser
// eslint-disable-next-line @typescript-eslint/no-explicit-any
if ((window as any).pywebview) {
  document.addEventListener('click', (e) => {
    const anchor = (e.target as HTMLElement).closest('a');
    if (anchor && anchor.target === '_blank' && anchor.href) {
      e.preventDefault();
      openExternal(anchor.href);
    }
  });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
