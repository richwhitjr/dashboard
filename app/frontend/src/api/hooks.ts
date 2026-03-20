import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from '@tanstack/react-query';
import { api } from './client';
import { pushUndo } from '../hooks/useUndo';
import type {
  PaginatedResponse,
  Person,
  PersonDetail,
  PersonLink,
  PersonAttribute,
  PersonConnection,
  Note,
  Issue,
  IssueGroupResponse,
  MeetingSearchResult,
  OneOnOneNote,
  DashboardData,
  BriefingData,
  PrioritiesData,
  SyncStatus,
  AuthStatus,
  ServiceAuthStatus,
  NewsResponse,
  SearchResults,
  GitHubPullRequest,
  GitHubPullRequestDetail,
  GitHubSearchResult,
  GitHubCodeSearchResult,
  PrioritizedGitHubData,
  MeetingNote,
  MeetingsResponse,
  SlackMessage,
  PrioritizedSlackData,
  NotionPage,
  PrioritizedNotionData,
  ObsidianNote,
  ObsidianNoteDetail,
  PrioritizedObsidianData,
  PrioritizedEmailData,
  Email,
  EmailThreadDetail,
  RampData,
  RampBillsResponse,
  Project,
  ProjectsResponse,
  PrioritizedNewsData,
  DriveFile,
  PrioritizedDriveData,
  GoogleSheetsResponse,
  GoogleDocsResponse,
  GoogleSheet,
  SheetValuesResponse,
  LongformPost,
  LongformPostDetail,
  LongformComment,
  LongformAIEditResponse,
  ClaudeSession,
  ClaudeSessionContent,
  Persona,
  UserProfile,
  SetupStatus,
  ConnectorInfo,
  SecretsStatus,
  DiscoveryStatus,
  DiscoveryProposalsResponse,
  MemoryEntry,
  MemorySummary,
  WhatsAppStatus,
  WhatsAppQR,
  AgentConversation,
  AgentMessage,
  SandboxApp,
} from './types';

export function usePeople(filters?: { is_coworker?: boolean; group?: string }) {
  const params = new URLSearchParams();
  if (filters?.is_coworker !== undefined) params.set('is_coworker', filters.is_coworker ? '1' : '0');
  if (filters?.group) params.set('group', filters.group);
  const qs = params.toString();
  return useQuery({
    queryKey: ['people', filters],
    queryFn: () => api.get<Person[]>(`/people${qs ? `?${qs}` : ''}`),
  });
}

export function useGroups() {
  return useQuery({
    queryKey: ['groups'],
    queryFn: () => api.get<string[]>('/people/groups'),
  });
}

export function useRenameGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      api.patch(`/people/groups/${encodeURIComponent(oldName)}`, { new_name: newName }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['people'] });
      qc.invalidateQueries({ queryKey: ['groups'] });
      qc.invalidateQueries({ queryKey: ['person'] });
    },
  });
}

export function usePerson(id: string) {
  return useQuery({
    queryKey: ['person', id],
    queryFn: () => api.get<PersonDetail>(`/people/${id}`),
    enabled: !!id,
  });
}

export function useNotes(filters?: {
  status?: string;
  person_id?: string;
  is_one_on_one?: boolean;
}) {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.person_id) params.set('person_id', filters.person_id);
  if (filters?.is_one_on_one !== undefined)
    params.set('is_one_on_one', String(filters.is_one_on_one));
  const qs = params.toString();
  return useQuery({
    queryKey: ['notes', filters],
    queryFn: () => api.get<Note[]>(`/notes${qs ? `?${qs}` : ''}`),
  });
}

