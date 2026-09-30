/** S6.4.1 effort: minutes ↔ "2h 30m". Parsing mirrors the API's CSV import (8h days, 5d weeks;
 * a bare number is hours). */
const DAY = 8 * 60;
const UNITS: Record<string, number> = { m: 1, h: 60, d: DAY, w: 5 * DAY };
const PART = /(\d+(?:[.,]\d+)?)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)(?![a-z])/g;

export function parseEffort(text: string): number | null {
  const s = text.trim().toLowerCase();
  if (!s) return null;
  if (/^\d+(?:[.,]\d+)?$/.test(s)) return Math.round(Number(s.replace(',', '.')) * 60);
  let total = 0;
  let matched = '';
  for (const [whole, n, unit] of s.matchAll(PART)) {
    total += Number(n!.replace(',', '.')) * UNITS[unit![0]!]!;
    matched += whole;
  }
  // everything but spaces must have been understood
  if (!matched || matched.replace(/\s/g, '').length !== s.replace(/\s/g, '').length) return null;
  return Math.round(total);
}

/** 150 → "2h 30m", 480 → "8h", 45 → "45m". */
export function formatEffort(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** Hours for charts and totals: 90 → "1.5h", 1800 → "30h". */
export function hours(minutes: number): string {
  const h = minutes / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(1)}h`;
}
