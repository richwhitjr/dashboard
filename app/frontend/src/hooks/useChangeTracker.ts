import { useEffect, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

/**
 * Polls GET /api/changes every 5s to detect backend writes from background agents
 * (WhatsApp, Claude Code). When a version changes, invalidates the relevant
 * React Query caches so the UI updates without manual refresh.
 */

const ENTITY_QUERY_KEYS: Record<string, string[][]> = {
  notes: [['notes'], ['dashboard'], ['person'], ['search']],
  issues: [['issues'], ['dashboard'], ['issue-tags'], ['search']],
  docs: [['longform'], ['longform-tags'], ['docs-folders']],
};

export function useChangeTracker() {
  const qc = useQueryClient();
  const versionsRef = useRef<Record<string, number>>({});

  const { data } = useQuery({
    queryKey: ['changes'],
    queryFn: () => api.get<Record<string, number>>('/changes'),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (!data) return;

    for (const [entity, version] of Object.entries(data)) {
      const prev = versionsRef.current[entity];
      if (prev !== undefined && prev !== version) {
        const keys = ENTITY_QUERY_KEYS[entity] ?? [];
        for (const key of keys) {
          qc.invalidateQueries({ queryKey: key });
        }
      }
      versionsRef.current[entity] = version;
    }
  }, [data, qc]);
}