export function useCreateNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (note: {
      text: string;
      priority?: number;
      person_id?: string;
      person_ids?: string[];
      is_one_on_one?: boolean;
      due_date?: string;
    }) => api.post<Note>('/notes', note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['person'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useUpdateNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...update }: { id: number } & Partial<Note>) =>
      api.patch<Note>(`/notes/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
      qc.invalidateQueries({ queryKey: ['person'] });
    },
  });
}

export function useDeleteNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/notes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notes'] }),
  });
}

export function useBriefing() {
  return useQuery({
    queryKey: ['briefing'],
    queryFn: () => api.get<BriefingData>('/briefing'),
    refetchInterval: 5 * 60 * 1000,
  });
}

export function useDashboard(days: number = 7) {
  return useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => api.get<DashboardData>(`/dashboard?days=${days}`),
    refetchInterval: 5 * 60 * 1000,
  });
}

export function usePriorities() {
  return useQuery({
    queryKey: ['priorities'],
    queryFn: () => api.get<PrioritiesData>('/priorities'),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPriorities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritiesData>('/priorities?refresh=true'),
    onSuccess: (data) => {
      qc.setQueryData<PrioritiesData>(['priorities'], data);
      // Immediately update briefing cache with fresh summary + attention items
      qc.setQueryData<BriefingData>(['briefing'], (old) => {
        if (!old) return old;
        return { ...old, summary: data.summary ?? null, attention_items: data.items };
      });
    },
  });
}

export function useDismissPriority() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; reason: 'done' | 'ignored' }) =>
      api.post('/priorities/dismiss', body),
    onMutate: async ({ title }) => {
      await qc.cancelQueries({ queryKey: ['priorities'] });
      await qc.cancelQueries({ queryKey: ['briefing'] });
      const prevPriorities = qc.getQueryData<PrioritiesData>(['priorities']);
      const prevBriefing = qc.getQueryData<BriefingData>(['briefing']);
      if (prevPriorities) {
        qc.setQueryData<PrioritiesData>(['priorities'], {
          ...prevPriorities,
          items: prevPriorities.items.filter((item) => item.title !== title),
        });
      }
      if (prevBriefing) {
        qc.setQueryData<BriefingData>(['briefing'], {
          ...prevBriefing,
          attention_items: prevBriefing.attention_items?.filter((item) => item.title !== title),
        });
      }
      return { prevPriorities, prevBriefing };
    },
    onSuccess: (_data, { title }) => {
      pushUndo({
        label: 'priority dismissed',
        undo: async () => {
          await api.post('/priorities/undismiss', { title });
          qc.invalidateQueries({ queryKey: ['priorities'] });
          qc.invalidateQueries({ queryKey: ['briefing'] });
        },
      });
    },
    onError: (_err, _vars, context) => {
      if (context?.prevPriorities) qc.setQueryData(['priorities'], context.prevPriorities);
      if (context?.prevBriefing) qc.setQueryData(['briefing'], context.prevBriefing);
    },
  });
}

export function useDismissDashboardItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { source: string; item_id: string }) =>
      api.post('/dashboard/dismiss', body),
    onMutate: async ({ source, item_id }) => {
      await qc.cancelQueries({ queryKey: ['dashboard'] });
      const allQueries = qc.getQueriesData<DashboardData>({ queryKey: ['dashboard'] });
      const snapshots: [readonly unknown[], DashboardData][] = [];
      for (const [key, data] of allQueries) {
        if (!data) continue;
        snapshots.push([key, data]);
        const updated = { ...data };
        if (source === 'slack') {
          updated.slack_recent = data.slack_recent.filter((m) => m.id !== item_id);
        } else if (source === 'notion') {
          updated.notion_recent = data.notion_recent.filter((p) => p.id !== item_id);
        } else if (source === 'github') {
          updated.github_review_requests = data.github_review_requests.filter(
            (pr) => String(pr.number) !== item_id
          );
        } else if (source === 'email') {
          updated.emails_recent = data.emails_recent.filter((e) => e.id !== item_id);
        }
        qc.setQueryData<DashboardData>(key, updated);
      }
      return { snapshots };
    },
    onSuccess: (_data, { source, item_id }) => {
      pushUndo({
        label: `${source} item dismissed`,
        undo: async () => {
          await api.post('/dashboard/undismiss', { source, item_id });
          qc.invalidateQueries({ queryKey: ['dashboard'] });
        },
      });
    },
    onError: (_err, _vars, context) => {
      if (context?.snapshots) {
        for (const [key, data] of context.snapshots) {
          qc.setQueryData(key, data);
        }
      }
    },
  });
}

export function useSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/sync'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
      qc.invalidateQueries({ queryKey: ['people'] });
      qc.invalidateQueries({ queryKey: ['groups'] });
    },
  });
}

export function useCancelSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/sync/cancel'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: ['sync-status'],
    queryFn: () => api.get<SyncStatus>('/sync/status'),
    refetchInterval: (query) => (query.state.data?.running ? 1000 : 3000),
  });
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ['auth-status'],
    queryFn: () => api.get<AuthStatus>('/auth/status'),
  });
}

export function useGoogleAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string; error?: string }>('/auth/google'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

export function useMicrosoftAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string; error?: string }>('/auth/microsoft'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

export function useMicrosoftRevoke() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>('/auth/microsoft/revoke'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

export function useSwitchEmailCalendarProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: 'google' | 'microsoft') =>
      api.post<{ status: string; provider: string; changed: boolean }>('/auth/email-calendar-provider/switch', { provider }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth-status'] });
      qc.invalidateQueries({ queryKey: ['profile'] });
      qc.invalidateQueries({ queryKey: ['sync-status'] });
      qc.invalidateQueries({ queryKey: ['connectors'] });
    },
  });
}

export function useGranolaAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string; error?: string }>('/auth/granola/connect'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

export function useGoogleRevoke() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>('/auth/google/revoke'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

export function useTestConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (service: string) =>
      api.post<ServiceAuthStatus>(`/auth/test/${service}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth-status'] }),
  });
}

// --- Issues ---

export function useIssues(filters?: {
  status?: string;
  person_id?: string;
  priority?: number;
  tshirt_size?: string;
  project_id?: number;
  tag?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.person_id) params.set('person_id', filters.person_id);
  if (filters?.priority !== undefined) params.set('priority', String(filters.priority));
  if (filters?.tshirt_size) params.set('tshirt_size', filters.tshirt_size);
  if (filters?.project_id !== undefined) params.set('project_id', String(filters.project_id));
  if (filters?.tag) params.set('tag', filters.tag);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.sort_by) params.set('sort_by', filters.sort_by);
  if (filters?.sort_dir) params.set('sort_dir', filters.sort_dir);
  const qs = params.toString();
  return useQuery({
    queryKey: ['issues', filters],
    queryFn: () => api.get<Issue[]>(`/issues${qs ? `?${qs}` : ''}`),
  });
}

export function useIssueTags() {
  return useQuery({
    queryKey: ['issue-tags'],
    queryFn: () => api.get<string[]>('/issues/tags'),
    staleTime: 30_000,
  });
}

export function useGroupIssues() {
  return useMutation({
    mutationFn: () => api.post<IssueGroupResponse>('/issues/group', {}),
  });
}

