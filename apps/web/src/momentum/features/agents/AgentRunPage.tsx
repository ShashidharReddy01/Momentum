import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { toast } from 'sonner';
import { AICallout } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { PreviewCard } from '@/features/ai';
import { cn } from '@/lib/cn';
import { useChannel } from '@/lib/realtime';
import { undoMessage } from './JobCard';
import { useJobControl } from './platform';
import { agentKeys, useAgentRun, type AgentRunDetail, type RunStep } from './queries';
import { StepTimeline } from './StepTimeline';
import { STEP_LABEL, TRIGGER_LABEL, duration, money, when } from './runMeta';

export { StatusBadge } from './StatusBadge';
import { StatusBadge } from './StatusBadge';

/** S5.1.3 `/agents/runs/:runId`: everything one agent run did, so every action it took can be
 * explained — why it ran, each step, what it proposed or changed, its answer, cost and errors. */
export function AgentRunPage() {
  const { runId } = useParams();
  const qc = useQueryClient();
  const run = useAgentRun(runId!);
  // spec §4.6: a job's page follows it live
  useChannel(`run:${runId}`, () => void qc.invalidateQueries({ queryKey: agentKeys.run(runId!) }));
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
          <h1 className="page-title">Run · {TRIGGER_LABEL[run.trigger] ?? run.trigger}</h1>
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
          {run.mode === 'job' ? (
            <>
              <dt className="text-muted">Working time</dt>
              <dd>
                {duration(run.active_seconds)}
                {run.attempt ? ` · attempt ${run.attempt + 1}` : ''}
              </dd>
            </>
          ) : null}
          {run.progress ? (
            <>
              <dt className="text-muted">Progress</dt>
              <dd>
                {run.progress.done} of {run.progress.total}
                {run.progress.label ? ` ${run.progress.label}` : ''}
              </dd>
            </>
          ) : null}
          {run.waiting_on ? (
            <>
              <dt className="text-muted">Waiting on</dt>
              <dd>{WAITING[run.waiting_on] ?? run.waiting_on}</dd>
            </>
          ) : null}
        </dl>
        {run.mode === 'job' && !run.parent_run_id ? <JobControls run={run} /> : null}
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

      {run.mode === 'job' ? <StepTimeline run={run} /> : null}

      {run.mode === 'job' && !run.trace.length ? null : (
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
      )}

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

const WAITING: Record<string, string> = {
  ask: 'An answer to its question',
  children: 'Its sub-jobs',
  timer: 'A timer',
  event: 'Something to happen',
  instruction: 'An instruction',
  paused: 'Someone to resume it',
  agent_off: 'The agent to be turned back on',
  packs_off: 'Agent packs to be turned back on',
};

const FINISHED = new Set(['succeeded', 'failed', 'cancelled', 'budget_exceeded', 'expired']);

/** Pause, resume, cancel, retry, and "Undo everything" (spec §4.7) for a job. */
function JobControls({ run }: { run: AgentRunDetail }) {
  const control = useJobControl(run.id);
  const [confirm, setConfirm] = useState(false);
  const busy = control.act.isPending || control.undoAll.isPending;
  const open = !FINISHED.has(run.status);
  return (
    <div className="flex flex-wrap gap-1.5">
      {run.status === 'paused' ? (
        <Button size="sm" disabled={busy} onClick={() => control.act.mutate('resume')}>
          Resume
        </Button>
      ) : open ? (
        <Button size="sm" disabled={busy} onClick={() => control.act.mutate('pause')}>
          Pause
        </Button>
      ) : null}
      {open ? (
        <Button size="sm" disabled={busy} onClick={() => control.act.mutate('cancel')}>
          Cancel
        </Button>
      ) : null}
      {run.status === 'failed' ? (
        <Button size="sm" disabled={busy} onClick={() => control.act.mutate('retry')}>
          Retry
        </Button>
      ) : null}
      {confirm ? (
        <>
          <Button
            size="sm"
            variant="danger"
            disabled={busy}
            onClick={() =>
              control.undoAll.mutate(undefined, {
                onSuccess: (r) => {
                  setConfirm(false);
                  toast.success(undoMessage(r));
                },
              })
            }
          >
            Undo all of it
          </Button>
          <Button size="sm" variant="text" onClick={() => setConfirm(false)}>
            Keep
          </Button>
        </>
      ) : (
        <Button size="sm" variant="text" disabled={busy} onClick={() => setConfirm(true)}>
          Undo everything {run.agent.name} did
        </Button>
      )}
    </div>
  );
}
