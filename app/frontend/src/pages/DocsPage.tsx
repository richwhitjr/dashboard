import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import {
  useLongformPosts,
  useLongformPost,
  useCreateLongform,
  useUpdateLongform,
  useDeleteLongform,
  useLongformTags,
  useDocsFolders,
  useCreateLongformComment,
  useDeleteLongformComment,
  useAIEditLongform,
  usePeople,
  useConnectors,
  useExportDocToNotion,
  useExportDocToGoogleDocs,
} from '../api/hooks';
import type { LongformComment, LongformPost } from '../api/types';
import { MarkdownRenderer } from '../components/shared/MarkdownRenderer';
import { TimeAgo } from '../components/shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import { KeyboardHints } from '../components/shared/KeyboardHints';

// --- Folder tree data model ---

interface FolderTreeNode {
  name: string;       // last path segment, e.g. "studio"
  path: string;       // full path, e.g. "prds/studio"
  count: number;      // docs with exactly this folder
  totalCount: number; // docs in this folder + all descendants
  children: FolderTreeNode[];
  isPending?: boolean;
}

function buildFolderTree(
  folders: { name: string; count: number }[],
  pendingFolders: string[] = [],
): FolderTreeNode[] {
  // Merge real + pending paths
  const pathMap = new Map<string, { count: number; isPending: boolean }>();
  for (const f of folders) {
    if (f.name) pathMap.set(f.name, { count: f.count, isPending: false });
  }
  for (const p of pendingFolders) {
    if (p && !pathMap.has(p)) pathMap.set(p, { count: 0, isPending: true });
  }

  // Build tree top-down
  const roots: FolderTreeNode[] = [];
  const nodeMap = new Map<string, FolderTreeNode>();

  // Process paths sorted so shorter paths come first
  const sorted = [...pathMap.keys()].sort();

  for (const path of sorted) {
    const segments = path.split('/');
    let parent: FolderTreeNode | null = null;

    for (let i = 0; i < segments.length; i++) {
      const currentPath = segments.slice(0, i + 1).join('/');
      if (!nodeMap.has(currentPath)) {
        const info = pathMap.get(currentPath);
        const node: FolderTreeNode = {
          name: segments[i],
          path: currentPath,
          count: info?.count ?? 0,
          totalCount: 0,
          children: [],
          isPending: info?.isPending ?? false,
        };
        nodeMap.set(currentPath, node);
        if (parent) {
          parent.children.push(node);
        } else {
          roots.push(node);
        }
      }
      parent = nodeMap.get(currentPath)!;
    }
  }

  // Compute totalCount bottom-up
  function computeTotal(node: FolderTreeNode): number {
    node.children.sort((a, b) => a.name.localeCompare(b.name));
    const childTotal = node.children.reduce((sum, c) => sum + computeTotal(c), 0);
    node.totalCount = node.count + childTotal;
    return node.totalCount;
  }
  roots.sort((a, b) => a.name.localeCompare(b.name));
  for (const root of roots) computeTotal(root);

  return roots;
}

function getNodeAtPath(nodes: FolderTreeNode[], pathSegments: string[]): FolderTreeNode | null {
  if (pathSegments.length === 0) return null;
  for (const node of nodes) {
    if (node.name === pathSegments[0]) {
      if (pathSegments.length === 1) return node;
      return getNodeAtPath(node.children, pathSegments.slice(1));
    }
  }
  return null;
}

// --- FolderPicker (for DocDetail) ---

function FolderPicker({
  value,
  folders,
  onChange,
}: {
  value: string | null;
  folders: { name: string; count: number }[];
  onChange: (folder: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [customInput, setCustomInput] = useState('');
  const tree = useMemo(() => buildFolderTree(folders), [folders]);

  const close = () => { setOpen(false); setCustomInput(''); };

  function renderPickerNode(node: FolderTreeNode, depth: number): React.ReactNode {
    return (
      <div key={node.path}>
        <div
          className={`docs-folder-picker-option ${value === node.path ? 'selected' : ''}`}
          style={{ paddingLeft: `${0.7 + depth * 1.2}rem` }}
          onMouseDown={(e) => { e.preventDefault(); onChange(node.path); close(); }}
        >
          <span className="docs-folder-picker-icon">▸</span>
          {node.name}
          {node.totalCount > 0 && (
            <span className="docs-folder-count" style={{ marginLeft: '0.4rem' }}>{node.totalCount}</span>
          )}
        </div>
        {node.children.map((c) => renderPickerNode(c, depth + 1))}
      </div>
    );
  }

  return (
    <div className="docs-folder-picker">
      <button
        className="docs-folder-picker-btn"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        {value || <span style={{ color: '#aaa' }}>No folder</span>}
        <span className="docs-folder-picker-chevron">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="docs-folder-picker-dropdown">
          <div
            className={`docs-folder-picker-option clear ${!value ? 'selected' : ''}`}
            onMouseDown={(e) => { e.preventDefault(); onChange(null); close(); }}
          >
            No folder
          </div>
          {tree.map((node) => renderPickerNode(node, 0))}
          <div className="docs-folder-picker-custom">
            <input
              className="docs-folder-picker-input"
              placeholder="Type a new path…"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && customInput.trim()) {
                  onChange(customInput.trim());
                  close();
                }
                if (e.key === 'Escape') close();
              }}
              autoFocus
            />
          </div>
        </div>
      )}
      {open && (
        <div
          className="docs-folder-picker-backdrop"
          onMouseDown={() => close()}
        />
      )}
    </div>
  );
}

// --- FolderTreePanel (left panel for list view) ---

