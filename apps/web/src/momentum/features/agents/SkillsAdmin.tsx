import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Lightbulb } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { Skeleton } from '@/components/ui/Skeleton';
import { Segmented } from '@/components/ui/Tabs';
import type { components } from '@/lib/api/schema';
import { toastError } from '@/lib/toast';
import { useApi } from '@/providers/api';

export type Skill = components['schemas']['SkillOut'];

export interface SkillFilters {
  pack_key?: string;
  status?: string;
  scope_type?: string;
  scope_id?: string;
}

export function useSkills(f: SkillFilters, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['skills', f],
    enabled,
    queryFn: async () =>
      (
        await api.GET('/api/v1/skills', {
          params: {
            query: {
              pack_key: f.pack_key,
              status: f.status,
              scope_type: f.scope_type,
              scope_id: f.scope_id,
            },
          },
        })
      ).data!.data,
  });
}

type Decision = 'approve' | 'reject' | 'retire';

function useDecide() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      decision,
      note,
      content,
    }: {
      id: string;
      decision: Decision;
      note?: string;
      content?: Record<string, unknown>;
    }) => {
      const params = {
        params: { path: { skill_id: id } },
        body: { note: note ?? null, content: content ?? null },
      };
      const r =
        decision === 'approve'
          ? await api.POST('/api/v1/skills/{skill_id}/approve', params)
          : decision === 'reject'
            ? await api.POST('/api/v1/skills/{skill_id}/reject', params)
            : await api.POST('/api/v1/skills/{skill_id}/retire', params);
      return r.data!;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['skills'] }),
    onError: (e) => toastError(e, "Couldn't decide on the skill"),
  });
}

