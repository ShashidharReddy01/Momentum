import { addDays, fromISODate, toISODate } from '@/lib/dates';

export type Tone = 'idle' | 'ok' | 'warn' | 'crit' | 'away';

/** How full a week is: under 85% ok, up to 100% warn, over crit; no hours at all = away. */
export function toneOf(planned: number, capacity: number): Tone {
  if (capacity <= 0) return planned > 0 ? 'crit' : 'away';
  if (planned <= 0) return 'idle';
  const r = planned / capacity;
  return r <= 0.85 ? 'ok' : r <= 1 ? 'warn' : 'crit';
}

/** The Monday of a date's week (weeks start on Monday, like the API). */
export function mondayOf(iso: string): string {
  const d = fromISODate(iso);
  return toISODate(addDays(d, -((d.getDay() + 6) % 7)));
}

/** A task's dates moved by whole weeks (keeps its length and weekday). */
export function shiftWeeks(
  task: { start_on?: string | null; due_on: string },
  weeks: number,
): { start_on: string | null; due_on: string } {
  const move = (iso: string) => toISODate(addDays(fromISODate(iso), weeks * 7));
  return { start_on: task.start_on ? move(task.start_on) : null, due_on: move(task.due_on) };
}

export function weeksBetween(fromWeek: string, toWeek: string): number {
  return Math.round((fromISODate(toWeek).getTime() - fromISODate(fromWeek).getTime()) / (7 * 86_400_000));
}
