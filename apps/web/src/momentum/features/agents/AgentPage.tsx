import { Bot, Pencil } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { useMe } from '@/features/auth';
import { AgentProjects } from './AgentProjects';
import { AgentSettings } from './AgentSettings';
import { AgentHealthPanel, AgentOverview, PackSettingsPanel } from './AgentTabs';
import { triggerSummary } from './AgentsGallery';
import { useAgentProfile } from './platform';
import { useAgent, useAgentRuns, type Agent, type AgentRun, type RunFilters } from './queries';
import { RunNowPanel } from './RunNowPanel';
import { SkillsAdmin } from './SkillsAdmin';
import { StatusBadge } from './StatusBadge';
import { TestRunPanel } from './TestRunPanel';
import { AUTONOMY_LABEL, RUN_STATUS, TRIGGER_LABEL, money, when } from './runMeta';

const TABS = ['overview', 'runs', 'health', 'skills', 'settings'] as const;
type Tab = (typeof TABS)[number];

/** `/agents/:agentId` (S5.1.3, tabs in Phase 7.6 spec §12.2): Overview (what it's for, how to
 * hand it work, where it works), Runs, Health and Settings (the pack's settings form, and the
 * admin panel: on/off, autonomy, budget). */
export function AgentPage() {
  const { agentId } = useParams();
  const agent = useAgent(agentId!);
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : 'overview';
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

      <Tabs
        value={tab}
        onValueChange={(v) =>
          setParams(
            (p) => {
              const next = new URLSearchParams(p);
              if (v === 'overview') next.delete('tab');
              else next.set('tab', v);
              return next;
            },
            { replace: true },
          )
        }
      >
        <TabsList aria-label="Agent">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
          {a.pack_key ? <TabsTrigger value="skills">Skills</TabsTrigger> : null}
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="flex flex-col gap-6 pt-5">
          <AgentOverview agent={a} />
          <AgentProjects agent={a} />
          {a.enabled && a.triggers.some((t) => t.type === 'manual') ? <RunNowPanel agent={a} /> : null}
        </TabsContent>
        <TabsContent value="runs" className="pt-5">
          <RunHistory agent={a} />
        </TabsContent>
        <TabsContent value="health" className="pt-5">
          <AgentHealthPanel agent={a} />
        </TabsContent>
        {a.pack_key ? (
          <TabsContent value="skills" className="pt-5">
            <SkillsAdmin packKey={a.pack_key} />
          </TabsContent>
        ) : null}
        <TabsContent value="settings" className="flex flex-col gap-6 pt-5">
          <SettingsTab agent={a} isAdmin={isAdmin} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SettingsTab({ agent: a, isAdmin }: { agent: Agent; isAdmin: boolean }) {
  const profile = useAgentProfile(a.id);
  const hasPackSettings = !!profile.data?.has_settings;
  return (
    <>
      {hasPackSettings ? (
        <section aria-label="Pack settings" className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">How {a.name} works</h2>
          <PackSettingsPanel agent={a} />
        </section>
      ) : null}
      {isAdmin ? <AgentSettings agent={a} /> : null}
      {isAdmin && a.kind === 'llm' ? <TestRunPanel agent={a} /> : null}
      {!hasPackSettings && !isAdmin && !profile.isPending ? (
        <p className="text-sm text-muted">{a.name} has no settings you can change.</p>
      ) : null}
    </>
  );
}

function RunHistory({ agent: a }: { agent: Agent }) {
  const [filters, setFilters] = useState<RunFilters>({});
  const runs = useAgentRuns(a.id, filters);
  const profile = useAgentProfile(a.id);
  const capabilities = profile.data?.capabilities ?? [];
  const projects = a.projects ?? [];
  const select = 'rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink';
  return (
    <section aria-label="Run history" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-sm font-semibold">Run history</h2>
        <label className="flex items-center gap-1 text-xs text-muted">
          Status
          <select
            className={select}
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
            className={select}
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
        {projects.length ? (
          <label className="flex items-center gap-1 text-xs text-muted">
            Project
            <select
              className={select}
              value={filters.project_id ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, project_id: e.target.value || undefined }))}
            >
              <option value="">All</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {capabilities.length > 1 ? (
          <label className="flex items-center gap-1 text-xs text-muted">
            Capability
            <select
              className={select}
              value={filters.capability ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, capability: e.target.value || undefined }))}
            >
              <option value="">All</option>
              {capabilities.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
        ) : null}
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
          {Object.values(filters).some(Boolean)
            ? 'No runs match these filters.'
            : `${a.name} hasn’t run where you can see it.`}
        </EmptyState>
      )}
    </section>
  );
}

const WAITING_SHORT: Record<string, string> = {
  ask: 'waiting for an answer',
  children: 'waiting for its sub-jobs',
  timer: 'waiting for a timer',
  event: 'waiting for an event',
  instruction: 'waiting for an instruction',
};

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
          {run.waiting_on ? `${WAITING_SHORT[run.waiting_on] ?? 'waiting'} · ` : ''}
          {run.progress ? `${run.progress.done} of ${run.progress.total} · ` : ''}
          {run.proposals ? `${run.proposals} proposed · ` : ''}
          {run.applied ? `${run.applied} applied · ` : ''}
          {money(run.cost_usd)}
          {run.error ? ` · ${run.error}` : ''}
        </span>
      </Link>
    </li>
  );
}
