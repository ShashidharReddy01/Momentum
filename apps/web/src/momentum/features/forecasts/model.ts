import type { Forecast } from './queries';

/** "Nov 12" for a YYYY-MM-DD date (read as a local date), "Feb 11, 2027" outside this year. */
export function day(iso: string, now = new Date()): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y!, m! - 1, d!).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(y === now.getFullYear() ? {} : { year: 'numeric' }),
  });
}

export function daysBetween(a: string, b: string): number {
  const [ay, am, ad] = a.split('-').map(Number);
  const [by, bm, bd] = b.split('-').map(Number);
  return Math.round((Date.UTC(by!, bm! - 1, bd!) - Date.UTC(ay!, am! - 1, ad!)) / 86_400_000);
}

/** Where the forecast stands against the due date, in one phrase and a tone. */
export function verdict(f: Forecast): { text: string; tone: 'ok' | 'warn' | 'crit' | 'none' } {
  if (f.status !== 'ok' || !f.p50 || !f.p80 || !f.p95) return { text: '', tone: 'none' };
  if (!f.due_on) return { text: 'No due date to compare with', tone: 'none' };
  if (f.p50 > f.due_on) {
    const late = daysBetween(f.due_on, f.p50);
    return { text: `Likely ${late} ${late === 1 ? 'day' : 'days'} late`, tone: 'crit' };
  }
  if (f.p80 > f.due_on) return { text: 'At risk of missing the due date', tone: 'warn' };
  if (f.p95 > f.due_on) return { text: 'On track, with a small risk', tone: 'ok' };
  return { text: 'On track for the due date', tone: 'ok' };
}

/** The line under the numbers: what the forecast is based on, honestly. */
export function basis(f: Forecast): string {
  const i = f.inputs as {
    mode?: string;
    remaining?: number;
    weeks?: number;
    throughput?: number[];
    runs?: number;
    chain_days?: number;
  };
  const unit = i.mode === 'hours' ? 'hours' : 'tasks';
  const tp = i.throughput ?? [];
  const avg = tp.length ? tp.reduce((a, b) => a + b, 0) / tp.length : 0;
  const parts = [
    `${i.remaining ?? 0} ${unit} left`,
    `${Math.round(avg * 10) / 10} ${unit}/week over the last ${i.weeks ?? 0} weeks`,
  ];
  const added = (f.inputs as { added?: number[] }).added ?? [];
  const addedAvg = added.length ? added.reduce((a, b) => a + b, 0) / added.length : 0;
  if (addedAvg > 0) parts.push(`${Math.round(addedAvg * 10) / 10} ${unit}/week added`);
  if (i.runs && f.status === 'ok') parts.push(`${i.runs.toLocaleString()} simulated futures`);
  return parts.join(' · ');
}
