import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export function HelpPage() {
  const navigate = useNavigate();

  useEffect(() => {
    localStorage.setItem('hasSeenIntro', '1');
  }, []);

  const goToDashboard = () => navigate('/');

  return (
    <div className="help-page">
      <header className="help-hero">
        <h1>Your dashboard. Your way.</h1>
        <p className="help-subtitle">
          Everything you need to stay on top of the day&mdash;email, Slack, calendar,
          team, and your own thoughts&mdash;all in one quiet place.
        </p>
        <button className="help-cta" onClick={goToDashboard}>
          Go to Dashboard
        </button>
        <p className="help-hint">
          Press <kbd>h</kbd> to come back here anytime
        </p>
      </header>

      <section className="help-section">
        <h2>&ldquo;What&rsquo;s happening today?&rdquo;</h2>
        <p>
          Your morning starts with a briefing&mdash;weather, inbox pulse counts,
          today&rsquo;s calendar timeline, AI-generated priorities, and an overnight
          digest of what came in while you were away. One glance tells you what
          matters.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>d</kbd> Morning briefing
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;Who do I need to talk to?&rdquo;</h2>
        <p>
          A unified people directory holds coworkers and external contacts with
          group filtering. Every person has a page showing their upcoming 1:1,
          open discussion topics, meeting history, custom attributes, and
          connections. Walk into every conversation prepared.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>p</kbd> People &middot; click any name in the sidebar
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;What was I thinking about?&rdquo;</h2>
        <p>
          Capture notes with a single keystroke. Tag them to people with <code>@mentions</code>,
          mark 1:1 topics with <code>[1]</code>, or file away private reflections
          with <code>[t]</code>. Everything stays connected to the right person and the right context.
        </p>
        <div className="help-keys">
          <kbd>c</kbd> new note &middot; <kbd>&#x2318;K</kbd> then <kbd>Tab</kbd> for quick create
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;What needs my attention?&rdquo;</h2>
        <p>
          Unread email, Slack DMs, GitHub review requests, Notion updates, and
          overdue bills surface right on the briefing page. Dismiss what you&rsquo;ve
          handled, focus on what&rsquo;s left.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>d</kbd> Briefing &middot; <kbd>d</kbd> dismiss an item
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;What are people working on?&rdquo;</h2>
        <p>
          Track issues with priorities, t-shirt sizes, tags, due dates, and person
          linking. Navigate and triage entirely from the keyboard&mdash;arrow keys
          change priority, <code>x</code> marks done.
        </p>
        <p>
          Press <kbd>D</kbd> to discover new issues automatically&mdash;AI scans your
          email, Slack, meetings, Notion, and calendar, then proposes tasks for you to
          accept, reject, or edit.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>i</kbd> Issues &middot; <kbd>D</kbd> Discover issues
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;I need to write something longer&hellip;&rdquo;</h2>
        <p>
          The longform editor gives you a markdown writing space for blog posts,
          drafts, and documents. Tag and filter posts, add comments and thoughts,
          toggle between edit, preview, and split modes, and open any draft
          directly in Claude for help.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>l</kbd> Longform writing
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;I need to find that thing&hellip;&rdquo;</h2>
        <p>
          <kbd>&#x2318;K</kbd> searches across everything&mdash;notes, meetings, email,
          Slack, Notion, and GitHub. Toggle external search with <kbd>&#x2318;E</kbd>.
          Press <kbd>Tab</kbd> to quick-create a note, thought, or issue without
          leaving the overlay.
        </p>
        <div className="help-keys">
          <kbd>&#x2318;K</kbd> search &middot; <kbd>?</kbd> all keyboard shortcuts
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;What&rsquo;s in my Drive?&rdquo;</h2>
        <p>
          Browse recent Google Drive files with AI-powered relevance ranking.
          Filter by score, switch between Docs, Sheets, and all files, and
          create issues directly from any document.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>v</kbd> Drive
        </div>
      </section>

      <section className="help-section">
        <h2>&ldquo;Can I just ask Claude?&rdquo;</h2>
        <p>
          An embedded Claude Code terminal lives right in the app. It has access to your
          dashboard&rsquo;s APIs, your database, and your team files. Ask it to prep for a
          meeting, draft a message, or analyze patterns across your data.
        </p>
        <div className="help-keys">
          <kbd>g</kbd> <kbd>c</kbd> Claude
        </div>
      </section>

      <footer className="help-footer">
        <h2>Built for the keyboard</h2>
        <p>
          Everything has a shortcut. Press <kbd>?</kbd> to see them all,
          or <kbd>&#x2318;K</kbd> to jump anywhere.
        </p>
        <button className="help-cta" onClick={goToDashboard}>
          Let&rsquo;s go
        </button>
      </footer>
    </div>
  );
}
