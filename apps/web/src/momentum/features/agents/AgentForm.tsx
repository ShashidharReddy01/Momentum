import { describeCron } from './cron';
import { Plus, X } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { MoMark } from '@/components/common/MoMark';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { errorText } from '@/features/ai';
import { useMe } from '@/features/auth';
import {
  useAgent,
  useAgentTools,
  useCreateAgent,
  useDraftAgent,
  useUpdateAgent,
  type Agent,
  type AgentDraft,
} from './queries';

type Simple = 'assigned' | 'mentioned' | 'manual';
type Alias = 'fast' | 'default' | 'smart';
/** A schedule keeps its timezone and per-person time (`at`) through an edit (Pulse's is
 * "each person's own time"); new ones run in workspace time. */
interface Schedule {
  cron: string;
  timezone: string;
  at?: string | null;
}

/** What the form edits: the parts of a definition a person writes. Autonomy beyond the first
 * choice, budgets and on/off live in the admin panel on the agent's page (S5.1.4). */
export interface AgentFormValues {
  name: string;
  description: string;
  instructions: string;
  simple: Simple[];
  schedules: Schedule[];
  events: string[];
  tools: string[];
  autonomy: 'suggest' | 'confirm';
  model_alias: Alias;
}

// events an agent can listen to (the same list the server offers Mo when drafting)
export const AGENT_EVENTS = [
  'task.created',
  'task.updated',
  'task.completed',
  'task.assigned',
  'task.moved',
  'task.tagged',
  'task.due_approaching',
  'task.unblocked',
  'comment.created',
  'project.created',
  'status_update.created',
  'approval.decided',
];

const SIMPLE: { value: Simple; label: string }[] = [
  { value: 'assigned', label: 'When a task is assigned to it' },
  { value: 'mentioned', label: 'When @mentioned in a comment' },
  { value: 'manual', label: '“Run now” by hand' },
];

const EMPTY: AgentFormValues = {
  name: '',
  description: '',
  instructions: '',
  simple: ['assigned', 'mentioned'],
  schedules: [],
  events: [],
  tools: ['get_task', 'search_tasks'],
  autonomy: 'confirm',
  model_alias: 'default',
};

type Triggers = Agent['triggers'];

export function fromTriggers(triggers: Triggers) {
  const simple: Simple[] = [];
  const schedules: Schedule[] = [];
  const events: string[] = [];
  for (const t of triggers) {
    const type = String(t.type);
    if (type === 'schedule')
      schedules.push({
        cron: String(t.cron ?? ''),
        timezone: String(t.timezone ?? 'workspace'),
        at: t.at ? String(t.at) : null,
      });
    else if (type === 'event') events.push(String(t.event ?? ''));
    else if (type === 'assigned' || type === 'mentioned' || type === 'manual') simple.push(type);
  }
  return { simple, schedules, events };
}

export function toTriggers(v: AgentFormValues) {
  return [
    ...v.simple.map((type) => ({ type })),
    ...v.schedules
      .filter((sc) => sc.cron.trim())
      .map((sc) => ({
        type: 'schedule' as const,
        cron: sc.cron.trim(),
        timezone: sc.timezone,
        ...(sc.at ? { at: sc.at as 'digest_time' } : {}),
      })),
    ...v.events.filter(Boolean).map((event) => ({ type: 'event' as const, event })),
  ];
}

function fromDraft(d: AgentDraft): AgentFormValues {
  const a = d.agent;
  return {
    name: a.name,
    description: a.description ?? '',
    instructions: a.instructions ?? '',
    ...fromTriggers((a.triggers ?? []) as Triggers),
    tools: a.tools ?? [],
    autonomy: a.autonomy === 'suggest' ? 'suggest' : 'confirm',
    model_alias: a.model_alias ?? 'default',
  };
}

/** `/agents/new`: create an agent by hand, or describe it and let Mo draft it first. */
export function NewAgentPage() {
  const navigate = useNavigate();
  const create = useCreateAgent();
  return (
    <AgentFormShell title="Create agent">
      <AgentForm
        initial={EMPTY}
        withDraft
        saving={create.isPending}
        submitLabel="Create agent"
        onSubmit={(v) =>
          create.mutate(
            {
              name: v.name.trim(),
              description: v.description.trim(),
              instructions: v.instructions.trim(),
              triggers: toTriggers(v),
              tools: v.tools,
              autonomy: v.autonomy,
              model_alias: v.model_alias,
              avatar: 'teammate',
              kind: 'llm',
              budget_monthly_usd: '5',
              budget_monthly_tokens: 2_000_000,
            },
            { onSuccess: (res) => void navigate(`/agents/${res.data.id}`) },
          )
        }
      />
    </AgentFormShell>
  );
}

