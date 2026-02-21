import { addError } from './errorLog';

const BASE_URL = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const msg = `${res.status} ${res.statusText} — ${options?.method ?? 'GET'} ${path}`;
    addError('api', msg);
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

/**
 * Open a URL in the system browser.
 * In pywebview (native app), window.open doesn't work, so we call the backend.
 */
export function openExternal(url: string) {
  // pywebview injects window.pywebview; if present, use the backend endpoint
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if ((window as any).pywebview) {
    fetch('/api/open-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }).catch(() => {});
  } else {
    window.open(url, '_blank');
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),

  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),

  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
