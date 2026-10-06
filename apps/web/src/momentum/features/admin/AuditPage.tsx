import { History } from 'lucide-react';
import { useState } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { useMembers } from '@/features/members';
import { useAudit, type AuditFilters } from './queries';

const KINDS: [string, string][] = [
  ['', 'Everything'],
  ['task', 'Tasks'],
  ['project', 'Projects'],
  ['comment', 'Comments'],
  ['user', 'People'],
  ['team', 'Teams'],
  ['rule', 'Rules'],
  ['agent', 'Agents'],
  ['import', 'Imports'],
  ['job', 'Jobs'],
];

/** S7.5.4: the audit trail for admins: every change, who made it (a person, Mo, an agent, a rule
 * or an import) and when, filtered by person, kind and dates. Items in private projects the admin
 * can't see are listed without their names. */
export function AuditPage() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const audit = useAudit(filters);
  const people = useMembers().data ?? [];
  const set = (patch: AuditFilters) =>
    setFilters((f) => Object.fromEntries(Object.entries({ ...f, ...patch }).filter(([, v]) => v)));
  const rows = audit.data?.pages.flat() ?? [];
  const field = 'h-8 rounded-md border border-hairline bg-surface px-2 text-sm text-ink';
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <h1 className="page-title">Audit trail</h1>
      <p className="mt-1 text-sm text-muted">Every change in the workspace, newest first.</p>
      <div role="group" aria-label="Filter the audit trail" className="mt-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted">
          Who
          <select
            className={field}
            value={filters.actor_id ?? ''}
            onChange={(e) => set({ actor_id: e.target.value || undefined })}
          >
            <option value="">Anyone</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          What
          <select
            className={field}
            value={filters.entity_type ?? ''}
            onChange={(e) => set({ entity_type: e.target.value || undefined })}
          >
            {KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          From
          <input
            type="date"
            className={field}
            value={filters.since?.slice(0, 10) ?? ''}
            onChange={(e) => set({ since: e.target.value ? `${e.target.value}T00:00:00` : undefined })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted">
          To
          <input
            type="date"
            className={field}
            value={filters.until?.slice(0, 10) ?? ''}
            onChange={(e) => set({ until: e.target.value ? `${e.target.value}T23:59:59` : undefined })}
          />
        </label>
      </div>
      <div className="mt-4">
        {audit.isPending ? (
          <Skeleton className="h-40" />
        ) : audit.isError ? (
          <ErrorState error={audit.error} onRetry={() => void audit.refetch()} />
        ) : !rows.length ? (
          <EmptyState icon={History} title="Nothing matches">
            Try another person, kind or date range.
          </EmptyState>
        ) : (
          <>
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-hairline text-xs text-muted">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    When
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Who
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Did
                  </th>
                  <th scope="col" className="py-1.5 font-medium">
                    To
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id} className="border-b border-hair-soft align-top">
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-3">
                      {a.actor_name ?? (a.actor_kind === 'system' ? 'Momentum' : 'Someone')}
                      {a.actor_kind !== 'user' ? (
                        <span className="ml-1 text-xs text-muted">({a.actor_kind})</span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {a.verb}
                      {a.changes.length ? (
                        <span className="text-muted"> · {a.changes.join(', ')}</span>
                      ) : null}
                      {a.undone ? <span className="ml-1 text-muted">(undone)</span> : null}
                    </td>
                    <td className="py-2 text-ink-2">
                      {a.entity_label ?? (
                        <span className="text-muted">a {a.entity_type} you can&apos;t see</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {audit.hasNextPage ? (
              <Button
                size="sm"
                variant="text"
                className="mt-2"
                disabled={audit.isFetchingNextPage}
                onClick={() => void audit.fetchNextPage()}
              >
                Older
              </Button>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
