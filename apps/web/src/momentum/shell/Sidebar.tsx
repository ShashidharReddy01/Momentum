import type { ReactNode } from 'react';
import {
  ChevronsUpDown,
  FolderPlus,
  Home,
  Inbox,
  ListChecks,
  LogOut,
  Moon,
  Plus,
  Sun,
  Users,
} from 'lucide-react';
import { NavLink } from 'react-router';
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
import { useLogout, useMe } from '@/features/auth';
import { cn } from '@/lib/cn';
import { useUi } from '@/stores/ui';

const NAV = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/my-tasks', label: 'My Tasks', icon: ListChecks },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
] as const;

export function Sidebar() {
  const collapsed = useUi((s) => s.sidebarCollapsed);
  return (
    <nav
      aria-label="Main"
      className={cn(
        'flex h-dvh flex-col border-r border-sidebar-line bg-sidebar text-sidebar-ink transition-[width] duration-150',
        collapsed ? 'w-0 overflow-hidden border-r-0' : 'w-[var(--sidebar-w)]',
      )}
    >
      <div className="flex h-[var(--topbar-h)] items-center gap-2 px-4">
        <BrandMark size={22} />
        <span className="text-[15px] font-semibold tracking-tight">Momentum</span>
      </div>
      <div className="px-3 pb-2">
        <CreateMenu />
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
      <SidebarSection title="Favorites">
        <p className="px-4 text-xs text-sidebar-muted">Star a project to pin it here.</p>
      </SidebarSection>
      <SidebarSection title="Teams">
        <p className="flex items-center gap-2 px-4 text-xs text-sidebar-muted">
          <Icon icon={Users} size={14} /> Teams arrive in Phase 1.
        </p>
      </SidebarSection>
      <div className="mt-auto border-t border-sidebar-line p-2">
        <UserMenu />
      </div>
    </nav>
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

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h2 className="section-label px-4 pb-1 !text-sidebar-muted">{title}</h2>
      {children}
    </section>
  );
}

function CreateMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="sidebar" className="w-full justify-start">
          <Icon icon={Plus} /> Create
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem disabled hint="Phase 1" shortcut="q">
          <Icon icon={ListChecks} /> Task
        </DropdownMenuItem>
        <DropdownMenuItem disabled hint="Phase 1">
          <Icon icon={FolderPlus} /> Project
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const me = useMe();
  const logout = useLogout();
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
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <Icon icon={LogOut} /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
