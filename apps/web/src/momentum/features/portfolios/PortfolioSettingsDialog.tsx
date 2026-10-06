import { Plus, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { Segmented, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { FieldValueEditor, useProjectFieldDefs, type Field } from '@/features/fields';
import { usePeople } from '@/features/people';
import { useTeams } from '@/features/teams';
import { useTemplates } from '@/features/templates';
import type { PortfolioDetail } from './queries';
import {
  useMemberMutations,
  usePortfolioMembers,
  usePortfolioSettings,
  type PortfolioRule,
} from './v2queries';

const selectClass =
  'h-8 rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none focus:ring-2 focus:ring-focus/25';
type Condition = NonNullable<PortfolioRule['project_field_conditions']>[number];
type Gate = { required_fields: string[]; required_milestones: string[]; required_files: string[] };
const OPS: { op: Condition['op']; label: string; needsValue: boolean }[] = [
  { op: 'is', label: 'is', needsValue: true },
  { op: 'is_not', label: 'is not', needsValue: true },
  { op: 'any', label: 'is any of', needsValue: true },
  { op: 'set', label: 'is set', needsValue: false },
  { op: 'empty', label: 'is empty', needsValue: false },
];
const list = (text: string) =>
  text
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

/**
 * Portfolio settings (spec §5.2, §5.5, §5.6; editors): how projects are picked (by hand, or a
 * rule: templates, teams, project field conditions), the stage field with a target and a gate
 * per stage, and members (the owner and admins manage those). Each save is one undoable change.
 */
export function PortfolioSettingsDialog({
  p,
  open,
  onOpenChange,
}: {
  p: PortfolioDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const manageMembers = p.my_role === 'owner' || p.my_role === 'admin';
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Portfolio settings"
      className="w-[min(720px,calc(100vw-32px))]"
    >
      <Tabs defaultValue="projects" className="p-5">
        <TabsList aria-label="Settings sections">
          <TabsTrigger value="projects">Projects</TabsTrigger>
          <TabsTrigger value="stages">Stages and gates</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
        </TabsList>
        <TabsContent value="projects" className="pt-4">
          <ProjectsSection p={p} />
        </TabsContent>
        <TabsContent value="stages" className="pt-4">
          <StagesSection p={p} />
        </TabsContent>
        <TabsContent value="members" className="pt-4">
          <MembersSection p={p} canManage={manageMembers} />
        </TabsContent>
      </Tabs>
    </Dialog>
  );
}

function ProjectsSection({ p }: { p: PortfolioDetail }) {
  const { configure, convert } = usePortfolioSettings(p.id);
  const templates = useTemplates('project');
  const teams = useTeams();
  const defs = useProjectFieldDefs();
  const initial = (p.rule ?? {}) as Partial<PortfolioRule>;
  const [templateIds, setTemplateIds] = useState<string[]>(initial.template_ids ?? []);
  const [teamIds, setTeamIds] = useState<string[]>(initial.team_ids ?? []);
  const [conditions, setConditions] = useState<Condition[]>(initial.project_field_conditions ?? []);
  const [includeCompleted, setIncludeCompleted] = useState(initial.include_completed ?? false);
  const [includeArchived, setIncludeArchived] = useState(initial.include_archived ?? false);
  const rule: PortfolioRule = {
    template_ids: templateIds,
    team_ids: teamIds,
    project_ids: initial.project_ids ?? [],
    project_field_conditions: conditions,
    include_completed: includeCompleted,
    include_archived: includeArchived,
  };
  const fields = defs.data ?? [];
  const toggle = (setter: (f: (prev: string[]) => string[]) => void, id: string, on: boolean) =>
    setter((prev) => (on ? [...prev, id] : prev.filter((x) => x !== id)));

  return (
    <div className="space-y-4">
      <Segmented<'manual' | 'rule'>
        label="How projects are picked"
        value={p.kind as 'manual' | 'rule'}
        onChange={(kind) => convert.mutate({ kind })}
        options={[
          { value: 'manual', label: 'By hand' },
          { value: 'rule', label: 'By a rule' },
        ]}
      />
      <p className="text-sm text-muted">
        {p.kind === 'rule'
          ? 'Every project that matches the rule is in the portfolio, as soon as it matches. Each person sees only the projects they can see.'
          : 'You add and remove projects by hand. Switching to a rule keeps today’s projects in it.'}
      </p>
      {p.kind === 'rule' ? (
        <form
          aria-label="Rule"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            configure.mutate({ rule });
          }}
        >
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">Made from these templates</legend>
            {(templates.data ?? []).length === 0 ? (
              <p className="text-sm text-muted">No project templates yet.</p>
            ) : (
              (templates.data ?? []).map((t) => (
                <label key={t.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={templateIds.includes(t.id)}
                    onChange={(e) => toggle(setTemplateIds, t.id, e.target.checked)}
                  />
                  {t.name}
                </label>
              ))
            )}
          </fieldset>
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">In these teams</legend>
            {(teams.data ?? []).map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={teamIds.includes(t.id)}
                  onChange={(e) => toggle(setTeamIds, t.id, e.target.checked)}
                />
                {t.name}
              </label>
            ))}
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Where project fields</legend>
            {conditions.map((c, i) => (
              <ConditionRow
                key={i}
                c={c}
                fields={fields}
                onChange={(next) => setConditions((prev) => prev.map((x, j) => (j === i ? next : x)))}
                onRemove={() => setConditions((prev) => prev.filter((_, j) => j !== i))}
              />
            ))}
            {fields.length ? (
              <Button
                type="button"
                size="sm"
                variant="text"
                onClick={() =>
                  setConditions((prev) => [...prev, { field_id: fields[0]!.id, op: 'set', value: null }])
                }
              >
                <Icon icon={Plus} size={14} /> Add a condition
              </Button>
            ) : (
              <p className="text-sm text-muted">No project fields yet.</p>
            )}
          </fieldset>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeCompleted}
                onChange={(e) => setIncludeCompleted(e.target.checked)}
              />
              Include completed projects
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
              />
              Include archived projects
            </label>
          </div>
          <Button type="submit" variant="primary" size="sm" loading={configure.isPending}>
            Save rule
          </Button>
        </form>
      ) : null}
    </div>
  );
}