function FolderTreeNodeRow({
  node,
  depth,
  selectedFolder,
  expandedFolders,
  dragOverFolder,
  onSelect,
  onToggleExpand,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  node: FolderTreeNode;
  depth: number;
  selectedFolder: string;
  expandedFolders: Set<string>;
  dragOverFolder: string | null;
  onSelect: (path: string) => void;
  onToggleExpand: (path: string) => void;
  onDragOver: (e: React.DragEvent, path: string) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent, path: string) => void;
}) {
  const isExpanded = expandedFolders.has(node.path);
  const isSelected = selectedFolder === node.path;
  const isDragOver = dragOverFolder === node.path;
  const hasChildren = node.children.length > 0;

  return (
    <>
      <div
        className={`docs-folder-item${isSelected ? ' active' : ''}${isDragOver ? ' drag-over' : ''}${node.isPending ? ' pending' : ''}`}
        style={{ paddingLeft: `${0.5 + depth * 1.1}rem` }}
        onClick={() => onSelect(node.path)}
        onDragOver={(e) => onDragOver(e, node.path)}
        onDragLeave={onDragLeave}
        onDrop={(e) => onDrop(e, node.path)}
      >
        {hasChildren ? (
          <button
            className="docs-folder-expand-btn"
            onClick={(e) => { e.stopPropagation(); onToggleExpand(node.path); }}
          >
            {isExpanded ? '▾' : '▸'}
          </button>
        ) : (
          <span className="docs-folder-expand-placeholder" />
        )}
        <span className="docs-folder-name" title={node.path}>{node.name}</span>
        <span className="docs-folder-count">{node.totalCount || ''}</span>
      </div>
      {isExpanded && hasChildren && node.children.map((child) => (
        <FolderTreeNodeRow
          key={child.path}
          node={child}
          depth={depth + 1}
          selectedFolder={selectedFolder}
          expandedFolders={expandedFolders}
          dragOverFolder={dragOverFolder}
          onSelect={onSelect}
          onToggleExpand={onToggleExpand}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        />
      ))}
    </>
  );
}

function FolderTreePanel({
  tree,
  selectedFolder,
  expandedFolders,
  dragOverFolder,
  totalDocCount,
  onSelect,
  onToggleExpand,
  onDragOver,
  onDragLeave,
  onDrop,
  onNewFolder,
}: {
  tree: FolderTreeNode[];
  selectedFolder: string;
  expandedFolders: Set<string>;
  dragOverFolder: string | null;
  totalDocCount: number;
  onSelect: (path: string) => void;
  onToggleExpand: (path: string) => void;
  onDragOver: (e: React.DragEvent, path: string) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent, path: string) => void;
  onNewFolder: (path: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  const handleSubmit = () => {
    const trimmed = newName.trim();
    if (trimmed) onNewFolder(trimmed);
    setNewName('');
    setAdding(false);
  };

  return (
    <div className="docs-folder-panel">
      {/* All docs */}
      <div
        className={`docs-folder-item${selectedFolder === '' ? ' active' : ''}${dragOverFolder === '' ? ' drag-over' : ''}`}
        onClick={() => onSelect('')}
        onDragOver={(e) => onDragOver(e, '')}
        onDragLeave={onDragLeave}
        onDrop={(e) => onDrop(e, '')}
      >
        <span className="docs-folder-expand-placeholder" />
        <span className="docs-folder-name">All docs</span>
        <span className="docs-folder-count">{totalDocCount || ''}</span>
      </div>
      {/* No folder */}
      <div
        className={`docs-folder-item${selectedFolder === '__root__' ? ' active' : ''}${dragOverFolder === '__root__' ? ' drag-over' : ''}`}
        onClick={() => onSelect('__root__')}
        onDragOver={(e) => onDragOver(e, '__root__')}
        onDragLeave={onDragLeave}
        onDrop={(e) => onDrop(e, '__root__')}
        style={{ opacity: 0.7 }}
      >
        <span className="docs-folder-expand-placeholder" />
        <span className="docs-folder-name" style={{ fontStyle: 'italic' }}>No folder</span>
      </div>
      {/* Tree */}
      {tree.map((node) => (
        <FolderTreeNodeRow
          key={node.path}
          node={node}
          depth={0}
          selectedFolder={selectedFolder}
          expandedFolders={expandedFolders}
          dragOverFolder={dragOverFolder}
          onSelect={onSelect}
          onToggleExpand={onToggleExpand}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        />
      ))}
      {/* New folder */}
      {adding ? (
        <div className="docs-folder-new-input-row">
          <input
            ref={inputRef}
            className="docs-folder-new-input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="folder name"
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSubmit();
              if (e.key === 'Escape') { setAdding(false); setNewName(''); }
            }}
            onBlur={() => { if (!newName.trim()) { setAdding(false); setNewName(''); } }}
          />
        </div>
      ) : (
        <button className="docs-folder-add-btn" onClick={() => setAdding(true)} title="New folder">+</button>
      )}
    </div>
  );
}

// --- FilesystemView ---

