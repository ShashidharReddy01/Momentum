import { Link, useParams } from 'react-router';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { PreviewCard } from '@/features/ai';
import { cn } from '@/lib/cn';
import { useAgentRun, type AgentRunDetail, type RunStep } from './queries';
import { RUN_STATUS, STEP_LABEL, TRIGGER_LABEL, money, when } from './runMeta';

/** S5.1.3 `/agents/runs/:runId`: everything one agent run did, so every action it took can be
 * explained — why it ran, each step, what it proposed or changed, its answer, cost and errors. */
export function AgentRunPage() {
  const { runId } = useParams();
  const run = useAgentRun(runId!);
  if (run.isPending) {
    return (
      <div className="mx-auto w-full max-w-3xl px-6 py-8">
        <Skeleton className="mb-4 h-7 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (run.isError) return <ErrorState error={run.error} onRetry={() => void run.refetch()} />;
  return <RunDetail run={run.data} />;
}

export function StatusBadge({ status }: { status: string }) {
  const s = RUN_STATUS[status] ?? RUN_STATUS.queued!;
  return (
    <span className={cn('inline-flex items-center gap-1 text-sm font-medium', s.className)}>
      <Icon
        icon={s.icon}
        size={15}
        className={status === 'running' ? 'animate-spin motion-reduce:animate-none' : undefined}
      />
      {s.label}
    </span>
  );
}

function RunDetail({ run }: { run: AgentRunDetail }) {
  const mine = run.actions.filter((a) => a.mine && a.state === 'proposed');
  const others = run.actions.filter((a) => !(a.mine && a.state === 'proposed'));
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
      <header className="flex flex-col gap-2">
        <Link
          to={`/agents/${run.agent.id}`}
          className="inline-flex w-fit items-center gap-1.5 text-sm font-medium text-amber-ink hover:underline"
        >
          <MoMark size={13} /> {run.agent.name}
        </Link>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <h1 className="text-lg font-semibold">Run · {TRIGGER_LABEL[run.trigger] ?? run.trigger}</h1>
          <StatusBadge status={run.status} />
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {run.task ? (
            <>
              <dt className="text-muted">Task</dt>
              <dd>
                <Link to={`/task/${run.task.id}`} className="hover:underline">
                  <span className="text-muted">{run.task.key}</span> {run.task.title}
                </Link>
              </dd>
            </>
          ) : null}
          {run.project ? (
            <>
              <dt className="text-muted">Project</dt>
              <dd>
                <Link to={`/projects/${run.project.id}`} className="hover:underline">
                  {run.project.name}
                </Link>
              </dd>
            </>
          ) : null}
          {run.requested_by ? (
            <>
              <dt className="text-muted">For</dt>
              <dd>{run.requested_by.name}</dd>
            </>
          ) : null}
          <dt className="text-muted">Started</dt>
          <dd>{when(run.started_at ?? run.created_at)}</dd>
          <dt className="text-muted">Finished</dt>
          <dd>{when(run.finished_at)}</dd>
          <dt className="text-muted">Usage</dt>
          <dd>
            {run.steps} model step{run.steps === 1 ? '' : 's'} ·{' '}
            {(run.tokens_in + run.tokens_out).toLocaleString()} tokens · {money(run.cost_usd)}
          </dd>
        </dl>
      </header>

      {run.error ? (
        <p role="alert" className="rounded-md border border-crit/40 bg-crit-tint px-3 py-2 text-sm text-crit">
          {run.error}
        </p>
      ) : null}

      {mine.length ? (
        <section aria-label="Waiting for you" className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold">Waiting for you</h2>
          {mine.map((a) => (
            <PreviewCard key={a.id} actionId={a.id} />
          ))}
        </section>
      ) : null}

      {run.answer ? (
        <AICallout label={`${run.agent.name} answered`}>
          <p className="whitespace-pre-wrap">{run.answer}</p>
        </AICallout>
      ) : null}

      <section aria-label="Steps" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Steps</h2>
        {run.detail === 'summary' ? (
          <p className="text-xs text-muted">
            This run used the agent’s own access, so step details are shown only to admins and the person it
            ran for.
          </p>
        ) : null}
        {run.trace.length ? (
          <ol className="flex flex-col">
            {run.trace.map((step, i) => (
              <StepRow key={i} step={step} />
            ))}
          </ol>
        ) : (
          <EmptyState title="No steps recorded yet">The run hasn’t started.</EmptyState>
        )}
      </section>

      {others.length ? (
        <section aria-label="Changes" className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">Changes</h2>
          <ul className="flex flex-col gap-1 text-sm">
            {others.map((a) => (
              <li key={a.id} className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-amber-ink">✦</span>
                <span>{a.summary || 'A change'}</span>
                <span className="text-xs text-muted">
                  {a.state}
                  {a.proposed_for ? ` · for ${a.proposed_for.name}` : ''}
                </span>
                {a.mine ? (
                  <Link to={`/ai/actions/${a.id}`} className="text-xs text-accent hover:underline">
                    Open
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function StepRow({ step }: { step: RunStep }) {
  const failed = step.ok === false || step.kind === 'error';
  return (
    <li className="flex gap-3 border-l border-hairline py-1.5 pl-3 text-sm">
      <span className="w-40 shrink-0 text-xs text-muted-2">{when(step.at)}</span>
      <div className="min-w-0">
        <span className={cn('font-medium', failed ? 'text-crit' : 'text-ink-2')}>
          {STEP_LABEL[step.kind] ?? step.kind}
          {step.name ? <span className="ml-1 font-mono text-xs text-muted">{step.name}</span> : null}
        </span>
        {step.summary ? <p className="text-muted">{step.summary}</p> : null}
      </div>
    </li>
  );
}
