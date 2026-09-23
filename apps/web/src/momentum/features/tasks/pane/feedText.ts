import { formatDay } from '@/lib/dates';
import type { ActivityItem, FeedItem } from '../comments';

export interface FeedNames {
  person: (id: string) => string | undefined;
  section: (id: string) => string | undefined;
}

const q = (s: unknown) => `“${String(s ?? '')}”`;

/**
 * Human sentences (without the actor) for one activity entry, e.g. "changed the due date to Oct 5".
 * `minor` entries can be folded together when the same person makes several in a row.
 */
export function describeActivity(a: ActivityItem, n: FeedNames): { lines: string[]; minor: boolean } {
  const c = a.changes as Record<string, [unknown, unknown]>;
  const sub = a.subject?.title;
  const who = (id: unknown) => (id === a.actor_id ? 'themselves' : (n.person(String(id)) ?? 'someone'));
  switch (a.verb) {
    case 'task.created':
      return { lines: [sub ? `added subtask ${q(sub)}` : 'created this task'], minor: false };
    case 'task.completed':
      return { lines: [sub ? `completed subtask ${q(sub)}` : 'marked this task complete'], minor: false };
    case 'task.uncompleted':
      return { lines: [sub ? `reopened subtask ${q(sub)}` : 'marked this task incomplete'], minor: false };
    case 'task.deleted':
      return { lines: [sub ? `deleted subtask ${q(sub)}` : 'deleted this task'], minor: false };
    case 'task.restored':
      return { lines: ['restored this task'], minor: false };
    case 'task.follower_added': {
      const id = c.follower?.[1];
      return {
        lines: [id === a.actor_id ? 'joined as a collaborator' : `added ${who(id)} as a collaborator`],
        minor: true,
      };
    }
    case 'task.follower_removed': {
      const id = c.follower?.[0];
      return {
        lines: [id === a.actor_id ? 'left as a collaborator' : `removed ${who(id)} as a collaborator`],
        minor: true,
      };
    }
    case 'task.moved': {
      if (c.section_id)
        return {
          lines: [`moved this task to ${n.section(String(c.section_id[1])) ?? 'another section'}`],
          minor: true,
        };
      if (c.parent_id)
        return {
          lines: [
            c.parent_id[1] ? 'moved this task under another task' : 'moved this task out of its parent',
          ],
          minor: true,
        };
      return { lines: [], minor: true };
    }
    case 'task.updated': {
      const lines: string[] = [];
      for (const [field, [, now]] of Object.entries(c)) {
        if (field === 'title') lines.push(`renamed this task to ${q(now)}`);
        else if (field === 'assignee_id')
          lines.push(now ? `assigned this task to ${who(now)}` : 'unassigned this task');
        else if (field === 'due_on')
          lines.push(now ? `changed the due date to ${formatDay(String(now))}` : 'removed the due date');
        else if (field === 'due_at' && !('due_on' in c))
          lines.push(now ? 'changed the due time' : 'removed the due time');
        else if (field === 'start_on')
          lines.push(now ? `changed the start date to ${formatDay(String(now))}` : 'removed the start date');
        else if (field === 'description')
          lines.push(now ? 'updated the description' : 'cleared the description');
      }
      return { lines, minor: !('description' in c) };
    }
    default:
      return { lines: [], minor: true };
  }
}

export type FeedEntry =
  | { kind: 'comment'; item: FeedItem }
  | { kind: 'activity'; item: FeedItem; lines: string[] }
  | { kind: 'folded'; actorId: string | null; at: string; entries: { item: FeedItem; lines: string[] }[] };

const FOLD_WINDOW_MS = 10 * 60_000;
const FOLD_MIN = 3;

/** Turn the raw feed into display entries: drop empty lines, fold runs of ≥3 minor changes by the
 * same person within 10 minutes into one "made N changes" entry. */
export function buildFeed(
  items: FeedItem[],
  n: FeedNames,
  filter: 'all' | 'comments' | 'activity',
): FeedEntry[] {
  const out: FeedEntry[] = [];
  let run: { item: FeedItem; lines: string[] }[] = [];
  const flush = () => {
    if (run.length >= FOLD_MIN) {
      out.push({
        kind: 'folded',
        actorId: run[0]!.item.activity!.actor_id ?? null,
        at: run.at(-1)!.item.at,
        entries: run,
      });
    } else run.forEach((r) => out.push({ kind: 'activity', item: r.item, lines: r.lines }));
    run = [];
  };
  for (const item of items) {
    if (item.kind === 'comment') {
      flush();
      if (filter !== 'activity') out.push({ kind: 'comment', item });
      continue;
    }
    if (filter === 'comments' || !item.activity) continue;
    const { lines, minor } = describeActivity(item.activity, n);
    if (!lines.length) continue;
    const prev = run.at(-1);
    const sameRun =
      minor &&
      prev &&
      prev.item.activity!.actor_id === item.activity.actor_id &&
      new Date(item.at).getTime() - new Date(prev.item.at).getTime() <= FOLD_WINDOW_MS;
    if (!sameRun) flush();
    if (minor) run.push({ item, lines });
    else out.push({ kind: 'activity', item, lines });
  }
  flush();
  return out;
}
