import { lazy, Suspense, useEffect, useState } from 'react';
import { Outlet } from 'react-router';
import { useLiveNotifications } from '@/features/notifications';
import { useUndoShortcut } from '@/lib/undo';
import { useHotkey } from '@/lib/keyboard';
import { useUi } from '@/stores/ui';
import { useRail } from './rail';
import { ShortcutSheet } from './ShortcutSheet';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

// Overlays load on first open (keeping the initial bundle inside its budget) and then stay
// mounted, so an Ask Mo conversation or a half-typed quick add survives closing and reopening.
const loadAskMo = () => import('./AskMoPanel');
const loadPalette = () => import('./CommandPalette');
const loadQuickAdd = () => import('@/features/tasks/QuickAddDialog');
const AskMoPanel = lazy(async () => ({ default: (await loadAskMo()).AskMoPanel }));
const CommandPalette = lazy(async () => ({ default: (await loadPalette()).CommandPalette }));
const QuickAddDialog = lazy(async () => ({ default: (await loadQuickAdd()).QuickAddDialog }));

/** Warm the overlay chunks once the page is idle, so the first ⌘K, ⌘J or Q opens instantly. */
function usePrefetchOverlays() {
  useEffect(() => {
    const warm = () => void Promise.all([loadPalette(), loadQuickAdd(), loadAskMo()]).catch(() => {});
    if (typeof window.requestIdleCallback === 'function') {
      const id = window.requestIdleCallback(warm, { timeout: 4000 });
      return () => window.cancelIdleCallback(id);
    }
    const t = window.setTimeout(warm, 2000);
    return () => window.clearTimeout(t);
  }, []);
}

/** True from the first time `open` is true. */
function useOpenedOnce(open: boolean): boolean {
  const [opened, setOpened] = useState(open);
  if (open && !opened) setOpened(true);
  return opened || open;
}

/** App shell: Sidebar · (TopBar + routed content) · task pane host (Phase 1) · Ask Mo panel. */
export function Layout() {
  const ui = useUi((s) => s);
  const rail = useRail();
  useUndoShortcut();
  useLiveNotifications(); // the inbox and the bell update on every page (S5.0.1)
  usePrefetchOverlays();
  useHotkey('mod+k', () => ui.setPaletteOpen(!ui.paletteOpen));
  useHotkey('mod+j', () => ui.setAskMoOpen(!ui.askMoOpen));
  useHotkey('mod+\\', rail.toggle);
  useHotkey('?', () => ui.setShortcutsOpen(true));
  useHotkey('mod+/', () => ui.setShortcutsOpen(true)); // Asana's
  useHotkey('/', () => ui.setPaletteOpen(true)); // search (Asana's Tab+/)
  useHotkey('q', () => ui.setQuickAddOpen(true));
  const mo = useOpenedOnce(ui.askMoOpen);
  const palette = useOpenedOnce(ui.paletteOpen);
  const quickAdd = useOpenedOnce(ui.quickAddOpen);

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <div className="flex min-h-0 flex-1">
          {/* the page's scroll container: focusable so the keyboard can scroll any page, even one
              with nothing else to focus (WCAG 2.1.1; axe scrollable-region-focusable) */}
          <main
            id="momentum-main"
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
            tabIndex={0}
            className="min-w-0 flex-1 overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-inset"
          >
            <Outlet />
          </main>
          <div id="momentum-task-pane" />
          {mo ? (
            <Suspense fallback={null}>
              <AskMoPanel />
            </Suspense>
          ) : null}
        </div>
      </div>
      {palette ? (
        <Suspense fallback={null}>
          <CommandPalette />
        </Suspense>
      ) : null}
      <ShortcutSheet />
      {quickAdd ? (
        <Suspense fallback={null}>
          <QuickAddDialog open={ui.quickAddOpen} onOpenChange={ui.setQuickAddOpen} />
        </Suspense>
      ) : null}
    </div>
  );
}
