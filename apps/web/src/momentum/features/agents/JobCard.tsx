import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { MoMark } from '@/components/common/MoMark';
import { Button } from '@/components/ui/Button';
import { useChannel } from '@/lib/realtime';
import { StatusBadge } from './StatusBadge';
import { platformKeys, useJobControl, useTaskJobs, type TaskJob, type UndoAll } from './platform';

/** The job cards at the top of a task (spec §12.3): which agent is working on it, how far it
 * got, what it's waiting for, and the controls. Updates live from the task's channel. */
export function TaskJobs({ taskId }: { taskId: string }) {
  const qc = useQueryClient();
  const jobs = useTaskJobs(taskId);
  useChannel(`task:${taskId}`, (e) => {
    if (e.entity_type === 'agent_run' || e.entity_type === 'ask' || e.event.startsWith('agent_run.'))
      void qc.invalidateQueries({ queryKey: platformKeys.taskJobs(taskId) });
  });
  if (!jobs.data?.length) return null;
  return (
    <div className="mb-4 flex flex-col gap-2">
      {jobs.data.map((j) => (
        <JobCard key={j.id} job={j} />
      ))}
    </div>
  );
}

export function undoMessage(r: UndoAll): string {
  const done = `Undid ${r.undone} change${r.undone === 1 ? '' : 's'}`;
  if (!r.skipped.length) return done;
  return `${done}; ${r.skipped.length} ${r.skipped.length === 1 ? 'was' : 'were'} changed by someone since and left as ${r.skipped.length === 1 ? 'it is' : 'they are'}`;
}

export function JobCard({ job }: { job: TaskJob }) {
  const control = useJobControl(job.id);
  const [confirmUndo, setConfirmUndo] = useState(false);
  const p = job.progress;
  const pctDone = p && p.total ? Math.round((p.done / p.total) * 100) : null;
  const busy = control.act.isPending || control.undoAll.isPending;
  return (
    <section
      aria-label={`${job.agent.name} job`}
      className="rounded-lg border border-amber/60 bg-amber-2/40 px-3 py-2 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <MoMark size={13} className="text-amber-ink" />
        <span className="font-medium">{job.agent.name}</span>
        {job.capability ? (
          <span className="text-xs text-muted">{job.capability.replace(/_/g, ' ')}</span>
        ) : null}
        <span className="ml-auto">
          <StatusBadge status={job.status} />
        </span>
      </div>
      {p ? (
        <div className="mt-1.5">
          <div
            role="progressbar"
            aria-label="Progress"
            aria-valuemin={0}
            aria-valuemax={p.total}
            aria-valuenow={p.done}
            className="h-1.5 overflow-hidden rounded-full bg-surface-2"
          >
            <div className="h-full bg-amber" style={{ width: `${pctDone ?? 0}%` }} />
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {p.done} of {p.total}
            {p.label ? ` ${p.label}` : ''}
          </p>
        </div>
      ) : null}
      {job.waiting_reason ? <p className="mt-1 text-ink-2">{job.waiting_reason}</p> : null}
      {job.current_step && job.status === 'running' ? (
        <p className="mt-0.5 text-xs text-muted">
          Now: <span className="font-mono">{job.current_step}</span>
        </p>
      ) : null}
      {job.error ? <p className="mt-1 text-xs text-crit">{job.error}</p> : null}
      {job.asks_for_me ? (
        <p className="mt-1 text-xs font-medium text-amber-ink">
          Waiting on you: {job.asks_for_me} question{job.asks_for_me === 1 ? '' : 's'} (below)
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Button asChild size="sm" variant="text">
          <Link to={`/agents/runs/${job.id}`}>Open run</Link>
        </Button>
        {job.status === 'paused' ? (
          <Button size="sm" disabled={busy} onClick={() => control.act.mutate('resume')}>
            Resume
          </Button>
        ) : job.status !== 'failed' ? (
          <Button size="sm" disabled={busy} onClick={() => control.act.mutate('pause')}>
            Pause
          </Button>
        ) : null}
        {job.status === 'failed' ? (
          <Button size="sm" disabled={busy} onClick={() => control.act.mutate('retry')}>
            Retry
          </Button>
        ) : (
          <Button size="sm" disabled={busy} onClick={() => control.act.mutate('cancel')}>
            Cancel
          </Button>
        )}
        {confirmUndo ? (
          <>
            <Button
              size="sm"
              variant="danger"
              disabled={busy}
              onClick={() =>
                control.undoAll.mutate(undefined, {
                  onSuccess: (r) => {
                    setConfirmUndo(false);
                    toast.success(undoMessage(r));
                  },
                })
              }
            >
              Undo all of it
            </Button>
            <Button size="sm" variant="text" onClick={() => setConfirmUndo(false)}>
              Keep
            </Button>
          </>
        ) : (
          <Button size="sm" variant="text" disabled={busy} onClick={() => setConfirmUndo(true)}>
            Undo everything {job.agent.name} did
          </Button>
        )}
      </div>
    </section>
  );
}
