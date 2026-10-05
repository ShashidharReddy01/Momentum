import { Bell, ChevronRight, Download, KeyRound, Sparkles, Users, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router';
import { Icon } from '@/components/ui/Icon';
import { Segmented } from '@/components/ui/Tabs';
import { useMe } from '@/features/auth';
import { useUi } from '@/stores/ui';

type Entry = { to: string; icon: LucideIcon; title: string; detail: string; admin?: boolean };

const ENTRIES: Entry[] = [
  {
    to: '/settings/notifications',
    icon: Bell,
    title: 'Notifications',
    detail: 'What reaches your inbox and the bell, per kind of event',
  },
  {
    to: '/settings/ai',
    icon: Sparkles,
    title: 'Mo and AI',
    detail: 'Your AI preferences; for admins, budgets, models and autonomy',
  },
  {
    to: '/settings/tokens',
    icon: KeyRound,
    title: 'API tokens',
    detail: 'Personal tokens for scripts that call Momentum on your behalf',
  },
  { to: '/settings/members', icon: Users, title: 'Members', detail: 'Who is in this workspace' },
  {
    to: '/settings/import/asana',
    icon: Download,
    title: 'Import from Asana',
    detail: 'Bring a team’s projects, tasks and comments across',
  },
];

/** `/settings`: every settings screen in one place (the account menu links to each too). */
export function SettingsPage() {
  const me = useMe().data?.user;
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 md:px-8">
      <h1 className="page-title">Settings</h1>
      {me ? (
        <p className="mt-1 text-sm text-muted">
          Signed in as {me.name} ({me.email}) · {me.role === 'admin' ? 'workspace admin' : 'member'}
        </p>
      ) : null}
      <section
        aria-label="Appearance"
        className="mt-6 flex items-center justify-between rounded-xl border border-hairline bg-surface p-4"
      >
        <div>
          <h2 className="text-sm font-semibold">Theme</h2>
          <p className="text-xs text-muted">Saved in this browser</p>
        </div>
        <Segmented
          label="Theme"
          value={theme}
          onChange={setTheme}
          options={[
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
          ]}
        />
      </section>
      <ul
        aria-label="Settings"
        className="mt-4 divide-y divide-hair-soft rounded-xl border border-hairline bg-surface"
      >
        {ENTRIES.map((e) => (
          <li key={e.to}>
            <Link to={e.to} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2">
              <Icon icon={e.icon} size={18} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{e.title}</span>
                <span className="block text-xs text-muted">{e.detail}</span>
              </span>
              <Icon icon={ChevronRight} size={16} className="shrink-0 text-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
