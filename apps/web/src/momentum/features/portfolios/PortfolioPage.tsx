import { useQueryClient } from '@tanstack/react-query';
import { Briefcase, Plus, X } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';
import { EmptyState, ErrorState } from '@/components/common/States';
import { MoMark } from '@/components/common/MoMark';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { StatusChip, STATUS_LABEL, type Status } from '@/features/status';
import { cn } from '@/lib/cn';
import { useMomentumConfig } from '@/lib/config';
import { dayDiff, formatRelative, fromISODate } from '@/lib/dates';
import { useChannel } from '@/lib/realtime';
import {
  portfolioKeys,
  usePortfolio,
  usePortfolioLines,
  usePortfolioMutations,
  usePortfolioStatuses,
  type PortfolioDetail,
  type PortfolioRow,
  type StatusUpdateIn,
} from './queries';

const DATE = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
// least healthy first, the order the mix bar reads in
const ORDER: (Status | 'none')[] = ['off_track', 'at_risk', 'on_hold', 'on_track', 'complete', 'none'];
const MIX_COLOR: Record<Status | 'none', string> = {
  off_track: 'bg-crit',
  at_risk: 'bg-warn',
  on_hold: 'bg-info',
  on_track: 'bg-ok',
  complete: 'bg-muted-2',
  none: 'bg-hairline',
};

/**
 * A portfolio (S6.2.2): its projects side by side — status, progress, dates and the latest
 * update — with a status mix bar on top, a ✦ one-line read per project from Mo (only numbers the
 * row already shows; a plain facts line otherwise), and check-ins drafted from the projects'
 * own statuses. Rows are what the viewer can see; the rest are counted, never named.
 */
export function PortfolioPage() {
  const { portfolioId = '' } = useParams();
  const qc = useQueryClient();
  const q = usePortfolio(portfolioId);
  useChannel(
    `portfolio:${portfolioId}`,
    () => void qc.invalidateQueries({ queryKey: portfolioKeys.detail(portfolioId) }),
  );
  if (q.isPending) return <Skeleton className="m-8 h-64" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <PortfolioBody p={q.data} />;
}

