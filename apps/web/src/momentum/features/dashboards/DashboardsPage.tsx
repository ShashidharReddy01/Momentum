import { LayoutDashboard, Plus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatRelative } from '@/lib/dates';
import { useCreateDashboard, useDashboards } from './queries';

/** S6.5.1: the workspace's dashboards. Every member sees them; numbers inside are theirs. */
export function DashboardsPage() {
  const list = useDashboards();
  const create = useCreateDashboard();
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    create.mutate({ name: n, starter: true }, { onSuccess: (res) => navigate(`/dashboards/${res.data.id}`) });
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <header className="mb-6 flex items-center gap-3">
        <h1 className="flex-1 text-xl font-semibold">Dashboards</h1>
        <Button variant="primary" onClick={() => setAdding(true)}>
          <Icon icon={Plus} size={15} /> New dashboard
        </Button>
      </header>
      {adding ? (
        <form onSubmit={submit} className="mb-6 flex gap-2">
          <Input
            aria-label="Dashboard name"
            placeholder="e.g. Delivery this quarter"
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
        <EmptyState
          icon={LayoutDashboard}
          title="No workspace dashboards yet"
          action={
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Icon icon={Plus} size={15} /> New dashboard
            </Button>
          }
        >
          A dashboard starts with the numbers most teams check first (open, overdue, due soon, done this week,
          who has what). Change any chart, and click a bar to see its tasks. Each project also has its own on
          its Dashboard tab.
        </EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.data.map((d) => (
            <li key={d.id}>
              <Link
                to={`/dashboards/${d.id}`}
                className="flex h-full flex-col gap-2 rounded-xl border border-hairline bg-surface p-4 hover:bg-surface-2"
              >
                <span className="flex items-center gap-2 font-medium">
                  <Icon icon={LayoutDashboard} size={15} className="text-muted" />
                  <span className="truncate">{d.name}</span>
                </span>
                {d.description ? (
                  <span className="line-clamp-2 text-sm text-muted">{d.description}</span>
                ) : null}
                <span className="mt-auto text-sm text-muted">
                  {d.widget_count} {d.widget_count === 1 ? 'chart' : 'charts'} · updated{' '}
                  {formatRelative(d.updated_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
