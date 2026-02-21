"""Slack Web API connector for DMs and mentions."""

import os
import ssl

import certifi

from config import SLACK_MESSAGE_LIMIT
from database import get_db

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False


def _get_client() -> "WebClient":
    token = os.environ.get("SLACK_TOKEN", "")
    if not token:
        from pathlib import Path

        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("SLACK_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                    break
    if not token:
        raise ValueError("SLACK_TOKEN not set. Add it to app/backend/.env")
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=token, ssl=ssl_context)


def _get_user_info(client: "WebClient") -> dict:
    """Get the authenticated user's info including workspace URL."""
    resp = client.auth_test()
    return {"user_id": resp["user_id"], "user": resp["user"], "url": resp.get("url", "")}


def _make_permalink(base_url: str, channel_id: str, ts: str) -> str:
    """Construct a Slack permalink locally without an API call.

    Format: {workspace_url}archives/{channel_id}/p{ts_without_dot}
    e.g. https://osmo.slack.com/archives/D123456/p1234567890123456
    """
    ts_int = ts.replace(".", "")
    return f"{base_url.rstrip('/')}/archives/{channel_id}/p{ts_int}"


def sync_slack_data() -> int:
    if not HAS_SLACK:
        raise ImportError("slack_sdk not installed")

    client = _get_client()
    user = _get_user_info(client)
    my_user_id = user["user_id"]
    base_url = user["url"]  # e.g. "https://osmo.slack.com/"

    db = get_db()
    count = 0

    # Cache user display names: user_id -> display_name (avoids duplicate users_info calls)
    user_name_cache: dict[str, str] = {}

    def get_display_name(user_id: str) -> str:
        if user_id in user_name_cache:
            return user_name_cache[user_id]
        try:
            info = client.users_info(user=user_id)
            name = info.get("user", {}).get("real_name", user_id)
        except Exception:
            name = user_id
        user_name_cache[user_id] = name
        return name

    # 1. Fetch DMs
    try:
        dm_channels = client.conversations_list(types="im", limit=50)
        for ch in dm_channels.get("channels", []):
            try:
                history = client.conversations_history(channel=ch["id"], limit=10)
                other_user_id = ch.get("user", "unknown")
                user_name = get_display_name(other_user_id)

                for msg in history.get("messages", []):
                    ts = msg["ts"]
                    permalink = _make_permalink(base_url, ch["id"], ts) if base_url else None

                    db.execute(
                        """INSERT OR REPLACE INTO slack_messages
                           (id, channel_id, channel_name, channel_type, user_id, user_name,
                            text, ts, thread_ts, permalink, is_mention)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"{ch['id']}_{ts}",
                            ch["id"],
                            user_name,
                            "dm",
                            msg.get("user", ""),
                            user_name,
                            msg.get("text", ""),
                            ts,
                            msg.get("thread_ts"),
                            permalink,
                            0,
                        ),
                    )
                    count += 1
            except Exception:
                continue
    except Exception:
        pass

    # 2. Fetch mentions
    try:
        search_result = client.search_messages(query=f"<@{my_user_id}>", count=SLACK_MESSAGE_LIMIT)
        for match in search_result.get("messages", {}).get("matches", []):
            channel = match.get("channel", {})
            db.execute(
                """INSERT OR REPLACE INTO slack_messages
                   (id, channel_id, channel_name, channel_type, user_id, user_name,
                    text, ts, thread_ts, permalink, is_mention)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"{channel.get('id', '')}_{match.get('ts', '')}",
                    channel.get("id", ""),
                    channel.get("name", ""),
                    "channel",
                    match.get("user", ""),
                    match.get("username", ""),
                    match.get("text", ""),
                    match.get("ts", ""),
                    match.get("thread_ts"),
                    match.get("permalink"),
                    1,
                ),
            )
            count += 1
    except Exception:
        pass

    db.commit()
    db.close()
    return count
