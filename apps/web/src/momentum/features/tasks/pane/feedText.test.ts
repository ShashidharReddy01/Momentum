import { describe, expect, it } from 'vitest';
import type { FeedItem } from '../comments';
import { buildFeed, describeActivity } from './feedText';

const names = {
  person: (id: string) => ({ ana: 'Ana Souza', ravi: 'Ravi Kumar' })[id],
  section: (id: string) => ({ s2: 'Review' })[id],
};
let n = 0;
const act = (
  verb: string,
  changes: Record<string, unknown[]>,
  over: Partial<FeedItem['activity']> = {},
  at?: string,
): FeedItem => {
  n += 1;
  const time = at ?? new Date(Date.UTC(2026, 8, 23, 10, n)).toISOString();
  return {
    kind: 'activity',
    at: time,
    activity: {
      id: `a${n}`,
      verb,
      actor_id: 'ravi',
      actor_kind: 'user',
      created_at: time,
      changes,
      subject: null,
      ...over,
    },
  } as FeedItem;
};

describe('activity sentences', () => {
  it.each([
    [act('task.created', { title: [null, 'X'] }), ['created this task']],
    [
      act('task.created', { title: [null, 'Step'] }, { subject: { id: 's', title: 'Step' } }),
      ['added subtask “Step”'],
    ],
    [act('task.updated', { assignee_id: [null, 'ana'] }), ['assigned this task to Ana Souza']],
    [act('task.updated', { assignee_id: [null, 'ravi'] }), ['assigned this task to themselves']],
    [act('task.updated', { assignee_id: ['ana', null] }), ['unassigned this task']],
    [
      act('task.updated', { due_on: [null, '2026-10-05'], due_at: [null, 'x'] }),
      ['changed the due date to Oct 5'],
    ],
    [act('task.updated', { due_on: ['2026-10-05', null] }), ['removed the due date']],
    [
      act('task.updated', { title: ['a', 'b'], description: [null, 'x'] }),
      ['renamed this task to “b”', 'updated the description'],
    ],
    [act('task.moved', { position: ['a', 'b'], section_id: ['s1', 's2'] }), ['moved this task to Review']],
    [act('task.moved', { position: ['a', 'b'] }), []],
    [act('task.follower_added', { follower: [null, 'ana'] }), ['added Ana Souza as a collaborator']],
    [act('task.follower_removed', { follower: ['ravi', null] }), ['left as a collaborator']],
    [act('task.completed', { completed_at: [null, 'x'] }), ['marked this task complete']],
    [act('something.new', {}), []],
  ])('%#', (item, lines) => {
    expect(describeActivity(item.activity!, names).lines).toEqual(lines);
  });
});

describe('buildFeed', () => {
  it('folds 3+ minor changes by one person within 10 minutes; keeps comments and major entries apart', () => {
    const t0 = Date.UTC(2026, 8, 23, 12, 0);
    const at = (m: number) => new Date(t0 + m * 60_000).toISOString();
    const items = [
      act('task.created', { title: [null, 'X'] }, {}, at(0)),
      act('task.updated', { title: ['X', 'Y'] }, {}, at(1)),
      act('task.updated', { due_on: [null, '2026-10-05'] }, {}, at(2)),
      act('task.updated', { assignee_id: [null, 'ana'] }, {}, at(3)),
      { kind: 'comment', at: at(4), comment: { id: 'c1' } } as FeedItem,
      act('task.updated', { title: ['Y', 'Z'] }, {}, at(5)),
      act('task.updated', { title: ['Z', 'W'] }, { actor_id: 'ana' }, at(6)),
    ];
    const out = buildFeed(items, names, 'all');
    expect(out.map((e) => e.kind)).toEqual(['activity', 'folded', 'comment', 'activity', 'activity']);
    const folded = out[1] as Extract<(typeof out)[number], { kind: 'folded' }>;
    expect(folded.entries).toHaveLength(3);
    expect(buildFeed(items, names, 'comments').map((e) => e.kind)).toEqual(['comment']);
    expect(buildFeed(items, names, 'activity').some((e) => e.kind === 'comment')).toBe(false);
  });

  it('does not fold changes more than 10 minutes apart', () => {
    const t0 = Date.UTC(2026, 8, 23, 12, 0);
    const at = (m: number) => new Date(t0 + m * 60_000).toISOString();
    const items = [0, 11, 22].map((m) => act('task.updated', { title: ['a', 'b'] }, {}, at(m)));
    expect(buildFeed(items, names, 'all').map((e) => e.kind)).toEqual(['activity', 'activity', 'activity']);
  });
});