/** `/agents/:agentId/edit`: change what an agent is told, when it wakes and what it can use. */
export function EditAgentPage() {
  const { agentId } = useParams();
  const agent = useAgent(agentId!);
  const update = useUpdateAgent(agentId!);
  const navigate = useNavigate();
  if (agent.isPending) return <Skeleton className="mx-auto mt-8 h-64 w-full max-w-3xl" />;
  if (agent.isError) return <ErrorState error={agent.error} onRetry={() => void agent.refetch()} />;
  const a = agent.data;
  const initial: AgentFormValues = {
    name: a.name,
    description: a.description,
    instructions: a.instructions,
    ...fromTriggers(a.triggers),
    tools: a.tools,
    autonomy: a.autonomy === 'suggest' ? 'suggest' : 'confirm',
    model_alias: a.model_alias,
  };
  // handler and pack agents are code: their instructions and tools aren't edited here
  const fromCode = a.kind === 'handler' || a.kind === 'pack';
  return (
    <AgentFormShell title={`Edit ${a.name}`}>
      {a.kind === 'handler' ? (
        <p className="text-sm text-muted">
          {a.name} is code from your app: its instructions and tools live there.
        </p>
      ) : a.kind === 'pack' ? (
        <p className="text-sm text-muted">
          {a.name} comes from an installed pack: what it can do lives in the pack&rsquo;s code.
        </p>
      ) : null}
      <AgentForm
        initial={initial}
        handler={fromCode}
        editing
        saving={update.isPending}
        submitLabel="Save changes"
        onSubmit={(v) =>
          update.mutate(
            {
              name: v.name.trim(),
              description: v.description.trim(),
              triggers: toTriggers(v),
              model_alias: v.model_alias,
              ...(fromCode ? {} : { instructions: v.instructions.trim(), tools: v.tools }),
              expected_version: a.version,
            },
            { onSuccess: () => void navigate(`/agents/${a.id}`) },
          )
        }
      />
    </AgentFormShell>
  );
}

function AgentFormShell({ title, children }: { title: string; children: React.ReactNode }) {
  const isAdmin = useMe().data?.user.role === 'admin';
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-8">
      <h1 className="page-title">{title}</h1>
      {isAdmin ? children : <p className="text-sm text-muted">Only workspace admins can change agents.</p>}
    </div>
  );
}

const field =
  'rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-sm outline-none focus:border-focus';