export function useCreateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (issue: {
      title: string;
      description?: string;
      priority?: number;
      tshirt_size?: string;
      person_ids?: string[];
      meeting_ids?: { ref_type: string; ref_id: string }[];
      project_id?: number | null;
      tags?: string[];
      due_date?: string | null;
    }) => api.post<Issue>('/issues', issue),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['person'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useUpdateIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...update
    }: { id: number } & Partial<Issue> & {
      person_ids?: string[];
      meeting_ids?: { ref_type: string; ref_id: string }[];
    }) => api.patch<Issue>(`/issues/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['person'] });
    },
  });
}

export function useDeleteIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/issues/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['person'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

// --- Issue Discovery ---

export function useDiscoverIssues() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string; run_id: number }>('/issues/discover', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovery-status'] });
    },
  });
}

export function useDiscoveryStatus(enabled: boolean = false) {
  return useQuery({
    queryKey: ['discovery-status'],
    queryFn: () => api.get<DiscoveryStatus>('/issues/discover/status'),
    refetchInterval: () => {
      return enabled ? 1000 : false;
    },
    enabled,
  });
}

export function useDiscoveryProposals(runId: number | null) {
  return useQuery({
    queryKey: ['discovery-proposals', runId],
    queryFn: () => api.get<DiscoveryProposalsResponse>(
      `/issues/discover/proposals${runId ? `?run_id=${runId}` : ''}`
    ),
    enabled: runId !== null,
  });
}

export function useAcceptProposal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, overrides }: { proposalId: number; overrides?: Record<string, unknown> }) =>
      api.post(`/issues/discover/accept/${proposalId}`, overrides || {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovery-proposals'] });
      qc.invalidateQueries({ queryKey: ['issues'] });
    },
  });
}

export function useRejectProposal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (proposalId: number) => api.post(`/issues/discover/reject/${proposalId}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovery-proposals'] });
    },
  });
}

export function useBulkDiscoveryAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { action: 'accept_all' | 'reject_all'; run_id: number }) =>
      api.post('/issues/discover/bulk', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovery-proposals'] });
      qc.invalidateQueries({ queryKey: ['issues'] });
    },
  });
}

export function useSearchMeetings(query: string) {
  return useQuery({
    queryKey: ['search-meetings', query],
    queryFn: () => api.get<MeetingSearchResult[]>(`/issues/search-meetings?q=${encodeURIComponent(query)}`),
    enabled: query.length > 0,
    staleTime: 10_000,
  });
}

// --- Longform ---

export function useLongformPosts(filters?: {
  status?: string;
  tag?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.tag) params.set('tag', filters.tag);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.sort_by) params.set('sort_by', filters.sort_by);
  if (filters?.sort_dir) params.set('sort_dir', filters.sort_dir);
  const qs = params.toString();
  return useQuery({
    queryKey: ['longform', filters],
    queryFn: () => api.get<LongformPost[]>(`/longform${qs ? `?${qs}` : ''}`),
  });
}

export function useLongformPost(id: number | null) {
  return useQuery({
    queryKey: ['longform', id],
    queryFn: () => api.get<LongformPostDetail>(`/longform/${id}`),
    enabled: id !== null,
  });
}

export function useLongformTags() {
  return useQuery({
    queryKey: ['longform-tags'],
    queryFn: () => api.get<string[]>('/longform/tags'),
    staleTime: 30_000,
  });
}

export function useCreateLongform() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (post: { title?: string; body?: string; status?: string; tags?: string[]; person_ids?: string[] }) =>
      api.post<LongformPost>('/longform', post),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useUpdateLongform() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...update
    }: {
      id: number;
      title?: string;
      body?: string;
      status?: string;
      tags?: string[];
      person_ids?: string[];
    }) => api.patch<LongformPostDetail>(`/longform/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
      qc.invalidateQueries({ queryKey: ['search'] });
      qc.invalidateQueries({ queryKey: ['person'] });
    },
  });
}

export function useDeleteLongform() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/longform/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
      qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}

export function useCreateLongformComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ postId, text, is_thought }: { postId: number; text: string; is_thought?: boolean }) =>
      api.post<LongformComment>(`/longform/${postId}/comments`, { text, is_thought }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
    },
  });
}

export function useDeleteLongformComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ postId, commentId }: { postId: number; commentId: number }) =>
      api.delete(`/longform/${postId}/comments/${commentId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
    },
  });
}

