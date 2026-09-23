import { Bell, PanelLeft, Search } from 'lucide-react';
import { useMatches } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Kbd } from '@/components/ui/Kbd';
import { useUi } from '@/stores/ui';

export interface RouteHandle {
  crumb?: string;
}

export function TopBar() {
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const askMoOpen = useUi((s) => s.askMoOpen);
  const setAskMoOpen = useUi((s) => s.setAskMoOpen);
  const crumbs = useMatches()
    .map((m) => (m.handle as RouteHandle | undefined)?.crumb)
    .filter((c): c is string => Boolean(c));

  return (
    <header className="flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-hair-soft bg-cream px-3">
      <IconButton icon={PanelLeft} label="Toggle sidebar" shortcut="mod+\" onClick={toggleSidebar} />
      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => (
            <li key={i} className={i === crumbs.length - 1 ? 'font-medium' : 'text-muted'}>
              {i > 0 ? <span className="mr-1.5 text-muted-2">/</span> : null}
              {c}
            </li>
          ))}
        </ol>
      </nav>
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="hidden h-8 w-[min(360px,32vw)] items-center gap-2 rounded-md border border-hairline bg-paper px-2.5 text-sm text-muted-2 hover:border-muted-2 md:flex"
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
      >
        <MoMark size={14} /> Ask Mo
      </Button>
      <IconButton icon={Bell} label="Notifications (Phase 2)" disabled />
    </header>
  );
}
