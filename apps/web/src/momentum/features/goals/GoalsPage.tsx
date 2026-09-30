import { ChevronDown, ChevronRight, Plus, Target } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { StatusChip, type Status } from '@/features/status';
import { cn } from '@/lib/cn';
import { quarters, useCreateGoal, useGoals, type Goal, type GoalIn } from './queries';

type Filter = 'current' | 'next' | 'all';
const SOURCE_LABEL = { manual: 'Metric', projects: 'Linked work', subgoals: 'Sub-goals' } as const;

/** The progress bar every goal view shares; "No data yet" instead of a fake 0%. */
export function GoalProgress({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined)
    return <span className={cn('text-xs text-muted-2', className)}>No data yet</span>;
  const pct = Math.round(value * 100);
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <span className="h-1.5 w-28 overflow-hidden rounded-full bg-hair-soft" aria-hidden>
        <span className="block h-full rounded-full bg-ok" style={{ width: `${pct}%` }} />
      </span>
      <span className="text-sm tabular-nums">{pct}%</span>
    </span>
  );
}

/**
 * Goals (S6.3.1): what the team is aiming for, by quarter, as a tree (goal → sub-goals), each with
 * its owner, check-in status and progress measured from its own source (a metric, the linked
 * work, or its sub-goals) as you can see it.
 */
