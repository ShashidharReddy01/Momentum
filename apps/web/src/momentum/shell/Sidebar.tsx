import { useEffect, useState, type ReactNode, type UIEvent } from 'react';
import {
  Bell,
  Bot,
  Briefcase,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Download,
  FolderPlus,
  Gauge,
  Home,
  Inbox,
  KeyRound,
  LayoutDashboard,
  ListChecks,
  Lock,
  LogOut,
  Moon,
  Plus,
  Sparkles,
  Star,
  Sun,
  Target,
  Users,
} from 'lucide-react';
import { NavLink, useLocation, useNavigate } from 'react-router';
import { BrandMark } from '@/components/common/BrandMark';
import { MoMark } from '@/components/common/MoMark';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/DropdownMenu';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Tooltip } from '@/components/ui/Tooltip';
import { useLogout, useMe } from '@/features/auth';
import {
  NewProjectDialog,
  ProjectFromBriefDialog,
  useFavorites,
  useProjects,
  type Project,
} from '@/features/projects';
import { colorVar, NewTeamDialog, useTeams } from '@/features/teams';
import { cn } from '@/lib/cn';
import { useNarrow } from '@/lib/media';
import { useMomentumConfig } from '@/lib/config';
import { useUi } from '@/stores/ui';
import { useRail } from './rail';

const NAV = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/my-tasks', label: 'My Tasks', icon: ListChecks },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
  { to: '/portfolios', label: 'Portfolios', icon: Briefcase },
  { to: '/goals', label: 'Goals', icon: Target },
  { to: '/workload', label: 'Workload', icon: Gauge },
  { to: '/dashboards', label: 'Dashboards', icon: LayoutDashboard },
  { to: '/agents', label: 'Agents', icon: Bot },
] as const;

