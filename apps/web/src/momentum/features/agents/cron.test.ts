import { describe, expect, it } from 'vitest';
import { describeCron } from './cron';

const at = (h: number, m: number) =>
  new Date(2026, 0, 5, h, m).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });

describe('describeCron (agent schedules in words)', () => {
  it('reads the shapes the starter agents and people use', () => {
    expect(describeCron('0 9 * * 1-5')).toBe(`Weekdays at ${at(9, 0)}`);
    expect(describeCron('30 8 * * 1-5')).toBe(`Weekdays at ${at(8, 30)}`);
    expect(describeCron('0 15 * * FRI')).toBe(`Fridays at ${at(15, 0)}`);
    expect(describeCron('0 10 * * 1,4')).toBe(`Mondays and Thursdays at ${at(10, 0)}`);
    expect(describeCron('0 7 * * *')).toBe(`Every day at ${at(7, 0)}`);
    expect(describeCron('0 7 * * 0,6')).toBe(`Weekends at ${at(7, 0)}`);
    expect(describeCron('0 9 1 * *')).toBe(`Monthly on the 1st at ${at(9, 0)}`);
    expect(describeCron('0 9 22 * *')).toBe(`Monthly on the 22nd at ${at(9, 0)}`);
    expect(describeCron('0 * * * *')).toBe('Every hour');
    expect(describeCron('*/15 * * * *')).toBe('Every 15 minutes');
    expect(describeCron('0 9 * * MON-FRI')).toBe(`Weekdays at ${at(9, 0)}`);
  });

  it('never guesses at anything else', () => {
    expect(describeCron('0 9 * 1 *')).toBe('Custom schedule (0 9 * 1 *)');
    expect(describeCron('0 9-17 * * *')).toBe('Custom schedule (0 9-17 * * *)');
    expect(describeCron('nonsense')).toBe('Custom schedule (nonsense)');
    expect(describeCron('0 9 * * XYZ')).toBe('Custom schedule (0 9 * * XYZ)');
  });
});
