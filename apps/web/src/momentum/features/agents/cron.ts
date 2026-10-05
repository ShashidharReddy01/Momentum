/**
 * A five-field cron expression in words ("Weekdays at 9:00 AM", "Fridays at 3:00 PM"), for the
 * agent gallery and the schedule editor. Covers the shapes people use (every N minutes, hourly,
 * daily, given weekdays, a day of the month); anything else reads "Custom schedule (expr)".
 */
const DAY_NAMES = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays'];
const DAY_ALIASES: Record<string, number> = { SUN: 0, MON: 1, TUE: 2, WED: 3, THU: 4, FRI: 5, SAT: 6 };

function dayNumber(token: string): number | null {
  const t = token.trim().toUpperCase();
  if (t in DAY_ALIASES) return DAY_ALIASES[t]!;
  if (/^\d$/.test(t)) return Number(t) % 7; // 7 is Sunday too
  return null;
}

/** The weekdays a day-of-week field allows (null: any day), or undefined if it can't be read. */
function daysOf(field: string): number[] | null | undefined {
  if (field === '*' || field === '?') return null;
  const out = new Set<number>();
  for (const part of field.split(',')) {
    const range = part.split('-');
    if (range.length === 2) {
      const a = dayNumber(range[0]!);
      const b = dayNumber(range[1]!);
      if (a === null || b === null) return undefined;
      for (let d = a; ; d = (d + 1) % 7) {
        out.add(d);
        if (d === b) break;
      }
    } else {
      const d = dayNumber(part);
      if (d === null) return undefined;
      out.add(d);
    }
  }
  return [...out].sort((x, y) => x - y);
}

function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : (['th', 'st', 'nd', 'rd'][n % 10] ?? 'th');
  return `${n}${s}`;
}

function clock(hour: number, minute: number): string {
  return new Date(2026, 0, 5, hour, minute).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function listDays(days: number[]): string {
  const key = days.join(',');
  if (key === '1,2,3,4,5') return 'Weekdays';
  if (key === '0,6') return 'Weekends';
  if (days.length === 7) return 'Every day';
  const names = days.map((d) => DAY_NAMES[d]!);
  return names.length === 1 ? names[0]! : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}

export function describeCron(expr: string): string {
  const raw = expr.trim();
  const fields = raw.split(/\s+/);
  const custom = `Custom schedule (${raw})`;
  if (fields.length !== 5) return custom;
  const [min, hour, dom, mon, dow] = fields as [string, string, string, string, string];
  const every = /^\*\/(\d+)$/;
  if (mon !== '*') return custom;
  if (every.test(min) && hour === '*' && dom === '*' && dow === '*') {
    const n = Number(every.exec(min)![1]);
    return n === 1 ? 'Every minute' : `Every ${n} minutes`;
  }
  if (/^\d+$/.test(min) && hour === '*' && dom === '*' && dow === '*')
    return Number(min) === 0 ? 'Every hour' : `Every hour at :${min.padStart(2, '0')}`;
  if (!/^\d+$/.test(min) || !/^\d+$/.test(hour)) return custom;
  const at = clock(Number(hour), Number(min));
  if (/^\d+$/.test(dom) && dow === '*') return `Monthly on the ${ordinal(Number(dom))} at ${at}`;
  if (dom !== '*') return custom;
  const days = daysOf(dow);
  if (days === undefined) return custom;
  return `${days === null ? 'Every day' : listDays(days)} at ${at}`;
}
