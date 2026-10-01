import { describe, expect, it } from 'vitest';
import { keepPending, type Task } from './queries';

const t = (id: string, section = 's1'): Task =>
  ({ id, title: id, section_id: section, parent_id: null, completed_at: null }) as unknown as Task;

describe('keepPending (rapid entry vs a refetch)', () => {
  it('keeps a still-saving task that a refetch came back without, in its place', () => {
    // the cache: a, b (confirmed), then tmp-3 typed right after b; the refetch only knows a, b
    const cached = [t('a'), t('b'), t('tmp-3')];
    expect(keepPending([t('a'), t('b')], cached).map((x) => x.id)).toEqual(['a', 'b', 'tmp-3']);
  });

  it('keeps several, in order, after the nearest task still present', () => {
    const cached = [t('a'), t('tmp-1'), t('tmp-2'), t('c', 's2')];
    const out = keepPending([t('a'), t('c', 's2')], cached).map((x) => x.id);
    expect(out).toEqual(['a', 'tmp-1', 'tmp-2', 'c']);
  });

  it('leaves a refetch alone when nothing is pending', () => {
    const fresh = [t('a'), t('z')];
    expect(keepPending(fresh, [t('a'), t('b')])).toBe(fresh);
  });
});
