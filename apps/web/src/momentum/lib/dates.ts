import * as chrono from 'chrono-node';

/** A due date as the API stores it: a local calendar date plus an optional exact time. */
export interface DueValue {
  date: string; // YYYY-MM-DD
  at: string | null; // ISO instant when a time was given
}

const pad = (n: number) => String(n).padStart(2, '0');

/** Local calendar date → `YYYY-MM-DD` (never via toISOString, which is UTC). */
export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** `YYYY-MM-DD` → local Date at midnight. */
export function fromISODate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y!, m! - 1, d);
}

export function addDays(d: Date, n: number): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  out.setDate(out.getDate() + n);
  return out;
}

/** Whole days from `a` to `b` (calendar days, DST-safe). */
export function dayDiff(a: Date, b: Date): number {
  const ua = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
  const ub = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
  return Math.round((ub - ua) / 86_400_000);
}

/**
 * Parse natural-language date input in the browser's timezone ("next fri", "in 3 days",
 * "sept 30", "tomorrow 5pm"). Dates without a year roll forward to the next occurrence.
 */
export function parseNaturalDate(text: string, now: Date = new Date()): DueValue | null {
  const input = text.trim();
  if (!input) return null;
  const [result] = chrono.parse(input, now, { forwardDate: true });
  if (!result) return null;
  const when = result.start.date();
  const hasTime = result.start.isCertain('hour');
  return { date: toISODate(when), at: hasTime ? when.toISOString() : null };
}

export type DueTone = 'overdue' | 'today' | 'soon' | 'later' | 'done';

export function dueTone(
  dueOn: string | null,
  dueAt: string | null,
  done: boolean,
  now = new Date(),
): DueTone {
  if (done) return 'done';
  if (!dueOn) return 'later';
  if (dueAt && new Date(dueAt) < now) return 'overdue';
  const diff = dayDiff(now, fromISODate(dueOn));
  if (diff < 0) return 'overdue';
  if (diff === 0) return 'today';
  return diff === 1 ? 'soon' : 'later';
}

const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: 'long' });
const MONTH_DAY = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
const MONTH_DAY_YEAR = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});
const TIME = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });
const HOUR = new Intl.DateTimeFormat(undefined, { hour: 'numeric' });

/** Compact time: "5 PM", "5:30 PM" (minutes only when not on the hour). */
export function formatTime(d: Date): string {
  return (d.getMinutes() === 0 ? HOUR : TIME).format(d);
}

/** Human label for a single date: Today / Tomorrow / Yesterday / weekday (this week) / "Oct 5". */
export function formatDay(iso: string, now = new Date()): string {
  const d = fromISODate(iso);
  const diff = dayDiff(now, d);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  if (diff > 1 && diff < 7) return WEEKDAY.format(d);
  return d.getFullYear() === now.getFullYear() ? MONTH_DAY.format(d) : MONTH_DAY_YEAR.format(d);
}

/** Label for a task's dates: "Tomorrow", "Today 5:00 PM", "Oct 1 – Oct 5". */
export function formatDue(
  dueOn: string | null,
  dueAt: string | null,
  startOn: string | null = null,
  now = new Date(),
): string {
  if (!dueOn) return '';
  const due = formatDay(dueOn, now) + (dueAt ? ` ${formatTime(new Date(dueAt))}` : '');
  return startOn ? `${formatDay(startOn, now)} – ${due}` : due;
}

/** Monday of the week after `now`. */
export function nextWeek(now = new Date()): Date {
  const daysToMonday = (8 - now.getDay()) % 7 || 7;
  return addDays(now, daysToMonday);
}

/** "just now", "5m ago", "3h ago", "Yesterday", "Mon", "Sep 21" (for comments and activity). */
export function formatRelative(iso: string, now = new Date()): string {
  const then = new Date(iso);
  const secs = Math.round((now.getTime() - then.getTime()) / 1000);
  if (secs < 45) return 'just now';
  if (secs < 3600) return `${Math.max(1, Math.round(secs / 60))}m ago`;
  if (secs < 6 * 3600 && dayDiff(then, now) === 0) return `${Math.round(secs / 3600)}h ago`;
  const label = formatDay(toISODate(then), now);
  const time = formatTime(then);
  return dayDiff(then, now) <= 1 ? `${label} ${time}` : label;
}
