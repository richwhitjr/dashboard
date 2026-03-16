#!/usr/bin/env python3
"""Seed the demo database with realistic fake data.

Run from repo root:
    cd app/backend && source venv/bin/activate && python ../../demo/seed.py
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# --- Environment setup (must be before any backend imports) ---
DEMO_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", str(DEMO_DIR / "data")))
REPO_ROOT = DEMO_DIR.parent

os.environ["DASHBOARD_DATA_DIR"] = str(DATA_DIR)
os.environ["DEMO_MODE"] = "1"

# Add backend to sys.path
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))

# --- Helpers ---

NOW = datetime.now()


def _ts(hours_ago: float = 0, days_ago: float = 0) -> str:
    """ISO datetime string relative to now."""
    dt = NOW - timedelta(hours=hours_ago, days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _unix_ts(hours_ago: float = 0) -> str:
    """Unix timestamp string relative to now."""
    dt = NOW - timedelta(hours=hours_ago)
    return str(int(dt.timestamp()))


def _today(hour: int, minute: int = 0) -> str:
    """ISO datetime for a specific time today."""
    dt = NOW.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# --- Config ---

CONFIG = {
    "profile": {
        "user_name": "Alex Chen",
        "user_title": "VP of Engineering",
        "user_company": "Acme Corp",
        "user_company_description": "a B2B SaaS platform for supply chain management",
        "user_email": "alex@acmecorp.com",
        "user_email_domain": "acmecorp.com",
        "user_location": "San Francisco",
        "github_repo": "acmecorp/platform",
        "news_topics": ["supply chain", "SaaS", "enterprise software", "AI"],
        "ai_provider": "gemini",
        "meeting_notes_provider": "granola",
        "auto_sync_interval_seconds": 0,
    },
    "secrets": {
        "SLACK_TOKEN": "xoxb-demo-token",
        "NOTION_TOKEN": "secret_demo_token",
        "GEMINI_API_KEY": "demo-gemini-key",
        "GOOGLE_CLIENT_ID": "demo-client-id",
        "GOOGLE_CLIENT_SECRET": "demo-client-secret",
    },
    "connectors": {
        "google": {"enabled": True},
        "google_drive": {"enabled": True},
        "slack": {"enabled": True},
        "notion": {"enabled": True},
        "github": {"enabled": True},
        "granola": {"enabled": True},
        "ramp": {"enabled": True},
        "news": {"enabled": True},
        "claude_code": {"enabled": True},
        "whatsapp": {"enabled": False},
    },
    "setup_complete": True,
}


# --- People data ---

PEOPLE = [
    # (id, name, title, reports_to, depth, is_coworker, company)
    ("p-ceo", "Emily Zhao", "CEO", None, 0, 1, "Acme Corp"),
    ("p-cfo", "David Park", "CFO", "p-ceo", 1, 1, "Acme Corp"),
    ("p-cpo", "Nina Patel", "Chief Product Officer", "p-ceo", 1, 1, "Acme Corp"),
    ("p-alex", "Alex Chen", "VP of Engineering", "p-ceo", 1, 1, "Acme Corp"),
    ("p-sarah", "Sarah Kim", "Engineering Manager", "p-alex", 2, 1, "Acme Corp"),
    ("p-marcus", "Marcus Johnson", "Senior Software Engineer", "p-sarah", 3, 1, "Acme Corp"),
    ("p-james", "James Wright", "Software Engineer", "p-sarah", 3, 1, "Acme Corp"),
    ("p-priya", "Priya Sharma", "Software Engineer", "p-sarah", 3, 1, "Acme Corp"),
    ("p-lisa", "Lisa Park", "Engineering Manager, Platform", "p-alex", 2, 1, "Acme Corp"),
    ("p-rachel", "Rachel Torres", "DevOps Lead", "p-lisa", 3, 1, "Acme Corp"),
    ("p-kevin", "Kevin Okafor", "Platform Engineer", "p-lisa", 3, 1, "Acme Corp"),
    ("p-anna", "Anna Kowalski", "QA Lead", "p-alex", 2, 1, "Acme Corp"),
    ("p-tom", "Tom Rivera", "Director of Design", "p-cpo", 2, 1, "Acme Corp"),
    ("p-megan", "Megan Liu", "Product Manager", "p-cpo", 2, 1, "Acme Corp"),
    ("p-chris", "Chris Anderson", "Head of Sales", "p-ceo", 1, 1, "Acme Corp"),
    # External contacts
    ("p-ext1", "Sandra Wells", "Account Executive", None, 0, 0, "CloudScale Inc"),
    ("p-ext2", "Michael Torres", "Partner, Engineering", None, 0, 0, "TechVentures"),
    ("p-ext3", "Jennifer Adams", "Recruiting Lead", None, 0, 0, "TopTalent Agency"),
]


def seed_people(db):
    for pid, name, title, reports_to, depth, is_cw, company in PEOPLE:
        db.execute(
            "INSERT OR REPLACE INTO people (id, name, title, reports_to, depth, is_coworker, company, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'demo')",
            (pid, name, title, reports_to, depth, is_cw, company),
        )
    db.commit()


def seed_notes(db):
    notes = [
        # (text, priority, status, person_id, is_one_on_one, hours_ago, due_date)
        ("Review Q1 OKR targets with leadership team", 2, "open", "p-alex", 0, 24, _ts(days_ago=-2)),
        ("[1] @Sarah Kim discuss API migration timeline and latency concerns", 2, "open", "p-sarah", 1, 8, _today(10)),
        ("[1] @Lisa Park budget approval for Datadog upgrade", 1, "open", "p-lisa", 1, 12, _today(14)),
        ("Follow up with recruiting on senior backend role — 2 candidates in final round", 1, "open", "p-ext3", 0, 48, None),
        ("[t] Consider moving to Kubernetes for the platform layer", 0, "open", None, 0, 72, None),
        ("[1] @Marcus Johnson review auth refactor approach", 1, "done", "p-marcus", 1, 96, None),
        ("Schedule team retro for end of sprint", 0, "open", None, 0, 36, _ts(days_ago=-3)),
        ("[1] @Rachel Torres discuss CI/CD pipeline improvements", 1, "open", "p-rachel", 1, 24, _ts(days_ago=-1)),
        ("Prepare board deck engineering section", 2, "open", None, 0, 6, _today(14)),
        ("[1] @Anna Kowalski testing strategy for auth migration", 1, "open", "p-anna", 1, 48, None),
        ("Send updated headcount plan to finance", 1, "done", "p-cfo", 0, 120, None),
        ("[1] @James Wright check on WebSocket memory leak fix", 0, "done", "p-james", 1, 72, None),
        ("Review vendor contract renewal terms for CloudScale", 1, "open", "p-ext1", 0, 24, _ts(days_ago=-1)),
        ("[t] Look into GraphQL federation for the API layer", 0, "open", None, 0, 96, None),
        ("Update engineering wiki with new on-call rotation", 0, "open", None, 0, 48, None),
        ("[1] @Priya Sharma career growth discussion", 1, "open", "p-priya", 1, 12, _ts(days_ago=-2)),
        ("Draft proposal for engineering all-hands topic", 0, "open", None, 0, 24, _ts(days_ago=-4)),
        ("[1] @Kevin Okafor platform monitoring dashboard review", 0, "open", "p-kevin", 1, 36, None),
        ("Review infrastructure cost report Q1", 1, "open", "p-rachel", 0, 8, None),
        ("Coordinate with product on onboarding redesign timeline", 0, "open", "p-megan", 0, 24, None),
    ]
    for text, priority, status, person_id, is_1on1, hours_ago, due_date in notes:
        completed_at = _ts(hours_ago=hours_ago - 2) if status == "done" else None
        db.execute(
            "INSERT INTO notes (text, priority, status, person_id, is_one_on_one, created_at, completed_at, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (text, priority, status, person_id, is_1on1, _ts(hours_ago=hours_ago), completed_at, due_date),
        )
    db.commit()


def seed_issues(db):
    issues = [
        # (title, description, priority, size, status, tags, hours_ago, due)
        ("Auth migration: OAuth 2.1 upgrade", "Migrate all auth endpoints to OAuth 2.1 standard", 3, "l", "in_progress", ["backend", "security"], 168, _ts(days_ago=-5)),
        ("API latency p99 > 200ms on /orders endpoint", "Profiling shows N+1 query in order lookup", 3, "m", "open", ["backend", "performance"], 48, _ts(days_ago=-2)),
        ("Onboarding flow redesign", "New UX flow based on user research", 2, "xl", "in_progress", ["frontend", "design"], 240, _ts(days_ago=-14)),
        ("Add rate limiting to public API", "Implement token bucket rate limiting", 2, "m", "in_progress", ["backend", "security"], 120, None),
        ("Fix flaky integration test suite", "3 tests intermittently fail on CI", 1, "s", "open", ["testing", "ci"], 72, None),
        ("Kubernetes migration plan", "Draft architecture for K8s migration", 1, "l", "open", ["platform", "infrastructure"], 96, None),
        ("Update monitoring dashboards", "Add new SLO dashboards for auth service", 1, "m", "open", ["platform", "observability"], 48, None),
        ("Database query optimization sprint", "Identified 5 slow queries in analytics", 2, "m", "open", ["backend", "performance"], 36, _ts(days_ago=-7)),
        ("WebSocket memory leak", "Connection handler not releasing buffers", 3, "s", "done", ["backend", "bug"], 96, None),
        ("Design system component library", "Extract shared components into library", 1, "xl", "open", ["frontend", "design"], 168, None),
        ("CI/CD pipeline improvements", "Reduce build time from 12min to under 5min", 2, "l", "in_progress", ["platform", "ci"], 120, None),
        ("Hire senior backend engineer (2 openings)", "Complete interview pipeline for 2 roles", 2, "l", "in_progress", ["hiring"], 336, None),
    ]
    for title, desc, priority, size, status, tags, hours_ago, due in issues:
        completed_at = _ts(hours_ago=hours_ago - 24) if status == "done" else None
        db.execute(
            "INSERT INTO issues (title, description, priority, tshirt_size, status, created_at, completed_at, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, desc, priority, size, status, _ts(hours_ago=hours_ago), completed_at, due),
        )
        issue_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        for tag in tags:
            db.execute("INSERT INTO issue_tags (issue_id, tag) VALUES (?, ?)", (issue_id, tag))
    db.commit()


def seed_calendar(db):
    events = [
        # (id, summary, start_hour, end_hour, attendees, description)
        ("cal-1", "Engineering Standup", 9, 9.25, ["sarah@acmecorp.com", "marcus@acmecorp.com", "james@acmecorp.com", "priya@acmecorp.com"], "Daily standup — blockers and progress"),
        ("cal-2", "1:1 with Sarah Kim", 10, 10.5, ["sarah@acmecorp.com"], "Weekly 1:1"),
        ("cal-3", "1:1 with Lisa Park", 11, 11.5, ["lisa@acmecorp.com"], "Weekly 1:1"),
        ("cal-4", "Lunch", 12, 13, [], None),
        ("cal-5", "Board Deck Review", 14, 15, ["david@acmecorp.com", "emily@acmecorp.com"], "Review engineering section of board deck"),
        ("cal-6", "Design Review: Onboarding", 15.5, 16.5, ["nina@acmecorp.com", "tom@acmecorp.com", "megan@acmecorp.com"], "Review new onboarding mockups"),
        ("cal-7", "1:1 with Anna Kowalski", 16.5, 17, ["anna@acmecorp.com"], "Bi-weekly 1:1"),
    ]
    for eid, summary, start_h, end_h, attendees, desc in events:
        start = NOW.replace(hour=int(start_h), minute=int((start_h % 1) * 60), second=0, microsecond=0)
        end = NOW.replace(hour=int(end_h), minute=int((end_h % 1) * 60), second=0, microsecond=0)
        db.execute(
            "INSERT OR REPLACE INTO calendar_events (id, summary, description, start_time, end_time, attendees_json, organizer_email, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'alex@acmecorp.com', 'confirmed')",
            (eid, summary, desc, start.isoformat(), end.isoformat(), json.dumps(attendees)),
        )

    # Tomorrow's events
    tomorrow = NOW + timedelta(days=1)
    for i, (summary, start_h, end_h) in enumerate([
        ("Team Standup", 9, 9.25),
        ("Product Sync", 10, 11),
        ("Vendor Meeting — CloudScale", 14, 15),
    ]):
        start = tomorrow.replace(hour=int(start_h), minute=int((start_h % 1) * 60), second=0)
        end = tomorrow.replace(hour=int(end_h), minute=int((end_h % 1) * 60), second=0)
        db.execute(
            "INSERT OR REPLACE INTO calendar_events (id, summary, start_time, end_time, organizer_email, status) "
            "VALUES (?, ?, ?, ?, 'alex@acmecorp.com', 'confirmed')",
            (f"cal-tmrw-{i}", summary, start.isoformat(), end.isoformat()),
        )
    db.commit()


def seed_emails(db):
    emails = [
        # (id, thread_id, subject, snippet, from_name, from_email, hours_ago, is_unread, labels)
        ("em-1", "t-1", "Re: Q1 Engineering OKR Review", "Thanks for the updated targets. I think we should revisit the latency goal given the migration timeline...", "Sarah Kim", "sarah@acmecorp.com", 2, 1, '["INBOX"]'),
        ("em-2", "t-2", "Board Deck - Engineering Section Draft", "Hi Alex, attached is the latest version. Please review the headcount slide before our 2pm sync.", "David Park", "david@acmecorp.com", 4, 1, '["INBOX", "IMPORTANT"]'),
        ("em-3", "t-3", "Auth Refactor PR - Ready for Review", "PR #247 is ready. I've addressed all the comments from the first round.", "Marcus Johnson", "marcus@acmecorp.com", 10, 0, '["INBOX"]'),
        ("em-4", "t-4", "Re: Vendor Meeting - CloudScale Contract Renewal", "Confirmed for Thursday 10am. I'll prepare the usage report and bring the renewal terms.", "Lisa Park", "lisa@acmecorp.com", 14, 0, '["INBOX"]'),
        ("em-5", "t-5", "Quarterly Infrastructure Cost Report", "Please find the attached Q1 infrastructure cost breakdown. AWS spend is up 12% from last quarter.", "Rachel Torres", "rachel@acmecorp.com", 18, 0, '["INBOX"]'),
        ("em-6", "t-6", "Re: Senior Backend Engineer - Candidate Pipeline", "We have 2 strong candidates moving to final round. Both available for onsite next week.", "Jennifer Adams", "jennifer@toptalent.com", 20, 1, '["INBOX"]'),
        ("em-7", "t-7", "Design System Component Library Proposal", "Attached is the proposal for extracting shared components. Would love your feedback.", "Tom Rivera", "tom@acmecorp.com", 24, 0, '["INBOX"]'),
        ("em-8", "t-8", "Re: Sprint Retrospective Action Items", "Here are the action items from yesterday's retro. I'll track progress in our next standup.", "Anna Kowalski", "anna@acmecorp.com", 28, 0, '["INBOX"]'),
        ("em-9", "t-9", "Datadog Enterprise Plan Renewal", "Your current plan expires April 1. Here are the renewal options and pricing.", "Sandra Wells", "sandra@cloudscale.io", 36, 0, '["INBOX"]'),
        ("em-10", "t-10", "Re: Engineering All-Hands Agenda", "Added the auth migration update to the agenda. Can you present the timeline?", "Nina Patel", "nina@acmecorp.com", 40, 0, '["INBOX"]'),
        ("em-11", "t-1", "Q1 Engineering OKR Review", "Team, here are the updated Q1 OKR targets for engineering. Please review and flag concerns by EOD.", "Alex Chen", "alex@acmecorp.com", 26, 0, '["SENT"]'),
        ("em-12", "t-11", "Weekly Engineering Digest", "This week: auth migration at 60%, 3 PRs merged, CI build time reduced to 8min.", "Alex Chen", "alex@acmecorp.com", 48, 0, '["SENT"]'),
        ("em-13", "t-12", "Acme Q1 Product Updates", "Dear customers, we're excited to share our Q1 product updates...", "Acme Marketing", "marketing@acmecorp.com", 72, 0, '["INBOX", "CATEGORY_PROMOTIONS"]'),
        ("em-14", "t-13", "Your AWS bill for February 2026", "Your AWS account charges for February 2026 total $34,521.89.", "AWS Billing", "billing@aws.amazon.com", 96, 0, '["INBOX", "CATEGORY_UPDATES"]'),
        # More recent emails from team
        ("em-15", "t-14", "CI pipeline green again", "Fixed the flaky test. Root cause was a race condition in the setup fixture.", "James Wright", "james@acmecorp.com", 6, 1, '["INBOX"]'),
        ("em-16", "t-15", "Platform monitoring update", "New Grafana dashboards are live. Added p99 latency and error rate panels.", "Kevin Okafor", "kevin@acmecorp.com", 8, 0, '["INBOX"]'),
        ("em-17", "t-16", "Re: Onboarding Flow User Research", "Completed 8 user interviews. Key finding: 40% of users drop off at the integration step.", "Megan Liu", "megan@acmecorp.com", 12, 0, '["INBOX"]'),
    ]
    for eid, tid, subj, snip, fname, femail, hours, unread, labels in emails:
        db.execute(
            "INSERT OR REPLACE INTO emails (id, thread_id, subject, snippet, from_name, from_email, date, is_unread, labels_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, tid, subj, snip, fname, femail, _ts(hours_ago=hours), unread, labels),
        )
    db.commit()


def seed_slack(db):
    messages = [
        # (id, channel_name, channel_type, user_name, text, hours_ago, is_mention, channel_id)
        ("sl-1", "dm", "dm", "Lisa Park", "Hey Alex, quick question — do you have budget approval for the Datadog upgrade? We need to decide before the vendor meeting Thursday.", 3, 0, "D001"),
        ("sl-2", "engineering", "channel", "James Wright", "The deploy pipeline is green again. Root cause was a flaky integration test — I've quarantined it for now.", 4, 0, "C002"),
        ("sl-3", "product", "channel", "Nina Patel", "Shared the updated onboarding mockups in the design channel. @alex would love your feedback on the new flow before we finalize.", 6, 1, "C003"),
        ("sl-4", "engineering", "channel", "Sarah Kim", "Heads up — the auth migration load test showed 2x latency increase at peak. I'm investigating but might need to push the rollout.", 8, 0, "C002"),
        ("sl-5", "dm", "dm", "Marcus Johnson", "PR #247 is updated with all review feedback. Ready for final approval when you get a chance.", 10, 0, "D002"),
        ("sl-6", "engineering", "channel", "Rachel Torres", "AWS costs for February came in at $34.5k. That's 12% above budget — mostly from the new staging env. Happy to walk through the breakdown.", 12, 0, "C002"),
        ("sl-7", "general", "channel", "Emily Zhao", "Reminder: company all-hands next Friday 3pm. Please submit agenda topics by Wednesday.", 14, 0, "C001"),
        ("sl-8", "engineering", "channel", "Kevin Okafor", "New Grafana dashboards are live! Added p99 latency tracking for all API endpoints. Link in the wiki.", 16, 0, "C002"),
        ("sl-9", "product", "channel", "Megan Liu", "User research results are in — 8 interviews completed. Short version: onboarding drop-off is 40% at the integration step. Full report in Notion.", 18, 0, "C003"),
        ("sl-10", "dm", "dm", "Anna Kowalski", "Finished the test plan for the auth migration. Can we review in our 1:1 this week?", 20, 0, "D003"),
        ("sl-11", "engineering", "channel", "Priya Sharma", "Just merged the order lookup optimization. Query time down from 340ms to 45ms. 🎉", 22, 0, "C002"),
        ("sl-12", "incidents", "channel", "Rachel Torres", "Resolved: The API gateway timeout issue was caused by a misconfigured health check. No customer impact.", 24, 0, "C005"),
        ("sl-13", "design", "channel", "Tom Rivera", "Posted the design system component inventory. 47 components identified, 12 are duplicates we can consolidate.", 28, 0, "C004"),
        ("sl-14", "engineering", "channel", "James Wright", "FYI — upgrading Node.js to v22 across all services next sprint. Please check your service compatibility.", 32, 0, "C002"),
        ("sl-15", "dm", "dm", "Chris Anderson", "Hey Alex, can we chat about the API stability report? The sales team needs it for the enterprise pitch.", 36, 0, "D004"),
    ]
    for sid, ch_name, ch_type, uname, text, hours, mention, ch_id in messages:
        db.execute(
            "INSERT OR REPLACE INTO slack_messages (id, channel_id, channel_name, channel_type, user_name, text, ts, is_mention, permalink) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, ch_id, ch_name, ch_type, uname, text, _unix_ts(hours), mention,
             f"https://acmecorp.slack.com/archives/{ch_id}/p{_unix_ts(hours)}"),
        )
    db.commit()


def seed_notion(db):
    pages = [
        ("n-1", "Q1 2026 Engineering Roadmap", "https://notion.so/acmecorp/q1-roadmap", 6, "Sarah Kim"),
        ("n-2", "Auth Migration — Technical Design Doc", "https://notion.so/acmecorp/auth-migration", 14, "Marcus Johnson"),
        ("n-3", "Onboarding Flow Redesign — PRD", "https://notion.so/acmecorp/onboarding-prd", 18, "Nina Patel"),
        ("n-4", "Engineering Team OKRs — Q1 2026", "https://notion.so/acmecorp/eng-okrs", 26, "Alex Chen"),
        ("n-5", "Incident Response Runbook", "https://notion.so/acmecorp/incident-runbook", 48, "James Wright"),
        ("n-6", "Platform Architecture Overview", "https://notion.so/acmecorp/platform-arch", 72, "Lisa Park"),
        ("n-7", "Interview Guide — Senior Backend", "https://notion.so/acmecorp/interview-guide", 96, "Alex Chen"),
        ("n-8", "Sprint Planning Template", "https://notion.so/acmecorp/sprint-template", 120, "Sarah Kim"),
        ("n-9", "API Rate Limiting Design", "https://notion.so/acmecorp/rate-limiting", 36, "Sarah Kim"),
        ("n-10", "User Research — Onboarding Insights", "https://notion.so/acmecorp/onboarding-research", 20, "Megan Liu"),
    ]
    for nid, title, url, hours, edited_by in pages:
        db.execute(
            "INSERT OR REPLACE INTO notion_pages (id, title, url, last_edited_time, last_edited_by) VALUES (?, ?, ?, ?, ?)",
            (nid, title, url, _ts(hours_ago=hours), edited_by),
        )
    db.commit()


def seed_github(db):
    prs = [
        # (id, number, title, state, draft, author, hours_ago, review_requested, adds, dels, body)
        (1001, 247, "Refactor auth middleware to support OAuth 2.1", "open", 0, "marcusjohnson", 72, 1, 342, 128, "Major auth system refactor to support OAuth 2.1 spec"),
        (1002, 245, "Add rate limiting to public API endpoints", "open", 0, "sarahkim", 96, 1, 156, 23, "Implements token bucket rate limiting"),
        (1003, 243, "Fix memory leak in WebSocket connection handler", "merged", 0, "jameswright", 120, 0, 45, 12, "Fixed buffer not being released on disconnect"),
        (1004, 241, "Redesign onboarding flow components", "open", 1, "tomrivera", 144, 0, 890, 234, "New onboarding UX based on user research"),
        (1005, 239, "Upgrade PostgreSQL driver to v5.2", "merged", 0, "alexchen", 168, 0, 12, 8, "Routine dependency upgrade"),
        (1006, 237, "Optimize order lookup query (N+1 fix)", "open", 0, "priyasharma", 48, 1, 67, 23, "Fixes N+1 query in order lookup endpoint"),
        (1007, 235, "Add p99 latency SLO dashboards", "merged", 0, "kevinokafor", 96, 0, 234, 0, "New Grafana dashboards for SLO monitoring"),
        (1008, 233, "CI pipeline: quarantine flaky tests", "merged", 0, "jameswright", 24, 0, 34, 5, "Quarantine 3 flaky integration tests"),
        (1009, 231, "Update Node.js to v22 across services", "open", 1, "jameswright", 36, 0, 45, 45, "Node.js v22 upgrade draft"),
        (1010, 229, "Design system: extract Button component", "open", 0, "tomrivera", 120, 0, 156, 89, "First component extraction for design system"),
    ]
    for pid, num, title, state, draft, author, hours, review_req, adds, dels, body in prs:
        merged_at = _ts(hours_ago=hours - 24) if state == "merged" else None
        db.execute(
            "INSERT OR REPLACE INTO github_pull_requests "
            "(id, number, title, state, draft, author, html_url, created_at, updated_at, merged_at, "
            "review_requested, additions, deletions, body_preview) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, num, title, state, draft, author,
             f"https://github.com/acmecorp/platform/pull/{num}",
             _ts(hours_ago=hours), _ts(hours_ago=hours - 12), merged_at,
             review_req, adds, dels, body),
        )
    db.commit()


def seed_granola(db):
    meetings = [
        ("g-1", "Engineering Standup", 25, "p-sarah",
         ["Sarah Kim", "Marcus Johnson", "James Wright", "Priya Sharma"],
         "Team discussed auth migration progress (60% complete), CI pipeline improvements, and upcoming sprint priorities. Sarah flagged latency concerns with the migration.",
         "Discussed blockers on auth migration. Marcus is close to finishing PR #247. James fixed the flaky test suite. Priya completed the order lookup optimization."),
        ("g-2", "1:1 with Sarah Kim", 49, "p-sarah",
         ["Sarah Kim"],
         "Reviewed auth migration timeline. Sarah expressed concerns about p99 latency increase. Agreed to run load tests before proceeding with wider rollout.",
         "Sarah walked through the latency numbers. Load test shows 2x increase at peak traffic. Agreed to investigate caching layer before proceeding."),
        ("g-3", "Product Sync", 73, "p-cpo",
         ["Nina Patel", "Megan Liu", "Tom Rivera"],
         "Reviewed onboarding redesign progress. User research shows 40% drop-off at integration step. Design team presenting new mockups next week.",
         "Nina shared updated roadmap. Megan presented user research findings. Tom showed early mockups of the new onboarding flow."),
        ("g-4", "1:1 with Lisa Park", 97, "p-lisa",
         ["Lisa Park"],
         "Discussed platform team priorities. Lisa needs budget approval for Datadog upgrade. Reviewed CloudScale contract renewal terms.",
         "Lisa walked through platform monitoring improvements. Discussed vendor meeting prep for CloudScale renewal. Need to finalize budget for monitoring tools."),
        ("g-5", "Engineering All-Hands", 121, None,
         ["Sarah Kim", "Lisa Park", "Marcus Johnson", "James Wright", "Priya Sharma", "Rachel Torres", "Kevin Okafor", "Anna Kowalski"],
         "Quarterly all-hands covering Q1 progress, hiring updates, and tech roadmap. Announced auth migration milestone and infrastructure cost review.",
         "Presented Q1 engineering metrics. Discussed hiring pipeline — 2 senior backend roles open. Rachel presented infrastructure cost breakdown. Team Q&A on migration timeline."),
    ]
    for gid, title, hours, person_id, attendees, summary, transcript in meetings:
        db.execute(
            "INSERT OR REPLACE INTO granola_meetings "
            "(id, title, created_at, attendees_json, panel_summary_plain, transcript_text, person_id, valid_meeting) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (gid, title, _ts(hours_ago=hours), json.dumps(attendees), summary, transcript, person_id),
        )
    db.commit()


def seed_drive(db):
    files = [
        ("d-1", "Q1 2026 Engineering OKRs", "application/vnd.google-apps.spreadsheet", 6, "Sarah Kim", "alex@acmecorp.com", "Alex Chen"),
        ("d-2", "Board Deck — March 2026", "application/vnd.google-apps.presentation", 8, "David Park", "david@acmecorp.com", "David Park"),
        ("d-3", "Auth Migration Architecture", "application/vnd.google-apps.document", 14, "Marcus Johnson", "alex@acmecorp.com", "Alex Chen"),
        ("d-4", "Q1 Infrastructure Cost Report", "application/vnd.google-apps.spreadsheet", 18, "Rachel Torres", "rachel@acmecorp.com", "Rachel Torres"),
        ("d-5", "Hiring Pipeline Tracker", "application/vnd.google-apps.spreadsheet", 48, "Alex Chen", "alex@acmecorp.com", "Alex Chen"),
        ("d-6", "Onboarding User Research Results", "application/vnd.google-apps.document", 20, "Megan Liu", "megan@acmecorp.com", "Megan Liu"),
        ("d-7", "Engineering Team Charter", "application/vnd.google-apps.document", 168, "Alex Chen", "alex@acmecorp.com", "Alex Chen"),
        ("d-8", "Sprint Velocity Dashboard", "application/vnd.google-apps.spreadsheet", 72, "Anna Kowalski", "anna@acmecorp.com", "Anna Kowalski"),
        ("d-9", "API Rate Limiting Proposal", "application/vnd.google-apps.document", 36, "Sarah Kim", "sarah@acmecorp.com", "Sarah Kim"),
        ("d-10", "Design System Inventory", "application/vnd.google-apps.spreadsheet", 28, "Tom Rivera", "tom@acmecorp.com", "Tom Rivera"),
        ("d-11", "Vendor Comparison — Monitoring Tools", "application/vnd.google-apps.spreadsheet", 96, "Lisa Park", "lisa@acmecorp.com", "Lisa Park"),
        ("d-12", "Engineering All-Hands Slides", "application/vnd.google-apps.presentation", 121, "Alex Chen", "alex@acmecorp.com", "Alex Chen"),
    ]
    for fid, name, mime, hours, mod_by, owner_email, owner_name in files:
        db.execute(
            "INSERT OR REPLACE INTO drive_files "
            "(id, name, mime_type, modified_time, modified_by_name, owner_email, owner_name, "
            "web_view_link, shared, trashed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
            (fid, name, mime, _ts(hours_ago=hours), mod_by, owner_email, owner_name,
             f"https://docs.google.com/document/d/{fid}"),
        )
    db.commit()


def seed_ramp(db):
    # Vendors
    vendors = [
        ("v-1", "Amazon Web Services"), ("v-2", "CloudScale Inc"),
        ("v-3", "Datadog"), ("v-4", "GitHub Enterprise"),
        ("v-5", "Notion"), ("v-6", "Slack Technologies"),
        ("v-7", "Figma"), ("v-8", "WeWork"),
    ]
    for vid, name in vendors:
        db.execute("INSERT OR REPLACE INTO ramp_vendors (id, name, is_active) VALUES (?, ?, 1)", (vid, name))

    # Transactions
    txns = [
        ("rt-1", 34521.89, "Amazon Web Services", "rachel@acmecorp.com", 48),
        ("rt-2", 4200.00, "Datadog", "lisa@acmecorp.com", 72),
        ("rt-3", 1890.00, "GitHub Enterprise", "alex@acmecorp.com", 96),
        ("rt-4", 320.00, "Notion", "alex@acmecorp.com", 120),
        ("rt-5", 250.00, "Slack Technologies", "alex@acmecorp.com", 144),
        ("rt-6", 780.00, "Figma", "tom@acmecorp.com", 168),
        ("rt-7", 5600.00, "WeWork", "alex@acmecorp.com", 192),
        ("rt-8", 156.99, "Amazon Web Services", "kevin@acmecorp.com", 24),
        ("rt-9", 89.99, "Google Cloud", "rachel@acmecorp.com", 36),
        ("rt-10", 2100.00, "TopTalent Agency", "alex@acmecorp.com", 60),
        ("rt-11", 450.00, "Vercel", "james@acmecorp.com", 84),
        ("rt-12", 1200.00, "Linear", "sarah@acmecorp.com", 108),
        ("rt-13", 340.00, "1Password", "alex@acmecorp.com", 132),
        ("rt-14", 8900.00, "Amazon Web Services", "rachel@acmecorp.com", 240),
        ("rt-15", 675.00, "Zoom", "alex@acmecorp.com", 156),
    ]
    for tid, amount, merchant, holder, hours in txns:
        db.execute(
            "INSERT OR REPLACE INTO ramp_transactions "
            "(id, amount, currency, merchant_name, cardholder_email, transaction_date) "
            "VALUES (?, ?, 'USD', ?, ?, ?)",
            (tid, amount, merchant, holder, _ts(hours_ago=hours)),
        )

    # Bills
    bills = [
        ("rb-1", "v-2", "CloudScale Inc", 12400.00, _ts(days_ago=5), "APPROVED", "PENDING", None),
        ("rb-2", "v-1", "Amazon Web Services", 34521.89, _ts(days_ago=-10), "APPROVED", "PENDING", None),
        ("rb-3", "v-3", "Datadog", 4200.00, _ts(days_ago=-5), "PENDING", "PENDING", None),
        ("rb-4", "v-4", "GitHub Enterprise", 1890.00, _ts(days_ago=-15), "APPROVED", "PAID", _ts(days_ago=-12)),
        ("rb-5", "v-8", "WeWork", 5600.00, _ts(days_ago=-2), "APPROVED", "PENDING", None),
        ("rb-6", "v-7", "Figma", 780.00, _ts(days_ago=-20), "APPROVED", "PAID", _ts(days_ago=-18)),
    ]
    for bid, vid, vname, amount, due, approval, payment, paid_at in bills:
        db.execute(
            "INSERT OR REPLACE INTO ramp_bills "
            "(id, vendor_id, vendor_name, amount, currency, due_at, approval_status, payment_status, paid_at) "
            "VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, ?)",
            (bid, vid, vname, amount, due, approval, payment, paid_at),
        )
    db.commit()


def seed_projects(db):
    projects = [
        ("Engineering Tools", "Internal tooling and developer experience", 50000.0, "active"),
        ("Platform Infrastructure", "Cloud infrastructure and monitoring", 200000.0, "active"),
        ("Product Development", "Core product feature development", 150000.0, "active"),
    ]
    for name, desc, budget, status in projects:
        db.execute(
            "INSERT INTO projects (name, description, budget_amount, currency, status) VALUES (?, ?, ?, 'USD', ?)",
            (name, desc, budget, status),
        )
    db.commit()


def seed_news(db):
    articles = [
        ("news-1", "OpenAI Announces GPT-5 with Reasoning Capabilities", "https://techcrunch.com/2026/03/gpt5", "techcrunch.com", "OpenAI unveiled GPT-5, featuring advanced reasoning and longer context windows.", "TechCrunch", 6),
        ("news-2", "Supply Chain AI Startups See Record Funding in Q1 2026", "https://reuters.com/2026/supply-chain-ai", "reuters.com", "Venture capital investment in supply chain AI companies reached $4.2B.", "Reuters", 8),
        ("news-3", "Kubernetes 1.32 Released with Enhanced Security Features", "https://kubernetes.io/blog/v132", "kubernetes.io", "The latest Kubernetes release includes pod-level security policies.", "Kubernetes Blog", 12),
        ("news-4", "Enterprise SaaS Growth Slows as Companies Cut Software Spend", "https://wsj.com/enterprise-saas-2026", "wsj.com", "Enterprise SaaS companies reported slower growth as customers consolidate tools.", "Wall Street Journal", 18),
        ("news-5", "Google Cloud Introduces AI-Powered Cost Optimization", "https://cloud.google.com/blog/ai-cost", "cloud.google.com", "New AI tools help predict and reduce cloud infrastructure costs.", "Google Cloud Blog", 24),
        ("news-6", "OAuth 2.1 Specification Finalized by IETF", "https://ietf.org/oauth21", "ietf.org", "The OAuth 2.1 spec consolidates best practices from OAuth 2.0.", "IETF", 30),
        ("news-7", "PostgreSQL 17 Benchmarks Show 2x Performance Improvement", "https://postgresql.org/blog/v17", "postgresql.org", "PostgreSQL 17 delivers significant performance gains for analytical workloads.", "PostgreSQL", 36),
        ("news-8", "Remote Work Trends: Engineering Teams Adopt Async-First", "https://hbr.org/remote-engineering", "hbr.org", "Top engineering teams are shifting to async-first collaboration.", "Harvard Business Review", 42),
        ("news-9", "Datadog Acquires AI Observability Startup for $500M", "https://techcrunch.com/datadog-acquisition", "techcrunch.com", "Datadog expands AI monitoring capabilities with strategic acquisition.", "TechCrunch", 48),
        ("news-10", "New NIST Framework for Software Supply Chain Security", "https://nist.gov/supply-chain-security", "nist.gov", "NIST releases updated guidelines for securing software supply chains.", "NIST", 60),
        ("news-11", "React 20 Released with Server Components GA", "https://react.dev/blog/v20", "react.dev", "React 20 makes Server Components generally available with improved DX.", "React Blog", 72),
        ("news-12", "Annual Developer Survey: Rust Adoption Grows 40%", "https://stackoverflow.com/survey-2026", "stackoverflow.com", "Rust continues its rise as developers cite safety and performance.", "Stack Overflow", 84),
        ("news-13", "AWS Announces 15% Price Reduction for EC2 Instances", "https://aws.amazon.com/blog/ec2-pricing", "aws.amazon.com", "AWS reduces EC2 pricing across multiple instance families.", "AWS Blog", 96),
        ("news-14", "GitHub Copilot Enterprise Adds Code Review Features", "https://github.blog/copilot-review", "github.blog", "GitHub Copilot Enterprise now provides automated code review suggestions.", "GitHub Blog", 108),
        ("news-15", "Figma Introduces AI-Powered Design System Management", "https://figma.com/blog/ai-design", "figma.com", "New AI features help teams maintain design system consistency.", "Figma Blog", 120),
        ("news-16", "Cloud Infrastructure Spending Hits $200B Globally", "https://gartner.com/cloud-2026", "gartner.com", "Gartner reports global cloud infrastructure spending reached $200B.", "Gartner", 132),
        ("news-17", "Linear Raises $100M to Build the Future of Project Management", "https://techcrunch.com/linear-funding", "techcrunch.com", "Linear raises Series C to expand its issue tracking platform.", "TechCrunch", 144),
        ("news-18", "TypeScript 6.0 Introduces Pattern Matching", "https://devblogs.microsoft.com/ts6", "devblogs.microsoft.com", "TypeScript 6.0 adds pattern matching and improved type inference.", "Microsoft DevBlogs", 156),
        ("news-19", "The Rise of Platform Engineering: A CTO's Guide", "https://infoq.com/platform-engineering", "infoq.com", "Platform engineering teams are becoming critical to developer productivity.", "InfoQ", 168),
        ("news-20", "Anthropic Releases Claude 4.5 with Extended Context", "https://anthropic.com/claude-45", "anthropic.com", "Claude 4.5 supports 1M token context with improved reasoning.", "Anthropic Blog", 180),
    ]
    for nid, title, url, domain, snippet, source, hours in articles:
        db.execute(
            "INSERT OR REPLACE INTO news_items (id, title, url, domain, snippet, source, found_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nid, title, url, domain, snippet, source, _ts(hours_ago=hours)),
        )
    db.commit()


def seed_longform(db):
    db.execute(
        "INSERT INTO longform_posts (title, body, status, created_at, updated_at, word_count) VALUES (?, ?, 'published', ?, ?, ?)",
        ("Lessons from Our Auth Migration",
         "# Lessons from Our Auth Migration\n\n"
         "After three months of planning and execution, we've successfully migrated 60% of our users "
         "to the new OAuth 2.1-based authentication system. Here are the key lessons learned.\n\n"
         "## Planning Phase\n\n"
         "The most important decision we made was to run the old and new systems in parallel. This allowed "
         "us to gradually shift traffic without a big-bang cutover.\n\n"
         "## Technical Challenges\n\n"
         "The biggest surprise was the latency impact. Adding an extra network hop for token validation "
         "increased p99 latency by 30ms. We solved this with an edge caching layer.\n\n"
         "## What's Next\n\n"
         "We're targeting 100% migration by end of Q1. The remaining 40% includes our highest-traffic "
         "endpoints, which need additional load testing.",
         _ts(days_ago=7), _ts(days_ago=2), 142),
    )
    db.execute(
        "INSERT INTO longform_posts (title, body, status, created_at, updated_at, word_count) VALUES (?, ?, 'draft', ?, ?, ?)",
        ("Building a Platform Engineering Team from Scratch",
         "# Building a Platform Engineering Team\n\n"
         "When I joined Acme Corp, we had zero platform engineers. Every team managed their own "
         "infrastructure, leading to inconsistency and duplicated effort.\n\n"
         "## The Case for Platform Engineering\n\n"
         "We were spending 30% of engineering time on infrastructure tasks that could be standardized...",
         _ts(days_ago=14), _ts(days_ago=3), 67),
    )
    db.commit()


def seed_personas(db):
    db.execute(
        "INSERT INTO personas (name, description, system_prompt, is_default) VALUES (?, ?, ?, ?)",
        ("Engineering Lead", "Helps with technical architecture, code review, and engineering strategy",
         "You are an experienced engineering leader at a B2B SaaS company. Help with technical decisions, code review, architecture, and engineering strategy.", 1),
    )
    db.execute(
        "INSERT INTO personas (name, description, system_prompt, is_default) VALUES (?, ?, ?, ?)",
        ("Writing Coach", "Helps with blog posts, documentation, and technical writing",
         "You are a technical writing coach. Help improve clarity, structure, and readability of engineering blog posts and documentation.", 0),
    )
    db.commit()


def seed_claude_sessions(db):
    """Seed Claude session history with realistic fake sessions."""
    sessions_dir = DATA_DIR / "claude_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    sessions = [
        (
            "Investigate auth migration latency spike",
            "Investigated the 2x latency increase during auth migration load test. "
            "Root cause: token validation was making a synchronous call to the identity provider on every request. "
            "Solution: add an edge caching layer for validated tokens with 5-minute TTL.",
            "- Analyzed auth migration load test results showing 2x latency at peak\n"
            "- Identified synchronous token validation as the bottleneck\n"
            "- Proposed edge caching layer with 5-minute TTL for validated tokens\n"
            "- Estimated 85% reduction in validation latency\n"
            "- Created draft PR #251 with the caching implementation",
            48,
        ),
        (
            "Draft Q1 engineering retrospective",
            "Helped draft the Q1 engineering retrospective covering auth migration progress, "
            "CI/CD improvements, and team growth. Identified key wins and areas for improvement.",
            "- Reviewed Q1 OKR progress across all engineering teams\n"
            "- Auth migration: 60% complete, on track for Q1 target\n"
            "- CI build time reduced from 14min to 8min\n"
            "- 3 new hires onboarded successfully\n"
            "- Areas for improvement: test coverage, on-call documentation\n"
            "- Generated retrospective document outline",
            120,
        ),
        (
            "Debug flaky Playwright test in CI",
            "Tracked down intermittent Playwright test failure in the onboarding flow. "
            "Race condition between navigation and form hydration. Fixed with explicit wait.",
            "- Investigated flaky `test-onboarding-flow` Playwright test\n"
            "- Reproduced locally with `--repeat-each=10`\n"
            "- Root cause: race condition — test clicking submit before React hydration completes\n"
            "- Fix: added `waitForSelector` before form interaction\n"
            "- Verified fix passes 50/50 runs locally",
            24,
        ),
        (
            "Plan API rate limiting implementation",
            "Designed rate limiting strategy for the public API. Chose token bucket algorithm "
            "with Redis backend, per-customer limits, and graceful degradation.",
            "- Evaluated rate limiting algorithms: fixed window, sliding window, token bucket, leaky bucket\n"
            "- Recommended token bucket with Redis for distributed rate limiting\n"
            "- Proposed per-customer rate limits: 100 req/min (free), 1000 req/min (pro), 10000 req/min (enterprise)\n"
            "- Designed graceful degradation: return 429 with Retry-After header\n"
            "- Outlined implementation plan across 3 PRs",
            168,
        ),
    ]

    for i, (title, preview, summary, hours_ago) in enumerate(sessions, 1):
        plain_text = f"$ claude\n\n> {title}\n\n{summary}\n\n> /quit\n\nSession ended."
        raw_output_text = (
            f"\x1b[1;34m╭─\x1b[0m Claude Code\r\n"
            f"\x1b[1;34m│\x1b[0m\r\n"
            f"\x1b[1;32m>\x1b[0m {title}\r\n\r\n"
            + summary.replace("\n", "\r\n")
            + "\r\n\r\n\x1b[90m--- session ended ---\x1b[0m\r\n"
        )
        import base64
        raw_b64 = base64.b64encode(raw_output_text.encode()).decode()

        filepath = sessions_dir / f"session_{i}.json"
        file_data = {
            "id": i,
            "raw_output": raw_b64,
            "plain_text": plain_text,
            "metadata": {"rows": 24, "cols": 80},
        }
        filepath.write_text(json.dumps(file_data))

        db.execute(
            "INSERT INTO claude_sessions (id, title, preview, summary, size_bytes, filepath, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, title, preview, summary, len(raw_output_text), str(filepath),
             _ts(hours_ago=hours_ago), _ts(hours_ago=hours_ago)),
        )
    db.commit()


def seed_sync_state(db):
    sources = [
        "gmail", "calendar", "slack", "notion", "notion_meetings",
        "github", "granola", "drive", "sheets", "docs",
        "ramp", "ramp_vendors", "ramp_bills", "news",
        "person_linking", "fts",
    ]
    for src in sources:
        db.execute(
            "INSERT OR REPLACE INTO sync_state (source, last_sync_at, last_sync_status, items_synced) VALUES (?, ?, 'success', ?)",
            (src, _ts(hours_ago=1), 10),
        )
    db.commit()


def seed_cached_priorities(db):
    """Pre-seed AI priorities so the briefing page works without Gemini."""
    priorities = [
        ("Prep for 1:1 with Sarah Kim", "She flagged concerns about the API migration timeline — discuss blockers and revised estimates.", "calendar", "high"),
        ("Review Marcus's PR for auth refactor", "PR #247 has been open for 3 days and is blocking the sprint.", "email", "high"),
        ("Respond to Lisa Park's Slack DM", "She asked about budget approval for the Datadog upgrade — needs your sign-off.", "slack", "high"),
        ("Board deck review with CEO", "Meeting at 2pm — review the engineering section and have updated headcount numbers ready.", "calendar", "high"),
        ("Overdue invoice from CloudScale", "$12,400 bill is 5 days past due. Verify with finance.", "ramp", "medium"),
        ("Q1 OKR draft updated", "Product team revised the shared OKR doc — check if engineering targets still align.", "drive", "medium"),
        ("Follow up on hiring pipeline", "Sync with recruiting on the senior backend role — 2 candidates in final round.", "note", "medium"),
        ("Design review feedback needed", "UX team shared new onboarding mockups — they need your input by EOD.", "slack", "low"),
    ]
    for title, reason, source, urgency in priorities:
        db.execute(
            "INSERT INTO cached_priorities (title, reason, source, urgency) VALUES (?, ?, ?, ?)",
            (title, reason, source, urgency),
        )

    # Briefing summary
    summary = (
        "Your morning is meeting-heavy with back-to-back 1:1s, but the key focus should be Sarah's API migration "
        "concerns and the board deck review with Emily at 2pm. Marcus's auth PR is blocking the sprint and needs "
        "your review. There's also an overdue CloudScale invoice that finance should have handled."
    )
    db.execute(
        "INSERT OR REPLACE INTO cached_briefing_summary (id, summary, data_hash) VALUES (1, ?, 'demo')",
        (summary,),
    )
    db.commit()


def seed_cached_rankings(db):
    """Pre-seed AI ranking caches for email, slack, notion, news, drive, ramp."""

    # Email rankings
    email_items = [
        {"id": "t-1", "thread_id": "t-1", "subject": "Re: Q1 Engineering OKR Review", "snippet": "Thanks for the updated targets...", "from_name": "Sarah Kim", "from_email": "sarah@acmecorp.com", "date": _ts(hours_ago=2), "is_unread": True, "message_count": 2, "priority_score": 9, "priority_reason": "Direct report flagging concerns about OKR targets"},
        {"id": "t-2", "thread_id": "t-2", "subject": "Board Deck - Engineering Section Draft", "snippet": "Please review the headcount slide...", "from_name": "David Park", "from_email": "david@acmecorp.com", "date": _ts(hours_ago=4), "is_unread": True, "message_count": 1, "priority_score": 9, "priority_reason": "CFO needs review before board meeting today"},
        {"id": "t-3", "thread_id": "t-3", "subject": "Auth Refactor PR - Ready for Review", "snippet": "PR #247 is ready...", "from_name": "Marcus Johnson", "from_email": "marcus@acmecorp.com", "date": _ts(hours_ago=10), "is_unread": False, "message_count": 1, "priority_score": 8, "priority_reason": "Blocking PR needs review"},
        {"id": "t-6", "thread_id": "t-6", "subject": "Re: Senior Backend Engineer - Candidate Pipeline", "snippet": "2 strong candidates moving to final round...", "from_name": "Jennifer Adams", "from_email": "jennifer@toptalent.com", "date": _ts(hours_ago=20), "is_unread": True, "message_count": 1, "priority_score": 7, "priority_reason": "Active hiring pipeline update"},
        {"id": "t-5", "thread_id": "t-5", "subject": "Quarterly Infrastructure Cost Report", "snippet": "AWS spend is up 12%...", "from_name": "Rachel Torres", "from_email": "rachel@acmecorp.com", "date": _ts(hours_ago=18), "is_unread": False, "message_count": 1, "priority_score": 6, "priority_reason": "Cost increase needs attention"},
        {"id": "t-14", "thread_id": "t-14", "subject": "CI pipeline green again", "snippet": "Fixed the flaky test...", "from_name": "James Wright", "from_email": "james@acmecorp.com", "date": _ts(hours_ago=6), "is_unread": True, "message_count": 1, "priority_score": 5, "priority_reason": "Good news — CI is unblocked"},
        {"id": "t-4", "thread_id": "t-4", "subject": "Re: Vendor Meeting - CloudScale Contract Renewal", "snippet": "Confirmed for Thursday 10am...", "from_name": "Lisa Park", "from_email": "lisa@acmecorp.com", "date": _ts(hours_ago=14), "is_unread": False, "message_count": 1, "priority_score": 5, "priority_reason": "Vendor meeting logistics"},
    ]
    db.execute("INSERT INTO cached_email_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": email_items}),))

    # Slack rankings
    slack_items = [
        {"id": "sl-1", "user_name": "Lisa Park", "text": "Hey Alex, quick question — do you have budget approval for the Datadog upgrade?", "channel_name": "dm", "channel_type": "dm", "ts": _unix_ts(3), "is_mention": False, "permalink": "", "priority_score": 9, "priority_reason": "Direct question needing your decision"},
        {"id": "sl-3", "user_name": "Nina Patel", "text": "Shared the updated onboarding mockups. @alex would love your feedback.", "channel_name": "product", "channel_type": "channel", "ts": _unix_ts(6), "is_mention": True, "permalink": "", "priority_score": 8, "priority_reason": "Direct mention requesting feedback"},
        {"id": "sl-4", "user_name": "Sarah Kim", "text": "Auth migration load test showed 2x latency increase at peak.", "channel_name": "engineering", "channel_type": "channel", "ts": _unix_ts(8), "is_mention": False, "permalink": "", "priority_score": 8, "priority_reason": "Critical issue with key project"},
        {"id": "sl-5", "user_name": "Marcus Johnson", "text": "PR #247 is updated. Ready for final approval.", "channel_name": "dm", "channel_type": "dm", "ts": _unix_ts(10), "is_mention": False, "permalink": "", "priority_score": 7, "priority_reason": "Blocking PR needs action"},
        {"id": "sl-15", "user_name": "Chris Anderson", "text": "Can we chat about the API stability report? Sales team needs it.", "channel_name": "dm", "channel_type": "dm", "ts": _unix_ts(36), "is_mention": False, "permalink": "", "priority_score": 6, "priority_reason": "Cross-functional request"},
        {"id": "sl-6", "user_name": "Rachel Torres", "text": "AWS costs for February came in at $34.5k. 12% above budget.", "channel_name": "engineering", "channel_type": "channel", "ts": _unix_ts(12), "is_mention": False, "permalink": "", "priority_score": 5, "priority_reason": "Budget overage needs attention"},
    ]
    db.execute("INSERT INTO cached_slack_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": slack_items}),))

    # Notion rankings
    notion_items = [
        {"id": "n-1", "title": "Q1 2026 Engineering Roadmap", "url": "https://notion.so/acmecorp/q1-roadmap", "last_edited_time": _ts(hours_ago=6), "last_edited_by": "Sarah Kim", "priority_score": 9, "priority_reason": "Active roadmap being updated by your team"},
        {"id": "n-2", "title": "Auth Migration — Technical Design Doc", "url": "https://notion.so/acmecorp/auth-migration", "last_edited_time": _ts(hours_ago=14), "last_edited_by": "Marcus Johnson", "priority_score": 8, "priority_reason": "Key project design doc recently updated"},
        {"id": "n-9", "title": "API Rate Limiting Design", "url": "https://notion.so/acmecorp/rate-limiting", "last_edited_time": _ts(hours_ago=36), "last_edited_by": "Sarah Kim", "priority_score": 7, "priority_reason": "Active feature design"},
        {"id": "n-10", "title": "User Research — Onboarding Insights", "url": "https://notion.so/acmecorp/onboarding-research", "last_edited_time": _ts(hours_ago=20), "last_edited_by": "Megan Liu", "priority_score": 6, "priority_reason": "Fresh user research findings"},
        {"id": "n-3", "title": "Onboarding Flow Redesign — PRD", "url": "https://notion.so/acmecorp/onboarding-prd", "last_edited_time": _ts(hours_ago=18), "last_edited_by": "Nina Patel", "priority_score": 5, "priority_reason": "Product requirement doc for active project"},
    ]
    db.execute("INSERT INTO cached_notion_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": notion_items}),))

    # News rankings
    news_items = [
        {"id": "news-1", "title": "OpenAI Announces GPT-5 with Reasoning Capabilities", "url": "https://techcrunch.com/2026/03/gpt5", "domain": "techcrunch.com", "snippet": "OpenAI unveiled GPT-5...", "source": "TechCrunch", "found_at": _ts(hours_ago=6), "priority_score": 8, "priority_reason": "Major AI industry development"},
        {"id": "news-2", "title": "Supply Chain AI Startups See Record Funding", "url": "https://reuters.com/2026/supply-chain-ai", "domain": "reuters.com", "snippet": "VC investment reached $4.2B...", "source": "Reuters", "found_at": _ts(hours_ago=8), "priority_score": 9, "priority_reason": "Directly relevant to your company's market"},
        {"id": "news-6", "title": "OAuth 2.1 Specification Finalized by IETF", "url": "https://ietf.org/oauth21", "domain": "ietf.org", "snippet": "The OAuth 2.1 spec consolidates best practices...", "source": "IETF", "found_at": _ts(hours_ago=30), "priority_score": 8, "priority_reason": "Directly relevant to your auth migration"},
        {"id": "news-3", "title": "Kubernetes 1.32 Released with Enhanced Security", "url": "https://kubernetes.io/blog/v132", "domain": "kubernetes.io", "snippet": "Pod-level security policies...", "source": "Kubernetes Blog", "found_at": _ts(hours_ago=12), "priority_score": 7, "priority_reason": "Relevant to planned K8s migration"},
        {"id": "news-13", "title": "AWS Announces 15% Price Reduction for EC2", "url": "https://aws.amazon.com/blog/ec2-pricing", "domain": "aws.amazon.com", "snippet": "AWS reduces EC2 pricing...", "source": "AWS Blog", "found_at": _ts(hours_ago=96), "priority_score": 7, "priority_reason": "Could reduce your infrastructure costs"},
        {"id": "news-9", "title": "Datadog Acquires AI Observability Startup", "url": "https://techcrunch.com/datadog-acquisition", "domain": "techcrunch.com", "snippet": "Datadog expands AI monitoring...", "source": "TechCrunch", "found_at": _ts(hours_ago=48), "priority_score": 6, "priority_reason": "Relevant to your monitoring vendor evaluation"},
    ]
    db.execute("INSERT INTO cached_news_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": news_items}),))

    # Drive rankings
    drive_items = [
        {"id": "d-1", "name": "Q1 2026 Engineering OKRs", "mime_type": "application/vnd.google-apps.spreadsheet", "modified_time": _ts(hours_ago=6), "web_view_link": "https://docs.google.com/spreadsheets/d/d-1", "modified_by_name": "Sarah Kim", "priority_score": 9, "priority_reason": "Your team OKRs being actively updated"},
        {"id": "d-2", "name": "Board Deck — March 2026", "mime_type": "application/vnd.google-apps.presentation", "modified_time": _ts(hours_ago=8), "web_view_link": "https://docs.google.com/presentation/d/d-2", "modified_by_name": "David Park", "priority_score": 9, "priority_reason": "Board meeting deck needs your review today"},
        {"id": "d-3", "name": "Auth Migration Architecture", "mime_type": "application/vnd.google-apps.document", "modified_time": _ts(hours_ago=14), "web_view_link": "https://docs.google.com/document/d/d-3", "modified_by_name": "Marcus Johnson", "priority_score": 7, "priority_reason": "Key project architecture doc updated"},
        {"id": "d-6", "name": "Onboarding User Research Results", "mime_type": "application/vnd.google-apps.document", "modified_time": _ts(hours_ago=20), "web_view_link": "https://docs.google.com/document/d/d-6", "modified_by_name": "Megan Liu", "priority_score": 6, "priority_reason": "Fresh user research for active project"},
        {"id": "d-4", "name": "Q1 Infrastructure Cost Report", "mime_type": "application/vnd.google-apps.spreadsheet", "modified_time": _ts(hours_ago=18), "web_view_link": "https://docs.google.com/spreadsheets/d/d-4", "modified_by_name": "Rachel Torres", "priority_score": 5, "priority_reason": "Cost report with 12% overage"},
    ]
    db.execute("INSERT INTO cached_drive_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": drive_items}),))

    # Ramp rankings
    ramp_items = [
        {"id": "rt-1", "amount": 34521.89, "currency": "USD", "merchant_name": "Amazon Web Services", "cardholder_email": "rachel@acmecorp.com", "transaction_date": _ts(hours_ago=48), "priority_score": 9, "priority_reason": "Largest monthly expense, 12% above budget"},
        {"id": "rt-7", "amount": 5600.00, "currency": "USD", "merchant_name": "WeWork", "cardholder_email": "alex@acmecorp.com", "transaction_date": _ts(hours_ago=192), "priority_score": 5, "priority_reason": "Office space — recurring"},
        {"id": "rt-2", "amount": 4200.00, "currency": "USD", "merchant_name": "Datadog", "cardholder_email": "lisa@acmecorp.com", "transaction_date": _ts(hours_ago=72), "priority_score": 7, "priority_reason": "Under review for possible upgrade"},
        {"id": "rt-10", "amount": 2100.00, "currency": "USD", "merchant_name": "TopTalent Agency", "cardholder_email": "alex@acmecorp.com", "transaction_date": _ts(hours_ago=60), "priority_score": 6, "priority_reason": "Recruiting costs for active hiring"},
        {"id": "rt-3", "amount": 1890.00, "currency": "USD", "merchant_name": "GitHub Enterprise", "cardholder_email": "alex@acmecorp.com", "transaction_date": _ts(hours_ago=96), "priority_score": 4, "priority_reason": "Standard tooling cost"},
    ]
    db.execute("INSERT INTO cached_ramp_priorities (data_json, data_hash) VALUES (?, 'demo')",
               (json.dumps({"items": ramp_items, "total_amount": sum(i["amount"] for i in ramp_items)}),))

    db.commit()


# --- Main ---

def main():
    print("Seeding demo database...")

    # 1. Create data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Write config
    config_path = DATA_DIR / "config.json"
    config_path.write_text(json.dumps(CONFIG, indent=2))
    config_path.chmod(0o600)
    print(f"  Config written to {config_path}")

    # 3. Remove existing DB
    db_path = DATA_DIR / "dashboard.db"
    if db_path.exists():
        db_path.unlink()

    # 4. Run migrations (creates schema)
    from database import init_db
    init_db()
    print(f"  Database created at {db_path}")

    # 5. Populate tables
    from database import get_write_db, rebuild_fts

    with get_write_db() as db:
        seed_people(db)
        print("  Seeded: people")
        seed_notes(db)
        print("  Seeded: notes")
        seed_issues(db)
        print("  Seeded: issues")
        seed_calendar(db)
        print("  Seeded: calendar_events")
        seed_emails(db)
        print("  Seeded: emails")
        seed_slack(db)
        print("  Seeded: slack_messages")
        seed_notion(db)
        print("  Seeded: notion_pages")
        seed_github(db)
        print("  Seeded: github_pull_requests")
        seed_granola(db)
        print("  Seeded: granola_meetings")
        seed_drive(db)
        print("  Seeded: drive_files")
        seed_ramp(db)
        print("  Seeded: ramp (transactions, bills, vendors)")
        seed_projects(db)
        print("  Seeded: projects")
        seed_news(db)
        print("  Seeded: news_items")
        seed_longform(db)
        print("  Seeded: longform_posts")
        seed_personas(db)
        print("  Seeded: personas")
        seed_claude_sessions(db)
        print("  Seeded: claude_sessions")
        seed_sync_state(db)
        print("  Seeded: sync_state")
        seed_cached_priorities(db)
        print("  Seeded: cached_priorities + briefing_summary")
        seed_cached_rankings(db)
        print("  Seeded: cached rankings (email, slack, notion, news, drive, ramp)")

    # 6. Rebuild FTS indexes
    rebuild_fts()
    print("  Rebuilt FTS indexes")

    print(f"\nDemo database ready at {db_path}")
    print("Run 'make demo' to start the demo server.")


if __name__ == "__main__":
    main()