export function useCreateLongformFromSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: number) =>
      api.post<LongformPost>(`/longform/from-session/${sessionId}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['longform'] });
    },
  });
}

export function useAIEditLongform() {
  return useMutation({
    mutationFn: ({ postId, ...req }: {
      postId: number;
      instruction: string;
      body: string;
      title?: string;
      selected_text?: string;
      history?: { instruction: string; commentary: string }[];
    }) =>
      api.post<LongformAIEditResponse>(`/longform/${postId}/ai-edit`, req),
  });
}

// --- Person CRUD ---

export function useCreatePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (person: {
      name: string;
      title?: string;
      reports_to?: string | null;
      group_name?: string;
      email?: string;
      is_coworker?: boolean;
      company?: string;
      phone?: string;
      bio?: string;
      linkedin_url?: string;
    }) => api.post<Person>('/people', person),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['people'] });
      qc.invalidateQueries({ queryKey: ['groups'] });
      if (variables.reports_to) {
        qc.invalidateQueries({ queryKey: ['person', variables.reports_to] });
      }
    },
  });
}

export function useUpdatePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...update
    }: {
      id: string;
      name?: string;
      title?: string;
      reports_to?: string | null;
      group_name?: string;
      email?: string;
      role_content?: string;
      is_coworker?: boolean;
      company?: string;
      phone?: string;
      bio?: string;
      linkedin_url?: string;
    }) => api.patch<Person>(`/people/${id}`, update),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['people'] });
      qc.invalidateQueries({ queryKey: ['person', vars.id] });
      qc.invalidateQueries({ queryKey: ['groups'] });
    },
  });
}

export function useDeletePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/people/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['people'] });
      qc.invalidateQueries({ queryKey: ['groups'] });
    },
  });
}

// Backward compat aliases
export const useEmployees = usePeople;
export const useEmployee = usePerson;
export const useCreateEmployee = useCreatePerson;
export const useUpdateEmployee = useUpdatePerson;
export const useDeleteEmployee = useDeletePerson;

// --- Person Links ---

export function usePersonLinks(personId: string) {
  return useQuery({
    queryKey: ['person-links', personId],
    queryFn: () => api.get<PersonLink[]>(`/people/${personId}/links`),
    enabled: !!personId,
  });
}

export function useCreatePersonLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, ...link }: { personId: string; link_type: string; url: string; label?: string }) =>
      api.post<PersonLink>(`/people/${personId}/links`, link),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-links', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

export function useDeletePersonLink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, linkId }: { personId: string; linkId: number }) =>
      api.delete(`/people/${personId}/links/${linkId}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-links', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

// --- Person Attributes ---

export function usePersonAttributes(personId: string) {
  return useQuery({
    queryKey: ['person-attributes', personId],
    queryFn: () => api.get<PersonAttribute[]>(`/people/${personId}/attributes`),
    enabled: !!personId,
  });
}

export function useCreatePersonAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, ...attr }: { personId: string; key: string; value: string }) =>
      api.post<PersonAttribute>(`/people/${personId}/attributes`, attr),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-attributes', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

export function useUpdatePersonAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, attrId, ...update }: { personId: string; attrId: number; key?: string; value?: string }) =>
      api.patch<PersonAttribute>(`/people/${personId}/attributes/${attrId}`, update),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-attributes', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

export function useDeletePersonAttribute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, attrId }: { personId: string; attrId: number }) =>
      api.delete(`/people/${personId}/attributes/${attrId}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-attributes', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

// --- Person Connections ---

export function usePersonConnections(personId: string) {
  return useQuery({
    queryKey: ['person-connections', personId],
    queryFn: () => api.get<PersonConnection[]>(`/people/${personId}/connections`),
    enabled: !!personId,
  });
}

export function useCreatePersonConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, ...conn }: { personId: string; person_id: string; relationship?: string; notes?: string }) =>
      api.post<PersonConnection>(`/people/${personId}/connections`, conn),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-connections', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person-connections', vars.person_id] });
      qc.invalidateQueries({ queryKey: ['person', vars.person_id] });
    },
  });
}

export function useDeletePersonConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, connectionId }: { personId: string; connectionId: number }) =>
      api.delete(`/people/${personId}/connections/${connectionId}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person-connections', vars.personId] });
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

// --- 1:1 Notes CRUD ---

export function useCreateOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      personId,
      ...note
    }: {
      personId: string;
      meeting_date: string;
      title?: string;
      content: string;
    }) => api.post<OneOnOneNote>(`/people/${personId}/one-on-one-notes`, note),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

export function useUpdateOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      personId,
      id,
      ...update
    }: {
      personId: string;
      id: number;
      meeting_date?: string;
      title?: string;
      content?: string;
    }) => api.patch<OneOnOneNote>(`/people/${personId}/one-on-one-notes/${id}`, update),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

