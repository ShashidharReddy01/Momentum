import { Outlet } from 'react-router';
import { useHotkey } from '@/lib/keyboard';
import { useUi } from '@/stores/ui';
import { AskMoPanel } from './AskMoPanel';
import { CommandPalette } from './CommandPalette';
import { ShortcutSheet } from './ShortcutSheet';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

/** App shell: Sidebar · (TopBar + routed content) · task pane host (Phase 1) · Ask Mo panel. */
export function Layout() {
  const ui = useUi((s) => s);
  useHotkey('mod+k', () => ui.setPaletteOpen(!ui.paletteOpen));
  useHotkey('mod+j', () => ui.setAskMoOpen(!ui.askMoOpen));
  useHotkey('mod+\\', ui.toggleSidebar);
  useHotkey('?', () => ui.setShortcutsOpen(true));

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <div className="flex min-h-0 flex-1">
          <main id="momentum-main" className="min-w-0 flex-1 overflow-auto">
            <Outlet />
          </main>
          <div id="momentum-task-pane" />
          <AskMoPanel />
        </div>
      </div>
      <CommandPalette />
      <ShortcutSheet />
    </div>
  );
}
