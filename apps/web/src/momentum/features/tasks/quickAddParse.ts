import * as chrono from 'chrono-node';
import { toISODate, type DueValue } from '@/lib/dates';

export type Priority = 'urgent' | 'high' | 'medium' | 'low';

export interface Recurrence {
  freq: 'daily' | 'weekly' | 'monthly' | 'yearly';
  interval: number;
  by_weekday?: number[];
  workdays_only?: boolean;
  text: string;
}

export interface QuickAddPerson {
  id: string;
  name: string;
  email: string;
}

export interface QuickAddProject {
  id: string;
  name: string;
}

export interface ParsedQuickAdd {
  /** The task name with the recognized tokens taken out. */
  title: string;
  assignee: { id: string; name: string } | null;
  project: QuickAddProject | null;
  due: DueValue | null;
  priority: Priority | null;
  recurrence: Recurrence | null;
  /** Tokens that looked like a person/project but matched nothing or several ("@al"). */
  unresolved: string[];
}

const PRIORITY: Record<string, Priority> = {
  urgent: 'urgent',
  p1: 'urgent',
  '!!': 'urgent', // "!!!"
  high: 'high',
  p2: 'high',
  '!': 'high', // "!!"
  medium: 'medium',
  med: 'medium',
  normal: 'medium',
  p3: 'medium',
  low: 'low',
  p4: 'low',
};

const DAYS: Record<string, number> = {
  monday: 0,
  mon: 0,
  tuesday: 1,
  tue: 1,
  tues: 1,
  wednesday: 2,
  wed: 2,
  thursday: 3,
  thu: 3,
  thurs: 3,
  friday: 4,
  fri: 4,
  saturday: 5,
  sat: 5,
  sunday: 6,
  sun: 6,
};
const DAY = Object.keys(DAYS)
  .sort((a, b) => b.length - a.length)
  .join('|');
