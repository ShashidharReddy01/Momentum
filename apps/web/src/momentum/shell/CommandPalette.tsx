import { Command } from 'cmdk';
import { Home, Inbox, Keyboard, ListChecks, LogOut, Moon, PanelLeft } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useNavigate } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Kbd } from '@/components/ui/Kbd';
import { useLogout } from '@/features/auth';
import { useUi } from '@/stores/ui';

interface Action {
  id: string;
  label: string;
  icon?: LucideIcon;
  shortcut?: string;
  run: () => void;
}

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const ui = useUi((s) => s);
  const navigate = useNavigate();
  const logout = useLogout();

  const go = (to: string) => () => navigate(to);
  const groups: { heading: string; items: Action[] }[] = [
    {
      heading: 'Go to',
      items: [
        { id: 'home', label: 'Home', icon: Home, run: go('/') },
        { id: 'my-tasks', label: 'My Tasks', icon: ListChecks, run: go('/my-tasks') },
        { id: 'inbox', label: 'Inbox', icon: Inbox, run: go('/inbox') },
      ],
    },
    {
      heading: 'Actions',
      items: [
        { id: 'ask', label: 'Ask Mo', shortcut: 'mod+j', run: () => ui.setAskMoOpen(true) },
        {
          id: 'sidebar',
          label: 'Toggle sidebar',
          icon: PanelLeft,
          shortcut: 'mod+\\',
          run: ui.toggleSidebar,
        },
        { id: 'theme', label: 'Toggle dark theme', icon: Moon, run: ui.toggleTheme },
        {
          id: 'keys',
          label: 'Keyboard shortcuts',
          icon: Keyboard,
          shortcut: '?',
          run: () => ui.setShortcutsOpen(true),
        },
        { id: 'logout', label: 'Sign out', icon: LogOut, run: () => logout.mutate() },
      ],
    },
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title="Command palette"
      hideTitle
      className="top-[12vh] overflow-hidden p-0"
    >
      <Command label="Command palette" loop>
        <Command.Input
          // Focus moves to the input when the palette opens (Radix Dialog focuses the first field).
          placeholder="Search or type a command…"
          className="h-12 w-full border-b border-hair-soft bg-transparent px-4 text-[15px] outline-none placeholder:text-muted-2"
        />
        <Command.List className="max-h-[360px] overflow-auto p-1.5">
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted">
            No matches. Natural-language commands arrive with Mo in Phase 3.
          </Command.Empty>
          {groups.map((g) => (
            <Command.Group
              key={g.heading}
              heading={g.heading}
              className="[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {g.items.map((a) => (
                <Command.Item
                  key={a.id}
                  value={a.label}
                  onSelect={() => {
                    setOpen(false);
                    a.run();
                  }}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-paper-2"
                >
                  {a.icon ? <Icon icon={a.icon} className="text-muted" /> : <MoMark size={16} />}
                  <span className="flex-1">{a.label}</span>
                  {a.shortcut ? <Kbd combo={a.shortcut} /> : null}
                </Command.Item>
              ))}
            </Command.Group>
          ))}
        </Command.List>
      </Command>
    </Dialog>
  );
}