export function useDeleteOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ personId, id }: { personId: string; id: number }) =>
      api.delete(`/people/${personId}/one-on-one-notes/${id}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['person', vars.personId] });
    },
  });
}

// --- Search ---

export function useSearch(
  query: string,
  options?: {
    sources?: string;
    includeExternal?: boolean;
    enabled?: boolean;
  }
) {
  const params = new URLSearchParams();
  params.set('q', query);
  if (options?.sources) params.set('sources', options.sources);
  if (options?.includeExternal) params.set('include_external', 'true');

  return useQuery({
    queryKey: ['search', query, options?.sources, options?.includeExternal],
    queryFn: () => api.get<SearchResults>(`/search?${params}`),
    enabled: (options?.enabled ?? true) && query.length > 0,
    staleTime: 10_000,
    placeholderData: (prev: SearchResults | undefined) => prev,
  });
}

// --- GitHub ---

export function useGitHubPulls(filters?: {
  state?: string;
  review_requested?: boolean;
  author?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.state) params.set('state', filters.state);
  if (filters?.review_requested) params.set('review_requested', 'true');
  if (filters?.author) params.set('author', filters.author);
  const qs = params.toString();
  return useQuery({
    queryKey: ['github-pulls', filters],
    queryFn: () =>
      api.get<{ total: number; count: number; pulls: GitHubPullRequest[] }>(
        `/github/pulls${qs ? `?${qs}` : ''}`
      ),
    staleTime: 60_000,
  });
}

export function useGitHubPull(number: number) {
  return useQuery({
    queryKey: ['github-pull', number],
    queryFn: () => api.get<GitHubPullRequestDetail>(`/github/pulls/${number}`),
    enabled: !!number,
  });
}

export function useGitHubSearch(query: string, type?: string) {
  const params = new URLSearchParams({ q: query });
  if (type) params.set('type', type);
  return useQuery({
    queryKey: ['github-search', query, type],
    queryFn: () =>
      api.get<{ query: string; total: number; count: number; items: GitHubSearchResult[] }>(
        `/github/search?${params}`
      ),
    enabled: query.length > 0,
    staleTime: 30_000,
  });
}

export function useGitHubCodeSearch(query: string) {
  return useQuery({
    queryKey: ['github-code-search', query],
    queryFn: () =>
      api.get<{ query: string; total: number; count: number; items: GitHubCodeSearchResult[] }>(
        `/github/search/code?q=${encodeURIComponent(query)}`
      ),
    enabled: query.length > 0,
    staleTime: 30_000,
  });
}

const NEWS_PAGE_SIZE = 20;

export function useNews() {
  return useInfiniteQuery({
    queryKey: ['news'],
    queryFn: ({ pageParam = 0 }) =>
      api.get<NewsResponse>(`/news?offset=${pageParam}&limit=${NEWS_PAGE_SIZE}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function usePrioritizedNews(days: number = 14) {
  return useQuery({
    queryKey: ['news-prioritized', days],
    queryFn: () => api.get<PrioritizedNewsData>(`/news/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedNews(days: number = 14) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedNewsData>(`/news/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedNewsData>(['news-prioritized', days], data);
      if (data.stale) {
        // Background rerank in progress — poll for fresh result
        setTimeout(() => qc.invalidateQueries({ queryKey: ['news-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['news-prioritized', days] }), 8000);
      }
    },
  });
}

// --- Meetings ---

const MEETINGS_PAGE_SIZE = 30;

export function useMeetings(tab: 'upcoming' | 'past') {
  return useInfiniteQuery({
    queryKey: ['meetings', tab],
    queryFn: ({ pageParam = 0 }) =>
      api.get<MeetingsResponse>(
        `/meetings?tab=${tab}&limit=${MEETINGS_PAGE_SIZE}&offset=${pageParam}`
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function useAllMeetingNotes(provider?: string) {
  const params = provider ? `&provider=${provider}` : '';
  return useInfiniteQuery({
    queryKey: ['all-meeting-notes', provider],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<MeetingNote>>(`/meetings/notes/all?offset=${pageParam}&limit=${ALL_ITEMS_PAGE_SIZE}${params}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

// Legacy alias
export const useAllGranola = () => useAllMeetingNotes('granola');

export function useMeetingNotesProviders() {
  return useQuery({
    queryKey: ['connectors-meeting-notes'],
    queryFn: () => api.get<ConnectorInfo[]>('/auth/connectors?capability=meeting_notes'),
  });
}

export function useUpsertMeetingNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      refType,
      refId,
      content,
    }: {
      refType: 'calendar' | 'granola' | 'external';
      refId: string;
      content: string;
    }) => api.post(`/meetings/${refType}/${refId}/notes`, { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings'] });
    },
  });
}

export function useDeleteMeetingNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      refType,
      refId,
    }: {
      refType: 'calendar' | 'granola' | 'external';
      refId: string;
    }) => api.delete(`/meetings/${refType}/${refId}/notes`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings'] });
    },
  });
}

// --- Prioritized Slack & Notion ---

export function usePrioritizedSlack(days: number = 7) {
  return useQuery({
    queryKey: ['slack-prioritized', days],
    queryFn: () => api.get<PrioritizedSlackData>(`/slack/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedSlack(days: number = 7) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedSlackData>(`/slack/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedSlackData>(['slack-prioritized', days], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['slack-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['slack-prioritized', days] }), 8000);
      }
    },
  });
}

export function usePrioritizedNotion(days: number = 7) {
  return useQuery({
    queryKey: ['notion-prioritized', days],
    queryFn: () => api.get<PrioritizedNotionData>(`/notion/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedNotion(days: number = 7) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedNotionData>(`/notion/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedNotionData>(['notion-prioritized', days], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['notion-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['notion-prioritized', days] }), 8000);
      }
    },
  });
}

export function usePrioritizedObsidian(days: number = 365) {
  return useQuery({
    queryKey: ['obsidian-prioritized', days],
    queryFn: () => api.get<PrioritizedObsidianData>(`/obsidian/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
    // Poll while background ranking is in progress (stale + empty items)
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.stale && data.items.length === 0) return 4000;
      return false;
    },
  });
}

export function useRefreshPrioritizedObsidian(days: number = 365) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedObsidianData>(`/obsidian/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedObsidianData>(['obsidian-prioritized', days], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['obsidian-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['obsidian-prioritized', days] }), 8000);
      }
    },
  });
}

export function useObsidianNote(noteId: string | null) {
  return useQuery({
    queryKey: ['obsidian-note', noteId],
    queryFn: () => api.get<ObsidianNoteDetail>(`/obsidian/note/${noteId}`),
    enabled: !!noteId,
    staleTime: 5 * 60 * 1000,
  });
}

export function usePrioritizedEmail(days: number = 7) {
  return useQuery({
    queryKey: ['email-prioritized', days],
    queryFn: () => api.get<PrioritizedEmailData>(`/gmail/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedEmail(days: number = 7) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedEmailData>(`/gmail/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedEmailData>(['email-prioritized', days], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['email-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['email-prioritized', days] }), 8000);
      }
    },
  });
}

export function useSyncRamp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (orgOnly: boolean) =>
      api.post(`/sync/ramp?org_only=${orgOnly}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth-status'] });
      qc.invalidateQueries({ queryKey: ['ramp-prioritized'] });
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });
}

// --- Prioritized Ramp ---

export function usePrioritizedRamp(days: number = 7, orgOnly: boolean = true) {
  return useQuery({
    queryKey: ['ramp-prioritized', days, orgOnly],
    queryFn: () => api.get<RampData>(`/ramp/prioritized?days=${days}&org_only=${orgOnly}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedRamp(days: number = 7, orgOnly: boolean = true) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<RampData>(`/ramp/prioritized?refresh=true&days=${days}&org_only=${orgOnly}`),
    onSuccess: (data) => {
      qc.setQueryData<RampData>(['ramp-prioritized', days, orgOnly], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['ramp-prioritized', days, orgOnly] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['ramp-prioritized', days, orgOnly] }), 8000);
      }
    },
  });
}

export function useRampBills(filters?: { days?: number; status?: string; project_id?: number; vendor_id?: string }) {
  const params = new URLSearchParams();
  if (filters?.days) params.set('days', String(filters.days));
  if (filters?.status) params.set('status', filters.status);
  if (filters?.project_id != null) params.set('project_id', String(filters.project_id));
  if (filters?.vendor_id) params.set('vendor_id', filters.vendor_id);
  const qs = params.toString();
  return useQuery({
    queryKey: ['ramp-bills', filters],
    queryFn: () => api.get<RampBillsResponse>(`/ramp/bills${qs ? '?' + qs : ''}`),
    staleTime: 5 * 60 * 1000,
  });
}

export function useAssignBillProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ billId, projectId }: { billId: string; projectId: number | null }) =>
      api.patch(`/ramp/bills/${billId}/project`, { project_id: projectId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ramp-bills'] });
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<ProjectsResponse>('/projects'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string; budget_amount?: number; vendor_id?: string; notes?: string }) =>
      api.post<Project>('/projects', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...update }: { id: number; name?: string; description?: string; budget_amount?: number; status?: string; vendor_id?: string; notes?: string }) =>
      api.patch<Project>(`/projects/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/projects/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] });
      qc.invalidateQueries({ queryKey: ['ramp-bills'] });
    },
  });
}

// --- Drive / Sheets / Docs ---

export function usePrioritizedDrive(days: number = 7) {
  return useQuery({
    queryKey: ['drive-prioritized', days],
    queryFn: () => api.get<PrioritizedDriveData>(`/drive/prioritized?days=${days}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedDrive(days: number = 7) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedDriveData>(`/drive/prioritized?refresh=true&days=${days}`),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedDriveData>(['drive-prioritized', days], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['drive-prioritized', days] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['drive-prioritized', days] }), 8000);
      }
    },
  });
}

export function useDocs(days: number = 30) {
  return useQuery({
    queryKey: ['docs', days],
    queryFn: () => api.get<GoogleDocsResponse>(`/drive/docs?days=${days}`),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSheets(days: number = 30) {
  return useQuery({
    queryKey: ['sheets', days],
    queryFn: () => api.get<GoogleSheetsResponse>(`/sheets?days=${days}`),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSheetDetail(id: string | null) {
  return useQuery({
    queryKey: ['sheet-detail', id],
    queryFn: () => api.get<GoogleSheet>(`/sheets/${id}`),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSheetValues(id: string | null, range?: string, tab?: string) {
  const params = new URLSearchParams();
  if (range) params.set('range', range);
  if (tab) params.set('tab', tab);
  const qs = params.toString();
  return useQuery({
    queryKey: ['sheet-values', id, range, tab],
    queryFn: () => api.get<SheetValuesResponse>(`/sheets/${id}/values${qs ? '?' + qs : ''}`),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
}

export function useEmailThread(threadId: string | null) {
  return useQuery({
    queryKey: ['email-thread', threadId],
    queryFn: () => api.get<EmailThreadDetail>(`/gmail/thread/${threadId}`),
    enabled: !!threadId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDismissPrioritizedItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { source: string; item_id: string }) =>
      api.post('/dashboard/dismiss', body),
    onMutate: async ({ source, item_id }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const snapshots: [readonly unknown[], any][] = [];
      if (source === 'github') {
        await qc.cancelQueries({ queryKey: ['github-pulls'] });
        const allQueries = qc.getQueriesData<{ total: number; count: number; pulls: GitHubPullRequest[] }>({ queryKey: ['github-pulls'] });
        for (const [key, data] of allQueries) {
          if (!data) continue;
          snapshots.push([key, data]);
          const filtered = data.pulls.filter((pr) => String(pr.number) !== item_id);
          qc.setQueryData(key, { ...data, count: filtered.length, pulls: filtered });
        }
      } else {
        // Optimistic dismiss for all prioritized sources (slack, email, notion, ramp, news, drive)
        const keyMap: Record<string, string> = { slack: 'slack-prioritized', email: 'email-prioritized', notion: 'notion-prioritized', ramp: 'ramp-prioritized', news: 'news-prioritized', drive: 'drive-prioritized', obsidian: 'obsidian-prioritized' };
        const qkPrefix = keyMap[source];
        if (qkPrefix) {
          await qc.cancelQueries({ queryKey: [qkPrefix] });
          const allQueries = qc.getQueriesData<{ items: { id: string }[] }>({ queryKey: [qkPrefix] });
          for (const [key, data] of allQueries) {
            if (!data?.items) continue;
            snapshots.push([key, data]);
            qc.setQueryData(key, { ...data, items: data.items.filter((it) => it.id !== item_id) });
          }
        }
      }
      return { snapshots };
    },
    onSuccess: (_data, { source, item_id }) => {
      qc.invalidateQueries({ queryKey: ['slack-prioritized'] });
      qc.invalidateQueries({ queryKey: ['notion-prioritized'] });
      qc.invalidateQueries({ queryKey: ['email-prioritized'] });
      qc.invalidateQueries({ queryKey: ['ramp-prioritized'] });
      qc.invalidateQueries({ queryKey: ['news-prioritized'] });
      qc.invalidateQueries({ queryKey: ['drive-prioritized'] });
      qc.invalidateQueries({ queryKey: ['obsidian-prioritized'] });
      qc.invalidateQueries({ queryKey: ['github-pulls'] });
      qc.invalidateQueries({ queryKey: ['meetings'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      pushUndo({
        label: `${source} item dismissed`,
        undo: async () => {
          await api.post('/dashboard/undismiss', { source, item_id });
          qc.invalidateQueries({ queryKey: ['slack-prioritized'] });
          qc.invalidateQueries({ queryKey: ['notion-prioritized'] });
          qc.invalidateQueries({ queryKey: ['email-prioritized'] });
          qc.invalidateQueries({ queryKey: ['ramp-prioritized'] });
          qc.invalidateQueries({ queryKey: ['news-prioritized'] });
          qc.invalidateQueries({ queryKey: ['drive-prioritized'] });
          qc.invalidateQueries({ queryKey: ['obsidian-prioritized'] });
          qc.invalidateQueries({ queryKey: ['github-pulls'] });
          qc.invalidateQueries({ queryKey: ['meetings'] });
          qc.invalidateQueries({ queryKey: ['dashboard'] });
        },
      });
    },
    onError: (_err, _vars, context) => {
      if (context?.snapshots) {
        for (const [key, data] of context.snapshots) {
          qc.setQueryData(key, data);
        }
      }
    },
  });
}

// --- Claude Sessions ---

export function useClaudeSessions() {
  return useQuery({
    queryKey: ['claude-sessions'],
    queryFn: () => api.get<ClaudeSession[]>('/claude/sessions'),
  });
}

export function useClaudeSessionContent(id: number | null) {
  return useQuery({
    queryKey: ['claude-session-content', id],
    queryFn: () => api.get<ClaudeSessionContent>(`/claude/sessions/${id}/content`),
    enabled: !!id,
  });
}

export function useSaveClaudeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (session: {
      title?: string;
      content: string;
      plain_text?: string;
      rows?: number;
      cols?: number;
    }) => api.post<ClaudeSession>('/claude/sessions', session),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['claude-sessions'] });
    },
  });
}

export function useUpdateClaudeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...update }: { id: number; title?: string }) =>
      api.patch<ClaudeSession>(`/claude/sessions/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['claude-sessions'] });
    },
  });
}

export function useDeleteClaudeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/claude/sessions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['claude-sessions'] });
      qc.invalidateQueries({ queryKey: ['claude-session-content'] });
    },
  });
}

