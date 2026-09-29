import { Bot, Plus } from 'lucide-react';
import { Link } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { useAgents, useInstallAgents, type Agent } from './queries';
import { AUTONOMY_LABEL, TRIGGER_LABEL } from './runMeta';

type AgentSummary = Omit<Agent, 'projects'>;

/** S5.2.3 `/agents`: every agent in the workspace, what wakes it and how much it may do on its
 * own. Admins create agents here (by hand or "✦ Describe what you want") and can install the
 * starters when there are none yet. */
export function AgentsGallery() {
  const agents = useAgents();
  const isAdmin = useMe().data?.user.role === 'admin';
  const install = useInstallAgents();
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-8">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-lg font-semibold">Agents</h1>
        {isAdmin ? (
          <Button asChild variant="primary" size="sm">
            <Link to="/agents/new">
              <Plus size={14} aria-hidden /> Create agent
            </Link>
          </Button>
        ) : null}
      </header>
      <p className="-mt-3 text-sm text-muted">
        AI teammates with their own accounts. They work only in projects they’ve been added to, and everything
        they do shows ✦ and can be undone.
      </p>
      {agents.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : agents.isError ? (
        <ErrorState error={agents.error} onRetry={() => void agents.refetch()} />
      ) : agents.data.length ? (
        <ul aria-label="Agents" className="grid gap-3 sm:grid-cols-2">
          {agents.data.map((a) => (
            <AgentCard key={a.id} agent={a} />
          ))}
        </ul>
      ) : (
        <EmptyState icon={Bot} title="No agents yet">
          {isAdmin ? (
            <span className="flex flex-col items-center gap-2">
              Install the eight starter agents (they start switched off), or create your own.
              <Button size="sm" loading={install.isPending} onClick={() => install.mutate()}>
                Install starter agents
              </Button>
            </span>
          ) : (
            'An admin can add agents to this workspace.'
          )}
        </EmptyState>
      )}
    </div>
  );
}

export function triggerSummary(triggers: AgentSummary['triggers']): string {
  const labels = triggers.map((t) => {
    const type = String(t.type);
    if (type === 'schedule') return `Schedule (${String(t.cron)})`;
    if (type === 'event') return `On ${String(t.event)}`;
    return TRIGGER_LABEL[type] ?? type;
  });
  return labels.length ? labels.join(' · ') : 'No triggers';
}

function AgentCard({ agent: a }: { agent: AgentSummary }) {
  return (
    <li>
      <Link
        to={`/agents/${a.id}`}
        className="flex h-full flex-col gap-1.5 rounded-lg border border-hairline bg-surface p-4 hover:bg-surface-2"
      >
        <span className="flex items-center gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-2 ring-2 ring-amber">
            <MoMark size={13} className="text-amber-ink" />
          </span>
          <span className="min-w-0 flex-1 truncate font-medium">{a.name}</span>
          <span className={a.enabled ? 'text-xs text-ok' : 'text-xs text-muted'}>
            {a.enabled ? 'On' : 'Off'}
          </span>
        </span>
        {a.description ? <span className="line-clamp-2 text-sm text-ink-2">{a.description}</span> : null}
        <span className="mt-auto text-xs text-muted">
          {triggerSummary(a.triggers)} · {AUTONOMY_LABEL[a.autonomy] ?? a.autonomy}
          {a.source === 'custom' ? ' · custom' : a.source === 'host' ? ' · from your app' : ''}
        </span>
      </Link>
    </li>
  );
}
