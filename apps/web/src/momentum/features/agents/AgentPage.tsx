import { Bot, Pencil } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMe } from '@/features/auth';
import { StatusBadge } from './AgentRunPage';
import { AgentProjects } from './AgentProjects';
import { AgentSettings } from './AgentSettings';
import { triggerSummary } from './AgentsGallery';
import { useAgent, useAgentRuns, type AgentRun, type RunFilters } from './queries';
import { RunNowPanel } from './RunNowPanel';
import { TestRunPanel } from './TestRunPanel';
import { AUTONOMY_LABEL, RUN_STATUS, TRIGGER_LABEL, money, when } from './runMeta';

/** S5.1.3 `/agents/:agentId`: an agent's charter at a glance and its run history (filterable by
 * status and trigger). Admins also get its settings, an Edit link and a test run (S5.2.3). */
export function AgentPage() {
  const { agentId } = useParams();
  const agent = useAgent(agentId!);
  const [filters, setFilters] = useState<RunFilters>({});
  const runs = useAgentRuns(agentId!, filters);
  const isAdmin = useMe().data?.user.role === 'admin';
  if (agent.isPending) {
    return (
      <div className="mx-auto w-full max-w-3xl px-6 py-8">
        <Skeleton className="mb-4 h-7 w-64" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (agent.isError) return <ErrorState error={agent.error} onRetry={() => void agent.refetch()} />;
  const a = agent.data;
  const projects = a.projects ?? [];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-2 ring-2 ring-amber">
            <MoMark size={16} className="text-amber-ink" />
          </span>
          <h1 className="page-title">{a.name}</h1>
          <span className={a.enabled ? 'text-sm text-ok' : 'text-sm text-muted'}>
            {a.enabled ? 'On' : 'Off'}
          </span>
          {isAdmin ? (
            <Button asChild size="sm" variant="ghost" className="ml-auto">
              <Link to={`/agents/${a.id}/edit`}>
                <Pencil size={13} aria-hidden /> Edit
              </Link>
            </Button>
          ) : null}
        </div>
        {a.description ? <p className="text-sm text-ink-2">{a.description}</p> : null}
        <p className="text-xs text-muted">{triggerSummary(a.triggers)}</p>
        <p className="text-xs text-muted">
          {AUTONOMY_LABEL[a.autonomy] ?? a.autonomy} · budget {money(a.budget_monthly_usd)}/month
          {projects.length
            ? ` · works in ${projects.map((p) => p.name).join(', ')}`
            : ' · not added to any project you can see'}
        </p>
      </header>

      {isAdmin ? <AgentSettings agent={a} /> : null}
      <AgentProjects agent={a} />
      {a.enabled && a.triggers.some((t) => t.type === 'manual') ? <RunNowPanel agent={a} /> : null}
      {isAdmin && a.kind === 'llm' ? <TestRunPanel agent={a} /> : null}

      <section aria-label="Run history" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-sm font-semibold">Run history</h2>
          <label className="flex items-center gap-1 text-xs text-muted">
            Status
            <select
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink"
              value={filters.status ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value || undefined }))}
            >
              <option value="">All</option>
              {Object.entries(RUN_STATUS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1 text-xs text-muted">
            Trigger
            <select
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink"
              value={filters.trigger ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, trigger: e.target.value || undefined }))}
            >
              <option value="">All</option>
              {Object.entries(TRIGGER_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        </div>
        {runs.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : runs.isError ? (
          <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
        ) : runs.data.length ? (
          <ul aria-label="Runs" className="flex flex-col">
            {runs.data.map((r) => (
              <RunRow key={r.id} run={r} />
            ))}
          </ul>
        ) : (
          <EmptyState icon={Bot} title="No runs yet">
            {filters.status || filters.trigger
              ? 'No runs match these filters.'
              : `${a.name} hasn’t run where you can see it.`}
          </EmptyState>
        )}
      </section>
    </div>
  );
}

function RunRow({ run }: { run: AgentRun }) {
  return (
    <li className="border-b border-hair-soft last:border-0">
      <Link
        to={`/agents/runs/${run.id}`}
        className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 text-sm hover:bg-surface-2"
      >
        <StatusBadge status={run.status} />
        <span className="text-ink-2">{TRIGGER_LABEL[run.trigger] ?? run.trigger}</span>
        {run.task ? (
          <span className="min-w-0 truncate">
            <span className="text-muted">{run.task.key}</span> {run.task.title}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-2">{when(run.created_at)}</span>
        <span className="w-full text-xs text-muted">
          {run.proposals ? `${run.proposals} proposed · ` : ''}
          {run.applied ? `${run.applied} applied · ` : ''}
          {money(run.cost_usd)}
          {run.error ? ` · ${run.error}` : ''}
        </span>
      </Link>
    </li>
  );
}
