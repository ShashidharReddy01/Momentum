import { ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { Icon } from '@/components/ui/Icon';
import { cn } from '@/lib/cn';
import type { AgentRun, AgentRunDetail } from './queries';
import { StatusBadge } from './StatusBadge';
import { JOB_STEP_KIND, money } from './runMeta';

type JobStep = AgentRunDetail['job_steps'][number];

function ms(n: number | null | undefined): string {
  if (n == null) return '';
  return n < 1000 ? `${n} ms` : `${(n / 1000).toFixed(1)} s`;
}

/** A durable job's steps as a timeline (spec §4.6): kind, name, duration, tokens, cost and
 * status for each; sub-jobs nested underneath and collapsible. */
export function StepTimeline({ run }: { run: AgentRunDetail }) {
  return (
    <section aria-label="Timeline" className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">Timeline</h2>
      {run.job_steps.length ? (
        <ol className="flex flex-col">
          {run.job_steps.map((s) => (
            <StepItem key={s.seq} step={s} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted">No steps yet.</p>
      )}
      {run.children.length ? <Children kids={run.children} /> : null}
    </section>
  );
}

function StepItem({ step: s }: { step: JobStep }) {
  const failed = s.status === 'failed';
  const output = s.output == null ? null : JSON.stringify(s.output, null, 2);
  return (
    <li className="relative border-l border-hairline py-1.5 pl-4 text-sm">
      <span
        aria-hidden
        className={cn(
          'absolute top-3 -left-[4px] h-2 w-2 rounded-full',
          failed ? 'bg-crit' : s.status === 'running' ? 'bg-amber' : 'bg-muted-2',
        )}
      />
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className={cn('font-medium', failed ? 'text-crit' : 'text-ink-2')}>
          {JOB_STEP_KIND[s.kind] ?? s.kind}
        </span>
        <span className="font-mono text-xs text-muted">{s.key}</span>
        <span className="ml-auto text-xs text-muted-2">
          {[
            s.status === 'running' ? 'running' : failed ? 'failed' : null,
            ms(s.duration_ms),
            s.tokens_in + s.tokens_out ? `${(s.tokens_in + s.tokens_out).toLocaleString()} tokens` : null,
            Number(s.cost_usd) ? money(s.cost_usd) : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </div>
      {s.error ? <p className="text-xs text-crit">{s.error}</p> : null}
      {output ? (
        <details className="mt-0.5 text-xs">
          <summary className="cursor-pointer text-muted">Output</summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface-2 p-2">{output}</pre>
        </details>
      ) : null}
    </li>
  );
}

function Children({ kids }: { kids: AgentRun[] }) {
  const [open, setOpen] = useState(kids.length <= 5);
  const done = kids.filter((k) => k.status === 'succeeded').length;
  return (
    <div className="mt-1">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-sm font-medium text-ink-2 hover:text-ink"
      >
        <Icon icon={ChevronRight} size={14} className={cn('transition-transform', open && 'rotate-90')} />
        Sub-jobs ({done} of {kids.length} done)
      </button>
      {open ? (
        <ul aria-label="Sub-jobs" className="mt-1 ml-5 flex flex-col">
          {kids.map((k) => (
            <li key={k.id} className="border-b border-hair-soft last:border-0">
              <Link
                to={`/agents/runs/${k.id}`}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-sm hover:bg-surface-2"
              >
                <StatusBadge status={k.status} />
                <span className="text-ink-2">{k.capability?.replace(/_/g, ' ') ?? 'Sub-job'}</span>
                {k.task ? (
                  <span className="min-w-0 truncate">
                    <span className="text-muted">{k.task.key}</span> {k.task.title}
                  </span>
                ) : null}
                {k.progress ? (
                  <span className="text-xs text-muted">
                    {k.progress.done} of {k.progress.total}
                  </span>
                ) : null}
                {k.error ? <span className="w-full text-xs text-crit">{k.error}</span> : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
