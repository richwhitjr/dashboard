import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useIsFetching } from '@tanstack/react-query';
import { Sidebar } from './components/layout/Sidebar';
import { ErrorLogPanel } from './components/ErrorLogPanel';
import { SearchOverlay } from './components/SearchOverlay';
import { KeyboardHelp } from './components/KeyboardHelp';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { UndoToast, getUndoTrigger } from './components/UndoToast';
import { SyncProgressOverlay } from './components/SyncProgressOverlay';
import { IssueDiscoveryOverlay, type DiscoveryPhase } from './components/IssueDiscoveryOverlay';
import { useSync, useSetupStatus } from './api/hooks';
import { BriefingPage } from './pages/BriefingPage';
import { NotePage } from './pages/NotePage';
import { PersonPage } from './pages/PersonPage';
import { OrgTreePage } from './pages/OrgTreePage';
import { NewsPage } from './pages/NewsPage';
import { SettingsPage } from './pages/SettingsPage';
import { ClaudePage } from './pages/ClaudePage';
import { ThoughtsPage } from './pages/ThoughtsPage';
import { GitHubPage } from './pages/GitHubPage';
import { MeetingsPage } from './pages/MeetingsPage';
import { IssuesPage } from './pages/IssuesPage';
import { LongformPage } from './pages/LongformPage';
import { PrioritiesPage } from './pages/PrioritiesPage';
import { SlackPage } from './pages/SlackPage';
import { NotionPage } from './pages/NotionPage';
import { EmailPage } from './pages/EmailPage';
import { RampPage } from './pages/RampPage';
import { HelpPage } from './pages/HelpPage';
import { SetupPage } from './pages/SetupPage';
import { PersonasPage } from './pages/PersonasPage';
import { DrivePage } from './pages/DrivePage';
import { PeoplePage } from './pages/PeoplePage';
import './styles/tufte.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function RootRedirect() {
  const { data: setupStatus, isLoading } = useSetupStatus();
  if (isLoading) return null;
  if (setupStatus && !setupStatus.setup_complete) {
    return <Navigate to="/setup" replace />;
  }
  return <BriefingPage />;
}

function AppContent() {
  const location = useLocation();
  const navigate = useNavigate();
  const sync = useSync();
  const isFetching = useIsFetching();
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [discoveryPhase, setDiscoveryPhase] = useState<DiscoveryPhase>('hidden');
  const isClaudePage = location.pathname === '/claude';
  const isSetupPage = location.pathname === '/setup';

  useKeyboardShortcuts({
    navigate,
    onSearchOpen: () => setSearchOpen(prev => !prev),
    onHelpOpen: () => setHelpOpen(prev => !prev),
    onRefresh: () => queryClient.invalidateQueries(),
    onUndo: () => { getUndoTrigger()?.(); },
    onSync: () => sync.mutate(),
    onDiscoverIssues: () => {
      if (discoveryPhase === 'hidden') {
        setDiscoveryPhase('scanning');
      } else if (discoveryPhase === 'ready') {
        setDiscoveryPhase('reviewing');
      }
    },
    suppressWhen: searchOpen || helpOpen || discoveryPhase === 'reviewing',
  });

  // Setup page gets full-width layout without sidebar
  if (isSetupPage) {
    return (
      <main className="main" style={{ marginLeft: 0 }}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
        </Routes>
      </main>
    );
  }

  return (
    <>
      <div className="app-layout">
        <Sidebar />
        <main className="main">
          <Routes>
            <Route path="/help" element={<HelpPage />} />
            <Route path="/" element={<RootRedirect />} />
            <Route path="/priorities" element={<PrioritiesPage />} />
            <Route path="/notes" element={<NotePage />} />
            <Route path="/thoughts" element={<ThoughtsPage />} />
            <Route path="/issues" element={<IssuesPage />} />
            <Route path="/longform" element={<LongformPage />} />
            <Route path="/meetings" element={<MeetingsPage />} />
            <Route path="/news" element={<NewsPage />} />
            <Route path="/team" element={<OrgTreePage />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/people/:id" element={<PersonPage />} />
            <Route path="/employees/:id" element={<PersonPage />} /> {/* backward compat redirect */}
            <Route path="/github" element={<GitHubPage />} />
            <Route path="/email" element={<EmailPage />} />
            <Route path="/slack" element={<SlackPage />} />
            <Route path="/notion" element={<NotionPage />} />
            <Route path="/drive" element={<DrivePage />} />
            <Route path="/ramp" element={<RampPage />} />
            <Route path="/ramp/bills" element={<RampPage />} />
            <Route path="/ramp/projects" element={<RampPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/personas" element={<PersonasPage />} />
            <Route path="/claude" element={null} />
          </Routes>
          <div style={{ display: isClaudePage ? 'contents' : 'none' }}>
            <ClaudePage visible={isClaudePage} overlayOpen={searchOpen || helpOpen} />
          </div>
        </main>
      </div>
      <SyncProgressOverlay />
      <IssueDiscoveryOverlay phase={discoveryPhase} onPhaseChange={setDiscoveryPhase} />
      <ErrorLogPanel />
      <SearchOverlay
        isOpen={searchOpen}
        onClose={() => setSearchOpen(false)}
        onHelpOpen={() => { setSearchOpen(false); setHelpOpen(true); }}
      />
      <KeyboardHelp isOpen={helpOpen} onClose={() => setHelpOpen(false)} />
      <UndoToast />
      {isFetching > 0 && (
        <div className="global-fetch-indicator" aria-label="Loading data">
          <svg width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 14" />
          </svg>
        </div>
      )}
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
