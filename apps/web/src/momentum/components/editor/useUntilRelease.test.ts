import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useUntilRelease } from './useUntilRelease';

const fire = (type: string) => document.dispatchEvent(new Event(type, { bubbles: true }));

describe('useUntilRelease (editor toolbar, Phase 6.5 e2e J2)', () => {
  it('turns off at once when focus leaves without a press (e.g. Tab)', () => {
    const { result, rerender } = renderHook(({ on }) => useUntilRelease(on), { initialProps: { on: true } });
    rerender({ on: false });
    expect(result.current).toBe(false);
  });

  it('stays on until a press that took focus is released, so the click lands where aimed', async () => {
    const { result, rerender } = renderHook(({ on }) => useUntilRelease(on), { initialProps: { on: true } });
    act(() => fire('pointerdown'));
    rerender({ on: false }); // the mousedown blurred the editor
    expect(result.current).toBe(true);
    act(() => fire('pointerup'));
    await act(async () => new Promise((r) => setTimeout(r, 5)));
    expect(result.current).toBe(false);
    // the next blur without a press hides straight away
    rerender({ on: true });
    rerender({ on: false });
    expect(result.current).toBe(false);
  });
});
