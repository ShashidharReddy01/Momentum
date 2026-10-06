import { RotateCcw } from 'lucide-react';
import { useState } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useJobs, useRetryJob, type JobStatus } from './queries';

const TABS: { status: JobStatus; label: string }[] = [
  { status: 'failed', label: 'Failed' },
  { status: 'todo', label: 'Waiting' },
  { status: 'doing', label: 'Running' },
  { status: 'succeeded', label: 'Done' },
];

/** S7.5.4: the background queue for admins: how many jobs wait, run or failed; retry a failed
 * one. Why a job failed is in the server log (search by its name and time). */
export function JobsPage() {
  const [status, setStatus] = useState<JobStatus>('failed');
  const jobs = useJobs(status);
  const retry = useRetryJob();
  const counts = jobs.data?.counts ?? {};
  return (
    <div className="mx-auto max-w-4xl px-4 py-6 md:px-8">
      <h1 className="page-title">Background jobs</h1>
      <p className="mt-1 text-sm text-muted">
        Reminders, agents, search indexing and imports run here. Refreshes every 15 seconds.
      </p>
      <div role="tablist" aria-label="Job status" className="mt-4 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button
            key={t.status}
            type="button"
            role="tab"
            aria-selected={status === t.status}
            onClick={() => setStatus(t.status)}
            className={cn(
              'h-8 rounded-md px-3 text-sm',
              status === t.status
                ? 'bg-accent text-on-accent'
                : 'bg-surface-2 text-ink-2 hover:bg-accent-tint',
            )}
          >
            {t.label} <span className="tabular ml-1 text-xs opacity-80">{counts[t.status] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="mt-4">
        {jobs.isPending ? (
          <Skeleton className="h-32" />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />
        ) : !jobs.data.jobs.length ? (
          <EmptyState icon={RotateCcw} title={status === 'failed' ? 'No failed jobs' : 'Nothing here'}>
            {status === 'failed' ? 'Everything that ran, worked.' : 'No jobs with this status right now.'}
          </EmptyState>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-hairline text-xs text-muted">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Job
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Queue
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Attempts
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Last activity
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.jobs.map((j) => {
                const when = j.last_event_at ?? j.scheduled_at;
                return (
                  <tr key={j.id} className="border-b border-hair-soft">
                    <td className="py-2 pr-3 font-mono text-xs">{j.task_name.replace(/^momentum:/, '')}</td>
                    <td className="py-2 pr-3 text-xs text-muted">{j.queue_name.replace(/^momentum_/, '')}</td>
                    <td className="tabular py-2 pr-3">{j.attempts}</td>
                    <td className="py-2 pr-3 text-xs text-muted">
                      {when ? new Date(when).toLocaleString() : '—'}
                    </td>
                    <td className="py-2 text-right">
                      {j.status === 'failed' ? (
                        <Button
                          size="sm"
                          variant="text"
                          disabled={retry.isPending}
                          onClick={() => retry.mutate(j.id)}
                          aria-label={`Retry ${j.task_name} (job ${j.id})`}
                        >
                          <Icon icon={RotateCcw} /> Retry
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
