import { useState } from 'react';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Segmented } from '@/components/ui/Tabs';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { useUndoToast } from '@/lib/undo';
import { SchemaForm, type SettingsSchema } from './SchemaForm';
import { useAgentHealth, useAgentProfile, usePackSettings, useSavePackSettings } from './platform';
import type { Agent } from './queries';
import { DATA_CLASS, duration, money, pct } from './runMeta';

/** Overview tab (spec §12.2): what the agent is for and how to hand it work. */
export function AgentOverview({ agent }: { agent: Agent }) {
  const profile = useAgentProfile(agent.id);
  if (profile.isPending) return <Skeleton className="h-40 w-full" />;
  if (profile.isError) return <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />;
  const p = profile.data;
  const ways = [
    p.can_assign ? `Assign a task to ${agent.name}.` : null,
    p.can_mention ? `@mention ${agent.name} in a comment.` : null,
    p.can_run ? `Use “Run now” on this page (on a task, or with pasted text).` : null,
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-5">
      {p.title || p.data_class ? (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          {p.title ? <span className="font-medium">{p.title}</span> : null}
          {p.data_class ? <DataClassBadge value={p.data_class} /> : null}
          {p.reads_external_content ? (
            <span className="text-xs text-muted">Reads documents from outside the workspace</span>
          ) : null}
        </p>
      ) : null}
      {p.charter ? (
        <section aria-label="Charter">
          <h3 className="section-label mb-1">Charter</h3>
          <p className="whitespace-pre-wrap text-sm text-ink-2">{p.charter}</p>
        </section>
      ) : null}
      {p.capabilities.length ? (
        <section aria-label="Capabilities">
          <h3 className="section-label mb-1">What {agent.name} can do</h3>
          <ul className="flex flex-col gap-2">
            {p.capabilities.map((c) => (
              <li key={c.key} className="text-sm">
                <span className="font-medium">{c.title}</span>
                <span className="text-ink-2"> · {c.description}</span>
                {c.files.length ? (
                  <span className="text-xs text-muted"> · takes {c.files.join(', ')}</span>
                ) : null}
                {c.examples.length ? (
                  <ul className="mt-0.5 flex flex-wrap gap-1.5">
                    {c.examples.map((ex) => (
                      <li key={ex} className="rounded-md bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2">
                        “{ex}”
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {p.effects.length ? (
        <section aria-label="What it may do">
          <h3 className="section-label mb-1">When you hand {agent.name} work, they may…</h3>
          <ul className="list-disc pl-5 text-sm text-ink-2">
            {p.effects.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">
            Nothing else. Everything they do shows ✦ and can be undone.
          </p>
        </section>
      ) : null}
      <section aria-label="What wakes it">
        <h3 className="section-label mb-1">What wakes {agent.name}</h3>
        {p.triggers.length ? (
          <ul className="list-disc pl-5 text-sm text-ink-2">
            {p.triggers.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Nothing yet: it has no triggers.</p>
        )}
      </section>
      <section aria-label="Hand work">
        <h3 className="section-label mb-1">Hand work to {agent.name}</h3>
        {ways.length ? (
          <ul className="list-disc pl-5 text-sm text-ink-2">
            {ways.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{agent.name} works on its own schedule or events.</p>
        )}
        {!agent.enabled ? <p className="mt-1 text-xs text-warn">{agent.name} is off right now.</p> : null}
      </section>
    </div>
  );
}

export function DataClassBadge({ value }: { value: string }) {
  const d = DATA_CLASS[value] ?? { label: value, className: 'border-hairline text-muted' };
  return (
    <span className={cn('rounded-full border px-2 py-0.5 text-[11px] font-medium', d.className)}>
      {d.label}
    </span>
  );
}

/** Health tab (spec §8.8): the numbers for the last 30 or 90 days. */
export function AgentHealthPanel({ agent }: { agent: Agent }) {
  const [days, setDays] = useState<'30' | '90'>('30');
  const health = useAgentHealth(agent.id, Number(days));
  return (
    <div className="flex flex-col gap-4">
      <Segmented
        label="Period"
        value={days}
        onChange={setDays}
        options={[
          { value: '30', label: 'Last 30 days' },
          { value: '90', label: 'Last 90 days' },
        ]}
      />
      {health.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : health.isError ? (
        <ErrorState error={health.error} onRetry={() => void health.refetch()} />
      ) : health.data.jobs === 0 ? (
        <EmptyState title="No jobs yet">
          {agent.name} hasn’t done any work in the last {days} days, so there’s nothing to measure.
        </EmptyState>
      ) : (
        <HealthBody h={health.data} />
      )}
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface p-3" title={hint}>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}

function HealthBody({ h }: { h: NonNullable<ReturnType<typeof useAgentHealth>['data']> }) {
  return (
    <div className="flex flex-col gap-5">
      <div role="list" aria-label="Health numbers" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {(
          [
            ['Jobs', String(h.jobs)],
            ['Items', String(h.items)],
            ['Succeeded', pct(h.success_rate)],
            ['Median working time', duration(h.median_active_seconds)],
            ['Median waiting time', duration(h.median_waiting_seconds)],
            ['Questions per item', h.asks_per_item == null ? '—' : h.asks_per_item.toFixed(2)],
            ['Median time to answer', duration(h.median_answer_seconds)],
            ['Corrected by a person', pct(h.human_touch_rate)],
            ['Approved on its own', pct(h.auto_approved_rate)],
            ['Cost per item', h.cost_per_item_usd == null ? '—' : money(h.cost_per_item_usd)],
            [
              'Time saved (estimate)',
              h.time_saved_minutes == null ? '—' : duration(h.time_saved_minutes * 60),
            ],
          ] as const
        ).map(([label, value]) => (
          <div role="listitem" key={label}>
            <Tile label={label} value={value} />
          </div>
        ))}
      </div>
      {h.skills ? (
        <p className="text-sm text-ink-2">
          Skills: {h.skills.active} active, {h.skills.proposed} waiting for review · helped {h.skills.helped}{' '}
          time{h.skills.helped === 1 ? '' : 's'}, hurt {h.skills.hurt}
        </p>
      ) : null}
      {h.detail ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <section aria-label="Most corrected fields">
            <h3 className="section-label mb-1">Most corrected fields</h3>
            <CountList rows={h.top_corrected_fields ?? []} empty="No corrections." />
          </section>
          <section aria-label="Top failure reasons">
            <h3 className="section-label mb-1">Why jobs failed</h3>
            <CountList rows={h.top_failure_reasons ?? []} empty="No failures." />
          </section>
          <section aria-label="Calibration" className="sm:col-span-2">
            <h3 className="section-label mb-1">Calibration</h3>
            {h.calibration?.note ? (
              <p className="text-sm text-muted">
                {h.calibration.note} ({h.calibration.reviewed} reviewed).
              </p>
            ) : (
              <table className="text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="pr-4 font-normal">Confidence</th>
                    <th className="pr-4 font-normal">Items</th>
                    <th className="pr-4 font-normal">Predicted</th>
                    <th className="font-normal">Right first time</th>
                  </tr>
                </thead>
                <tbody>
                  {(h.calibration?.bands ?? []).map((b) => (
                    <tr key={b.band}>
                      <td className="pr-4 font-mono text-xs">{b.band}</td>
                      <td className="pr-4 tabular-nums">{b.items}</td>
                      <td className="pr-4 tabular-nums">{pct(b.predicted)}</td>
                      <td className="tabular-nums">{pct(b.actual)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function CountList({ rows, empty }: { rows: readonly (readonly (string | number)[])[]; empty: string }) {
  if (!rows.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="text-sm">
      {rows.map(([name, n]) => (
        <li key={String(name)} className="flex justify-between gap-3">
          <span className="truncate">{String(name)}</span>
          <span className="tabular-nums text-muted">{String(n)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Settings tab (spec §8.3, §12.2): the pack's settings form for the workspace and for each
 * project the agent works in; every save can be undone. */
export function PackSettingsPanel({ agent }: { agent: Agent }) {
  const [projectId, setProjectId] = useState<string | null>(null);
  const projects = agent.projects ?? [];
  return (
    <div className="flex flex-col gap-4">
      {projects.length ? (
        <Segmented
          label="Settings for"
          value={projectId ?? ''}
          onChange={(v) => setProjectId(v || null)}
          options={[
            { value: '', label: 'Workspace' },
            ...projects.map((p) => ({ value: p.id, label: p.name })),
          ]}
        />
      ) : null}
      <LevelForm key={projectId ?? 'ws'} agent={agent} projectId={projectId} />
    </div>
  );
}

function LevelForm({ agent, projectId }: { agent: Agent; projectId: string | null }) {
  const settings = usePackSettings(agent.id, projectId);
  const save = useSavePackSettings(agent.id, projectId);
  const undoToast = useUndoToast();
  if (settings.isPending) return <Skeleton className="h-40 w-full" />;
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  const s = settings.data;
  const own = (projectId ? s.project : s.workspace) ?? {};
  return (
    <>
      {!s.can_edit ? (
        <p className="text-xs text-muted">
          {projectId
            ? 'Only this project’s admins can change these.'
            : `Only workspace admins and ${agent.name}’s stewards can change these.`}
        </p>
      ) : null}
      <SchemaForm
        key={JSON.stringify(own)}
        schema={s.form as SettingsSchema}
        own={own}
        effective={s.effective}
        canEdit={s.can_edit}
        saving={save.isPending}
        inheritLabel={projectId ? 'the workspace value' : 'the default'}
        onSave={(values) =>
          save.mutate(values, {
            onSuccess: (r) => undoToast('Settings saved', { activity_id: r.activity_id }),
          })
        }
      />
    </>
  );
}
