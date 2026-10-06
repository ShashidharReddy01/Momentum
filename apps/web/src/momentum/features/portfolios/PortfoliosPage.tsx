import { Briefcase, Plus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { StatusChip, type Status } from '@/features/status';
import { money } from './cells';
import { useCreatePortfolio } from './queries';
import { usePortfolioSummaries } from './v2queries';

/** S6.2.2: every portfolio in the workspace, as cards (status, project count, description).
 * Phase 7.5: a lifecycle portfolio's card adds a mini-bar per stage and its total value. */
export function PortfoliosPage() {
  const list = usePortfolioSummaries();
  const create = useCreatePortfolio();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    create.mutate({ name: n }, { onSuccess: (res) => navigate(`/portfolios/${res.data.id}`) });
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <header className="mb-6 flex items-center gap-3">
        <h1 className="flex-1 page-title">Portfolios</h1>
        <Button variant="primary" onClick={() => setAdding(true)}>
          <Icon icon={Plus} size={15} /> New portfolio
        </Button>
      </header>
      {adding ? (
        <form onSubmit={submit} className="mb-6 flex gap-2">
          <Input
            aria-label="Portfolio name"
            placeholder="e.g. Q4 launches"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create
          </Button>
          <Button type="button" variant="text" onClick={() => setAdding(false)}>
            Cancel
          </Button>
        </form>
      ) : null}
      {list.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.length === 0 ? (
        <EmptyState icon={Briefcase} title="No portfolios yet">
          Group the projects you watch together (a launch, a client, a quarter) to see their status, progress
          and dates side by side.
        </EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.data.map((p) => (
            <li key={p.id}>
              <Link
                to={`/portfolios/${p.id}`}
                className="flex h-full flex-col gap-2 rounded-xl border border-hairline bg-surface p-4 hover:bg-surface-2"
              >
                <span className="flex items-center gap-2 font-medium">
                  <Icon icon={Briefcase} size={15} className="text-muted" />
                  <span className="truncate">{p.name}</span>
                </span>
                {p.description ? (
                  <span className="line-clamp-2 text-sm text-muted">{p.description}</span>
                ) : null}
                {p.summary && p.summary.stages.length ? <StageBars summary={p.summary} /> : null}
                <span className="mt-auto flex items-center gap-2 text-sm text-muted">
                  {p.status ? <StatusChip status={p.status as Status} /> : null}
                  {p.project_count} {p.project_count === 1 ? 'project' : 'projects'}
                  {p.summary?.total_value !== null && p.summary?.total_value !== undefined ? (
                    <span className="ml-auto tabular-nums" title={p.summary.value_field ?? undefined}>
                      {money(p.summary.total_value)}
                    </span>
                  ) : null}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type Summary = NonNullable<ReturnType<typeof usePortfolioSummaries>['data']>[number]['summary'];

/** One thin bar per stage, as tall as its share of the projects (the counts are in the label). */
function StageBars({ summary }: { summary: NonNullable<Summary> }) {
  const max = Math.max(1, ...summary.stages.map((s) => s.count));
  const label = summary.stages.map((s) => `${s.label} ${s.count}`).join(', ');
  return (
    <span
      role="img"
      aria-label={`Projects per stage: ${label}`}
      className="flex h-8 items-end gap-0.5"
      title={label}
    >
      {summary.stages.map((s) => (
        <span
          key={s.option_id}
          className={s.count ? 'flex-1 rounded-sm bg-accent/60' : 'flex-1 rounded-sm bg-hair-soft'}
          style={{ height: `${Math.max(8, (s.count / max) * 100)}%` }}
        />
      ))}
    </span>
  );
}