function FilesystemView({
  tree,
  fsPath,
  allDocs,
  pendingFolders,
  dragOverFolder,
  onNavigate,
  onOpenDoc,
  onNewFolder,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  tree: FolderTreeNode[];
  fsPath: string[];
  allDocs: LongformPost[];
  pendingFolders: string[];
  dragOverFolder: string | null;
  onNavigate: (segments: string[]) => void;
  onOpenDoc: (id: number) => void;
  onNewFolder: (name: string) => void;
  onDragOver: (e: React.DragEvent, path: string) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent, path: string) => void;
}) {
  const [addingFolder, setAddingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const newFolderRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (addingFolder) newFolderRef.current?.focus();
  }, [addingFolder]);

  const currentPathStr = fsPath.join('/');

  // Subfolders at current level
  const currentNode = fsPath.length === 0 ? null : getNodeAtPath(tree, fsPath);
  const subfolders: FolderTreeNode[] = fsPath.length === 0 ? tree : (currentNode?.children ?? []);

  // Pending folders at current level
  const pendingAtLevel = pendingFolders
    .filter((p) => {
      const prefix = currentPathStr ? currentPathStr + '/' : '';
      if (!p.startsWith(prefix)) return false;
      const rest = p.slice(prefix.length);
      return rest.length > 0 && !rest.includes('/');
    })
    .filter((p) => !subfolders.some((s) => s.path === p));

  // Docs at current level (exact folder match)
  const docsAtLevel = allDocs.filter((d) => {
    const docFolder = d.folder || '';
    return docFolder === currentPathStr;
  });

  const handleSubmitNewFolder = () => {
    const name = newFolderName.trim();
    if (!name || name.includes('/')) return;
    const fullPath = currentPathStr ? `${currentPathStr}/${name}` : name;
    onNewFolder(fullPath);
    setNewFolderName('');
    setAddingFolder(false);
  };

  return (
    <div className="docs-fs-container">
      {/* Breadcrumb */}
      <nav className="docs-breadcrumb">
        <span className="docs-breadcrumb-home" onClick={() => onNavigate([])}>Home</span>
        {fsPath.map((seg, i) => (
          <span key={i}>
            <span className="docs-breadcrumb-sep"> / </span>
            <span
              className="docs-breadcrumb-seg"
              onClick={() => onNavigate(fsPath.slice(0, i + 1))}
            >
              {seg}
            </span>
          </span>
        ))}
      </nav>

      {/* New folder row */}
      <div className="docs-fs-new-folder-row">
        {addingFolder ? (
          <>
            <input
              ref={newFolderRef}
              className="docs-fs-new-folder-input"
              placeholder="Folder name…"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSubmitNewFolder();
                if (e.key === 'Escape') { setAddingFolder(false); setNewFolderName(''); }
              }}
              onBlur={() => setTimeout(() => { setAddingFolder(false); setNewFolderName(''); }, 150)}
            />
            <button className="docs-fs-new-folder-confirm" onMouseDown={(e) => { e.preventDefault(); handleSubmitNewFolder(); }}>
              Add
            </button>
          </>
        ) : (
          <button className="docs-fs-new-folder-btn" onClick={() => setAddingFolder(true)}>
            + New folder
          </button>
        )}
      </div>

      {/* Subfolders grid */}
      {(subfolders.length > 0 || pendingAtLevel.length > 0) && (
        <div className="docs-fs-grid">
          {subfolders.map((node) => (
            <div
              key={node.path}
              className={`docs-fs-folder${dragOverFolder === node.path ? ' drag-over' : ''}`}
              onClick={() => onNavigate([...fsPath, node.name])}
              onDragOver={(e) => onDragOver(e, node.path)}
              onDragLeave={onDragLeave}
              onDrop={(e) => onDrop(e, node.path)}
            >
              <span className="docs-fs-folder-icon">📁</span>
              <span className="docs-fs-folder-name">{node.name}</span>
              <span className="docs-folder-count">{node.totalCount || ''}</span>
            </div>
          ))}
          {pendingAtLevel.map((path) => {
            const name = path.split('/').pop() ?? path;
            return (
              <div
                key={path}
                className={`docs-fs-folder pending${dragOverFolder === path ? ' drag-over' : ''}`}
                onDragOver={(e) => onDragOver(e, path)}
                onDragLeave={onDragLeave}
                onDrop={(e) => onDrop(e, path)}
              >
                <span className="docs-fs-folder-icon">📁</span>
                <span className="docs-fs-folder-name">{name}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Docs at this level */}
      {docsAtLevel.length > 0 ? (
        <div className="docs-fs-doc-list">
          {docsAtLevel.map((doc) => (
            <div
              key={doc.id}
              className="docs-fs-doc"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('text/doc-id', doc.id.toString());
                e.dataTransfer.effectAllowed = 'move';
              }}
              onClick={() => onOpenDoc(doc.id)}
            >
              <span className="docs-fs-doc-icon">📄</span>
              <span className="docs-fs-doc-title">{doc.title}</span>
              {doc.status === 'archived' && (
                <span className="longform-status-badge archived" style={{ marginLeft: '0.3rem', fontSize: '0.65rem' }}>archived</span>
              )}
              <span className="docs-fs-doc-date"><TimeAgo date={doc.updated_at} /></span>
            </div>
          ))}
        </div>
      ) : (
        subfolders.length === 0 && pendingAtLevel.length === 0 && (
          <p className="longform-empty" style={{ marginTop: '1rem' }}>
            {fsPath.length === 0 ? 'No unfiled docs.' : 'No docs in this folder.'}
          </p>
        )
      )}
    </div>
  );
}

// --- ExportModal ---

function ExportModal({ doc, onClose }: { doc: { id: number; title: string; body: string }; onClose: () => void }) {
  const { data: connectors } = useConnectors();
  const exportToNotion = useExportDocToNotion();
  const exportToGoogleDocs = useExportDocToGoogleDocs();

  const enabledSet = new Set((connectors || []).filter((c) => c.enabled).map((c) => c.id));
  const hasNotion = enabledSet.has('notion');
  const hasGoogleDrive = enabledSet.has('google_drive');
  const hasMicrosoftDrive = enabledSet.has('microsoft_drive');

  const [notionParentId, setNotionParentId] = useState('');
  const [notionParentType, setNotionParentType] = useState<'page_id' | 'database_id'>('page_id');
  const [googleFolderId, setGoogleFolderId] = useState('');
  const [results, setResults] = useState<Record<string, { url?: string; error?: string }>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  const handleDownloadMarkdown = useCallback(() => {
    const content = `# ${doc.title}\n\n${doc.body}`;
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doc.title.replace(/[^a-z0-9 _-]/gi, '').trim() || 'document'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [doc]);

  const handleExportPDF = useCallback(() => {
    window.open(`/api/docs/${doc.id}/export/pdf-html`, '_blank');
  }, [doc.id]);

  const handleDownloadDocx = useCallback(() => {
    window.open(`/api/docs/${doc.id}/export/docx`, '_blank');
  }, [doc.id]);

  const handleExportNotion = useCallback(async () => {
    setLoading((p) => ({ ...p, notion: true }));
    try {
      const result = await exportToNotion.mutateAsync({
        docId: doc.id,
        parentId: notionParentId.trim() || undefined,
        parentType: notionParentType,
      });
      setResults((p) => ({ ...p, notion: { url: result.url } }));
    } catch {
      setResults((p) => ({ ...p, notion: { error: 'Export failed. Check Notion token and parent ID.' } }));
    } finally {
      setLoading((p) => ({ ...p, notion: false }));
    }
  }, [doc.id, notionParentId, notionParentType, exportToNotion]);

  const handleExportGoogleDocs = useCallback(async () => {
    setLoading((p) => ({ ...p, gdocs: true }));
    try {
      const result = await exportToGoogleDocs.mutateAsync({
        docId: doc.id,
        folderId: googleFolderId.trim() || undefined,
      });
      setResults((p) => ({ ...p, gdocs: { url: result.url } }));
    } catch {
      setResults((p) => ({ ...p, gdocs: { error: 'Export failed. Check Google Drive connection.' } }));
    } finally {
      setLoading((p) => ({ ...p, gdocs: false }));
    }
  }, [doc.id, googleFolderId, exportToGoogleDocs]);

  const connectedServices = hasNotion || hasGoogleDrive || hasMicrosoftDrive;

  return (
    <div
      className="meeting-modal-overlay"
      ref={overlayRef}
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div className="meeting-modal docs-export-modal">
        <button className="meeting-modal-close" onClick={onClose}>&times;</button>
        <h3 className="docs-export-title">Export</h3>

        <div className="docs-export-section">
          <p className="docs-export-section-label">Download</p>
          <div className="docs-export-row">
            <button className="docs-export-btn" onClick={handleDownloadMarkdown}>
              ↓ Markdown (.md)
            </button>
            <button className="docs-export-btn" onClick={handleExportPDF}>
              ↓ PDF (print dialog)
            </button>
          </div>
        </div>

        {connectedServices && (
          <div className="docs-export-section">
            <p className="docs-export-section-label">Connected services</p>

            {hasNotion && (
              <div className="docs-export-service-row">
                <div className="docs-export-service-inputs">
                  <input
                    className="docs-export-input"
                    placeholder="Parent page/database ID (optional)"
                    value={notionParentId}
                    onChange={(e) => setNotionParentId(e.target.value)}
                  />
                  <select
                    className="docs-export-select"
                    value={notionParentType}
                    onChange={(e) => setNotionParentType(e.target.value as 'page_id' | 'database_id')}
                  >
                    <option value="page_id">Page</option>
                    <option value="database_id">Database</option>
                  </select>
                </div>
                <button
                  className="docs-export-btn primary"
                  onClick={handleExportNotion}
                  disabled={loading.notion}
                >
                  {loading.notion ? 'Exporting…' : '↑ Export to Notion'}
                </button>
                {results.notion?.url && (
                  <a className="docs-export-result-link" href={results.notion.url} target="_blank" rel="noopener noreferrer">
                    ✓ Opened in Notion →
                  </a>
                )}
                {results.notion?.error && <p className="docs-export-error">{results.notion.error}</p>}
              </div>
            )}

            {hasGoogleDrive && (
              <div className="docs-export-service-row">
                <input
                  className="docs-export-input"
                  placeholder="Google Drive folder ID (optional)"
                  value={googleFolderId}
                  onChange={(e) => setGoogleFolderId(e.target.value)}
                />
                <button
                  className="docs-export-btn primary"
                  onClick={handleExportGoogleDocs}
                  disabled={loading.gdocs}
                >
                  {loading.gdocs ? 'Exporting…' : '↑ Export to Google Docs'}
                </button>
                {results.gdocs?.url && (
                  <a className="docs-export-result-link" href={results.gdocs.url} target="_blank" rel="noopener noreferrer">
                    ✓ Opened in Google Docs →
                  </a>
                )}
                {results.gdocs?.error && <p className="docs-export-error">{results.gdocs.error}</p>}
              </div>
            )}

            {hasMicrosoftDrive && (
              <div className="docs-export-service-row">
                <button className="docs-export-btn" onClick={handleDownloadDocx}>
                  ↓ Word (.docx)
                </button>
                <span className="docs-export-hint">Downloads a Word-compatible file</span>
              </div>
            )}
          </div>
        )}

        {!connectedServices && (
          <p className="docs-export-hint">
            Enable Notion, Google Drive, or Microsoft OneDrive connectors in{' '}
            <a href="/settings">Settings</a> to export to those services.
          </p>
        )}
      </div>
    </div>
  );
}

// --- DocDetail ---

function DocDetail({
  docId,
  onBack,
}: {
  docId: number;
  onBack: () => void;
}) {
  const { data: doc, isLoading } = useLongformPost(docId);
  const updateDoc = useUpdateLongform();
  const deleteDoc = useDeleteLongform();
  const createComment = useCreateLongformComment();
  const deleteComment = useDeleteLongformComment();
  const { data: allTags } = useLongformTags();
  const { data: allFolders } = useDocsFolders();
  const { data: allPeople } = usePeople();
  const navigate = useNavigate();

  const [editTitle, setEditTitle] = useState('');
  const [editBody, setEditBody] = useState('');
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'split'>('edit');
  const [commentText, setCommentText] = useState('');
  const [thoughtText, setThoughtText] = useState('');
  const [tagInput, setTagInput] = useState('');
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [personInput, setPersonInput] = useState('');
  const [showPersonDropdown, setShowPersonDropdown] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showAIPanel, setShowAIPanel] = useState(false);
  const [aiHistory, setAIHistory] = useState<
    { instruction: string; commentary: string; revised_body: string }[]
  >([]);
  const [aiInstruction, setAIInstruction] = useState('');
  const [selectedText, setSelectedText] = useState('');
  const titleRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const aiEdit = useAIEditLongform();

  // Sync local state when doc loads
  const docTitle = doc?.title;
  const docBody = doc?.body;
  const docIdLoaded = doc?.id;
  useEffect(() => {
    if (docTitle !== undefined) setEditTitle(docTitle);
    if (docBody !== undefined) setEditBody(docBody);
  }, [docIdLoaded, docTitle, docBody]);

  const handleTitleBlur = useCallback(() => {
    if (doc && editTitle !== doc.title && editTitle.trim()) {
      updateDoc.mutate({ id: doc.id, title: editTitle.trim() });
    }
  }, [doc, editTitle, updateDoc]);

  const handleBodyBlur = useCallback(() => {
    if (doc && editBody !== doc.body) {
      updateDoc.mutate({ id: doc.id, body: editBody });
    }
  }, [doc, editBody, updateDoc]);

  const handleStatusToggle = useCallback(() => {
    if (!doc) return;
    updateDoc.mutate({ id: doc.id, status: doc.status === 'active' ? 'archived' : 'active' });
  }, [doc, updateDoc]);

  const handleDelete = useCallback(() => {
    if (!doc) return;
    if (confirm('Delete this doc?')) {
      deleteDoc.mutate(doc.id);
      onBack();
    }
  }, [doc, deleteDoc, onBack]);

  const handleCopyMarkdown = useCallback(() => {
    if (!doc) return;
    navigator.clipboard.writeText(`# ${doc.title}\n\n${doc.body}`);
    setCopyFeedback(true);
    setTimeout(() => setCopyFeedback(false), 2000);
  }, [doc]);

  const handleOpenInClaude = useCallback(() => {
    if (!doc) return;
    navigate(`/claude?longform=${doc.id}`);
  }, [doc, navigate]);

  const handleAddTag = useCallback((tag: string) => {
    if (!doc) return;
    const t = tag.trim().toLowerCase();
    if (t && !doc.tags.includes(t)) {
      updateDoc.mutate({ id: doc.id, tags: [...doc.tags, t] });
    }
    setTagInput('');
    setShowTagDropdown(false);
  }, [doc, updateDoc]);

  const handleRemoveTag = useCallback((tag: string) => {
    if (!doc) return;
    updateDoc.mutate({ id: doc.id, tags: doc.tags.filter((t) => t !== tag) });
  }, [doc, updateDoc]);

  const handleFolderChange = useCallback((folder: string | null) => {
    if (!doc) return;
    updateDoc.mutate({ id: doc.id, folder: folder ?? '' });
  }, [doc, updateDoc]);

  const handleAddPerson = useCallback((personId: string) => {
    if (!doc) return;
    const currentIds = (doc.people || []).map((p) => p.id);
    if (!currentIds.includes(personId)) {
      updateDoc.mutate({ id: doc.id, person_ids: [...currentIds, personId] });
    }
    setPersonInput('');
    setShowPersonDropdown(false);
  }, [doc, updateDoc]);

  const handleRemovePerson = useCallback((personId: string) => {
    if (!doc) return;
    updateDoc.mutate({ id: doc.id, person_ids: (doc.people || []).filter((p) => p.id !== personId).map((p) => p.id) });
  }, [doc, updateDoc]);

  const handleAddComment = useCallback(() => {
    if (!doc || !commentText.trim()) return;
    createComment.mutate({ postId: doc.id, text: commentText.trim(), is_thought: false });
    setCommentText('');
  }, [doc, commentText, createComment]);

  const handleAddThought = useCallback(() => {
    if (!doc || !thoughtText.trim()) return;
    createComment.mutate({ postId: doc.id, text: thoughtText.trim(), is_thought: true });
    setThoughtText('');
  }, [doc, thoughtText, createComment]);

  const handleDeleteComment = useCallback((commentId: number) => {
    if (!doc) return;
    deleteComment.mutate({ postId: doc.id, commentId });
  }, [doc, deleteComment]);

  const handleTextSelect = useCallback(() => {
    if (bodyRef.current) {
      const start = bodyRef.current.selectionStart;
      const end = bodyRef.current.selectionEnd;
      setSelectedText(start !== end ? editBody.substring(start, end) : '');
    }
  }, [editBody]);

  const handleAIEdit = useCallback(() => {
    if (!doc || !aiInstruction.trim()) return;
    aiEdit.mutate(
      {
        postId: doc.id,
        instruction: aiInstruction.trim(),
        body: editBody,
        title: editTitle,
        selected_text: selectedText,
        history: aiHistory.slice(-3).map((h) => ({ instruction: h.instruction, commentary: h.commentary })),
      },
      {
        onSuccess: (result) => {
          if (!result.error) {
            setAIHistory((prev) => [...prev, { instruction: aiInstruction.trim(), commentary: result.commentary, revised_body: result.revised_body }]);
          }
          setAIInstruction('');
          setSelectedText('');
        },
      },
    );
  }, [doc, aiInstruction, editBody, editTitle, selectedText, aiHistory, aiEdit]);

  const handleApplyAIEdit = useCallback((revisedBody: string) => {
    setEditBody(revisedBody);
    if (doc) updateDoc.mutate({ id: doc.id, body: revisedBody });
  }, [doc, updateDoc]);

  const handleSaveAsThought = useCallback((text: string) => {
    if (!doc) return;
    createComment.mutate({ postId: doc.id, text: `[AI] ${text}`, is_thought: true });
  }, [doc, createComment]);

  const filteredTags = (allTags || []).filter(
    (t) => t.includes(tagInput.toLowerCase()) && !(doc?.tags || []).includes(t),
  );
  const filteredPeople = (allPeople || []).filter(
    (p) => p.name.toLowerCase().includes(personInput.toLowerCase()) && !(doc?.people || []).some((pp) => pp.id === p.id),
  );

  if (isLoading) return <p>Loading...</p>;
  if (!doc) return <p>Doc not found.</p>;

  return (
    <div className="longform-detail">
      <div className="longform-detail-header">
        <button className="longform-back-btn" onClick={onBack}>&larr; All Docs</button>
        <div className="longform-detail-actions">
          <button className={`longform-status-toggle ${doc.status}`} onClick={handleStatusToggle}>
            {doc.status === 'active' ? 'Archive' : 'Activate'}
          </button>
          <button onClick={handleCopyMarkdown}>{copyFeedback ? 'Copied!' : 'Copy MD'}</button>
          <button onClick={() => setShowExportModal(true)}>Export</button>
          <button onClick={handleOpenInClaude}>Open in Claude</button>
          <button className="longform-delete-btn" onClick={handleDelete}>Delete</button>
        </div>
      </div>

      <input
        ref={titleRef}
        className="longform-title-input"
        value={editTitle}
        onChange={(e) => setEditTitle(e.target.value)}
        onBlur={handleTitleBlur}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); bodyRef.current?.focus(); } }}
        placeholder="Doc title..."
      />

      <div className="longform-meta">
        <span className={`longform-status-badge ${doc.status}`}>{doc.status}</span>
        <span className="longform-word-count">{doc.word_count} words</span>
        <span className="longform-date">Updated <TimeAgo date={doc.updated_at} /></span>
        {doc.claude_session_id && (
          <a href={`/claude?session=${doc.claude_session_id}`} className="longform-session-link">From Claude session</a>
        )}
      </div>

      {/* Folder picker */}
      <div className="longform-tags-row">
        <span className="longform-field-label">Folder:</span>
        <FolderPicker
          value={doc.folder || null}
          folders={allFolders ?? []}
          onChange={handleFolderChange}
        />
      </div>

      {/* Tags */}
      <div className="longform-tags-row">
        {doc.tags.map((tag) => (
          <span key={tag} className="longform-tag-badge">
            {tag}<button onClick={() => handleRemoveTag(tag)}>&times;</button>
          </span>
        ))}
        <div className="longform-tag-input-wrapper">
          <input
            className="longform-tag-input"
            placeholder="Add tag..."
            value={tagInput}
            onChange={(e) => { setTagInput(e.target.value); setShowTagDropdown(true); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && tagInput.trim()) { e.preventDefault(); handleAddTag(tagInput); }
              if (e.key === 'Escape') setShowTagDropdown(false);
            }}
            onFocus={() => setShowTagDropdown(true)}
            onBlur={() => setTimeout(() => setShowTagDropdown(false), 200)}
          />
          {showTagDropdown && filteredTags.length > 0 && (
            <div className="longform-tag-dropdown">
              {filteredTags.slice(0, 8).map((t) => (
                <div key={t} className="longform-tag-option" onMouseDown={(e) => { e.preventDefault(); handleAddTag(t); }}>{t}</div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* People */}
      <div className="longform-tags-row">
        {(doc.people || []).map((person) => (
          <span key={person.id} className="longform-tag-badge">
            <Link to={`/people/${person.id}`}>{person.name}</Link>
            <button onClick={() => handleRemovePerson(person.id)}>&times;</button>
          </span>
        ))}
        <div className="longform-tag-input-wrapper">
          <input
            className="longform-tag-input"
            placeholder="Add person..."
            value={personInput}
            onChange={(e) => { setPersonInput(e.target.value); setShowPersonDropdown(true); }}
            onKeyDown={(e) => { if (e.key === 'Escape') setShowPersonDropdown(false); }}
            onFocus={() => setShowPersonDropdown(true)}
            onBlur={() => setTimeout(() => setShowPersonDropdown(false), 200)}
          />
          {showPersonDropdown && personInput && filteredPeople.length > 0 && (
            <div className="longform-tag-dropdown">
              {filteredPeople.slice(0, 8).map((p) => (
                <div key={p.id} className="longform-tag-option" onMouseDown={(e) => { e.preventDefault(); handleAddPerson(p.id); }}>
                  {p.name}
                  {p.title && <span style={{ color: 'var(--color-text-light)', marginLeft: '0.5em' }}>{p.title}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Body editor */}
      <div className="longform-editor-toolbar">
        <button className={viewMode === 'edit' ? 'active' : ''} onClick={() => setViewMode('edit')}>Edit</button>
        <button className={viewMode === 'preview' ? 'active' : ''} onClick={() => setViewMode('preview')}>Preview</button>
        <button className={viewMode === 'split' ? 'active' : ''} onClick={() => setViewMode('split')}>Split</button>
        <button className={`longform-ai-toggle ${showAIPanel ? 'active' : ''}`} onClick={() => setShowAIPanel((v) => !v)}>
          AI Editor
        </button>
      </div>

      <div className={`longform-editor-area ${viewMode}`}>
        {(viewMode === 'edit' || viewMode === 'split') && (
          <textarea
            ref={bodyRef}
            className="longform-body-textarea"
            value={editBody}
            onChange={(e) => setEditBody(e.target.value)}
            onBlur={handleBodyBlur}
            onSelect={handleTextSelect}
            onMouseUp={handleTextSelect}
            placeholder="Write your doc in Markdown..."
          />
        )}
        {(viewMode === 'preview' || viewMode === 'split') && (
          <div className="longform-body-preview">
            <MarkdownRenderer content={editBody || '_No content yet._'} />
          </div>
        )}
      </div>

      {showAIPanel && (
        <div className="longform-ai-panel">
          <h3>AI Editor</h3>
          {aiHistory.length > 0 && (
            <div className="longform-ai-history">
              {aiHistory.map((entry, i) => (
                <div key={i} className="longform-ai-exchange">
                  <div className="longform-ai-instruction">{entry.instruction}</div>
                  <div className="longform-ai-response">
                    <MarkdownRenderer content={entry.commentary} />
                    <div className="longform-ai-actions">
                      <button onClick={() => handleApplyAIEdit(entry.revised_body)}>Apply Changes</button>
                      <button onClick={() => handleSaveAsThought(entry.commentary)}>Save as Thought</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {selectedText && (
            <div className="longform-ai-selection">
              Selected: &ldquo;{selectedText.length > 80 ? selectedText.slice(0, 80) + '...' : selectedText}&rdquo;
            </div>
          )}
          <div className="longform-ai-input">
            <input
              value={aiInstruction}
              onChange={(e) => setAIInstruction(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAIEdit(); } }}
              placeholder={selectedText ? 'How should I edit the selected text?' : "How should I edit this doc?"}
              disabled={aiEdit.isPending}
            />
            <button onClick={handleAIEdit} disabled={!aiInstruction.trim() || aiEdit.isPending}>
              {aiEdit.isPending ? 'Editing...' : 'Edit'}
            </button>
          </div>
          {aiEdit.data?.error && <div className="longform-ai-error">{aiEdit.data.error}</div>}
          {aiHistory.length > 0 && (
            <button className="longform-ai-clear" onClick={() => setAIHistory([])}>Clear history</button>
          )}
        </div>
      )}

      <div className="longform-comments-section">
        <h3>Comments ({doc.comments?.length || 0})</h3>
        {doc.comments?.map((c: LongformComment) => (
          <div key={c.id} className="longform-comment-item">
            <div className="longform-comment-text">{c.text}</div>
            <div className="longform-comment-meta">
              <TimeAgo date={c.created_at} />
              <button className="longform-comment-delete" onClick={() => handleDeleteComment(c.id)}>&times;</button>
            </div>
          </div>
        ))}
        <div className="longform-comment-add">
          <input value={commentText} onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAddComment(); } }}
            placeholder="Add a comment..." />
          <button onClick={handleAddComment} disabled={!commentText.trim()}>Add</button>
        </div>
      </div>

      <div className="longform-thoughts-section">
        <h3>Thoughts ({doc.thoughts?.length || 0})</h3>
        {doc.thoughts?.map((t: LongformComment) => (
          <div key={t.id} className="longform-comment-item thought">
            <div className="longform-comment-text">{t.text}</div>
            <div className="longform-comment-meta">
              <TimeAgo date={t.created_at} />
              <button className="longform-comment-delete" onClick={() => handleDeleteComment(t.id)}>&times;</button>
            </div>
          </div>
        ))}
        <div className="longform-comment-add">
          <input value={thoughtText} onChange={(e) => setThoughtText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAddThought(); } }}
            placeholder="Add a thought..." />
          <button onClick={handleAddThought} disabled={!thoughtText.trim()}>Add</button>
        </div>
      </div>

      {showExportModal && doc && (
        <ExportModal
          doc={{ id: doc.id, title: editTitle || doc.title, body: editBody || doc.body || '' }}
          onClose={() => setShowExportModal(false)}
        />
      )}
    </div>
  );
}

// --- DocsPage ---

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const docIdParam = searchParams.get('postId');
  const selectedDocId = docIdParam ? parseInt(docIdParam, 10) : null;

  // List view state
  const [pageViewMode, setPageViewMode] = useState<'list' | 'folders'>('list');
  const [statusFilter, setStatusFilter] = useState<string>('active');
  const [searchText, setSearchText] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [folderFilter, setFolderFilter] = useState(''); // '' = all, '__root__' = no folder, 'prds/...' = prefix
  const [sortBy, setSortBy] = useState('updated_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  // Folder tree state
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);
  const [pendingFolders, setPendingFolders] = useState<string[]>([]);

  // Filesystem view state
  const [fsPath, setFsPath] = useState<string[]>([]);

  const createDoc = useCreateLongform();
  const updateDoc = useUpdateLongform();

  const isPrefix = folderFilter !== '' && folderFilter !== '__root__';
  const { data: docs, isLoading } = useLongformPosts({
    status: statusFilter || undefined,
    tag: tagFilter || undefined,
    folder: folderFilter || undefined,
    folder_prefix: isPrefix ? true : undefined,
    search: debouncedSearch || undefined,
    sort_by: sortBy || undefined,
    sort_dir: sortDir,
  });

  // For filesystem view we need all docs regardless of folder filter
  const { data: allDocsForFs } = useLongformPosts({
    status: statusFilter || undefined,
    sort_by: 'updated_at',
    sort_dir: 'desc',
  });

  const { data: allTags } = useLongformTags();
  const { data: folders } = useDocsFolders();

  const folderTree = useMemo(
    () => buildFolderTree(folders ?? [], pendingFolders),
    [folders, pendingFolders],
  );

  const { containerRef } = useFocusNavigation({
    selector: '.longform-table-row',
    enabled: !selectedDocId && pageViewMode === 'list',
    onOpen: (i) => { if (docs?.[i]) handleSelectDoc(docs[i].id); },
  });

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchText), 400);
    return () => clearTimeout(timer);
  }, [searchText]);

  // Auto-expand path of selected folder
  useEffect(() => {
    if (!folderFilter || folderFilter === '__root__') return;
    const segments = folderFilter.split('/');
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      for (let i = 1; i <= segments.length; i++) {
        next.add(segments.slice(0, i).join('/'));
      }
      return next;
    });
  }, [folderFilter]);

  const handleNewDoc = useCallback(() => {
    const initialFolder = pageViewMode === 'folders' && fsPath.length > 0 ? fsPath.join('/') : undefined;
    createDoc.mutate({ title: 'Untitled', body: '', status: 'active', folder: initialFolder }, {
      onSuccess: (newDoc) => setSearchParams({ postId: String(newDoc.id) }),
    });
  }, [createDoc, setSearchParams, pageViewMode, fsPath]);

  const handleSelectDoc = useCallback((id: number) => {
    setSearchParams({ postId: String(id) });
  }, [setSearchParams]);

  const handleBack = useCallback(() => { setSearchParams({}); }, [setSearchParams]);

  const handleFolderSelect = useCallback((path: string) => {
    setFolderFilter(path);
  }, []);

  const handleToggleExpand = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, path: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverFolder((prev) => (prev === path ? prev : path));
  }, []);

  const handleDragLeave = useCallback(() => { setDragOverFolder(null); }, []);

  const handleDrop = useCallback((e: React.DragEvent, targetPath: string) => {
    e.preventDefault();
    setDragOverFolder(null);
    const docIdStr = e.dataTransfer.getData('text/doc-id');
    if (!docIdStr) return;
    const docId = parseInt(docIdStr, 10);
    if (isNaN(docId)) return;
    const newFolder = (targetPath === '__root__' || targetPath === '') ? '' : targetPath;
    updateDoc.mutate({ id: docId, folder: newFolder });
    setPendingFolders((prev) => prev.filter((p) => p !== targetPath));
  }, [updateDoc]);

  const handleNewFolder = useCallback((fullPath: string) => {
    if (!pendingFolders.includes(fullPath) && !(folders ?? []).some((f) => f.name === fullPath)) {
      setPendingFolders((prev) => [...prev, fullPath]);
    }
  }, [pendingFolders, folders]);

  const hasFolders = (folders && folders.length > 0) || pendingFolders.length > 0;

  if (selectedDocId) {
    return <DocDetail docId={selectedDocId} onBack={handleBack} />;
  }

  return (
    <div className="longform-page">
      <div className="longform-list-header">
        <h1>Docs</h1>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <div className="issue-view-modes">
            <button
              className={`filter-btn${pageViewMode === 'list' ? ' active' : ''}`}
              onClick={() => setPageViewMode('list')}
            >
              List
            </button>
            <button
              className={`filter-btn${pageViewMode === 'folders' ? ' active' : ''}`}
              onClick={() => setPageViewMode('folders')}
            >
              Folders
            </button>
          </div>
          <button className="longform-new-btn" onClick={handleNewDoc} disabled={createDoc.isPending}>
            + New Doc
          </button>
        </div>
      </div>

      {/* Filters (list view only) */}
      {pageViewMode === 'list' && (
        <div className="longform-filters">
          <div className="longform-status-tabs">
            {[{ value: '', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'archived', label: 'Archived' }].map((s) => (
              <button key={s.value} className={statusFilter === s.value ? 'active' : ''} onClick={() => setStatusFilter(s.value)}>
                {s.label}
              </button>
            ))}
          </div>
          <input
            className="longform-search-input"
            type="text"
            placeholder="Search docs..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          {allTags && allTags.length > 0 && (
            <select className="longform-tag-filter" value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}>
              <option value="">All tags</option>
              {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          )}
          <select
            className="longform-sort-select"
            value={`${sortBy}:${sortDir}`}
            onChange={(e) => { const [by, dir] = e.target.value.split(':'); setSortBy(by); setSortDir(dir as 'asc' | 'desc'); }}
          >
            <option value="updated_at:desc">Recently updated</option>
            <option value="created_at:desc">Newest first</option>
            <option value="created_at:asc">Oldest first</option>
            <option value="title:asc">Title A-Z</option>
            <option value="title:desc">Title Z-A</option>
            <option value="word_count:desc">Longest first</option>
            <option value="word_count:asc">Shortest first</option>
          </select>
        </div>
      )}

      {/* Folder view */}
      {pageViewMode === 'folders' && (
        <FilesystemView
          tree={folderTree}
          fsPath={fsPath}
          allDocs={allDocsForFs ?? []}
          pendingFolders={pendingFolders}
          dragOverFolder={dragOverFolder}
          onNavigate={setFsPath}
          onOpenDoc={handleSelectDoc}
          onNewFolder={handleNewFolder}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        />
      )}

      {/* List view */}
      {pageViewMode === 'list' && (
        <div className={hasFolders ? 'docs-layout-with-folders' : undefined}>
          {hasFolders && (
            <FolderTreePanel
              tree={folderTree}
              selectedFolder={folderFilter}
              expandedFolders={expandedFolders}
              dragOverFolder={dragOverFolder}
              totalDocCount={docs?.length ?? 0}
              onSelect={handleFolderSelect}
              onToggleExpand={handleToggleExpand}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onNewFolder={handleNewFolder}
            />
          )}

          <div className="docs-table-area">
            {isLoading ? (
              <p>Loading...</p>
            ) : !docs || docs.length === 0 ? (
              <p className="longform-empty">No docs yet. Click &ldquo;+ New Doc&rdquo; to get started.</p>
            ) : (
              <div ref={containerRef}>
                <table className="longform-table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Folder</th>
                      <th>Tags</th>
                      <th>Words</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((doc) => (
                      <tr
                        key={doc.id}
                        className="longform-table-row"
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData('text/doc-id', doc.id.toString());
                          e.dataTransfer.effectAllowed = 'move';
                        }}
                        onClick={() => handleSelectDoc(doc.id)}
                      >
                        <td className="longform-table-title">
                          {doc.title}
                          {(doc.comment_count > 0 || doc.thought_count > 0) && (
                            <span className="longform-table-counts">
                              {doc.comment_count > 0 && ` ${doc.comment_count}c`}
                              {doc.thought_count > 0 && ` ${doc.thought_count}t`}
                            </span>
                          )}
                          {doc.status === 'archived' && (
                            <span className="longform-status-badge archived" style={{ marginLeft: '0.5em' }}>archived</span>
                          )}
                        </td>
                        <td className="longform-table-folder" title={doc.folder || ''}>
                          {doc.folder || ''}
                        </td>
                        <td className="longform-table-tags">
                          {doc.tags.map((t) => <span key={t} className="longform-tag-badge small">{t}</span>)}
                        </td>
                        <td className="longform-table-words">{doc.word_count}</td>
                        <td className="longform-table-date"><TimeAgo date={doc.updated_at} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {pageViewMode === 'list' && docs && docs.length > 0 && (
        <KeyboardHints hints={['j/k navigate', 'Enter open']} />
      )}
    </div>
  );
}