export function GoalsPage() {
  const list = useGoals();
  const [filter, setFilter] = useState<Filter>('current');
  const [creating, setCreating] = useState(false);
  const qs = useMemo(() => quarters(), []);
  const people = usePeople('', 'all').data;
  const peopleById = useMemo(() => new Map((people ?? []).map((u) => [u.id, u])), [people]);

  const shown = useMemo(() => {
    const all = list.data ?? [];
    if (filter === 'all') return all;
    const q = qs[filter === 'current' ? 1 : 2]!;
    return all.filter((g) => g.period_start <= q.end && g.period_end >= q.start);
  }, [list.data, filter, qs]);
  const ids = new Set(shown.map((g) => g.id));
  const roots = shown.filter((g) => !g.parent_id || !ids.has(g.parent_id));
  const childrenOf = (id: string) => shown.filter((g) => g.parent_id === id);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="flex-1 text-xl font-semibold">Goals</h1>
        <div className="flex rounded-md bg-surface-2 p-0.5 text-sm" role="group" aria-label="Period">
          {(
            [
              ['current', qs[1]!.label],
              ['next', qs[2]!.label],
              ['all', 'All'],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={filter === k}
              onClick={() => setFilter(k)}
              className={cn(
                'rounded px-2.5 py-1',
                filter === k ? 'bg-surface shadow-sm' : 'text-muted hover:text-ink',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Icon icon={Plus} size={15} /> New goal
        </Button>
      </header>
      {list.isPending ? (
        <Skeleton className="h-40" />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : roots.length === 0 ? (
        <EmptyState icon={Target} title={filter === 'all' ? 'No goals yet' : 'No goals in this quarter'}>
          Set what the team is aiming for, how you'll measure it, and link the projects that move it.
        </EmptyState>
      ) : (
        <ul
          aria-label="Goals"
          className="divide-y divide-hair-soft rounded-xl border border-hairline bg-surface"
        >
          {roots.map((g) => (
            <GoalRow key={g.id} goal={g} depth={0} childrenOf={childrenOf} peopleById={peopleById} />
          ))}
        </ul>
      )}
      <NewGoalDialog open={creating} onOpenChange={setCreating} goals={list.data ?? []} />
    </div>
  );
}

function GoalRow({
  goal,
  depth,
  childrenOf,
  peopleById,
}: {
  goal: Goal;
  depth: number;
  childrenOf: (id: string) => Goal[];
  peopleById: Map<string, { name: string; avatar_url?: string | null }>;
}) {
  const [open, setOpen] = useState(true);
  const kids = childrenOf(goal.id);
  const owner = peopleById.get(goal.owner_id);
  return (
    <li>
      <div className="flex items-center gap-3 px-4 py-3" style={{ paddingLeft: 16 + depth * 24 }}>
        {kids.length ? (
          <button
            type="button"
            aria-expanded={open}
            aria-label={open ? `Hide sub-goals of ${goal.name}` : `Show sub-goals of ${goal.name}`}
            onClick={() => setOpen((v) => !v)}
            className="rounded text-muted hover:text-ink"
          >
            <Icon icon={open ? ChevronDown : ChevronRight} size={15} />
          </button>
        ) : (
          <Icon icon={Target} size={15} className="text-muted-2" />
        )}
        <Link to={`/goals/${goal.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">
          {goal.name}
        </Link>
        <span className="hidden text-xs text-muted sm:inline">
          {goal.period_label ?? `${goal.period_start} – ${goal.period_end}`}
        </span>
        {owner ? <Avatar name={owner.name} src={owner.avatar_url ?? null} size={22} /> : null}
        <span className="hidden w-24 text-xs text-muted-2 md:inline">
          {SOURCE_LABEL[goal.progress_source]}
        </span>
        <GoalProgress value={goal.progress} className="w-40" />
        <span className="w-20">{goal.status ? <StatusChip status={goal.status as Status} /> : null}</span>
      </div>
      {open && kids.length ? (
        <ul className="divide-y divide-hair-soft border-t border-hair-soft">
          {kids.map((k) => (
            <GoalRow key={k.id} goal={k} depth={depth + 1} childrenOf={childrenOf} peopleById={peopleById} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function NewGoalDialog({
  open,
  onOpenChange,
  goals,
  parent,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  goals: Goal[];
  parent?: Goal;
}) {
  const create = useCreateGoal();
  const navigate = useNavigate();
  const qs = useMemo(() => quarters(), []);
  const [name, setName] = useState('');
  const [quarter, setQuarter] = useState(1);
  const [source, setSource] = useState<GoalIn['progress_source']>('manual');
  const [start, setStart] = useState('0');
  const [target, setTarget] = useState('');
  const [unit, setUnit] = useState('');
  const [parentId, setParentId] = useState<string>(parent?.id ?? '');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = qs[quarter]!;
    const metric =
      source === 'manual' && target.trim()
        ? {
            type: 'number' as const,
            start: Number(start) || 0,
            target: Number(target),
            current: Number(start) || 0,
            unit: unit.trim() || null,
          }
        : null;
    create.mutate(
      {
        name: name.trim(),
        period_start: parent?.period_start ?? q.start,
        period_end: parent?.period_end ?? q.end,
        period_label: parent?.period_label ?? q.label,
        progress_source: source,
        metric,
        parent_id: parentId || null,
      },
      {
        onSuccess: (res) => {
          onOpenChange(false);
          setName('');
          setTarget('');
          if (!parent) navigate(`/goals/${res.data.id}`);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={parent ? `New sub-goal of ${parent.name}` : 'New goal'}
    >
      <form onSubmit={submit} className="space-y-4 px-5 py-4" aria-label="New goal">
        <label className="block text-sm" htmlFor="goal-name">
          <span className="mb-1 block text-muted">Goal</span>
          <Input
            id="goal-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Grow paying customers to 200"
          />
        </label>
        {!parent ? (
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Quarter</span>
            <select
              value={quarter}
              onChange={(e) => setQuarter(Number(e.target.value))}
              className="w-full rounded-md border border-hairline bg-surface px-2 py-1.5"
            >
              {qs.map((q, i) => (
                <option key={q.label} value={i}>
                  {q.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <fieldset className="text-sm">
          <legend className="mb-1 text-muted">Progress comes from</legend>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(SOURCE_LABEL) as (keyof typeof SOURCE_LABEL)[]).map((k) => (
              <label
                key={k}
                className={cn(
                  'flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1',
                  source === k ? 'border-accent bg-accent-tint' : 'border-hairline',
                )}
              >
                <input
                  type="radio"
                  name="source"
                  value={k}
                  checked={source === k}
                  onChange={() => setSource(k)}
                  className="sr-only"
                />
                {SOURCE_LABEL[k]}
              </label>
            ))}
          </div>
        </fieldset>
        {source === 'manual' ? (
          <div className="grid grid-cols-3 gap-2 text-sm">
            <label htmlFor="goal-start">
              <span className="mb-1 block text-muted">From</span>
              <Input
                id="goal-start"
                inputMode="decimal"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label htmlFor="goal-target">
              <span className="mb-1 block text-muted">Target</span>
              <Input
                id="goal-target"
                inputMode="decimal"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="200"
              />
            </label>
            <label htmlFor="goal-unit">
              <span className="mb-1 block text-muted">Unit</span>
              <Input
                id="goal-unit"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                placeholder="customers"
              />
            </label>
          </div>
        ) : null}
        {!parent && goals.length ? (
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Part of (optional)</span>
            <select
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
              className="w-full rounded-md border border-hairline bg-surface px-2 py-1.5"
            >
              <option value="">— A top-level goal —</option>
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="text" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>
            Create goal
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