export function AgentForm({
  initial,
  withDraft = false,
  editing = false,
  handler = false,
  saving,
  submitLabel,
  onSubmit,
}: {
  initial: AgentFormValues;
  withDraft?: boolean;
  editing?: boolean;
  handler?: boolean;
  saving: boolean;
  submitLabel: string;
  onSubmit: (v: AgentFormValues) => void;
}) {
  const [v, setV] = useState<AgentFormValues>(initial);
  const [drafted, setDrafted] = useState<string[] | null>(null);
  const tools = useAgentTools().data ?? [];
  const set = <K extends keyof AgentFormValues>(k: K, value: AgentFormValues[K]) =>
    setV((old) => ({ ...old, [k]: value }));
  const toggle = <T,>(list: T[], item: T) =>
    list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
  const hasTrigger =
    v.simple.length + v.schedules.filter((sc) => sc.cron.trim()).length + v.events.filter(Boolean).length > 0;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (v.name.trim() && hasTrigger) onSubmit(v);
      }}
    >
      {withDraft ? (
        <DescribeAgent
          onDraft={(d) => {
            setV(fromDraft(d));
            setDrafted(d.notes ?? []);
          }}
        />
      ) : null}
      {drafted ? (
        <div className="flex flex-col gap-1 rounded-md border border-dashed border-amber bg-amber-2/40 p-3 text-sm">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-ink">
            <MoMark size={13} /> Mo drafted this — check it before saving.
          </p>
          {drafted.length ? (
            <ul aria-label="Draft notes" className="list-disc pl-5 text-xs text-ink-2">
              {drafted.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <label className="flex flex-col gap-1 text-sm font-medium">
        Name
        <input
          className={field}
          value={v.name}
          maxLength={80}
          required
          onChange={(e) => set('name', e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium">
        Description
        <input
          className={field}
          value={v.description}
          maxLength={500}
          placeholder="One line for the gallery"
          onChange={(e) => set('description', e.target.value)}
        />
      </label>
      {handler ? null : (
        <label className="flex flex-col gap-1 text-sm font-medium">
          Instructions
          <textarea
            className={`${field} min-h-40 font-normal`}
            value={v.instructions}
            maxLength={20_000}
            placeholder="What it should look at, produce and leave alone"
            onChange={(e) => set('instructions', e.target.value)}
          />
        </label>
      )}

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-sm font-medium">Runs</legend>
        {SIMPLE.map((s) => (
          <label key={s.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={v.simple.includes(s.value)}
              onChange={() => set('simple', toggle(v.simple, s.value))}
            />
            {s.label}
          </label>
        ))}
        {v.schedules.map((sc, i) => (
          <span key={`s${i}`} className="flex items-center gap-2 text-sm">
            On a schedule
            <input
              aria-label="Schedule (cron)"
              className={`${field} w-40 font-mono`}
              value={sc.cron}
              placeholder="0 9 * * 1-5"
              onChange={(e) =>
                set(
                  'schedules',
                  v.schedules.map((c, j) => (j === i ? { ...c, cron: e.target.value } : c)),
                )
              }
            />
            {sc.cron.trim() ? <span className="text-xs text-ink-2">{describeCron(sc.cron)},</span> : null}
            <span className="text-xs text-muted">
              {sc.timezone === 'user'
                ? sc.at
                  ? 'each person’s own digest time'
                  : 'each person’s own timezone'
                : sc.timezone === 'workspace'
                  ? 'workspace time'
                  : sc.timezone}
            </span>
            <button
              type="button"
              aria-label="Remove schedule"
              onClick={() =>
                set(
                  'schedules',
                  v.schedules.filter((_, j) => j !== i),
                )
              }
            >
              <X size={14} />
            </button>
          </span>
        ))}
        {v.events.map((ev, i) => (
          <span key={`e${i}`} className="flex items-center gap-2 text-sm">
            When
            <select
              aria-label="Event"
              className={field}
              value={ev}
              onChange={(e) =>
                set(
                  'events',
                  v.events.map((x, j) => (j === i ? e.target.value : x)),
                )
              }
            >
              {AGENT_EVENTS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label="Remove event"
              onClick={() =>
                set(
                  'events',
                  v.events.filter((_, j) => j !== i),
                )
              }
            >
              <X size={14} />
            </button>
          </span>
        ))}
        <span className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="text"
            onClick={() => set('schedules', [...v.schedules, { cron: '0 9 * * 1-5', timezone: 'workspace' }])}
          >
            <Plus size={13} aria-hidden /> Schedule
          </Button>
          <Button
            type="button"
            size="sm"
            variant="text"
            onClick={() => set('events', [...v.events, 'task.created'])}
          >
            <Plus size={13} aria-hidden /> Event
          </Button>
        </span>
        {hasTrigger ? null : <p className="text-xs text-crit">Pick at least one way for it to run.</p>}
      </fieldset>

      {handler ? null : (
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1 text-sm font-medium">Tools</legend>
          <div className="grid gap-1 sm:grid-cols-2">
            {tools.map((t) => (
              <label key={t.name} className="flex items-start gap-2 text-sm" title={t.description}>
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={v.tools.includes(t.name)}
                  onChange={() => set('tools', toggle(v.tools, t.name))}
                />
                <span>
                  <span className="font-mono text-[12.5px]">{t.name}</span>{' '}
                  <span className="text-xs text-muted">
                    {t.risk === 'read' ? 'reads' : `changes · ${t.risk} risk`}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <div className="flex flex-wrap gap-4">
        {editing ? null : (
          <label className="flex flex-col gap-1 text-sm font-medium">
            Autonomy
            <select
              className={field}
              value={v.autonomy}
              onChange={(e) => set('autonomy', e.target.value as 'suggest' | 'confirm')}
            >
              <option value="confirm">Asks before changing</option>
              <option value="suggest">Suggests only</option>
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1 text-sm font-medium">
          Model
          <select
            className={field}
            value={v.model_alias}
            onChange={(e) => set('model_alias', e.target.value as Alias)}
          >
            <option value="fast">Fast</option>
            <option value="default">Default</option>
            <option value="smart">Smart</option>
          </select>
        </label>
      </div>
      <p className="text-xs text-muted">
        {editing
          ? 'On/off, autonomy and budget are on the agent’s page.'
          : 'New agents start switched off, with a $5 monthly budget. Add it to a project and switch it on from its page.'}
      </p>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={saving} disabled={!v.name.trim() || !hasTrigger}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function DescribeAgent({ onDraft }: { onDraft: (d: AgentDraft) => void }) {
  const [text, setText] = useState('');
  const draft = useDraftAgent();
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-hairline bg-surface-2 p-3">
      <label
        htmlFor="describe-agent"
        className="flex items-center gap-1.5 text-sm font-medium text-amber-ink"
      >
        <MoMark size={13} /> Describe what you want
      </label>
      <textarea
        id="describe-agent"
        className={`${field} min-h-16`}
        placeholder="E.g. Every Friday at 3pm, draft a status update for each project I own."
        value={text}
        maxLength={2000}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex items-center justify-end gap-2">
        {draft.isError ? (
          <p role="alert" className="mr-auto text-sm text-crit">
            {errorText(draft.error)}
          </p>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="ai"
          loading={draft.isPending}
          disabled={!text.trim()}
          onClick={() => draft.mutate(text.trim(), { onSuccess: onDraft })}
        >
          <MoMark size={13} /> Draft it
        </Button>
      </div>
    </div>
  );
}