function ConditionRow({
  c,
  fields,
  onChange,
  onRemove,
}: {
  c: Condition;
  fields: Field[];
  onChange: (c: Condition) => void;
  onRemove: () => void;
}) {
  const field = fields.find((f) => f.id === c.field_id);
  const op = OPS.find((o) => o.op === c.op) ?? OPS[0]!;
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-hair-soft p-2">
      <select
        aria-label="Condition field"
        className={selectClass}
        value={c.field_id}
        onChange={(e) => onChange({ field_id: e.target.value, op: c.op, value: null })}
      >
        {fields.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Condition operator"
        className={selectClass}
        value={c.op}
        onChange={(e) => onChange({ ...c, op: e.target.value as Condition['op'], value: null })}
      >
        {OPS.map((o) => (
          <option key={o.op} value={o.op}>
            {o.label}
          </option>
        ))}
      </select>
      {op.needsValue && field ? (
        <FieldValueEditor
          field={
            c.op === 'any' && field.type === 'single_select' ? { ...field, type: 'multi_select' } : field
          }
          value={c.value ?? null}
          onChange={(value) => onChange({ ...c, value })}
        />
      ) : null}
      <IconButton
        icon={Trash2}
        label="Remove condition"
        size="icon-sm"
        className="ml-auto"
        onClick={onRemove}
      />
    </div>
  );
}

