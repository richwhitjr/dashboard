"""News aggregator connector.

Extracts article/paper links from:
1. Slack messages (URLs shared in channels and DMs)
2. Emails from colleagues (links in subject/snippet)
3. Web search for topics relevant to the user's role and company
"""

import hashlib
import re
import traceback
from datetime import datetime, timezone
from urllib.parse import urlparse

from database import batch_upsert, get_db_connection, get_write_db

# Default domains to skip — internal tools, not articles
_DEFAULT_SKIP_DOMAINS = {
    "slack.com",
    "docs.google.com",
    "drive.google.com",
    "meet.google.com",
    "zoom.us",
    "calendar.google.com",
    "mail.google.com",
    "notion.so",
    "figma.com",
    "linear.app",
    "github.com",
    "gitlab.com",
    "jira.atlassian.com",
    "confluence.atlassian.com",
    "localhost",
}


def _get_skip_domains() -> set[str]:
    """Return the set of domains to skip, including profile-configured ones."""
    from app_config import get_profile

    profile = get_profile()
    extra = profile.get("skip_domains", [])
    domains = set(_DEFAULT_SKIP_DOMAINS)
    if isinstance(extra, list):
        for d in extra:
            if isinstance(d, str) and d.strip():
                domains.add(d.strip())
    return domains


# Domains that are likely articles/papers
ARTICLE_DOMAINS = {
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "nature.com",
    "science.org",
    "sciencedirect.com",
    "pubmed.ncbi.nlm.nih.gov",
    "pubs.acs.org",
    "cell.com",
    "pnas.org",
    "chemrxiv.org",
    "springer.com",
    "wiley.com",
    "acs.org",
    "rsc.org",
    "techcrunch.com",
    "wired.com",
    "arstechnica.com",
    "theverge.com",
    "nytimes.com",
    "wsj.com",
    "bloomberg.com",
    "reuters.com",
    "ft.com",
    "medium.com",
    "substack.com",
    "hbr.org",
    "a16z.com",
    "firstround.com",
    "lenny.com",
    "stratechery.com",
    "theinformation.com",
    "semafor.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
}

URL_PATTERN = re.compile(
    r"https?://[^\s<>\[\]|)\"'`,;]+",
    re.IGNORECASE,
)


def _make_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def _should_include(url: str) -> bool:
    """Decide if a URL is likely an article worth surfacing."""
    domain = _extract_domain(url)
    if not domain:
        return False
    # Skip internal tool domains
    skip_domains = _get_skip_domains()
    for skip in skip_domains:
        if domain == skip or domain.endswith("." + skip):
            return False
    # Skip file extensions that aren't articles
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".mp4"]):
        return False
    # Skip very short URLs (probably not articles)
    if len(url) < 20:
        return False
    return True


def _clean_url(url: str) -> str:
    """Strip Slack encoding artifacts from URLs."""
    url = url.rstrip(">").rstrip("|").rstrip(")")
    # Slack wraps URLs in <url> or <url|label>
    if "|" in url:
        url = url.split("|")[0]
    return url.strip()


def _title_from_url(url: str) -> str:
    """Generate a readable title from a URL when we don't have one."""
    parsed = urlparse(url)
    domain = _extract_domain(url)
    path = parsed.path.strip("/")
    if path:
        # Take last meaningful path segment
        segments = [s for s in path.split("/") if s and not s.startswith("?")]
        if segments:
            title = segments[-1].replace("-", " ").replace("_", " ")
            # Remove file extensions
            title = re.sub(r"\.\w+$", "", title)
            if len(title) > 3:
                return f"{title.title()} — {domain}"
    return domain


