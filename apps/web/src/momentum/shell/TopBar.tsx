import { Bell, PanelLeft, Search } from 'lucide-react';
import { useMatches } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Kbd } from '@/components/ui/Kbd';
import { cn } from '@/lib/cn';
import { useNarrow } from '@/lib/media';
import { useUi } from '@/stores/ui';

export interface RouteHandle {
  crumb?: string;
}

export function TopBar() {
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const drawerOpen = useUi((s) => s.drawerOpen);
  const setDrawerOpen = useUi((s) => s.setDrawerOpen);
  const narrow = useNarrow();
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const askMoOpen = useUi((s) => s.askMoOpen);
  const setAskMoOpen = useUi((s) => s.setAskMoOpen);
  const override = useUi((s) => s.crumbs);
  const routeCrumbs = useMatches()
    .map((m) => (m.handle as RouteHandle | undefined)?.crumb)
    .filter((c): c is string => Boolean(c));
  const crumbs = override ?? routeCrumbs;

  return (
    <header className="flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-hair-soft bg-topbar px-3">
      <IconButton
        icon={PanelLeft}
        label={narrow ? 'Open menu' : 'Toggle sidebar'}
        shortcut="mod+\"
        onClick={narrow ? () => setDrawerOpen(!drawerOpen) : toggleSidebar}
      />
      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => (
            <li
              key={i}
              className={cn(
                'truncate',
                i === crumbs.length - 1 ? 'min-w-0 font-medium' : 'text-muted max-sm:hidden',
              )}
            >
              {i > 0 ? <span className="mr-1.5 text-muted-2 max-sm:hidden">/</span> : null}
              {c}
            </li>
          ))}
        </ol>
      </nav>
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="hidden h-8 w-[min(360px,32vw)] items-center gap-2 rounded-md border border-hairline bg-surface px-2.5 text-sm text-muted-2 hover:border-muted-2 md:flex"
        aria-label="Search or run a command"
      >
        <Icon icon={Search} />
        <span className="flex-1 text-left">Search or ask…</span>
        <Kbd combo="mod+k" />
      </button>
      <Button
        variant={askMoOpen ? 'ai' : 'ghost'}
        onClick={() => setAskMoOpen(!askMoOpen)}
        aria-pressed={askMoOpen}
        title="Ask Mo (⌘J)"
        aria-label="Ask Mo"
      >
        <MoMark size={14} /> <span className="max-sm:hidden">Ask Mo</span>
      </Button>
      <IconButton icon={Bell} label="Notifications (Phase 2)" disabled />
    </header>
  );
}
