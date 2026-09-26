import { Archive, ArchiveRestore, Bell, Inbox as InboxIcon } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { EmptyState } from '@/components/common/States';
import { IconButton } from '@/components/ui/IconButton';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { SummaryButton } from '@/features/ai';
import { TaskNavProvider, TaskPane, useTaskNav } from '@/features/tasks';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/dates';
import { useNotificationMutations, useNotifications, type Notification } from './queries';

const KIND_LABEL: Record<Notification['kind'], string> = {
  assigned: 'Assigned',
  mentioned: 'Mentioned',
  commented: 'Commented',
  completed: 'Completed',
  due_soon: 'Due soon',
  overdue: 'Overdue',
  approval_requested: 'Approval requested',
  approval_decided: 'Approval decided',
  agent_proposal: 'Agent proposal',
  digest: 'Digest',
};

export function InboxPage() {
  return (
    <TaskNavProvider>
      <InboxBody />
    </TaskNavProvider>
  );
}

function InboxBody() {
  const [tab, setTab] = useState<'active' | 'archive'>('active');
  const notes = useNotifications(tab === 'archive');
  const m = useNotificationMutations();
  const nav = useTaskNav()!;
  const [focused, setFocused] = useState<string | null>(null);

  const groups = useMemo(() => {
    const map = new Map<string, Notification[]>();
    for (const n of notes.data ?? []) {
      const list = map.get(n.entity_id);
      if (list) list.push(n);
      else map.set(n.entity_id, [n]);
    }
    return [...map.entries()];
  }, [notes.data]);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, n: Notification) => {
    // Enter/Space already activate the button natively (calls `open` via onClick).
    if (e.key === 'e' && tab === 'active') {
      e.preventDefault();
      m.setArchived.mutate({ id: n.id, archived: true });
    } else if (e.key === 'u') {
      e.preventDefault();
      m.setRead.mutate({ id: n.id, read: false });
    }
  };

  const open = (n: Notification) => {
    if (!n.read_at) m.setRead.mutate({ id: n.id, read: true });
    if (n.entity_type === 'task') nav.open(n.entity_id);
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-auto px-4 md:px-8 py-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h1 className="page-title flex flex-1 items-center gap-2">
            <Icon icon={InboxIcon} size={20} /> Inbox
          </h1>
          {tab === 'active' ? <SummaryButton body={{ target: 'inbox' }} label="Catch me up" /> : null}
        </div>
        <div role="tablist" aria-label="Inbox" className="mb-3 flex gap-1 border-b border-hair-soft">
          {(['active', 'archive'] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn(
                'h-9 border-b-2 px-3 text-sm font-medium',
                tab === t ? 'border-accent text-ink' : 'border-transparent text-muted hover:text-ink',
              )}
            >
              {t === 'active' ? 'Activity' : 'Archive'}
            </button>
          ))}
        </div>

        {notes.isPending ? (
          <div className="flex flex-col gap-2" aria-busy>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <EmptyState icon={Bell} title={tab === 'active' ? "You're all caught up" : 'Nothing archived'}>
            {tab === 'active'
              ? 'New activity on tasks you follow, get assigned, or are mentioned in shows up here.'
              : 'Items you archive from the inbox land here.'}
          </EmptyState>
        ) : (
          <ul aria-label="Notifications" className="flex flex-col">
            {groups.map(([entityId, items]) => (
              <li key={entityId} className="border-b border-hair-soft py-2">
                <ul className="flex flex-col gap-1">
                  {items.map((n) => (
                    <li
                      key={n.id}
                      className={cn(
                        'flex items-start gap-2 rounded-md px-2 py-1.5',
                        !n.read_at && 'bg-accent-tint/40',
                      )}
                    >
                      <button
                        type="button"
                        aria-label={n.title}
                        onFocus={() => setFocused(n.id)}
                        onBlur={() => setFocused((f) => (f === n.id ? null : f))}
                        onKeyDown={(e) => onKeyDown(e, n)}
                        onClick={() => open(n)}
                        className={cn(
                          'flex min-w-0 flex-1 items-start gap-2 rounded-md text-left outline-none',
                          focused === n.id && 'ring-2 ring-focus',
                        )}
                      >
                        {!n.read_at ? (
                          <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                        ) : (
                          <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0" />
                        )}
                        <span className="min-w-0 flex-1">
                          <p className="truncate text-sm">
                            <span className="text-muted-2">{KIND_LABEL[n.kind]} · </span>
                            {n.title}
                          </p>
                          {n.snippet ? <p className="truncate text-xs text-muted">{n.snippet}</p> : null}
                        </span>
                        <span className="shrink-0 text-xs text-muted-2">{formatRelative(n.created_at)}</span>
                      </button>
                      <IconButton
                        icon={tab === 'active' ? Archive : ArchiveRestore}
                        label={tab === 'active' ? 'Archive' : 'Unarchive'}
                        size="icon-sm"
                        onClick={() => m.setArchived.mutate({ id: n.id, archived: tab === 'active' })}
                      />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
      {nav.openId ? (
        <TaskPane
          taskId={nav.openId}
          onClose={nav.close}
          onStep={nav.step}
          onOpenTask={(id) => nav.open(id)}
        />
      ) : null}
    </div>
  );
}
