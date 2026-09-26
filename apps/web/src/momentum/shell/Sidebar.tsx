import { useEffect, useState, type ReactNode } from 'react';
import {
  Bell,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Download,
  Lock,
  Star,
  FolderPlus,
  Home,
  Inbox,
  ListChecks,
  LogOut,
  Moon,
  Plus,
  Sparkles,
  Sun,
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

const NAV = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/my-tasks', label: 'My Tasks', icon: ListChecks },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
] as const;

export function Sidebar() {
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const drawerOpen = useUi((s) => s.drawerOpen);
  const setDrawerOpen = useUi((s) => s.setDrawerOpen);
  const setQuickAddOpen = useUi((s) => s.setQuickAddOpen);
  const narrow = useNarrow();
  const location = useLocation();
  const [newTeam, setNewTeam] = useState(false);
  const [newProject, setNewProject] = useState(false);
  const [fromBrief, setFromBrief] = useState(false);
  // the drawer closes when you go somewhere, or when the window gets wide again
  useEffect(() => setDrawerOpen(false), [location.pathname, narrow, setDrawerOpen]);
  useEffect(() => {
    if (!narrow || !drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [narrow, drawerOpen, setDrawerOpen]);
  return (
    <>
      {narrow && drawerOpen ? (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-ink/20"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}
      <nav
        aria-label="Main"
        hidden={narrow && !drawerOpen}
        className={cn(
          'flex h-dvh flex-col border-r border-sidebar-line bg-sidebar text-sidebar-ink transition-[width] duration-150',
          narrow
            ? drawerOpen
              ? 'fixed inset-y-0 left-0 z-50 w-[min(var(--sidebar-w),85vw)] shadow-pop'
              : 'hidden'
            : collapsed
              ? 'w-0 overflow-hidden border-r-0'
              : 'w-[var(--sidebar-w)]',
        )}
      >
        <div className="flex h-[var(--topbar-h)] items-center gap-2 px-4">
          <BrandMark size={22} />
          <span className="text-[15px] font-semibold tracking-tight">Momentum</span>
        </div>
        <div className="px-3 pb-2">
          <CreateMenu
            onNewTask={() => setQuickAddOpen(true)}
            onNewTeam={() => setNewTeam(true)}
            onNewProject={() => setNewProject(true)}
            onFromBrief={() => setFromBrief(true)}
          />
        </div>
        <ul className="flex flex-col gap-0.5 px-2">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavItem to={n.to} end={'end' in n ? n.end : false}>
                <Icon icon={n.icon} />
                {n.label}
              </NavItem>
            </li>
          ))}
          <li>
            <NavItem to="/ask">
              <MoMark size={16} />
              Ask Mo
            </NavItem>
          </li>
        </ul>
        <FavoritesSection />
        <TeamsSection onNewTeam={() => setNewTeam(true)} />
        <div className="mt-auto border-t border-sidebar-line p-2">
          <UserMenu />
        </div>
        <NewTeamDialog open={newTeam} onOpenChange={setNewTeam} />
        <NewProjectDialog open={newProject} onOpenChange={setNewProject} />
        <ProjectFromBriefDialog open={fromBrief} onOpenChange={setFromBrief} />
      </nav>
    </>
  );
}

function NavItem({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm text-sidebar-ink/85 hover:bg-sidebar-hover hover:text-sidebar-ink',
          isActive && 'bg-sidebar-active font-medium text-sidebar-ink',
        )
      }
    >
      {children}
    </NavLink>
  );
}

function SidebarSection({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mt-5">
      <div className="flex items-center justify-between pr-2">
        <h2 className="section-label px-4 pb-1 !text-sidebar-muted">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function TeamsSection({ onNewTeam }: { onNewTeam: () => void }) {
  const teams = useTeams();
  const projects = useProjects();
  const byTeam = new Map<string, Project[]>();
  for (const p of projects.data ?? []) byTeam.set(p.team_id, [...(byTeam.get(p.team_id) ?? []), p]);
  return (
    <SidebarSection
      title="Teams"
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
        <p className="flex items-center gap-2 px-4 text-xs text-sidebar-muted">
          <Icon icon={Users} size={14} /> No teams yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5 px-2">
          {teams.data?.map((t) => (
            <TeamTree
              key={t.id}
              teamId={t.id}
              name={t.name}
              color={t.color}
              projects={byTeam.get(t.id) ?? []}
            />
          ))}
        </ul>
      )}
    </SidebarSection>
  );
}

function CreateMenu({
  onNewTask,
  onNewTeam,
  onNewProject,
  onFromBrief,
}: {
  onNewTask: () => void;
  onNewTeam: () => void;
  onNewProject: () => void;
  onFromBrief: () => void;
}) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="sidebar" className="w-full justify-start">
          <Icon icon={Plus} /> Create
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
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

function UserMenu() {
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
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-sidebar-hover"
          aria-label="Account menu"
        >
          <Avatar name={user.name} src={user.avatar_url} size={26} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{user.name}</span>
            <span className="block truncate text-xs text-sidebar-muted">{me.data?.workspace.name}</span>
          </span>
          <Icon icon={ChevronsUpDown} size={14} className="text-sidebar-muted" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-[var(--radix-dropdown-menu-trigger-width)]">
        <DropdownMenuItem onSelect={toggleTheme}>
          <Icon icon={theme === 'dark' ? Sun : Moon} />{' '}
          {theme === 'dark' ? 'Light theme (Paper)' : 'Dark theme (Graphite)'}
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
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <Icon icon={LogOut} /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ProjectLink({ p }: { p: Project }) {
  return (
    <NavItem to={`/projects/${p.id}`}>
      <span
        aria-hidden
        className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
        style={{ background: colorVar(p.color) }}
      />
      <span className="truncate">{p.name}</span>
      {p.privacy === 'private' ? <Icon icon={Lock} size={12} className="ml-auto text-sidebar-muted" /> : null}
    </NavItem>
  );
}

function TeamTree({
  teamId,
  name,
  color,
  projects,
}: {
  teamId: string;
  name: string;
  color: string | null | undefined;
  projects: Project[];
}) {
  const [open, setOpen] = useState(true);
  return (
    <li>
      <div className="group flex items-center">
        <button
          type="button"
          aria-label={open ? `Collapse ${name}` : `Expand ${name}`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="grid h-8 w-5 shrink-0 place-items-center rounded text-sidebar-muted hover:text-sidebar-ink"
        >
          <Icon icon={open ? ChevronDown : ChevronRight} size={13} />
        </button>
        <div className="min-w-0 flex-1">
          <NavItem to={`/teams/${teamId}`}>
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: colorVar(color) }}
            />
            <span className="truncate">{name}</span>
          </NavItem>
        </div>
      </div>
      {open && projects.length > 0 ? (
        <ul className="ml-5 flex flex-col gap-0.5">
          {projects.map((p) => (
            <li key={p.id}>
              <ProjectLink p={p} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function FavoritesSection() {
  const favorites = useFavorites();
  return (
    <SidebarSection title="Favorites">
      {(favorites.data ?? []).length === 0 ? (
        <p className="flex items-center gap-2 px-4 text-xs text-sidebar-muted">
          <Icon icon={Star} size={13} /> Star a project to pin it here.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5 px-2">
          {favorites.data?.map((p) => (
            <li key={p.id}>
              <ProjectLink p={p} />
            </li>
          ))}
        </ul>
      )}
    </SidebarSection>
  );
}
