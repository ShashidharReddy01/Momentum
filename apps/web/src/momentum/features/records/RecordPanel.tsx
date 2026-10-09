import { Link } from 'react-router';
import { getPath, humanize, type Display } from './model';
import { useRecords, useRecordTypes } from './queries';
import { RecordStatus } from './RecordStatus';

type Check = { passed?: boolean; severity?: string; title?: string };

/** The record panel on a task (spec §12.3): each record made from this task with its status, key
 * fields (the type's first columns), blocking checks and the decision's reason, and Open review. */
export function RecordPanel({ taskId }: { taskId: string }) {
  const records = useRecords(null, { task_id: taskId });
  const types = useRecordTypes(null, !!records.data?.length);
  if (!records.data?.length) return null;
  return (
    <section aria-label="Records" className="mt-4 flex flex-col gap-2">
      {records.data.map((r) => {
        const display = (types.data?.find((t) => t.key === r.type)?.display ?? {}) as Display;
        const cols = (display.columns ?? []).slice(0, 4);
        const blocking = (r.checks as Check[]).filter((c) => !c.passed && c.severity === 'block');
        const reason = (r.decision as { reason?: string } | null)?.reason;
        return (
          <article key={r.id} className="rounded-lg border border-hairline p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{r.title}</span>
              <RecordStatus status={r.status} />
              <span className="text-xs text-muted">{r.type_label}</span>
              <Link
                to={`/records/${r.id}`}
                className="ml-auto text-xs font-medium text-accent hover:underline"
              >
                Open review
              </Link>
            </div>
            {cols.length ? (
              <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                {cols.map((c) => (
                  <div key={c} className="contents">
                    <dt className="text-muted">{humanize(c)}</dt>
                    <dd>{String(getPath(r.data, c) ?? '—')}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {blocking.length ? (
              <ul className="mt-1.5 text-xs text-crit">
                {blocking.map((c, i) => (
                  <li key={i}>✕ {c.title}</li>
                ))}
              </ul>
            ) : null}
            {reason ? <p className="mt-1 text-xs text-ink-2">✦ {reason}</p> : null}
          </article>
        );
      })}
    </section>
  );
}
