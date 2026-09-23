import { useSyncExternalStore } from 'react';

/** Below the `md` breakpoint (900px): sidebar becomes a drawer, panes go full-screen. */
const NARROW = '(max-width: 899.98px)';

function query(): MediaQueryList | null {
  try {
    return typeof window.matchMedia === 'function' ? window.matchMedia(NARROW) : null;
  } catch {
    return null;
  }
}

export function useNarrow(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const q = query();
      q?.addEventListener('change', onChange);
      return () => q?.removeEventListener('change', onChange);
    },
    () => query()?.matches ?? false,
    () => false,
  );
}
