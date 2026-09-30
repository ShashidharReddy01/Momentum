import { useQueryClient } from '@tanstack/react-query';
import { Briefcase, FolderKanban, Link2, Plus, Target, X } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';
import { AICallout, AIBadge } from '@/components/common/AI';
import { MoMark } from '@/components/common/MoMark';
import { ErrorState } from '@/components/common/States';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover';
import { Skeleton } from '@/components/ui/Skeleton';
import { usePeople } from '@/features/people';
import { usePortfolios } from '@/features/portfolios';
import { useProjects } from '@/features/projects';
import { StatusChip, STATUS_LABEL, type Status } from '@/features/status';
import { useMomentumConfig } from '@/lib/config';
import { formatRelative } from '@/lib/dates';
import { useChannel } from '@/lib/realtime';
import { GoalProgress, NewGoalDialog } from './GoalsPage';
import {
  goalKeys,
  useGoal,
  useGoalAi,
  useGoalCheckIns,
  useGoalMutations,
  useGoals,
  type GoalDetail,
  type GoalSuggestion,
} from './queries';

const SOURCE_TEXT = {
  manual: 'Measured by its metric, moved at each check-in',
  projects: 'Measured by the completion of the linked projects and portfolios you can see',
  subgoals: 'Measured by the average of its sub-goals',
} as const;

