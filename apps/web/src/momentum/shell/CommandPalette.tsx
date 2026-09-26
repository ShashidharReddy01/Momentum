import { Command } from 'cmdk';
import {
  FolderKanban,
  Home,
  Inbox,
  Keyboard,
  ListChecks,
  LogOut,
  MessageSquare,
  Moon,
  PanelLeft,
  Search,
  User,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { looksLikeInstruction } from '@/features/ai';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Kbd } from '@/components/ui/Kbd';
import { useLogout } from '@/features/auth';
import { useMarkOnboarding, useOnboarding } from '@/features/members';
import { useSearch } from '@/features/search';
import { useMomentumConfig } from '@/lib/config';
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
  const [query, setQuery] = useState('');
  const results = useSearch(query, { limit: 4 });
  const paletteQuery = useUi((s) => s.paletteQuery);
  const sendToMo = useUi((s) => s.sendToMo);
  const aiEnabled = useMomentumConfig().ai_enabled;
  // opened with text (Edit on a Mo suggestion): start from it
  useEffect(() => {
    if (open && paletteQuery) setQuery(paletteQuery);
  }, [open, paletteQuery]);
  const askMo = aiEnabled && looksLikeInstruction(query);

  // S2.7.3: the "try ⌘K" onboarding checklist step has no natural DB record (unlike "create a
  // project" or "import"), so it's pinged once, the first time the palette is actually opened.
  // `enabled: open` (rather than always-on) matters beyond perf: CommandPalette mounts on every
  // authenticated page via Layout, so an unconditional query here would mean every existing test
  // that renders the app shell now needs an onboarding-status mock too, not just the ones that
  // actually open the palette.
  const onboarding = useOnboarding({ enabled: open });
  const markOnboarding = useMarkOnboarding();
  const pinged = useRef(false);
  useEffect(() => {
    if (!open || pinged.current || !onboarding.data) return;
    pinged.current = true;
    if (!onboarding.data.used_command_palette) {
      markOnboarding.mutate({ used_command_palette: true });
    }
  }, [open, onboarding.data, markOnboarding]);

  const go = (to: string) => () => {
    setOpen(false);
    navigate(to);
  };
  const staticGroups: { heading: string; items: Action[] }[] = [
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

  // cmdk's own fuzzy filter only knows about the static command list above — the search groups
  // below are already server-filtered (`useSearch`), so double-filtering them through cmdk's
  // matcher risked hiding a real match cmdk's own scorer didn't recognize (e.g. a comment
  // snippet matching a word cmdk wouldn't fuzzy-rank against the item's `value`). `shouldFilter`
  // is off on the root <Command>, and the static groups are filtered by hand instead — a handful
  // of items, cheap enough to just recompute each render rather than memoize.
  const trimmed = query.trim().toLowerCase();
  const visibleStatic = trimmed
    ? staticGroups
        .map((g) => ({ ...g, items: g.items.filter((a) => a.label.toLowerCase().includes(trimmed)) }))
        .filter((g) => g.items.length > 0)
    : staticGroups;

  const data = results.data;
  const hasSearchResults =
    !!data && (data.tasks.length || data.projects.length || data.people.length || data.comments.length);

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) setQuery('');
      }}
      title="Command palette"
      hideTitle
      className="top-[12vh] overflow-hidden p-0"
    >
      <Command label="Command palette" loop shouldFilter={false}>
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search or type a command…"
          className="h-12 w-full border-b border-hair-soft bg-transparent px-4 text-[15px] outline-none placeholder:text-muted-2"
        />
        <Command.List className="max-h-[360px] overflow-auto p-1.5">
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted">No matches.</Command.Empty>
          {askMo ? (
            <Command.Group
              heading="Mo"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              <Command.Item
                value={`ask-mo-${query}`}
                onSelect={() => {
                  setOpen(false);
                  setQuery('');
                  sendToMo(query.trim());
                }}
                className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm text-amber-ink data-[selected=true]:bg-amber-2"
              >
                <MoMark size={16} />
                <span className="flex-1 truncate">Ask Mo to do this</span>
                <span className="text-xs text-muted-2">preview first</span>
              </Command.Item>
            </Command.Group>
          ) : null}
          {visibleStatic.map((g) => (
            <Command.Group
              key={g.heading}
              heading={g.heading}
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {g.items.map((a) => (
                <Command.Item
                  key={a.id}
                  value={a.label}
                  onSelect={a.run}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
                >
                  {a.icon ? <Icon icon={a.icon} className="text-muted" /> : <MoMark size={16} />}
                  <span className="flex-1">{a.label}</span>
                  {a.shortcut ? <Kbd combo={a.shortcut} /> : null}
                </Command.Item>
              ))}
            </Command.Group>
          ))}

          {query.trim().length >= 2 ? (
            <Command.Group
              heading="Search"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              <Command.Item
                value={`view-all-${query}`}
                onSelect={go(`/search?q=${encodeURIComponent(query)}`)}
                className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
              >
                <Icon icon={Search} className="text-muted" />
                <span className="flex-1">View all results for "{query}"</span>
              </Command.Item>
            </Command.Group>
          ) : null}

          {data?.tasks.length ? (
            <Command.Group
              heading="Tasks"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {data.tasks.map((t) => (
                <Command.Item
                  key={t.id}
                  value={`task-${t.id}`}
                  onSelect={go(`/task/${t.id}`)}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
                >
                  <Icon icon={ListChecks} className="text-muted" />
                  <span className="flex-1 truncate">{t.title}</span>
                  {t.project_name ? (
                    <span className="shrink-0 text-xs text-muted-2">{t.project_name}</span>
                  ) : null}
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}

          {data?.projects.length ? (
            <Command.Group
              heading="Projects"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {data.projects.map((p) => (
                <Command.Item
                  key={p.id}
                  value={`project-${p.id}`}
                  onSelect={go(`/projects/${p.id}`)}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
                >
                  <Icon icon={FolderKanban} className="text-muted" />
                  <span className="flex-1 truncate">{p.name}</span>
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}

          {data?.people.length ? (
            <Command.Group
              heading="People"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {data.people.map((p) => (
                <Command.Item
                  key={p.id}
                  value={`person-${p.id}`}
                  onSelect={go(`/search?assignee_id=${p.id}`)}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
                >
                  <Icon icon={User} className="text-muted" />
                  <span className="flex-1 truncate">{p.name}</span>
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}

          {data?.comments.length ? (
            <Command.Group
              heading="Comments"
              className="[&_[cmdk-group-heading]]:section-label [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5"
            >
              {data.comments.map((c) => (
                <Command.Item
                  key={c.id}
                  value={`comment-${c.id}`}
                  onSelect={go(`/task/${c.task_id}`)}
                  className="flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm data-[selected=true]:bg-surface-2"
                >
                  <Icon icon={MessageSquare} className="text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{c.snippet}</span>
                    <span className="block truncate text-xs text-muted-2">{c.task_title}</span>
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}

          {query.trim().length >= 2 && !hasSearchResults && !results.isPending ? (
            <p className="px-3 py-2 text-center text-xs text-muted-2">No results for "{query}"</p>
          ) : null}
        </Command.List>
      </Command>
    </Dialog>
  );
}
