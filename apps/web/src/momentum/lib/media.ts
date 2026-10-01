import { useSyncExternalStore } from 'react';

/** Below the `md` breakpoint (900px): sidebar becomes a drawer, panes go full-screen. */
const NARROW = '(max-width: 899.98px)';
/** Below 1280px (tablets, small laptops): the rail starts as icons (Phase 6.5, UX2). */
const COMPACT = '(max-width: 1279.98px)';

function query(q: string): MediaQueryList | null {
  try {
    return typeof window.matchMedia === 'function' ? window.matchMedia(q) : null;
  } catch {
    return null;
  }
}

function useMedia(q: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const m = query(q);
      m?.addEventListener('change', onChange);
      return () => m?.removeEventListener('change', onChange);
    },
    () => query(q)?.matches ?? false,
    () => false,
  );
}

export function useNarrow(): boolean {
  return useMedia(NARROW);
}

export function useCompact(): boolean {
  return useMedia(COMPACT);
}