function PortfolioBody({ p }: { p: PortfolioDetail }) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const m = usePortfolioMutations(p.id);
  const lines = usePortfolioLines(p.id, p.version, aiEnabled && p.projects.length > 0);
  const lineFor = useMemo(() => new Map((lines.data ?? []).map((l) => [l.project_id, l])), [lines.data]);
  const people = usePeople('', 'all').data;
  const peopleById = useMemo(() => new Map((people ?? []).map((u) => [u.id, u])), [people]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 page-title">
            <Icon icon={Briefcase} size={18} className="text-muted" />
            <span className="truncate">{p.name}</span>
            {p.status ? <StatusChip status={p.status as Status} /> : null}
          </h1>
          {p.description ? <p className="mt-1 text-sm text-muted">{p.description}</p> : null}
        </div>
        {p.can_edit ? <AddProject p={p} onAdd={(id) => m.addProject.mutate(id)} /> : null}
      </header>

      {p.projects.length ? <StatusMix rows={p.projects} /> : null}

      {p.projects.length === 0 ? (
        <EmptyState icon={Briefcase} title="No projects in this portfolio yet">
          {p.can_edit
            ? 'Add the projects you want to watch together.'
            : 'Its owner hasn’t added any projects you can see.'}
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
          <table className="w-full min-w-[860px] text-sm">
            <caption className="sr-only">Projects in {p.name}</caption>
            <thead className="border-b border-hairline text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Project</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Progress</th>
                <th className="px-2 py-2 font-medium">Due</th>
                <th className="px-2 py-2 font-medium">Latest update</th>
                {aiEnabled ? (
                  <th className="px-2 py-2 font-medium text-amber-ink">
                    <span className="inline-flex items-center gap-1">
                      <MoMark size={12} /> Mo’s read
                    </span>
                  </th>
                ) : null}
                {p.can_edit ? <th className="w-10" aria-label="Remove" /> : null}
              </tr>
            </thead>
            <tbody>
              {p.projects.map((row) => {
                const owner = row.owner_id ? peopleById.get(row.owner_id) : undefined;
                const line = lineFor.get(row.id);
                return (
                  <tr key={row.id} className="border-b border-hair-soft last:border-0 hover:bg-surface-2">
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <span
                          aria-hidden
                          className="h-2.5 w-2.5 shrink-0 rounded-sm"
                          style={{ background: `var(--${row.color ?? 'hairline'})` }}
                        />
                        <Link
                          to={`/projects/${row.id}/overview`}
                          className="truncate font-medium hover:underline"
                        >
                          {row.name}
                        </Link>
                        {owner ? <Avatar name={owner.name} src={owner.avatar_url} size={20} /> : null}
                      </div>
                    </td>
                    <td className="px-2 py-2.5 whitespace-nowrap">
                      {row.status ? (
                        <StatusChip status={row.status as Status} />
                      ) : (
                        <span className="text-muted-2">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2.5">
                      <Progress row={row} />
                    </td>
                    <td className="px-2 py-2.5 whitespace-nowrap tabular-nums">
                      <Due iso={row.due_on ?? null} />
                    </td>
                    <td className="max-w-56 px-2 py-2.5">
                      {row.latest_update_title ? (
                        <span className="block truncate" title={row.latest_update_title}>
                          {row.latest_update_title}
                          <span className="ml-1.5 text-xs text-muted-2">
                            {formatRelative(row.latest_update_at!)}
                          </span>
                        </span>
                      ) : (
                        <span className="text-muted-2">No updates</span>
                      )}
                    </td>
                    {aiEnabled ? (
                      <td className="max-w-72 px-2 py-2.5">
                        {lines.isPending ? (
                          <Skeleton className="h-4" />
                        ) : line ? (
                          <span
                            className={cn('block text-[13px]', line.ai ? 'text-amber-ink' : 'text-muted')}
                          >
                            {line.text}
                          </span>
                        ) : null}
                      </td>
                    ) : null}
                    {p.can_edit ? (
                      <td className="pr-2">
                        <IconButton
                          icon={X}
                          size="icon-sm"
                          label={`Remove ${row.name}`}
                          onClick={() => m.removeProject.mutate(row.id)}
                        />
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {p.hidden_projects ? (
        <p className="text-sm text-muted">
          {p.hidden_projects} more {p.hidden_projects === 1 ? 'project is' : 'projects are'} in this portfolio
          but not shown, because you can’t see {p.hidden_projects === 1 ? 'it' : 'them'}.
        </p>
      ) : null}

      <CheckIns p={p} />
    </div>
  );
}

function StatusMix({ rows }: { rows: PortfolioRow[] }) {
  const counts = new Map<Status | 'none', number>();
  for (const r of rows) {
    const k = (r.status ?? 'none') as Status | 'none';
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const parts = ORDER.filter((k) => counts.get(k));
  return (
    <section aria-label="Status mix" className="space-y-2">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-hair-soft">
        {parts.map((k) => (
          <span
            key={k}
            className={MIX_COLOR[k]}
            style={{ width: `${(100 * counts.get(k)!) / rows.length}%` }}
          />
        ))}
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {parts.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={cn('h-2 w-2 rounded-full', MIX_COLOR[k])} />
            {counts.get(k)} {k === 'none' ? 'no status' : STATUS_LABEL[k].toLowerCase()}
          </span>
        ))}
      </p>
    </section>
  );
}

function Progress({ row }: { row: PortfolioRow }) {
  if (!row.total_tasks) return <span className="text-muted-2">No tasks</span>;
  const pct = Math.round((100 * row.completed_tasks) / row.total_tasks);
  return (
    <div
      className="flex items-center gap-2"
      title={`${row.completed_tasks} of ${row.total_tasks} tasks done`}
    >
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-hair-soft">
        <div className="h-full rounded-full bg-ok" style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums">{pct}%</span>
      {row.overdue_tasks ? (
        <span className="text-xs whitespace-nowrap text-crit tabular-nums">{row.overdue_tasks} overdue</span>
      ) : null}
    </div>
  );
}

function Due({ iso }: { iso: string | null }) {
  if (!iso) return <span className="text-muted-2">—</span>;
  const left = dayDiff(new Date(), fromISODate(iso));
  return (
    <span>
      {DATE.format(fromISODate(iso))}{' '}
      <span className={cn('text-meta', left < 0 ? 'text-crit' : left <= 7 ? 'text-warn' : 'text-muted')}>
        {left < 0 ? `${-left}d late` : left === 0 ? 'today' : `${left}d`}
      </span>
    </span>
  );
}

function AddProject({ p, onAdd }: { p: PortfolioDetail; onAdd: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const projects = useProjects().data ?? [];
  const inIt = new Set(p.projects.map((r) => r.id));
  const options = projects
    .filter((x) => !inIt.has(x.id) && x.name.toLowerCase().includes(q.trim().toLowerCase()))
    .slice(0, 12);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost">
          <Icon icon={Plus} size={15} /> Add project
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-2">
        <Input
          aria-label="Find a project"
          placeholder="Find a project…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ul className="mt-2 max-h-64 overflow-auto">
          {options.map((x) => (
            <li key={x.id}>
              <button
                type="button"
                onClick={() => {
                  onAdd(x.id);
                  setOpen(false);
                  setQ('');
                }}
                className="w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-surface-2"
              >
                {x.name}
              </button>
            </li>
          ))}
          {options.length === 0 ? (
            <li className="px-2 py-1.5 text-sm text-muted-2">No more projects</li>
          ) : null}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function CheckIns({ p }: { p: PortfolioDetail }) {
  const m = usePortfolioMutations(p.id);
  const history = usePortfolioStatuses(p.id);
  const [editing, setEditing] = useState<StatusUpdateIn | null>(null);
  const start = () => m.draft.mutate(undefined, { onSuccess: (d) => setEditing(d) });
  const post = (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    m.postStatus.mutate(editing, { onSuccess: () => setEditing(null) });
  };
  const sections = editing
    ? (['slipped', 'blockers', 'next', 'completed'] as const).filter((k) => editing.sections?.[k]?.length)
    : [];
  return (
    <section aria-labelledby="checkins" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="checkins" className="flex-1 text-[15px] font-semibold">
          Check-ins
        </h2>
        {p.can_edit && !editing ? (
          <Button size="sm" variant="ghost" loading={m.draft.isPending} onClick={start}>
            Draft check-in
          </Button>
        ) : null}
      </div>
      {editing ? (
        <form
          onSubmit={post}
          className="space-y-3 rounded-xl border border-hairline bg-surface p-4"
          aria-label="New check-in"
        >
          <p className="text-xs text-muted">
            Drafted from the projects’ own statuses and numbers. Edit before posting.
          </p>
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="Status"
              value={editing.status}
              onChange={(e) => setEditing({ ...editing, status: e.target.value as Status })}
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm"
            >
              {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
            <Input
              aria-label="Title"
              className="min-w-64 flex-1"
              value={editing.title}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
            />
          </div>
          <textarea
            aria-label="Summary"
            value={editing.summary ?? ''}
            onChange={(e) => setEditing({ ...editing, summary: e.target.value })}
            className="min-h-16 w-full rounded-md border border-hairline bg-surface p-2 text-sm"
          />
          {sections.map((k) => (
            <div key={k}>
              <p className="text-xs font-medium text-muted capitalize">{k}</p>
              <ul className="list-disc pl-5 text-sm">
                {editing.sections![k]!.map((i, n) => (
                  <li key={n}>{i.text}</li>
                ))}
              </ul>
            </div>
          ))}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="text" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={m.postStatus.isPending}
              disabled={!editing.title.trim()}
            >
              Post check-in
            </Button>
          </div>
        </form>
      ) : null}
      {history.data?.length === 0 && !editing ? (
        <p className="text-sm text-muted-2">No check-ins yet.</p>
      ) : null}
      <ol aria-label="Check-in history" className="space-y-2">
        {history.data?.map((u) => (
          <li key={u.id} className="rounded-xl border border-hairline bg-surface p-4">
            <p className="flex items-center gap-2">
              <StatusChip status={u.status as Status} />
              <span className="font-medium">{u.title}</span>
              <span className="ml-auto text-xs text-muted-2">{formatRelative(u.created_at)}</span>
            </p>
            {u.summary ? <p className="mt-1 text-sm text-muted">{u.summary}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
