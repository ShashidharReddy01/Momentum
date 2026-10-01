import { useCallback } from 'react';
import { useCompact, useNarrow } from '@/lib/media';
import { useUi } from '@/stores/ui';

/** Whether the rail shows icons only, and the one toggle (⌘\, top bar, palette) that flips it.
 * Wide windows remember the choice; below 1280px the rail starts as icons and expands for the
 * session; on phones the rail is a drawer instead (Phase 6.5, UX2). */
export function useRail(): { iconsOnly: boolean; toggle: () => void } {
  const narrow = useNarrow();
  const compact = useCompact();
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const expanded = useUi((s) => s.railExpanded);
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const drawerOpen = useUi((s) => s.drawerOpen);
  const setDrawerOpen = useUi((s) => s.setDrawerOpen);
  const iconsOnly = narrow ? false : compact ? !expanded : collapsed;
  const toggle = useCallback(() => {
    if (narrow) setDrawerOpen(!drawerOpen);
    else toggleSidebar(compact);
  }, [narrow, compact, drawerOpen, setDrawerOpen, toggleSidebar]);
  return { iconsOnly, toggle };
}
