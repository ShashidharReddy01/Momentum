import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROW_HEIGHT, VIRTUALIZE_OVER, VirtualRows } from './VirtualRows';

const items = (n: number) => Array.from({ length: n }, (_, i) => `row-${i}`);

function Harness({ n }: { n: number }) {
  return (
    <div style={{ height: 600, overflowY: 'auto' }}>
      <VirtualRows items={items(n)} getKey={(x) => x} render={(x) => <span data-row>{x}</span>} />
    </div>
  );
}

describe('VirtualRows', () => {
  // jsdom has no layout: give elements a 600px-high box so the virtualizer has a viewport.
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800);
  });
  afterEach(() => vi.restoreAllMocks());

  it('renders every row for everyday sizes', () => {
    const { container } = render(<Harness n={VIRTUALIZE_OVER} />);
    expect(container.querySelectorAll('[data-row]')).toHaveLength(VIRTUALIZE_OVER);
  });

  it('mounts only a window of rows for large lists, with the full scroll height', () => {
    const { container } = render(<Harness n={2000} />);
    const mounted = container.querySelectorAll('[data-row]').length;
    expect(mounted).toBeGreaterThan(0);
    expect(mounted).toBeLessThan(100);
    const list = container.querySelector('[data-row]')!.parentElement!.parentElement as HTMLElement;
    expect(list.style.height).toBe(`${2000 * ROW_HEIGHT}px`);
  });
});