const num = (n: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(n);

/** One goal (S6.3.1): progress and how it's measured, the work linked to it, its sub-goals and
 * its check-ins. Owners and admins edit; everyone else reads. */
export function GoalPage() {
  const { goalId = '' } = useParams();
  const qc = useQueryClient();
  const q = useGoal(goalId);
  useChannel(`goal:${goalId}`, () => void qc.invalidateQueries({ queryKey: goalKeys.detail(goalId) }));
  if (q.isPending) return <Skeleton className="m-8 h-64" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <GoalBody g={q.data} />;
}

function Ring({ value }: { value: number | null | undefined }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden className="-rotate-90">
        <circle cx="48" cy="48" r={r} fill="none" stroke="var(--hair-soft)" strokeWidth="8" />
        {value !== null && value !== undefined ? (
          <circle
            cx="48"
            cy="48"
            r={r}
            fill="none"
            stroke="var(--ok)"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${c * value} ${c}`}
          />
        ) : null}
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-lg font-semibold tabular-nums">
        {value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`}
      </span>
    </div>
  );
}

function GoalBody({ g }: { g: GoalDetail }) {
  const people = usePeople('', 'all').data;
  const owner = useMemo(() => (people ?? []).find((u) => u.id === g.owner_id), [people, g.owner_id]);
  const all = useGoals().data ?? [];
  const m = useGoalMutations(g.id);
  const [addingSub, setAddingSub] = useState(false);
  const [suggestions, setSuggestions] = useState<GoalSuggestion[] | null>(null);
  const metric = g.metric;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-start gap-6 rounded-xl border border-hairline bg-surface p-5">
        <Ring value={g.progress} />
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Icon icon={Target} size={18} className="text-muted" />
            <span className="truncate">{g.name}</span>
            {g.status ? <StatusChip status={g.status as Status} /> : null}
          </h1>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
            <span>{g.period_label ?? `${g.period_start} – ${g.period_end}`}</span>
            {owner ? (
              <span className="inline-flex items-center gap-1.5">
                <Avatar name={owner.name} src={owner.avatar_url} size={18} /> {owner.name}
              </span>
            ) : null}
          </p>
          <p className="text-sm text-muted">{SOURCE_TEXT[g.progress_source]}.</p>
          {metric ? (
            <p className="text-sm">
              <span className="text-2xl font-semibold tabular-nums">
                {metric.current === null || metric.current === undefined ? '—' : num(metric.current)}
              </span>
              <span className="text-muted">
                {' '}
                of {num(metric.target)} {metric.unit ?? ''} · started at {num(metric.start ?? 0)}
              </span>
            </p>
          ) : null}
          {g.description ? <p className="pt-1 text-sm">{g.description}</p> : null}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="links-h" className="rounded-xl border border-hairline bg-surface p-5">
          <div className="mb-3 flex items-center gap-2">
            <h2 id="links-h" className="flex flex-1 items-center gap-2 text-[15px] font-semibold">
              <Icon icon={Link2} size={15} /> Linked work
            </h2>
            {g.can_edit ? <SuggestButton g={g} onFound={setSuggestions} /> : null}
            {g.can_edit ? <AddLink g={g} onLink={(v) => m.link.mutate(v)} /> : null}
          </div>
          {suggestions ? (
            <AICallout
              label="Mo suggests"
              className="mb-3"
              actions={
                <Button size="sm" variant="text" onClick={() => setSuggestions(null)}>
                  Dismiss
                </Button>
              }
            >
              {suggestions.length === 0 ? (
                <p className="text-sm">No projects you can see look related yet.</p>
              ) : (
                <ul aria-label="Suggested projects" className="space-y-2">
                  {suggestions.map((sug) => (
                    <li key={sug.id} className="flex items-start gap-2 text-sm">
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{sug.name}</p>
                        <p className="truncate text-xs text-amber-ink">{sug.reason}</p>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          m.link.mutate({ entity_type: 'project', entity_id: sug.id });
                          setSuggestions((cur) => (cur ?? []).filter((x) => x.id !== sug.id));
                        }}
                      >
                        Link
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </AICallout>
          ) : null}
          {g.links.length === 0 ? (
            <p className="text-sm text-muted-2">
              {g.progress_source === 'projects'
                ? 'Link the projects or portfolios that move this goal; their completion becomes its progress.'
                : 'Nothing linked.'}
            </p>
          ) : (
            <ul className="space-y-2">
              {g.links.map((l) => (
                <li key={`${l.entity_type}:${l.id}`} className="flex items-center gap-2 text-sm">
                  <Icon
                    icon={l.entity_type === 'project' ? FolderKanban : Briefcase}
                    size={14}
                    className="text-muted"
                  />
                  <Link
                    to={l.entity_type === 'project' ? `/projects/${l.id}/overview` : `/portfolios/${l.id}`}
                    className="min-w-0 flex-1 truncate hover:underline"
                  >
                    {l.name}
                  </Link>
                  <GoalProgress value={l.progress} />
                  {g.can_edit ? (
                    <IconButton
                      icon={X}
                      size="icon-sm"
                      label={`Unlink ${l.name}`}
                      onClick={() => m.unlink.mutate({ entity_type: l.entity_type, entity_id: l.id })}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {g.hidden_links ? (
            <p className="mt-2 text-xs text-muted">
              {g.hidden_links} linked {g.hidden_links === 1 ? 'project is' : 'projects are'} in projects you
              can’t see and not counted in your view.
            </p>
          ) : null}
        </section>

        <section aria-labelledby="subs-h" className="rounded-xl border border-hairline bg-surface p-5">
          <div className="mb-3 flex items-center gap-2">
            <h2 id="subs-h" className="flex flex-1 items-center gap-2 text-[15px] font-semibold">
              <Icon icon={Target} size={15} /> Sub-goals
            </h2>
            {g.can_edit ? (
              <Button size="sm" variant="ghost" onClick={() => setAddingSub(true)}>
                <Icon icon={Plus} size={14} /> Add
              </Button>
            ) : null}
          </div>
          {g.children.length === 0 ? (
            <p className="text-sm text-muted-2">No sub-goals.</p>
          ) : (
            <ul className="space-y-2">
              {g.children.map((c) => (
                <li key={c.id} className="flex items-center gap-2 text-sm">
                  <Link to={`/goals/${c.id}`} className="min-w-0 flex-1 truncate hover:underline">
                    {c.name}
                  </Link>
                  <GoalProgress value={c.progress} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <CheckIns g={g} />
      <NewGoalDialog open={addingSub} onOpenChange={setAddingSub} goals={all} parent={g} />
    </div>
  );
}

function SuggestButton({ g, onFound }: { g: GoalDetail; onFound: (s: GoalSuggestion[]) => void }) {
  const aiEnabled = useMomentumConfig().ai_enabled;
  const ai = useGoalAi(g.id);
  if (!aiEnabled) return null;
  return (
    <Button
      size="sm"
      variant="ai"
      loading={ai.suggest.isPending}
      onClick={() => ai.suggest.mutate(undefined, { onSuccess: onFound })}
    >
      <MoMark size={12} /> Suggest
    </Button>
  );
}

function AddLink({
  g,
  onLink,
}: {
  g: GoalDetail;
  onLink: (v: { entity_type: 'project' | 'portfolio'; entity_id: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const projects = useProjects().data ?? [];
  const portfolios = usePortfolios().data ?? [];
  const linked = new Set(g.links.map((l) => `${l.entity_type}:${l.id}`));
  const match = (name: string) => name.toLowerCase().includes(q.trim().toLowerCase());
  const options = [
    ...portfolios
      .filter((p) => !linked.has(`portfolio:${p.id}`) && match(p.name))
      .map((p) => ({ type: 'portfolio' as const, id: p.id, name: p.name })),
    ...projects
      .filter((p) => !linked.has(`project:${p.id}`) && match(p.name))
      .map((p) => ({ type: 'project' as const, id: p.id, name: p.name })),
  ].slice(0, 14);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="ghost">
          <Icon icon={Plus} size={14} /> Link
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-2">
        <Input
          aria-label="Find a project or portfolio"
          placeholder="Find a project or portfolio…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ul className="mt-2 max-h-64 overflow-auto">
          {options.map((o) => (
            <li key={`${o.type}:${o.id}`}>
              <button
                type="button"
                onClick={() => {
                  onLink({ entity_type: o.type, entity_id: o.id });
                  setOpen(false);
                  setQ('');
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-surface-2"
              >
                <Icon
                  icon={o.type === 'project' ? FolderKanban : Briefcase}
                  size={14}
                  className="text-muted"
                />
                <span className="truncate">{o.name}</span>
              </button>
            </li>
          ))}
          {options.length === 0 ? (
            <li className="px-2 py-1.5 text-sm text-muted-2">Nothing more to link</li>
          ) : null}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function CheckIns({ g }: { g: GoalDetail }) {
  const m = useGoalMutations(g.id);
  const history = useGoalCheckIns(g.id);
  const ai = useGoalAi(g.id);
  const aiEnabled = useMomentumConfig().ai_enabled;
  const [open, setOpen] = useState(false);
  const [drafted, setDrafted] = useState<null | 'ai' | 'plain'>(null);
  const [status, setStatus] = useState<Status>((g.status as Status | null) ?? 'on_track');
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [current, setCurrent] = useState('');
  const askMo = () =>
    ai.draft.mutate(undefined, {
      onSuccess: (r) => {
        setStatus(r.draft.status);
        setTitle(r.draft.title);
        setSummary(r.draft.summary);
        setDrafted(r.ai ? 'ai' : 'plain');
        setOpen(true);
      },
    });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.checkIn.mutate(
      {
        status,
        title: title.trim(),
        summary: summary.trim(),
        current: g.metric && current.trim() ? Number(current) : null,
        generated_by_ai: drafted === 'ai',
      },
      {
        onSuccess: () => {
          setOpen(false);
          setTitle('');
          setSummary('');
          setCurrent('');
          setDrafted(null);
        },
      },
    );
  };
  return (
    <section aria-labelledby="checkins-h" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="checkins-h" className="flex-1 text-[15px] font-semibold">
          Check-ins
        </h2>
        {g.can_edit && !open && aiEnabled ? (
          <Button size="sm" variant="ai" loading={ai.draft.isPending} onClick={askMo}>
            <MoMark size={12} /> Draft with Mo
          </Button>
        ) : null}
        {g.can_edit && !open ? (
          <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
            Check in
          </Button>
        ) : null}
      </div>
      {open ? (
        <form
          onSubmit={submit}
          aria-label="New check-in"
          className="space-y-3 rounded-xl border border-hairline bg-surface p-4"
        >
          {drafted === 'ai' ? (
            <p className="flex items-center gap-2 text-xs text-amber-ink">
              <AIBadge /> Drafted by Mo from this goal’s numbers and linked work. Check it before posting.
            </p>
          ) : drafted === 'plain' ? (
            <p className="text-xs text-muted">
              A plain draft from the goal’s numbers (Mo’s draft used a figure that isn’t in them, so it was
              set aside).
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="Status"
              value={status}
              onChange={(e) => setStatus(e.target.value as Status)}
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm"
            >
              {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]}
                </option>
              ))}
            </select>
            <Input
              aria-label="Headline"
              placeholder="What changed?"
              className="min-w-64 flex-1"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            {g.metric ? (
              <Input
                aria-label="Current value"
                inputMode="decimal"
                placeholder={`Now (${g.metric.unit ?? 'value'})`}
                className="w-36"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            ) : null}
          </div>
          <textarea
            aria-label="Notes"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Notes (optional)"
            className="min-h-16 w-full rounded-md border border-hairline bg-surface p-2 text-sm"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="text" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={m.checkIn.isPending} disabled={!title.trim()}>
              Post check-in
            </Button>
          </div>
        </form>
      ) : null}
      {history.data?.length === 0 && !open ? <p className="text-sm text-muted-2">No check-ins yet.</p> : null}
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
