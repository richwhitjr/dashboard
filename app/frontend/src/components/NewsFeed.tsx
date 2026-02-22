import { useRef, useEffect, useCallback } from 'react';
import { useNews, useCreateIssue } from '../api/hooks';
import { TimeAgo } from './shared/TimeAgo';
import { useFocusNavigation } from '../hooks/useFocusNavigation';
import type { NewsItem } from '../api/types';

function sourceLabel(item: NewsItem): string {
  if (item.source === 'slack') return 'via Slack';
  if (item.source === 'email') return 'via Email';
  return item.source_detail || 'Web';
}

export function NewsFeed() {
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useNews();
  const createIssue = useCreateIssue();

  const sentinelRef = useRef<HTMLDivElement>(null);

  const handleIntersect = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    },
    [fetchNextPage, hasNextPage, isFetchingNextPage],
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(handleIntersect, {
      rootMargin: '200px',
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleIntersect]);

  const allItems = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  const { containerRef } = useFocusNavigation({
    selector: '.news-item',
    onCreateIssue: (i) => { if (allItems[i]) createIssue.mutate({ title: allItems[i].title }); },
  });

  if (isLoading) {
    return <p className="empty-state">Loading news...</p>;
  }

  if (allItems.length === 0) {
    return (
      <p className="empty-state">
        No news yet — hit refresh to pull articles from Slack, email, and the web.
      </p>
    );
  }

  return (
    <div className="news-feed" ref={containerRef}>
      <div className="news-count"><span className="count-badge">{total}</span> articles</div>
      {allItems.map((item) => (
        <div key={item.id} className="news-item">
          <div className="news-item-header">
            {item.url ? (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="news-item-title"
              >
                {item.title}
              </a>
            ) : (
              <span className="news-item-title">{item.title}</span>
            )}
            {item.domain && (
              <span className="news-item-domain">{item.domain}</span>
            )}
          </div>
          {item.snippet && (
            <div className="news-item-snippet">
              {item.snippet.length > 200
                ? item.snippet.slice(0, 200) + '...'
                : item.snippet}
            </div>
          )}
          <div className="news-item-meta">
            <span className={`news-source-badge news-source-${item.source}`}>
              {sourceLabel(item)}
            </span>
            {item.source_detail && item.source !== 'web' && (
              <span className="news-item-from">{item.source_detail}</span>
            )}
            {item.published_at && (
              <span className="news-item-time">
                <TimeAgo date={item.published_at} />
              </span>
            )}
          </div>
        </div>
      ))}
      <div ref={sentinelRef} className="news-sentinel">
        {isFetchingNextPage && <p className="empty-state">Loading more...</p>}
      </div>
    </div>
  );
}