export function useCreateNoteFromSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: number) => api.post<Note>(`/claude/sessions/${sessionId}/create_note`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

// --- Profile & Setup ---

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get<UserProfile>('/profile'),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<UserProfile>) => api.patch<UserProfile>('/profile', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['profile'] }),
  });
}

export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup-status'],
    queryFn: () => api.get<SetupStatus>('/profile/setup-status'),
  });
}

export function useCompleteSetup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/profile/complete-setup', {}),
    onSuccess: () => {
      qc.setQueryData(['setup-status'], { setup_complete: true });
    },
  });
}

export function useResetData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/profile/reset', {}),
    onSuccess: () => qc.clear(),
  });
}

export function useBackupDatabase() {
  return useMutation({
    mutationFn: () => api.post<{ backup_path: string; size_bytes: number }>('/profile/backup', {}),
  });
}

// --- Connectors ---

export function useConnectors() {
  return useQuery({
    queryKey: ['connectors'],
    queryFn: () => api.get<ConnectorInfo[]>('/auth/connectors'),
  });
}

export function useToggleConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.post(`/auth/connectors/${id}/${enabled ? 'enable' : 'disable'}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

export function useSetGoogleAccessMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: 'readonly' | 'readwrite') =>
      api.post<{ status: string; mode: string; needs_reauth: boolean }>('/auth/google/access-mode', { mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

// --- Secrets ---

export function useSecrets() {
  return useQuery({
    queryKey: ['secrets'],
    queryFn: () => api.get<SecretsStatus>('/auth/secrets'),
  });
}

export function useUpdateSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      api.post('/auth/secrets', { key, value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['secrets'] });
      qc.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

export function useDeleteSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.delete(`/auth/secrets/${key}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['secrets'] });
      qc.invalidateQueries({ queryKey: ['auth-status'] });
    },
  });
}

