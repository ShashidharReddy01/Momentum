import { describe, expect, it } from 'vitest';
import { parseQuickAdd, looksLikeMoreDetail, type ParsedQuickAdd } from './quickAddParse';

const me = { id: 'u-ravi', name: 'Ravi Kumar', email: 'ravi@acme-demo.test' };
const people = [
  me,
  { id: 'u-ana', name: 'Ana Souza', email: 'ana@acme-demo.test' },
  { id: 'u-tom', name: 'Tom Becker', email: 'tom@acme-demo.test' },
  { id: 'u-tom2', name: 'Tom Okafor', email: 'tom.o@acme-demo.test' },
];
const projects = [
  { id: 'p-web', name: 'Website Revamp' },
  { id: 'p-q4', name: 'Q4 Launch Campaign' },
  { id: 'p-vendor', name: 'Vendor Onboarding' },
];
const now = new Date(2026, 8, 26, 10, 0); // Saturday 26 Sep 2026, local time

const parse = (text: string) => parseQuickAdd(text, { people, projects, me, now });
type Want = Partial<Omit<ParsedQuickAdd, 'assignee' | 'project' | 'due'>> & {
  assignee?: string;
  project?: string;
  due?: string;
  timed?: boolean;
};

// The 24 local phrases of S3.2.1's 30 (the other 6 go to the AI half: tests/test_ai_quick_add.py).
const PHRASES: [string, Want][] = [
  [
    'Review deck @ana tomorrow #website !high',
    {
      title: 'Review deck',
      assignee: 'Ana Souza',
      project: 'Website Revamp',
      due: '2026-09-27',
      priority: 'high',
    },
  ],
  ['Call the printer', { title: 'Call the printer' }],
  [
    'Draft pricing copy @me friday',
    { title: 'Draft pricing copy', assignee: 'Ravi Kumar', due: '2026-10-02' },
  ],
  ['Update footer links #website-revamp', { title: 'Update footer links', project: 'Website Revamp' }],
  [
    'Plan offsite @"Ana Souza" next monday',
    { title: 'Plan offsite', assignee: 'Ana Souza', due: '2026-09-28' },
  ],
  ['Send invoice by sept 30', { title: 'Send invoice', due: '2026-09-30' }],
  [
    'Standup notes every weekday',
    {
      title: 'Standup notes',
      recurrence: { freq: 'daily', interval: 1, workdays_only: true, text: 'every weekday' },
    },
  ],
  [
    'Water plants every monday and thursday',
    {
      title: 'Water plants',
      recurrence: { freq: 'weekly', interval: 1, by_weekday: [0, 3], text: 'every monday and thursday' },
    },
  ],
  [
    'Pay rent every month',
    { title: 'Pay rent', recurrence: { freq: 'monthly', interval: 1, text: 'every month' } },
  ],
  [
    'Backup check every 2 weeks',
    { title: 'Backup check', recurrence: { freq: 'weekly', interval: 2, text: 'every 2 weeks' } },
  ],
  [
    'Sync with design every other friday',
    {
      title: 'Sync with design',
      recurrence: { freq: 'weekly', interval: 2, by_weekday: [4], text: 'every other friday' },
    },
  ],
  ['Fix login bug !urgent', { title: 'Fix login bug', priority: 'urgent' }],
  ['Tidy backlog !low', { title: 'Tidy backlog', priority: 'low' }],
  ['Ship release !p2', { title: 'Ship release', priority: 'high' }],
  ['Book venue @ravi.kumar in 3 days', { title: 'Book venue', assignee: 'Ravi Kumar', due: '2026-09-29' }],
  ['Review contract @bob', { title: 'Review contract', unresolved: ['@bob'] }],
  ['Plan launch #q4', { title: 'Plan launch', project: 'Q4 Launch Campaign' }],
  ['Kickoff call tomorrow at 3pm', { title: 'Kickoff call', due: '2026-09-27', timed: true }],
  [
    'Weekly report every friday #website @me !medium',
    {
      title: 'Weekly report',
      project: 'Website Revamp',
      assignee: 'Ravi Kumar',
      priority: 'medium',
      recurrence: { freq: 'weekly', interval: 1, by_weekday: [4], text: 'every friday' },
    },
  ],
  ['Email @ana about the budget', { title: 'Email about the budget', assignee: 'Ana Souza' }],
  ['Check #unknown project', { title: 'Check project', unresolved: ['#unknown'] }],
  ['Pair on tests @tom', { title: 'Pair on tests', unresolved: ['@tom'] }],
  ['Renew domain on oct 3', { title: 'Renew domain', due: '2026-10-03' }],
  ['Escalate outage !!!', { title: 'Escalate outage', priority: 'urgent' }],
];

describe('parseQuickAdd (S3.2.1)', () => {
  it.each(PHRASES)('%s', (text, want) => {
    const got = parse(text);
    expect(got.title).toBe(want.title);
    expect(got.assignee?.name ?? undefined).toBe(want.assignee);
    expect(got.project?.name ?? undefined).toBe(want.project);
    expect(got.due?.date ?? undefined).toBe(want.due);
    expect(Boolean(got.due?.at)).toBe(Boolean(want.timed));
    expect(got.priority ?? undefined).toBe(want.priority);
    expect(got.recurrence ?? undefined).toEqual(want.recurrence);
    expect(got.unresolved).toEqual(want.unresolved ?? []);
  });

  it('leaves numbers and punctuation that are not dates alone', () => {
    expect(parse('Migrate 3 posts').title).toBe('Migrate 3 posts');
    expect(parse('Migrate 3 posts').due).toBeNull();
    expect(parse('Ship it !').priority).toBeNull();
    expect(parse('Email support@acme.test').assignee).toBeNull();
    expect(parse('Pay rent monthly').recurrence).toEqual({ freq: 'monthly', interval: 1, text: 'monthly' });
    expect(parse('Pay rent monthly').title).toBe('Pay rent');
  });

  it('flags text that still reads like unparsed details', () => {
    expect(looksLikeMoreDetail('Prepare the budget deck for Ana by end of next week')).toBe(true);
    expect(looksLikeMoreDetail('Priya should review the vendor contract asap')).toBe(true);
    expect(looksLikeMoreDetail('Review deck')).toBe(false);
    expect(looksLikeMoreDetail('Plan for the offsite')).toBe(false); // "for" + lowercase isn't a person
  });
});