/** A skill's content in words: a hint's text, a rule's settings, a field map, an example. */
export function skillText(s: Pick<Skill, 'kind' | 'content'>): string {
  const c = s.content as Record<string, unknown>;
  if (s.kind === 'hint') return String(c.text ?? '');
  if (s.kind === 'field_map') return `“${String(c.label)}” fills ${String(c.field)}`;
  if (s.kind === 'example') return `Example: ${JSON.stringify(c.input)} → ${JSON.stringify(c.output)}`;
  return Object.entries(c)
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`)
    .join(' · ');
}

const KINDS = ['hint', 'rule', 'field_map', 'example'];

/**
 * Skills admin (agent page → Skills; Phase 7.6 S76-08, spec §12.6): the proposed queue (what was
 * learned, from where, the tryout's before/after and regressions; approve, edit and approve,
 * reject) and the active list (helped / hurt, the "may be hurting" flag, retire). Members see the
 * lists; workspace admins and the pack's stewards decide (the server checks).
 */
export function SkillsAdmin({ packKey }: { packKey: string }) {
  const [tab, setTab] = useState<'proposed' | 'active' | 'history'>('proposed');
  const [kind, setKind] = useState('');
  const [scope, setScope] = useState('');
  const [field, setField] = useState('');
  const status = tab === 'history' ? undefined : tab;
  const skills = useSkills({ pack_key: packKey, status, scope_type: scope || undefined });
  const rows = (skills.data ?? [])
    .filter((s) => (tab === 'history' ? !['proposed', 'active'].includes(s.status) : true))
    .filter((s) => !kind || s.kind === kind)
    .filter((s) => !field || (s.field ?? '').includes(field));
  const select = 'rounded-md border border-hairline bg-surface px-2 py-1 text-sm text-ink';
  return (
    <section aria-label="Skills" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="Skills"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'proposed', label: 'Proposed' },
            { value: 'active', label: 'Active' },
            { value: 'history', label: 'History' },
          ]}
        />
        <span className="flex-1" />
        <label className="flex items-center gap-1 text-xs text-muted">
          Scope
          <select className={select} value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="">Any</option>
            <option value="workspace">Everywhere</option>
            <option value="entity">One vendor</option>
            <option value="project">One project</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Kind
          <select className={select} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Any</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k.replace('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Field
          <input className={`${select} w-28`} value={field} onChange={(e) => setField(e.target.value)} />
        </label>
      </div>
      {skills.isPending ? (
        <Skeleton className="h-32" />
      ) : skills.isError ? (
        <ErrorState error={skills.error} onRetry={() => void skills.refetch()} />
      ) : rows.length ? (
        <ul className="flex flex-col gap-2">
          {rows.map((s) => (
            <SkillCard key={s.id} skill={s} />
          ))}
        </ul>
      ) : (
        <EmptyState icon={Lightbulb} title={tab === 'proposed' ? 'Nothing to review' : 'No skills here'}>
          {tab === 'proposed'
            ? 'When people correct the agent, it proposes what it learned here for a steward to check.'
            : 'Nothing matches these filters.'}
        </EmptyState>
      )}
    </section>
  );
}

function SkillCard({ skill: s }: { skill: Skill }) {
  const decide = useDecide();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(String((s.content as { text?: string }).text ?? ''));
  const m = s.metrics as { uses?: number; helped?: number; hurt?: number };
  const prov = s.provenance as { record_id?: string; task_id?: string; ops_summary?: string };
  const t = s.tryout as {
    status?: string;
    before?: Record<string, number>;
    after?: Record<string, number>;
    regressions?: unknown[];
  } | null;
  const act = (decision: Decision, content?: Record<string, unknown>) =>
    decide.mutate(
      { id: s.id, decision, content },
      {
        onSuccess: () =>
          toast.success(decision === 'approve' ? 'Approved' : decision === 'reject' ? 'Rejected' : 'Retired'),
      },
    );
  return (
    <li className="rounded-lg border border-hairline p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="rounded bg-amber-2 px-1.5 py-0.5 text-amber-ink">✦ {s.kind.replace('_', ' ')}</span>
        <span>
          {s.scope_type === 'workspace'
            ? 'Everywhere'
            : s.scope_type === 'entity'
              ? 'One vendor'
              : 'One project'}
        </span>
        {s.field ? <span className="font-mono">{s.field}</span> : null}
        <span>
          {s.source === 'learned'
            ? 'Learned from a correction'
            : s.source === 'starter'
              ? 'Starter'
              : 'Written by a person'}
        </span>
        {s.version > 1 ? <span>v{s.version}</span> : null}
      </div>
      {editing && s.kind === 'hint' ? (
        <textarea
          aria-label="Skill text"
          rows={2}
          className="mt-1 w-full rounded-md border border-hairline bg-surface p-2 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : (
        <p className="mt-1">{skillText(s)}</p>
      )}
      {prov.ops_summary || prov.record_id || prov.task_id ? (
        <p className="mt-1 text-xs text-muted">
          {prov.ops_summary ? `From: ${prov.ops_summary}` : 'From a correction'}
          {prov.record_id ? (
            <>
              {' · '}
              <Link to={`/records/${prov.record_id}`} className="text-accent underline">
                the record
              </Link>
            </>
          ) : null}
          {prov.task_id ? (
            <>
              {' · '}
              <Link to={`/task/${prov.task_id}`} className="text-accent underline">
                the task
              </Link>
            </>
          ) : null}
        </p>
      ) : null}
      {s.status === 'proposed' ? (
        <p aria-label="Tryout" className="mt-1 text-xs">
          {t?.status === 'done' ? (
            <>
              Tried on past records:{' '}
              {Object.entries(t.before ?? {})
                .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v} → ${t.after?.[k] ?? '?'}`)
                .join(', ') || 'no change'}
              {t.regressions?.length ? (
                <span className="text-crit"> · {t.regressions.length} got worse</span>
              ) : (
                <span className="text-ok"> · nothing got worse</span>
              )}
            </>
          ) : (
            <span className="text-muted">Not tried out yet.</span>
          )}
        </p>
      ) : null}
      {s.status === 'active' ? (
        <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
          Used {m.uses ?? 0} times · helped {m.helped ?? 0} · hurt {m.hurt ?? 0}
          {s.may_be_hurting ? (
            <span className="inline-flex items-center gap-1 font-medium text-warn">
              <Icon icon={AlertTriangle} size={12} /> May be hurting
            </span>
          ) : null}
        </p>
      ) : null}
      {s.decision_note ? <p className="mt-1 text-xs text-muted">“{s.decision_note}”</p> : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {s.status === 'proposed' ? (
          editing ? (
            <>
              <Button
                size="sm"
                variant="primary"
                disabled={!text.trim() || decide.isPending}
                onClick={() => act('approve', { text })}
              >
                Approve edited
              </Button>
              <Button size="sm" variant="text" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="primary" disabled={decide.isPending} onClick={() => act('approve')}>
                Approve
              </Button>
              {s.kind === 'hint' ? (
                <Button size="sm" disabled={decide.isPending} onClick={() => setEditing(true)}>
                  Edit and approve
                </Button>
              ) : null}
              <Button size="sm" variant="text" disabled={decide.isPending} onClick={() => act('reject')}>
                Reject
              </Button>
            </>
          )
        ) : s.status === 'active' ? (
          <Button size="sm" variant="text" disabled={decide.isPending} onClick={() => act('retire')}>
            Retire
          </Button>
        ) : (
          <span className="text-xs text-muted">{s.status}</span>
        )}
      </div>
    </li>
  );
}