// --- Personas ---

export function usePersonas() {
  return useQuery({
    queryKey: ['personas'],
    queryFn: () => api.get<Persona[]>('/personas'),
  });
}

export function useCreatePersona() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (persona: {
      name: string;
      description?: string;
      system_prompt?: string;
    }) => api.post<Persona>('/personas', persona),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['personas'] }),
  });
}

export function useUpdatePersona() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...update
    }: {
      id: number;
      name?: string;
      description?: string;
      system_prompt?: string;
    }) => api.patch<Persona>(`/personas/${id}`, update),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['personas'] }),
  });
}

export function useDeletePersona() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/personas/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['personas'] }),
  });
}

export function useUploadPersonaAvatar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) =>
      api.upload(`/personas/${id}/avatar`, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['personas'] }),
  });
}

// --- Memory ---

export function useMemoryEntries(limit = 50) {
  return useQuery({
    queryKey: ['memory', limit],
    queryFn: () => api.get<MemoryEntry[]>(`/memory?limit=${limit}`),
  });
}

export function useMemorySummary() {
  return useQuery({
    queryKey: ['memory-summary'],
    queryFn: () => api.get<MemorySummary>('/memory/summary'),
  });
}

export function useCompactMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<MemoryEntry>('/memory/compact', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory'] });
      qc.invalidateQueries({ queryKey: ['memory-summary'] });
    },
  });
}

export function useRebuildMemorySummary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<MemorySummary>('/memory/rebuild-summary', {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory-summary'] });
    },
  });
}

