import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from '@tanstack/react-query';
import { api } from './client';
import { pushUndo } from '../hooks/useUndo';
import type {
  Employee,
  EmployeeDetail,
  Note,
  Issue,
  MeetingSearchResult,
  OneOnOneNote,
  DashboardData,
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
  MeetingsResponse,
  PrioritizedSlackData,
  PrioritizedNotionData,
  PrioritizedEmailData,
  EmailThreadDetail,
  RampData,
  RampBillsResponse,
  Project,
  ProjectsResponse,
  PrioritizedNewsData,
  ClaudeSession,
  ClaudeSessionContent,
} from './types';

export function useEmployees() {
  return useQuery({
    queryKey: ['employees'],
    queryFn: () => api.get<Employee[]>('/employees'),
  });
}

export function useEmployee(id: string) {
  return useQuery({
    queryKey: ['employee', id],
    queryFn: () => api.get<EmployeeDetail>(`/employees/${id}`),
    enabled: !!id,
  });
}

export function useNotes(filters?: {
  status?: string;
  employee_id?: string;
  is_one_on_one?: boolean;
}) {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.employee_id) params.set('employee_id', filters.employee_id);
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
      employee_id?: string;
      employee_ids?: string[];
      is_one_on_one?: boolean;
      due_date?: string;
    }) => api.post<Note>('/notes', note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notes'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['employee'] });
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
      qc.invalidateQueries({ queryKey: ['employee'] });
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
      const prev = qc.getQueryData<PrioritiesData>(['priorities']);
      if (prev) {
        qc.setQueryData<PrioritiesData>(['priorities'], {
          ...prev,
          items: prev.items.filter((item) => item.title !== title),
        });
      }
      return { prev };
    },
    onSuccess: (_data, { title }) => {
      pushUndo({
        label: 'priority dismissed',
        undo: async () => {
          await api.post('/priorities/undismiss', { title });
          qc.invalidateQueries({ queryKey: ['priorities'] });
        },
      });
    },
    onError: (_err, _vars, context) => {
      if (context?.prev) qc.setQueryData(['priorities'], context.prev);
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
      // Update all dashboard query cache entries (any days value)
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
  return useMutation({
    mutationFn: () => api.post('/sync'),
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
  employee_id?: string;
  priority?: number;
  tshirt_size?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.status) params.set('status', filters.status);
  if (filters?.employee_id) params.set('employee_id', filters.employee_id);
  if (filters?.priority !== undefined) params.set('priority', String(filters.priority));
  if (filters?.tshirt_size) params.set('tshirt_size', filters.tshirt_size);
  const qs = params.toString();
  return useQuery({
    queryKey: ['issues', filters],
    queryFn: () => api.get<Issue[]>(`/issues${qs ? `?${qs}` : ''}`),
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
      employee_ids?: string[];
      meeting_ids?: { ref_type: string; ref_id: string }[];
    }) => api.post<Issue>('/issues', issue),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['employee'] });
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
      employee_ids?: string[];
      meeting_ids?: { ref_type: string; ref_id: string }[];
    }) => api.patch<Issue>(`/issues/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['issues'] });
      qc.invalidateQueries({ queryKey: ['employee'] });
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
      qc.invalidateQueries({ queryKey: ['employee'] });
      qc.invalidateQueries({ queryKey: ['search'] });
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

// --- Employee CRUD ---

export function useCreateEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (emp: {
      name: string;
      title?: string;
      reports_to?: string | null;
      group_name?: string;
      email?: string;
    }) => api.post<Employee>('/employees', emp),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees'] });
    },
  });
}

export function useUpdateEmployee() {
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
    }) => api.patch<Employee>(`/employees/${id}`, update),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['employees'] });
      qc.invalidateQueries({ queryKey: ['employee', vars.id] });
    },
  });
}

export function useDeleteEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/employees/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['employees'] });
    },
  });
}

// --- 1:1 Notes CRUD ---

export function useCreateOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      employeeId,
      ...note
    }: {
      employeeId: string;
      meeting_date: string;
      title?: string;
      content: string;
    }) => api.post<OneOnOneNote>(`/employees/${employeeId}/one-on-one-notes`, note),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['employee', vars.employeeId] });
    },
  });
}

export function useUpdateOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      employeeId,
      id,
      ...update
    }: {
      employeeId: string;
      id: number;
      meeting_date?: string;
      title?: string;
      content?: string;
    }) => api.patch<OneOnOneNote>(`/employees/${employeeId}/one-on-one-notes/${id}`, update),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['employee', vars.employeeId] });
    },
  });
}

export function useDeleteOneOnOneNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ employeeId, id }: { employeeId: string; id: number }) =>
      api.delete(`/employees/${employeeId}/one-on-one-notes/${id}`),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['employee', vars.employeeId] });
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

export function useUpsertMeetingNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      refType,
      refId,
      content,
    }: {
      refType: 'calendar' | 'granola';
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
      refType: 'calendar' | 'granola';
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
    },
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
    onSuccess: (_data, { source, item_id }) => {
      qc.invalidateQueries({ queryKey: ['slack-prioritized'] });
      qc.invalidateQueries({ queryKey: ['notion-prioritized'] });
      qc.invalidateQueries({ queryKey: ['email-prioritized'] });
      qc.invalidateQueries({ queryKey: ['ramp-prioritized'] });
      qc.invalidateQueries({ queryKey: ['news-prioritized'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      pushUndo({
        label: `${source} item dismissed`,
        undo: async () => {
          await api.post('/dashboard/undismiss', { source, item_id });
          qc.invalidateQueries({ queryKey: ['slack-prioritized'] });
          qc.invalidateQueries({ queryKey: ['notion-prioritized'] });
          qc.invalidateQueries({ queryKey: ['email-prioritized'] });
          qc.invalidateQueries({ queryKey: ['ramp-prioritized'] });
          qc.invalidateQueries({ queryKey: ['dashboard'] });
        },
      });
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
