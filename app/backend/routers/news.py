import json
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def get_news(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Return paginated news items, newest first."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT * FROM news_items
               ORDER BY COALESCE(published_at, found_at) DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()

        total = db.execute("SELECT COUNT(*) as count FROM news_items").fetchone()["count"]

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


# --- Gemini-ranked news ---


def _build_news_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}.

You will receive a list of recent news articles. Rank them by relevance and importance to the user.

For each article, assign a priority_score from 1-10 where:
- 10: Directly about the user's company, its core technology, or a major competitor
- 7-9: Highly relevant (industry breakthroughs, key moves in the user's domain, \
scaling insights from top sources)
- 4-6: Moderately relevant (general advances in the user's field, industry news, leadership content, \
interesting tech trends)
- 1-3: Low relevance (generic tech news, unrelated industries, clickbait, automated aggregator junk)

Consider:
1. Articles directly related to the user's company or industry are top priority
2. AI/ML and technology applied to the user's domain is high priority
3. Leadership, scaling, and role-relevant content is medium-high
4. General tech news is medium
5. Clickbait, listicles, and generic business news are low
6. Duplicate or near-duplicate articles should score lower

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL articles provided, scored."""


def _rank_news_with_gemini(articles: list[dict]) -> list[dict]:
    """Call Gemini to rank news articles by priority."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nNews articles to rank:\n{json.dumps(articles, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_news_rank_prompt(),
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_news_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'news'").fetchall()
    return {r["item_id"] for r in rows}


def _published_within_days(published_at: str | None, days: int) -> bool:
    """Check if a published_at timestamp is within N days of now."""
    if not published_at:
        return True  # keep items with no date
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt
        return delta.days <= days
    except (ValueError, TypeError):
        return True


@router.get("/prioritized")
def get_prioritized_news(refresh: bool = Query(False), days: int = Query(14, ge=1, le=90)):
    """Return news articles ranked by Gemini priority score."""
    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_news_ids(db)
        cutoff = f"-{days} days"

        # Check cache first
        if not refresh:
            cached = db.execute(
                "SELECT data_json, generated_at FROM cached_news_priorities ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if cached:
                data = json.loads(cached["data_json"])
                data["items"] = [
                    item
                    for item in data.get("items", [])
                    if item["id"] not in dismissed and _published_within_days(item.get("published_at"), days)
                ]
                return data

        # Fetch recent news from DB
        rows = db.execute(
            """SELECT id, title, url, source, source_detail, domain, snippet, published_at, found_at
               FROM news_items
               WHERE COALESCE(published_at, found_at) >= datetime('now', ?)
               ORDER BY COALESCE(published_at, found_at) DESC
               LIMIT 150""",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {"items": [], "error": "No news items synced yet"}

    articles_for_llm = [
        {
            "id": r["id"],
            "title": r["title"],
            "domain": r["domain"],
            "source": r["source"],
            "snippet": (r["snippet"] or "")[:300],
        }
        for r in rows
    ]

    # Check if input data has changed since last ranking
    items_hash = compute_items_hash(articles_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute(
            "SELECT data_json, data_hash FROM cached_news_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cached and cached["data_hash"] == items_hash:
            logger.info("News ranking cache hit (hash match)")
            data = json.loads(cached["data_json"])
            data["items"] = [
                item
                for item in data.get("items", [])
                if item["id"] not in dismissed and _published_within_days(item.get("published_at"), days)
            ]
            return data

    logger.info("News ranking cache miss — calling Gemini (%d articles)", len(articles_for_llm))
    try:
        ranked = _rank_news_with_gemini(articles_for_llm)
    except Exception as e:
        logger.error("News ranking failed: %s", e)
        return {"items": [], "error": "Ranking service unavailable"}

    # Build lookup of full article data
    article_lookup = {r["id"]: dict(r) for r in rows}

    # Merge rankings with full article data
    items = []
    for rank in ranked:
        article_id = rank.get("id", "")
        article = article_lookup.get(article_id)
        if not article:
            continue
        items.append(
            {
                "id": article["id"],
                "title": article["title"],
                "url": article["url"],
                "source": article["source"],
                "source_detail": article["source_detail"],
                "domain": article["domain"],
                "snippet": article["snippet"],
                "published_at": article["published_at"],
                "found_at": article["found_at"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    # Sort by score desc, filter dismissed
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed]

    result = {"items": items}

    # Cache result with hash
    with get_write_db() as db:
        db.execute("DELETE FROM cached_news_priorities")
        db.execute(
            "INSERT INTO cached_news_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    return result