function StagesSection({ p }: { p: PortfolioDetail }) {
  const { configure } = usePortfolioSettings(p.id);
  const defs = useProjectFieldDefs();
  const fields = useMemo(() => defs.data ?? [], [defs.data]);
  const [stageId, setStageId] = useState<string>(p.stage_field_id ?? '');
  const [targets, setTargets] = useState<Record<string, number>>(
    (p.stage_targets ?? {}) as Record<string, number>,
  );
  const [gates, setGates] = useState<Record<string, Gate>>((p.stage_gates ?? {}) as Record<string, Gate>);
  const stage = fields.find((f) => f.id === stageId);
  const options = ((stage?.options as { id: string; label: string }[] | null) ?? []).filter(Boolean);
  const choices = fields.filter((f) => f.type === 'single_select');
  const gate = (id: string): Gate =>
    gates[id] ?? { required_fields: [], required_milestones: [], required_files: [] };
  const setGate = (id: string, g: Partial<Gate>) =>
    setGates((prev) => ({ ...prev, [id]: { ...gate(id), ...g } }));

  return (
    <form
      aria-label="Stages and gates"
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        const ids = new Set(options.map((o) => o.id));
        const cleanGates = Object.fromEntries(
          Object.entries(gates).filter(
            ([k, g]) =>
              ids.has(k) &&
              (g.required_fields.length || g.required_milestones.length || g.required_files.length),
          ),
        );
        configure.mutate({
          stage_field_id: stageId || null,
          stage_targets: Object.fromEntries(Object.entries(targets).filter(([k]) => ids.has(k))),
          stage_gates: cleanGates,
        });
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Stage field</span>
        <select className={selectClass} value={stageId} onChange={(e) => setStageId(e.target.value)}>
          <option value="">No stage field</option>
          {choices.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">
          A single-choice project field; its choices, in order, are the lifecycle.
        </span>
      </label>
      {options.length ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Targets and gates per stage</caption>
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 font-medium">Stage</th>
              <th className="py-1 font-medium">Target (days)</th>
              <th className="py-1 font-medium">Gate: fields, milestones, files</th>
            </tr>
          </thead>
          <tbody>
            {options.map((o) => (
              <tr key={o.id} className="border-t border-hair-soft align-top">
                <th scope="row" className="py-2 pr-2 text-left font-medium">
                  {o.label}
                </th>
                <td className="py-2 pr-2">
                  <Input
                    type="number"
                    min={0}
                    aria-label={`Target days for ${o.label}`}
                    className="h-8 w-20"
                    value={targets[o.id] ?? ''}
                    onChange={(e) => {
                      const n = e.target.value === '' ? null : Number(e.target.value);
                      setTargets((prev) => {
                        const next = { ...prev };
                        if (n === null || Number.isNaN(n)) delete next[o.id];
                        else next[o.id] = n;
                        return next;
                      });
                    }}
                  />
                </td>
                <td className="space-y-1.5 py-2">
                  <select
                    multiple
                    aria-label={`Fields ${o.label} needs`}
                    className="h-16 w-full rounded-md border border-hairline bg-surface-2 px-1 text-sm"
                    value={gate(o.id).required_fields}
                    onChange={(e) =>
                      setGate(o.id, { required_fields: [...e.target.selectedOptions].map((x) => x.value) })
                    }
                  >
                    {fields
                      .filter((f) => f.id !== stageId)
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                  </select>
                  <Input
                    aria-label={`Milestones ${o.label} needs`}
                    placeholder="Milestones (comma-separated titles)"
                    className="h-8"
                    defaultValue={gate(o.id).required_milestones.join(', ')}
                    onBlur={(e) => setGate(o.id, { required_milestones: list(e.target.value) })}
                  />
                  <Input
                    aria-label={`Files ${o.label} needs`}
                    placeholder="Files (patterns like *signed*)"
                    className="h-8"
                    defaultValue={gate(o.id).required_files.join(', ')}
                    onBlur={(e) => setGate(o.id, { required_files: list(e.target.value) })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <Button type="submit" variant="primary" size="sm" loading={configure.isPending}>
        Save stages
      </Button>
    </form>
  );
}

function MembersSection({ p, canManage }: { p: PortfolioDetail; canManage: boolean }) {
  const members = usePortfolioMembers(p.id);
  const m = useMemberMutations(p.id);
  const people = usePeople('').data ?? [];
  const [userId, setUserId] = useState('');
  const [role, setRole] = useState<'editor' | 'viewer'>('editor');
  const taken = new Set([p.owner_id, ...(members.data ?? []).map((x) => x.user_id)]);
  const owner = people.find((x) => x.id === p.owner_id);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        Editors change the settings, the columns and shared views. Everyone in the workspace can see the
        portfolio; guests only when they are members.
      </p>
      <ul className="space-y-1" aria-label="Members">
        <li className="flex items-center justify-between text-sm">
          <span>{owner?.name ?? 'Owner'}</span>
          <span className="text-xs text-muted">Owner</span>
        </li>
        {(members.data ?? []).map((x) => (
          <li key={x.user_id} className="flex items-center gap-2 text-sm">
            <span className="flex-1 truncate">{x.name}</span>
            {canManage ? (
              <>
                <select
                  aria-label={`Role of ${x.name}`}
                  className={selectClass}
                  value={x.role}
                  onChange={(e) =>
                    m.set.mutate({ userId: x.user_id, role: e.target.value as 'editor' | 'viewer' })
                  }
                >
                  <option value="editor">Editor</option>
                  <option value="viewer">Viewer</option>
                </select>
                <IconButton
                  icon={Trash2}
                  label={`Remove ${x.name}`}
                  size="icon-sm"
                  onClick={() => m.remove.mutate(x.user_id)}
                />
              </>
            ) : (
              <span className="text-xs text-muted">{x.role === 'editor' ? 'Editor' : 'Viewer'}</span>
            )}
          </li>
        ))}
      </ul>
      {canManage ? (
        <form
          aria-label="Add a member"
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (userId) m.set.mutate({ userId, role }, { onSuccess: () => setUserId('') });
          }}
        >
          <select
            aria-label="Person"
            className={selectClass}
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          >
            <option value="">Add someone…</option>
            {people
              .filter((x) => !taken.has(x.id))
              .map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
          </select>
          <select
            aria-label="Role"
            className={selectClass}
            value={role}
            onChange={(e) => setRole(e.target.value as 'editor' | 'viewer')}
          >
            <option value="editor">Editor</option>
            <option value="viewer">Viewer</option>
          </select>
          <Button type="submit" size="sm" disabled={!userId}>
            Add
          </Button>
        </form>
      ) : (
        <p className="text-xs text-muted">Only the owner or an admin can change members.</p>
      )}
    </div>
  );
}