export function useDeleteMemoryEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/memory/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory'] });
    },
  });
}

export function useSearchMemory(q: string) {
  return useQuery({
    queryKey: ['memory-search', q],
    queryFn: () => api.get<MemoryEntry[]>(`/memory/search?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
  });
}

// --- All Items (paginated from synced DB) ---

const ALL_ITEMS_PAGE_SIZE = 30;

export interface AllTabSearchParams {
  q?: string;
  author?: string;
  from_date?: string;
  to_date?: string;
}

function buildAllQS(pageParam: number, params: AllTabSearchParams, authorKey = 'author'): string {
  const qs = new URLSearchParams({ offset: String(pageParam), limit: String(ALL_ITEMS_PAGE_SIZE) });
  if (params.q) qs.set('q', params.q);
  if (params.author) qs.set(authorKey, params.author);
  if (params.from_date) qs.set('from_date', params.from_date);
  if (params.to_date) qs.set('to_date', params.to_date);
  return qs.toString();
}

export function useAllEmails(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-emails', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<Email>>(`/gmail/all?${buildAllQS(pageParam, params, 'from_email')}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function useAllSlack(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-slack', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<SlackMessage>>(`/slack/all?${buildAllQS(pageParam, params)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function useAllNotion(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-notion', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<NotionPage>>(`/notion/all?${buildAllQS(pageParam, params)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function useObsidianVault() {
  return useQuery({
    queryKey: ['obsidian-vault'],
    queryFn: () => api.get<{ configured_path: string | null; detected_path: string | null; active_path: string | null }>('/obsidian/vault'),
    staleTime: 60 * 60 * 1000,
  });
}

export function useAllObsidian(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-obsidian', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<ObsidianNote>>(`/obsidian/all?${buildAllQS(pageParam, params)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function useAllGitHub(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-github', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<GitHubPullRequest>>(`/github/all?${buildAllQS(pageParam, params)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

export function usePrioritizedGitHub() {
  return useQuery({
    queryKey: ['github-prioritized'],
    queryFn: () => api.get<PrioritizedGitHubData>('/github/prioritized'),
    staleTime: 10 * 60 * 1000,
  });
}

export function useRefreshPrioritizedGitHub() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.get<PrioritizedGitHubData>('/github/prioritized?refresh=true'),
    onSuccess: (data) => {
      qc.setQueryData<PrioritizedGitHubData>(['github-prioritized'], data);
      if (data.stale) {
        setTimeout(() => qc.invalidateQueries({ queryKey: ['github-prioritized'] }), 3000);
        setTimeout(() => qc.invalidateQueries({ queryKey: ['github-prioritized'] }), 8000);
      }
    },
  });
}

export function useAllDriveFiles(params: AllTabSearchParams = {}) {
  return useInfiniteQuery({
    queryKey: ['all-drive', params],
    queryFn: ({ pageParam = 0 }) =>
      api.get<PaginatedResponse<DriveFile>>(`/drive/all?${buildAllQS(pageParam, params)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
  });
}

// --- WhatsApp ---

export function useWhatsAppStatus() {
  return useQuery({
    queryKey: ['whatsapp-status'],
    queryFn: () => api.get<WhatsAppStatus>('/whatsapp/status'),
    refetchInterval: 10000,
  });
}

export function useWhatsAppQR(enabled = false) {
  return useQuery({
    queryKey: ['whatsapp-qr'],
    queryFn: () => api.get<WhatsAppQR>('/whatsapp/qr'),
    refetchInterval: 3000,
    enabled,
  });
}

// --- Agent Chat ---

export function useAgentConversations() {
  return useQuery({
    queryKey: ['agent-conversations'],
    queryFn: () => api.get<AgentConversation[]>('/agent/conversations?saved=1'),
  });
}

export function useAgentMessages(conversationId: number | null) {
  return useQuery({
    queryKey: ['agent-messages', conversationId],
    queryFn: () => api.get<AgentMessage[]>(`/agent/conversations/${conversationId}/messages`),
    enabled: conversationId !== null,
  });
}

export function useCreateAgentConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) =>
      api.post<AgentConversation>('/agent/conversations', title ? { title } : {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-conversations'] });
    },
  });
}

export function useUpdateAgentConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api.patch<AgentConversation>(`/agent/conversations/${id}`, { title }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-conversations'] });
    },
  });
}

export function useDeleteAgentConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/agent/conversations/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-conversations'] });
    },
  });
}

export function useSaveAgentConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title?: string }) =>
      api.post<AgentConversation>(`/agent/conversations/${id}/save`, title ? { title } : {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-conversations'] });
    },
  });
}

// --- Sandbox ---

export function useSandboxApps() {
  return useQuery({
    queryKey: ['sandbox-apps'],
    queryFn: () => api.get<SandboxApp[]>('/sandbox/apps'),
  });
}

export function useCreateSandboxApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.post<SandboxApp>('/sandbox/apps', data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sandbox-apps'] });
    },
  });
}

export function useRenameSandboxApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...update }: { id: string; name?: string; description?: string }) =>
      api.patch<SandboxApp>(`/sandbox/apps/${id}`, update),
    onSuccess: (updated, { id: oldId }) => {
      qc.setQueryData<SandboxApp[]>(['sandbox-apps'], (old) =>
        old?.map((a) => (a.id === oldId ? updated : a)),
      );
      qc.invalidateQueries({ queryKey: ['sandbox-apps'] });
    },
  });
}

export function useDeleteSandboxApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/sandbox/apps/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sandbox-apps'] });
    },
  });
}
