import { describeCron } from './cron';
import { Bot, Plus, Search } from 'lucide-react';
import { useDeferredValue, useState } from 'react';
import { Link } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { DataClassBadge } from './AgentTabs';
import { useDirectory, type DirectoryCard, type DirectoryFilters } from './platform';
import { useAgents, useInstallAgents, type Agent } from './queries';
import { AUTONOMY_LABEL, DATA_CLASS, TRIGGER_LABEL, pct } from './runMeta';

type AgentSummary = Omit<Agent, 'projects'>;

/** `/agents` (S5.2.3; directory v2 in Phase 7.6 spec §12.1): every agent in the workspace,
 * searchable by what it can do ("who can read invoices?") and filterable by capability, data
 * class and on/off. Cards show capabilities, the data class, on/off and a health summary. Admins
 * create agents here and can install the starters when there are none yet. */
export function AgentsGallery() {
  const [q, setQ] = useState('');
  const [filters, setFilters] = useState<Omit<DirectoryFilters, 'q'>>({});
  const deferredQ = useDeferredValue(q.trim());
  const directory = useDirectory({ ...filters, q: deferredQ });
  const all = useDirectory({});
  const agents = useAgents();
  const isAdmin = useMe().data?.user.role === 'admin';
  const install = useInstallAgents();
  const capabilities = [
    ...new Map((all.data ?? []).flatMap((c) => c.capabilities.map((cap) => [cap.key, cap.title] as const))),
  ];
  const filtering = !!deferredQ || Object.values(filters).some((v) => v !== undefined && v !== '');
  const byId = new Map((agents.data ?? []).map((a) => [a.id, a]));
  const select = 'rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink';
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-8">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto page-title">Agents</h1>
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
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-56 flex-1 items-center">
          <Icon icon={Search} size={14} className="pointer-events-none absolute left-2 text-muted" />
          <span className="sr-only">Search agents</span>
          <input
            type="search"
            placeholder="Who can… (e.g. read invoices)"
            className="h-8 w-full rounded-md border border-hairline bg-surface pr-2 pl-7 text-sm"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        {capabilities.length ? (
          <label className="flex items-center gap-1 text-xs text-muted">
            Capability
            <select
              className={select}
              value={filters.capability ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, capability: e.target.value || undefined }))}
            >
              <option value="">Any</option>
              {capabilities.map(([key, title]) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex items-center gap-1 text-xs text-muted">
          Data
          <select
            className={select}
            value={filters.data_class ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, data_class: e.target.value || undefined }))}
          >
            <option value="">Any</option>
            {Object.entries(DATA_CLASS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          State
          <select
            className={select}
            value={filters.enabled === undefined ? '' : filters.enabled ? 'on' : 'off'}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                enabled: e.target.value === '' ? undefined : e.target.value === 'on',
              }))
            }
          >
            <option value="">Any</option>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
        </label>
      </div>
      {directory.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : directory.isError ? (
        <ErrorState error={directory.error} onRetry={() => void directory.refetch()} />
      ) : directory.data.length ? (
        <ul aria-label="Agents" className="grid gap-3 sm:grid-cols-2">
          {directory.data.map((c) => (
            <AgentCard key={c.id} card={c} agent={byId.get(c.id)} />
          ))}
        </ul>
      ) : filtering ? (
        <EmptyState icon={Search} title="No agent matches">
          Try other words, or clear the filters.
        </EmptyState>
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
    if (type === 'schedule') return describeCron(String(t.cron));
    if (type === 'event') return `On ${String(t.event)}`;
    return TRIGGER_LABEL[type] ?? type;
  });
  return labels.length ? labels.join(' · ') : 'No triggers';
}

/** Capability chips (directory cards, the assignee picker). */
export function CapabilityChips({
  card,
  max = 3,
}: {
  card: Pick<DirectoryCard, 'capabilities'>;
  max?: number;
}) {
  if (!card.capabilities.length) return null;
  const shown = card.capabilities.slice(0, max);
  const more = card.capabilities.length - shown.length;
  return (
    <span className="flex flex-wrap gap-1" aria-label="Capabilities">
      {shown.map((c) => (
        <span key={c.key} className="rounded-full bg-amber-2 px-1.5 py-0.5 text-[11px] text-amber-ink">
          {c.title}
        </span>
      ))}
      {more > 0 ? <span className="text-[11px] text-muted">+{more}</span> : null}
    </span>
  );
}

function AgentCard({ card: c, agent }: { card: DirectoryCard; agent?: AgentSummary }) {
  return (
    <li>
      <Link
        to={`/agents/${c.id}`}
        className="flex h-full flex-col gap-1.5 rounded-lg border border-hairline bg-surface p-4 hover:bg-surface-2"
      >
        <span className="flex items-center gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-2 ring-2 ring-amber">
            <MoMark size={13} className="text-amber-ink" />
          </span>
          <span className="min-w-0 flex-1 truncate">
            <span className="font-medium">{c.name}</span>
            {c.title ? <span className="text-sm text-muted"> · {c.title}</span> : null}
          </span>
          <span className={c.enabled ? 'text-xs text-ok' : 'text-xs text-muted'}>
            {c.enabled ? 'On' : 'Off'}
          </span>
        </span>
        {c.description ? <span className="line-clamp-2 text-sm text-ink-2">{c.description}</span> : null}
        <span className="flex flex-wrap items-center gap-1.5">
          <CapabilityChips card={c} />
          {c.data_class ? <DataClassBadge value={c.data_class} /> : null}
        </span>
        <span className="mt-auto text-xs text-muted">
          {agent
            ? `${triggerSummary(agent.triggers)} · ${AUTONOMY_LABEL[agent.autonomy] ?? agent.autonomy}`
            : null}
          {c.source === 'custom' ? ' · custom' : c.source === 'host' ? ' · from your app' : ''}
        </span>
        {c.health ? (
          <span className="text-xs text-muted">
            {c.health.jobs
              ? `Last 30 days: ${c.health.jobs} job${c.health.jobs === 1 ? '' : 's'}, ${c.health.items} item${c.health.items === 1 ? '' : 's'}, ${pct(c.health.success_rate)} succeeded`
              : 'No jobs in the last 30 days'}
          </span>
        ) : null}
      </Link>
    </li>
  );
}