const EVERY = new RegExp(
  String.raw`\bevery\s+(?:(other)\s+|(\d{1,2})\s+)?(day|weekday|workday|week|month|year|(?:${DAY})(?:\s*(?:,|and|&)\s*(?:${DAY}))*)s?\b`,
  'i',
);
// "pay rent monthly": only when it isn't the first word ("Weekly report" is a name, not a rule)
const ADVERB = /(?<=\S\s+)\b(daily|weekly|monthly|yearly|annually)\b/i;
// quoted ("@\"Ana Souza\"") or a single run of word characters, dots and dashes
const TOKEN = /(^|\s)([@#])(?:"([^"]+)"|([\p{L}\p{N}][\p{L}\p{N}._-]*))/u;
const PRIO_TOKEN = /(^|\s)!(!!|!|urgent|high|medium|med|normal|low|p[1-4])(?=\s|$)/i;
const DANGLING = /\s+(?:by|on|due|at|before|until|for|from|starting)$/i;

const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

function matchPerson(raw: string, people: QuickAddPerson[], me: QuickAddPerson | null): QuickAddPerson[] {
  const q = raw
    .toLowerCase()
    .replace(/[._-]+/g, ' ')
    .trim();
  if (q === 'me' || q === 'myself') return me ? [me] : [];
  const full = people.filter((p) => p.name.toLowerCase() === q);
  if (full.length) return full;
  // first names before email handles: "@tom" with two Toms is ambiguous, whoever owns tom@
  const first = people.filter((p) => p.name.toLowerCase().split(/\s+/)[0] === q);
  if (first.length) return first;
  const local = people.filter((p) => p.email.toLowerCase().split('@')[0] === raw.toLowerCase());
  if (local.length) return local;
  return people.filter((p) => p.name.toLowerCase().startsWith(q));
}

function matchProject(raw: string, projects: QuickAddProject[]): QuickAddProject[] {
  const q = norm(raw);
  if (!q) return [];
  const exact = projects.filter((p) => norm(p.name) === q);
  if (exact.length) return exact;
  const starts = projects.filter((p) => norm(p.name).startsWith(q));
  if (starts.length) return starts;
  // any word of the name ("#marketing" → "Q4 Launch Campaign" wouldn't match; "#launch" would)
  return projects.filter((p) =>
    p.name
      .toLowerCase()
      .split(/\s+/)
      .some((w) => norm(w).startsWith(q)),
  );
}

function parseEvery(m: RegExpExecArray, adverb?: string): Recurrence {
  const text = m[0];
  const [other, n, unit] = adverb ? [undefined, undefined, undefined] : [m[1], m[2], m[3]];
  const interval = other ? 2 : n ? Number(n) : 1;
  const u = (unit ?? adverb ?? '').toLowerCase();
  if (u === 'daily' || u === 'day') return { freq: 'daily', interval, text: text.trim() };
  if (u === 'weekday' || u === 'workday')
    return { freq: 'daily', interval: 1, workdays_only: true, text: text.trim() };
  if (u === 'weekly' || u === 'week') return { freq: 'weekly', interval, text: text.trim() };
  if (u === 'monthly' || u === 'month') return { freq: 'monthly', interval, text: text.trim() };
  if (u === 'yearly' || u === 'annually' || u === 'year')
    return { freq: 'yearly', interval, text: text.trim() };
  const days = [...u.matchAll(new RegExp(DAY, 'gi'))].map((d) => DAYS[d[0].toLowerCase()]!);
  return {
    freq: 'weekly',
    interval,
    by_weekday: [...new Set(days)].sort((a, b) => a - b),
    text: text.trim(),
  };
}

/**
 * S3.2.1 local quick-add parsing: `Review deck @ana tomorrow #website !high every monday`.
 * Pure and synchronous, so it runs on every keystroke. `@`/`#` match people and projects the
 * caller passes in (only projects they can add tasks to); anything that matches nothing or several
 * goes to `unresolved` instead of being guessed. Dates use the same chrono setup as the date
 * picker (browser timezone, dates roll forward).
 */
export function parseQuickAdd(
  input: string,
  ctx: { people: QuickAddPerson[]; projects: QuickAddProject[]; me: QuickAddPerson | null; now?: Date },
): ParsedQuickAdd {
  let text = ` ${input} `;
  const out: ParsedQuickAdd = {
    title: '',
    assignee: null,
    project: null,
    due: null,
    priority: null,
    recurrence: null,
    unresolved: [],
  };

  for (let m = TOKEN.exec(text); m; m = TOKEN.exec(text)) {
    const [whole, lead, sigil, quoted, bare] = m;
    const raw = (quoted ?? bare ?? '').replace(/[.,;:]+$/, '');
    if (sigil === '@') {
      const hits = matchPerson(raw, ctx.people, ctx.me);
      if (hits.length === 1 && !out.assignee) out.assignee = { id: hits[0]!.id, name: hits[0]!.name };
      else out.unresolved.push(`@${raw}`);
    } else {
      const hits = matchProject(raw, ctx.projects);
      if (hits.length === 1 && !out.project) out.project = hits[0]!;
      else out.unresolved.push(`#${raw}`);
    }
    text = text.slice(0, m.index) + lead + ' ' + text.slice(m.index + whole.length);
  }

  const p = PRIO_TOKEN.exec(text);
  if (p) {
    out.priority = PRIORITY[p[2]!.toLowerCase()] ?? null;
    text = text.slice(0, p.index) + p[1] + text.slice(p.index + p[0].length);
  }

  const every = EVERY.exec(text) ?? ADVERB.exec(text);
  if (every) {
    out.recurrence = parseEvery(every, every[0].toLowerCase().startsWith('every') ? undefined : every[1]);
    text = text.slice(0, every.index) + text.slice(every.index + every[0].length);
  }

  const [date] = chrono.parse(text, ctx.now ?? new Date(), { forwardDate: true });
  if (date) {
    const when = date.start.date();
    out.due = { date: toISODate(when), at: date.start.isCertain('hour') ? when.toISOString() : null };
    text = text.slice(0, date.index) + text.slice(date.index + date.text.length);
  }

  let title = text.replace(/\s+/g, ' ').trim();
  while (DANGLING.test(title)) title = title.replace(DANGLING, '');
  out.title = title.replace(/[\s,;:-]+$/, '');
  return out;
}

/** Whether what's left still reads like details a person would expect to be understood
 * ("for Ana", "by end of next week", "asap"). Then quick add offers "✦ Let Mo fill in the
 * details": the AI half (S3.2.1), never applied without the user clicking it. */
export function looksLikeMoreDetail(title: string): boolean {
  return /\b(for\s+[A-Z][a-z]+|assign(?:ed)?\s+to|remind me|needs? to|should|asap|urgent|important|end of|next sprint|before|after|each|someone|in the [\w ]+ project)\b/.test(
    title,
  );
}