def _extract_urls_from_slack() -> list[dict]:
    """Pull article URLs from synced Slack messages."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, text, user_name, ts, channel_name FROM slack_messages ORDER BY ts DESC"
        ).fetchall()

    items = []
    for row in rows:
        text = row["text"] or ""
        urls = URL_PATTERN.findall(text)
        for raw_url in urls:
            url = _clean_url(raw_url)
            if not _should_include(url):
                continue
            ts = row["ts"]
            try:
                published = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            except (ValueError, TypeError, OSError):
                published = None

            items.append(
                {
                    "id": _make_id(url),
                    "title": _title_from_url(url),
                    "url": url,
                    "source": "slack",
                    "source_detail": f"{row['user_name']} in #{row['channel_name'] or 'DM'}",
                    "domain": _extract_domain(url),
                    "snippet": text[:300] if text else None,
                    "published_at": published,
                }
            )
    return items


def _extract_urls_from_email() -> list[dict]:
    """Pull article URLs from synced emails."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT id, subject, snippet, from_name, from_email, date, body_preview
               FROM emails ORDER BY date DESC"""
        ).fetchall()

    items = []
    for row in rows:
        # Check snippet and body_preview for URLs
        text = f"{row['subject'] or ''} {row['snippet'] or ''} {row['body_preview'] or ''}"
        urls = URL_PATTERN.findall(text)
        for raw_url in urls:
            url = _clean_url(raw_url)
            if not _should_include(url):
                continue
            items.append(
                {
                    "id": _make_id(url),
                    "title": _title_from_url(url),
                    "url": url,
                    "source": "email",
                    "source_detail": row["from_name"] or row["from_email"] or "Unknown",
                    "domain": _extract_domain(url),
                    "snippet": row["subject"],
                    "published_at": row["date"],
                }
            )
    return items


def _get_news_queries() -> list[str]:
    """Return news search queries from the user profile, or sensible defaults."""
    from app_config import get_profile

    profile = get_profile()
    custom_topics = profile.get("news_topics", [])
    if isinstance(custom_topics, list) and custom_topics:
        return [t for t in custom_topics if isinstance(t, str) and t.strip()]

    # Build generic defaults from profile info
    company = profile.get("user_company", "").strip()
    title = profile.get("user_title", "").strip()
    desc = profile.get("user_company_description", "").strip()

    queries = []
    if company and desc:
        queries.append(f"{company} OR {desc}")
    elif company:
        queries.append(company)
    if title:
        queries.append(f"{title} leadership OR startup scaling")
    if not queries:
        queries.append("technology industry news")
    return queries


def _fetch_web_news() -> list[dict]:
    """Fetch relevant web news via Google News RSS feeds.

    Topics are driven by the user profile's news_topics setting,
    or generated from the user's company/title/description.
    """
    items = []
    try:
        import httpx
    except ImportError:
        return items

    # Google News RSS queries — no API key needed
    queries = _get_news_queries()

    for query in queries:
        try:
            encoded = query.replace(" ", "+")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            resp = httpx.get(url, timeout=10, follow_redirects=True)
            if resp.status_code != 200:
                continue

            # Simple XML parsing — avoid heavy deps
            text = resp.text
            # Extract <item> blocks
            item_blocks = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
            for block in item_blocks[:5]:  # Top 5 per query
                title_match = re.search(r"<title>(.*?)</title>", block)
                link_match = re.search(r"<link/?\s*>(.*?)<", block)
                if not link_match:
                    link_match = re.search(r"<link[^>]*href=[\"']([^\"']+)", block)
                pubdate_match = re.search(r"<pubDate>(.*?)</pubDate>", block)
                source_match = re.search(r"<source[^>]*>(.*?)</source>", block)

                title = title_match.group(1) if title_match else "Untitled"
                # Unescape basic HTML entities
                title = (
                    title.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&#39;", "'")
                    .replace("&quot;", '"')
                )

                link = ""
                if link_match:
                    link = link_match.group(1).strip()
                if not link:
                    continue

                published = None
                if pubdate_match:
                    try:
                        from email.utils import parsedate_to_datetime

                        published = parsedate_to_datetime(pubdate_match.group(1)).isoformat()
                    except Exception:
                        published = pubdate_match.group(1)

                source_name = source_match.group(1) if source_match else "Google News"

                items.append(
                    {
                        "id": _make_id(link),
                        "title": title,
                        "url": link,
                        "source": "web",
                        "source_detail": source_name,
                        "domain": _extract_domain(link),
                        "snippet": None,
                        "published_at": published,
                    }
                )
        except Exception:
            continue

    return items


def sync_news() -> int:
    """Main sync: extract news from all sources and store in DB."""
    all_items: list[dict] = []

    # 1. Slack links
    try:
        all_items.extend(_extract_urls_from_slack())
    except Exception:
        traceback.print_exc()

    # 2. Email links
    try:
        all_items.extend(_extract_urls_from_email())
    except Exception:
        traceback.print_exc()

    # 3. Web news
    try:
        all_items.extend(_fetch_web_news())
    except Exception:
        traceback.print_exc()

    # Deduplicate by URL (keep first occurrence)
    seen_urls: set[str] = set()
    unique_items: list[dict] = []
    for item in all_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_items.append(item)

    # Build rows and write in batches
    rows = [
        (
            item["id"],
            item["title"],
            item["url"],
            item["source"],
            item.get("source_detail"),
            item.get("domain"),
            item.get("snippet"),
            item.get("published_at"),
            datetime.now().isoformat(),
        )
        for item in unique_items
    ]

    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR IGNORE INTO news_items
               (id, title, url, source, source_detail, domain, snippet, published_at, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)