export function Sidebar() {
  const { iconsOnly } = useRail();
  const drawerOpen = useUi((s) => s.drawerOpen);
  const setDrawerOpen = useUi((s) => s.setDrawerOpen);
  const setQuickAddOpen = useUi((s) => s.setQuickAddOpen);
  const narrow = useNarrow();
  const location = useLocation();
  const [newTeam, setNewTeam] = useState(false);
  const [newProject, setNewProject] = useState(false);
  const [fromBrief, setFromBrief] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  // the drawer closes when you go somewhere, or when the window gets wide again
  useEffect(() => setDrawerOpen(false), [location.pathname, narrow, setDrawerOpen]);
  useEffect(() => {
    if (!narrow || !drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [narrow, drawerOpen, setDrawerOpen]);
  const onScroll = (e: UIEvent<HTMLDivElement>) => setScrolled(e.currentTarget.scrollTop > 0);
  return (
    <>
      {narrow && drawerOpen ? (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-ink/25 animate-[m-fade-in_var(--dur-2)_var(--ease)]"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}
      {/* Pinned header · scrolling middle · pinned footer: the profile and settings stay
          reachable at any window height (Phase 6.5, UX2). */}
      <nav
        aria-label="Main"
        hidden={narrow && !drawerOpen}
        data-icons-only={iconsOnly || undefined}
        className={cn(
          'flex h-dvh shrink-0 flex-col bg-sidebar text-sidebar-ink transition-[width] duration-[var(--dur-2)] ease-[var(--ease)]',
          narrow
            ? drawerOpen
              ? 'fixed inset-y-0 left-0 z-50 w-[min(var(--sidebar-w),85vw)] shadow-pop animate-[m-sheet-in_var(--dur-3)_var(--ease)]'
              : 'hidden'
            : iconsOnly
              ? 'w-[var(--rail-collapsed-w)]'
              : 'w-[var(--sidebar-w)]',
        )}
      >
        <div
          className={cn(
            'flex shrink-0 flex-col gap-3 border-b px-3 pt-3 pb-3 transition-colors',
            scrolled ? 'border-sidebar-line' : 'border-transparent',
            iconsOnly && 'items-center px-2',
          )}
        >
          <div className={cn('flex h-7 items-center gap-2', iconsOnly ? 'justify-center' : 'px-1')}>
            <BrandMark size={22} />
            {iconsOnly ? null : <span className="text-heading font-bold tracking-tight">Momentum</span>}
          </div>
          <CreateMenu
            iconsOnly={iconsOnly}
            onNewTask={() => setQuickAddOpen(true)}
            onNewTeam={() => setNewTeam(true)}
            onNewProject={() => setNewProject(true)}
            onFromBrief={() => setFromBrief(true)}
          />
        </div>
        <div
          onScroll={onScroll}
          className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-2 pt-1 pb-4 [scrollbar-color:var(--color-sidebar-active)_transparent]"
        >
          <ul className="flex flex-col gap-px">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavItem to={n.to} end={'end' in n ? n.end : false} label={n.label} iconsOnly={iconsOnly}>
                  <Icon icon={n.icon} />
                </NavItem>
              </li>
            ))}
            <li>
              <NavItem to="/ask" label="Ask Mo" iconsOnly={iconsOnly}>
                <MoMark size={16} />
              </NavItem>
            </li>
          </ul>
          <FavoritesSection iconsOnly={iconsOnly} />
          <TeamsSection iconsOnly={iconsOnly} onNewTeam={() => setNewTeam(true)} />
        </div>
        <div className={cn('shrink-0 border-t border-sidebar-line p-2', iconsOnly && 'px-1.5')}>
          <UserMenu iconsOnly={iconsOnly} />
        </div>
        <NewTeamDialog open={newTeam} onOpenChange={setNewTeam} />
        <NewProjectDialog open={newProject} onOpenChange={setNewProject} />
        <ProjectFromBriefDialog open={fromBrief} onOpenChange={setFromBrief} />
      </nav>
    </>
  );
}

/** A rail row: quiet until hovered; the current place gets the lime "you are here" marker.
 * With icons only, the label moves into a tooltip (and stays the accessible name). */
function NavItem({
  to,
  end,
  label,
  iconsOnly = false,
  trailing,
  children,
}: {
  to: string;
  end?: boolean;
  label: string;
  iconsOnly?: boolean;
  trailing?: ReactNode;
  children: ReactNode;
}) {
  const link = (
    <NavLink
      to={to}
      end={end}
      aria-label={iconsOnly ? label : undefined}
      className={({ isActive }) =>
        cn(
          'relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-body text-sidebar-muted transition-colors duration-[var(--dur-1)] select-none hover:bg-sidebar-hover hover:text-sidebar-ink active:bg-sidebar-active',
          iconsOnly && 'justify-center px-0',
          isActive &&
            'bg-sidebar-active font-semibold text-sidebar-ink before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-r-full before:bg-marker',
        )
      }
    >
      {children}
      {iconsOnly ? null : <span className="min-w-0 flex-1 truncate">{label}</span>}
      {iconsOnly ? null : trailing}
    </NavLink>
  );
  return iconsOnly ? (
    <Tooltip content={label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

function SidebarSection({
  title,
  action,
  iconsOnly,
  children,
}: {
  title: string;
  action?: ReactNode;
  iconsOnly: boolean;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="mt-4">
      {iconsOnly ? (
        <div aria-hidden className="mx-3 mb-2 h-px bg-sidebar-line" />
      ) : (
        <div className="flex h-7 items-center justify-between pr-1 pl-2.5">
          <h2 className="section-label !text-sidebar-muted">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

function TeamsSection({ iconsOnly, onNewTeam }: { iconsOnly: boolean; onNewTeam: () => void }) {
  const teams = useTeams();
  const projects = useProjects();
  const byTeam = new Map<string, Project[]>();
  for (const p of projects.data ?? []) byTeam.set(p.team_id, [...(byTeam.get(p.team_id) ?? []), p]);
  return (
    <SidebarSection
      title="Teams"
      iconsOnly={iconsOnly}
      action={
        <IconButton
          icon={Plus}
          label="New team"
          size="icon-sm"
          className="h-6 w-6 text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-ink"
          onClick={onNewTeam}
        />
      }
    >
      {teams.isPending ? null : (teams.data ?? []).length === 0 ? (
        iconsOnly ? null : (
          <p className="flex items-center gap-2 px-2.5 text-meta text-sidebar-muted">
            <Icon icon={Users} size={14} /> No teams yet.
          </p>
        )
      ) : (
        <ul className="flex flex-col gap-px">
          {teams.data?.map((t) => (
            <TeamTree
              key={t.id}
              teamId={t.id}
              name={t.name}
              color={t.color}
              iconsOnly={iconsOnly}
              projects={byTeam.get(t.id) ?? []}
            />
          ))}
        </ul>
      )}
    </SidebarSection>
  );
}

function CreateMenu({
  iconsOnly,
  onNewTask,
  onNewTeam,
  onNewProject,
  onFromBrief,
}: {
  iconsOnly: boolean;
  onNewTask: () => void;
  onNewTeam: () => void;
  onNewProject: () => void;
  onFromBrief: () => void;
}) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const trigger = (
    <DropdownMenuTrigger asChild>
      <Button
        variant="sidebar"
        aria-label={iconsOnly ? 'Create' : undefined}
        className={cn(iconsOnly ? 'h-8 w-8 px-0' : 'w-full justify-start')}
      >
        <Icon icon={Plus} />
        {iconsOnly ? null : 'Create'}
      </Button>
    </DropdownMenuTrigger>
  );
  // opens beside the rail, so it never covers the navigation it belongs to
  return (
    <DropdownMenu>
      {iconsOnly ? (
        <Tooltip content="Create" side="right">
          {trigger}
        </Tooltip>
      ) : (
        trigger
      )}
      <DropdownMenuContent side="right" align="start" sideOffset={10} className="w-56">
        <DropdownMenuItem onSelect={onNewTask} shortcut="q">
          <Icon icon={ListChecks} /> Task
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onNewProject}>
          <Icon icon={FolderPlus} /> Project
        </DropdownMenuItem>
        {aiEnabled ? (
          <DropdownMenuItem onSelect={onFromBrief}>
            <MoMark size={14} /> Project from a brief
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={onNewTeam}>
          <Icon icon={Users} /> Team
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu({ iconsOnly }: { iconsOnly: boolean }) {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const theme = useUi((s) => s.theme);
  const toggleTheme = useUi((s) => s.toggleTheme);
  const user = me.data?.user;
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors duration-[var(--dur-1)] hover:bg-sidebar-hover active:bg-sidebar-active',
            iconsOnly && 'justify-center px-0',
          )}
          aria-label="Account menu"
        >
          <Avatar name={user.name} src={user.avatar_url} size={28} />
          {iconsOnly ? null : (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-body font-semibold">{user.name}</span>
                <span className="block truncate text-label text-sidebar-muted">
                  {me.data?.workspace.name}
                </span>
              </span>
              <Icon icon={ChevronsUpDown} size={14} className="text-sidebar-muted" />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={iconsOnly ? 'right' : 'top'}
        align={iconsOnly ? 'end' : 'start'}
        sideOffset={8}
        className="w-60"
      >
        <DropdownMenuItem onSelect={toggleTheme}>
          <Icon icon={theme === 'dark' ? Sun : Moon} /> {theme === 'dark' ? 'Light theme' : 'Dark theme'}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/notifications')}>
          <Icon icon={Bell} /> Notification settings
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/import/asana')}>
          <Icon icon={Download} /> Import from Asana
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/members')}>
          <Icon icon={Users} /> Members
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/ai')}>
          <Icon icon={Sparkles} /> AI settings
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate('/settings/tokens')}>
          <Icon icon={KeyRound} /> API tokens
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <Icon icon={LogOut} /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ProjectDot({ color, round = false }: { color: string | null | undefined; round?: boolean }) {
  return (
    <span aria-hidden className="grid h-4 w-4 shrink-0 place-items-center">
      <span
        className={cn('h-2.5 w-2.5', round ? 'rounded-full' : 'rounded-[3px]')}
        style={{ background: colorVar(color) }}
      />
    </span>
  );
}

function ProjectLink({ p, iconsOnly }: { p: Project; iconsOnly: boolean }) {
  return (
    <NavItem
      to={`/projects/${p.id}`}
      label={p.name}
      iconsOnly={iconsOnly}
      trailing={
        p.privacy === 'private' ? <Icon icon={Lock} size={12} className="text-sidebar-muted" /> : null
      }
    >
      <ProjectDot color={p.color} />
    </NavItem>
  );
}

function TeamTree({
  teamId,
  name,
  color,
  iconsOnly,
  projects,
}: {
  teamId: string;
  name: string;
  color: string | null | undefined;
  iconsOnly: boolean;
  projects: Project[];
}) {
  const folded = useUi((s) => s.collapsedTeams.includes(teamId));
  const toggleTeam = useUi((s) => s.toggleTeam);
  if (iconsOnly) {
    return (
      <li>
        <NavItem to={`/teams/${teamId}`} label={name} iconsOnly>
          <ProjectDot color={color} round />
        </NavItem>
      </li>
    );
  }
  return (
    <li>
      <div className="relative">
        <NavItem to={`/teams/${teamId}`} label={name}>
          <ProjectDot color={color} round />
        </NavItem>
        {projects.length > 0 ? (
          <button
            type="button"
            aria-label={folded ? `Expand ${name}` : `Collapse ${name}`}
            aria-expanded={!folded}
            onClick={() => toggleTeam(teamId)}
            className="absolute top-1 right-1 grid h-6 w-6 place-items-center rounded text-sidebar-muted transition-colors hover:bg-sidebar-active hover:text-sidebar-ink"
          >
            <Icon icon={folded ? ChevronRight : ChevronDown} size={14} />
          </button>
        ) : null}
      </div>
      {!folded && projects.length > 0 ? (
        <ul className="ml-[17px] flex flex-col gap-px border-l border-sidebar-line pl-1.5">
          {projects.map((p) => (
            <li key={p.id}>
              <ProjectLink p={p} iconsOnly={false} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function FavoritesSection({ iconsOnly }: { iconsOnly: boolean }) {
  const favorites = useFavorites();
  const list = favorites.data ?? [];
  if (iconsOnly && list.length === 0) return null;
  return (
    <SidebarSection title="Favorites" iconsOnly={iconsOnly}>
      {list.length === 0 ? (
        <p className="flex items-center gap-2 px-2.5 text-meta text-sidebar-muted">
          <Icon icon={Star} size={13} /> Star a project to pin it here.
        </p>
      ) : (
        <ul className="flex flex-col gap-px">
          {list.map((p) => (
            <li key={p.id}>
              <ProjectLink p={p} iconsOnly={iconsOnly} />
            </li>
          ))}
        </ul>
      )}
    </SidebarSection>
  );
}
