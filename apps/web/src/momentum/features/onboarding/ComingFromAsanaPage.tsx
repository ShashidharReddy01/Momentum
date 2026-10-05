import { ArrowRight, Download } from 'lucide-react';
import { Link } from 'react-router';
import { Icon } from '@/components/ui/Icon';
import { Kbd } from '@/components/ui/Kbd';

/** Asana's words, and what Momentum calls the same thing (only where they differ). */
const TERMS: [string, string, string?][] = [
  ['Hearts on comments', 'Reactions', 'Any emoji; imported hearts show as 👍.'],
  ['Reporting', 'Dashboards', 'Charts by any field, across projects; ✦ Ask for a chart in words.'],
  [
    'Asana AI, AI teammates',
    'Ask Mo, Agents',
    'Mo answers and drafts changes you confirm; agents run on a schedule.',
  ],
  ['Board columns', 'Sections', 'The same sections show as list groups and board columns.'],
  ['Gantt / Timeline', 'Timeline', 'Moving a task shows what moves with it before anything is saved.'],
  [
    'Do today, Do next week, Do later',
    'Today, This week, Later',
    'My Tasks buckets; tasks move by due date each morning.',
  ],
  ['Project brief', 'Overview → Brief', ''],
  ['Waiting on / blocking', 'Blocked by / Blocking', 'Dependencies; a task says when it is unblocked.'],
];

/** Asana's shortcut, and Momentum's (Asana's Tab-prefixed keys work without Tab here). */
const KEYS: [string, string][] = [
  ['Tab + Q', 'q'],
  ['Tab + M', 'm'],
  ['Tab + A', 'a'],
  ['Tab + D', 'd'],
  ['Tab + C', 'c'],
  ['Tab + F', 'f'],
  ['Tab + /', '/'],
  ['Ctrl/⌘ + Enter', 'mod+enter'],
  ['Ctrl/⌘ + /', 'mod+/'],
];
const KEY_WORDS: Record<string, string> = {
  q: 'Add a task',
  m: 'Assign to me',
  a: 'Assign',
  d: 'Set the due date',
  c: 'Comment on the open task',
  f: 'Follow or unfollow the open task',
  '/': 'Search',
  'mod+enter': 'Complete',
  'mod+/': 'All keyboard shortcuts',
};

/**
 * S7.4.4: "Coming from Asana?" — what carries over, the words that differ, and the shortcuts.
 * Reachable from Home and from ⌘K.
 */
export function ComingFromAsanaPage() {
  return (
    <div className="min-w-0 flex-1 overflow-auto px-4 py-6 md:px-8">
      <div className="max-w-3xl">
        <h1 className="page-title mb-1">Coming from Asana?</h1>
        <p className="mb-6 text-sm text-muted">
          Most of what you know works the same way: projects with sections, list and board, My Tasks, the
          Inbox, custom fields, dependencies, approvals and milestones. Here is what differs.
        </p>

        <section
          aria-labelledby="asana-bring"
          className="mb-8 rounded-lg border border-hairline bg-surface p-4"
        >
          <h2 id="asana-bring" className="mb-2 text-sm font-semibold">
            Bring your work over
          </h2>
          <p className="mb-3 text-sm text-ink-2">
            The importer brings projects, sections, tasks and subtasks, custom fields, comments, files,
            followers, dependencies and status updates, keeping who did what and when. Try a dry run first: it
            shows what will come over and changes nothing. Rules and forms don't come over: recreate them in
            plain words with the rule builder and the form builder.
          </p>
          <Link
            to="/settings/import/asana"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink underline-offset-2 hover:underline"
          >
            <Icon icon={Download} size={14} /> Import from Asana <Icon icon={ArrowRight} size={14} />
          </Link>
        </section>

        <section aria-labelledby="asana-words" className="mb-8">
          <h2 id="asana-words" className="section-label mb-2">
            Words that differ
          </h2>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-hairline text-xs text-muted">
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  In Asana
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  In Momentum
                </th>
                <th scope="col" className="hidden py-1.5 font-medium sm:table-cell">
                  Good to know
                </th>
              </tr>
            </thead>
            <tbody>
              {TERMS.map(([asana, ours, note]) => (
                <tr key={asana} className="border-b border-hair-soft align-top">
                  <td className="py-2 pr-4 text-ink-2">{asana}</td>
                  <td className="py-2 pr-4 font-medium">{ours}</td>
                  <td className="hidden py-2 text-muted sm:table-cell">{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section aria-labelledby="asana-keys">
          <h2 id="asana-keys" className="section-label mb-2">
            Your shortcuts
          </h2>
          <p className="mb-2 text-sm text-muted">
            Tab moves between controls here (as it does on any web page), so Asana's Tab + key shortcuts are
            just the key.
          </p>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-hairline text-xs text-muted">
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  In Asana
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  In Momentum
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  Does
                </th>
              </tr>
            </thead>
            <tbody>
              {KEYS.map(([asana, ours]) => (
                <tr key={asana} className="border-b border-hair-soft">
                  <td className="py-2 pr-4 text-ink-2">{asana}</td>
                  <td className="py-2 pr-4">
                    <Kbd combo={ours} />
                  </td>
                  <td className="py-2 text-muted">{KEY_WORDS[ours]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
