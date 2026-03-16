import { getPageLabel } from '../hooks/usePageHistory';

interface RecentPagesOverlayProps {
  isOpen: boolean;
  history: string[];
  selectedIndex: number;
}

export function RecentPagesOverlay({ isOpen, history, selectedIndex }: RecentPagesOverlayProps) {
  if (!isOpen || history.length < 2) return null;

  return (
    <div className="recent-pages-overlay">
      <div className="recent-pages-list">
        {history.map((path, i) => (
          <div
            key={path}
            className={`recent-pages-item${i === selectedIndex ? ' selected' : ''}${i === 0 ? ' current' : ''}`}
          >
            {getPageLabel(path)}
          </div>
        ))}
      </div>
    </div>
  );
}
