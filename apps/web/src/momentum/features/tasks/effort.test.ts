import { describe, expect, it } from 'vitest';
import { formatEffort, hours, parseEffort } from './effort';

describe('effort (S6.4.1)', () => {
  it('parses the ways people write effort', () => {
    expect(parseEffort('2h30m')).toBe(150);
    expect(parseEffort('2h 30m')).toBe(150);
    expect(parseEffort('3 hours')).toBe(180);
    expect(parseEffort('1,5h')).toBe(90);
    expect(parseEffort('1d')).toBe(480);
    expect(parseEffort('1w')).toBe(2400);
    expect(parseEffort('3')).toBe(180);
    expect(parseEffort('lots')).toBeNull();
    expect(parseEffort('3h and change')).toBeNull();
    expect(parseEffort('')).toBeNull();
  });
  it('formats minutes', () => {
    expect(formatEffort(150)).toBe('2h 30m');
    expect(formatEffort(480)).toBe('8h');
    expect(formatEffort(45)).toBe('45m');
    expect(formatEffort(null)).toBe('');
    expect(hours(90)).toBe('1.5h');
    expect(hours(1800)).toBe('30h');
  });
});
