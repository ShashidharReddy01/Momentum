import { describe, expect, it } from 'vitest';
import { formatCombo, matchesCombo } from './keyboard';

const key = (k: string, mods: Partial<KeyboardEventInit> = {}) =>
  new KeyboardEvent('keydown', { key: k, ...mods });

describe('keyboard', () => {
  it('matches mod combos using Ctrl off macOS', () => {
    expect(matchesCombo(key('k', { ctrlKey: true }), 'mod+k')).toBe(true);
    expect(matchesCombo(key('k'), 'mod+k')).toBe(false);
    expect(matchesCombo(key('k', { ctrlKey: true, shiftKey: true }), 'mod+k')).toBe(false);
  });
  it('matches plain keys including ?', () => {
    expect(matchesCombo(key('?', { shiftKey: true }), '?')).toBe(true);
    expect(matchesCombo(key('q'), 'q')).toBe(true);
  });
  it('formats combos for display', () => {
    expect(formatCombo('mod+k')).toEqual(['Ctrl', 'K']);
    expect(formatCombo('mod+enter')).toEqual(['Ctrl', 'enter']);
  });
});
