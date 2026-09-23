import { describe, expect, it } from 'vitest';
import { clickRow, dropNeighbors, emptySelection, prune, selectAll, step, targets } from './selection';

const order = ['a', 'b', 'c', 'd', 'e'];
const sel = (s: { selected: ReadonlySet<string> }) => [...s.selected].sort();

describe('selection', () => {
  it('plain click focuses and clears; meta toggles incl. the anchor; shift selects a range', () => {
    let s = clickRow(emptySelection, 'b', {}, order);
    expect(sel(s)).toEqual([]);
    expect(s.focus).toBe('b');
    s = clickRow(s, 'd', { meta: true }, order);
    expect(sel(s)).toEqual(['b', 'd']);
    s = clickRow(s, 'b', { meta: true }, order);
    expect(sel(s)).toEqual(['d']);
    // the anchor is the last ⌘-clicked row (b)
    s = clickRow(s, 'a', { shift: true }, order);
    expect(sel(s)).toEqual(['a', 'b']);
    // shift ranges re-anchor from the same anchor, they don't accumulate
    s = clickRow(s, 'e', { shift: true }, order);
    expect(sel(s)).toEqual(['b', 'c', 'd', 'e']);
    s = clickRow(s, 'c', {}, order);
    expect(sel(s)).toEqual([]);
  });

  it('shift with no anchor behaves like a click', () => {
    const s = clickRow(emptySelection, 'c', { shift: true }, order);
    expect(sel(s)).toEqual([]);
    expect(s.anchor).toBe('c');
  });

  it('arrow keys move focus within bounds; shift+arrow extends from the anchor', () => {
    let s = step(emptySelection, 1, false, order);
    expect(s.focus).toBe('a');
    s = step(s, -1, false, order);
    expect(s.focus).toBe('a');
    s = step(s, 1, true, order);
    s = step(s, 1, true, order);
    expect(sel(s)).toEqual(['a', 'b', 'c']);
    s = step(s, -1, true, order);
    expect(sel(s)).toEqual(['a', 'b']);
    s = step(s, 1, false, order);
    expect(sel(s)).toEqual([]);
    expect(s.focus).toBe('c');
    expect(step(emptySelection, -1, false, order).focus).toBe('e');
    expect(step(emptySelection, 1, false, [])).toBe(emptySelection);
  });

  it('shift+arrow after focus moved elsewhere starts the range at the focused row', () => {
    const s = { selected: new Set<string>(), anchor: 'a', focus: 'd' };
    expect(sel(step(s, 1, true, order))).toEqual(['d', 'e']);
  });

  it('select all, prune and targets', () => {
    let s = selectAll(clickRow(emptySelection, 'b', {}, order), ['b', 'c']);
    expect(sel(s)).toEqual(['b', 'c']);
    expect(targets(s, order)).toEqual(['b', 'c']);
    s = prune(s, ['a', 'c', 'd']);
    expect(sel(s)).toEqual(['c']);
    expect(s.focus).toBeNull();
    expect(prune(s, ['a', 'c'])).toBe(s); // unchanged → same object (no re-render)
    expect(targets(clickRow(emptySelection, 'd', {}, order), order)).toEqual(['d']);
    expect(targets(emptySelection, order)).toEqual([]);
  });
});

describe('dropNeighbors', () => {
  it('before/after a row, at the section end, and into an empty section', () => {
    expect(dropNeighbors(order, ['e'], 'b', 'before')).toEqual({ afterId: 'a', beforeId: null });
    expect(dropNeighbors(order, ['a'], 'c', 'after')).toEqual({ afterId: 'c', beforeId: null });
    expect(dropNeighbors(order, ['c'], 'a', 'before')).toEqual({ afterId: null, beforeId: 'a' });
    expect(dropNeighbors(order, ['a'], null, 'after')).toEqual({ afterId: 'e', beforeId: null });
    expect(dropNeighbors([], ['x'], null, 'after')).toEqual({ afterId: null, beforeId: null });
    expect(dropNeighbors(['y'], ['x'], null, 'after')).toEqual({ afterId: 'y', beforeId: null });
  });

  it('multi-drag onto one of the dragged rows collapses the block there', () => {
    expect(dropNeighbors(order, ['b', 'd'], 'd', 'after')).toEqual({ afterId: 'c', beforeId: null });
  });

  it('returns null for no-op drops', () => {
    expect(dropNeighbors(order, ['b'], 'b', 'before')).toBeNull();
    expect(dropNeighbors(order, ['b'], 'a', 'after')).toBeNull();
    expect(dropNeighbors(order, ['b'], 'c', 'before')).toBeNull();
    expect(dropNeighbors(order, ['b', 'c'], 'd', 'before')).toBeNull();
    expect(dropNeighbors(order, ['e'], null, 'after')).toBeNull();
    // non-contiguous block is not a no-op
    expect(dropNeighbors(order, ['b', 'd'], 'c', 'after')).toEqual({ afterId: 'c', beforeId: null });
  });
});
