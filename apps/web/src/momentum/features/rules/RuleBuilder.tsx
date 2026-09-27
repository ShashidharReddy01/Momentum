import { Plus, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { IconButton } from '@/components/ui/IconButton';
import { Input } from '@/components/ui/Input';
import { useFieldLibrary, useProjectFields } from '@/features/fields';
import { usePeople } from '@/features/people';
import { useProjects } from '@/features/projects';
import { useSections } from '@/features/sections';
import { useTagLibrary } from '@/features/tags';
import {
  ACTIONS,
  actionComplete,
  AI_STEP_KINDS,
  CONDITION_FIELDS,
  defaultAction,
  defaultCondition,
  defaultTrigger,
  describeRule,
  OPS,
  TRIGGER_FIELDS,
  TRIGGERS,
  type RuleLookups,
} from './ruleMeta';
import type { RuleAction, RuleCondition, RuleOut, RuleSpec, RuleTrigger } from './queries';

const selectClass =
  'h-8 rounded-md border border-hairline bg-surface-2 px-2.5 text-sm focus:border-focus focus:outline-none';
const rowClass = 'flex flex-wrap items-center gap-1.5 rounded-md border border-hair-soft p-2';

function Select({
  value,
  onChange,
  options,
  placeholder,
  'aria-label': ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { id: string; label: string }[];
  placeholder?: string;
  'aria-label': string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={selectClass}
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Everything a rule's trigger/conditions/actions can reference, by project — loaded once and
 * threaded through the trigger/condition/action editors and the readable-sentence preview. */
function useRuleLookups(projectId: string) {
  const people = usePeople();
  const tags = useTagLibrary();
  const sections = useSections(projectId);
  const projects = useProjects();
  const projectFields = useProjectFields(projectId);
  const fieldLibrary = useFieldLibrary();

  const lookups: RuleLookups = useMemo(
    () => ({
      people: new Map((people.data ?? []).map((p) => [p.id, p.name])),
      tags: new Map((tags.data ?? []).map((t) => [t.id, t.name])),
      sections: new Map((sections.data ?? []).map((s) => [s.id, s.name])),
      projects: new Map((projects.data ?? []).map((p) => [p.id, p.name])),
      fields: new Map((fieldLibrary.data ?? []).map((f) => [f.id, f.name])),
    }),
    [people.data, tags.data, sections.data, projects.data, fieldLibrary.data],
  );

  return {
    lookups,
    peopleOptions: (people.data ?? []).map((p) => ({ id: p.id, label: p.name })),
    tagOptions: (tags.data ?? []).map((t) => ({ id: t.id, label: t.name })),
    sectionOptions: (sections.data ?? []).map((s) => ({ id: s.id, label: s.name })),
    otherProjectOptions: (projects.data ?? [])
      .filter((p) => p.id !== projectId)
      .map((p) => ({ id: p.id, label: p.name })),
    fieldOptions: [
      { id: 'priority', label: 'Priority' },
      ...(projectFields.data ?? []).map((pf) => ({ id: pf.field.id, label: pf.field.name })),
    ],
  };
}

function SectionPicker({
  projectId,
  value,
  onChange,
  placeholder,
}: {
  projectId: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const sections = useSections(projectId, !!projectId);
  return (
    <Select
      aria-label="Section"
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      options={(sections.data ?? []).map((s) => ({ id: s.id, label: s.name }))}
    />
  );
}

function TriggerEditor({
  projectId,
  trigger,
  onChange,
  lookups,
}: {
  projectId: string;
  trigger: RuleTrigger;
  onChange: (t: RuleTrigger) => void;
  lookups: ReturnType<typeof useRuleLookups>;
}) {
  const meta = TRIGGERS.find((t) => t.type === trigger.type) ?? TRIGGERS[0]!;
  return (
    <div className={rowClass}>
      <span className="text-sm text-muted">When</span>
      <Select
        aria-label="Trigger"
        value={trigger.type}
        onChange={(type) => onChange(defaultTrigger(type))}
        options={TRIGGERS.map((t) => ({ id: t.type, label: t.label }))}
      />
      {meta.params.includes('to_section') ? (
        <SectionPicker
          projectId={projectId}
          value={trigger.to_section ?? ''}
          onChange={(v) => onChange({ ...trigger, to_section: v || null })}
          placeholder="Any section"
        />
      ) : null}
      {meta.params.includes('field') ? (
        <>
          <Select
            aria-label="Field"
            value={trigger.field ?? ''}
            onChange={(v) => onChange({ ...trigger, field: v || null })}
            placeholder="Any field"
            options={[
              ...TRIGGER_FIELDS.map((f) => ({ id: f, label: f.replace('_', ' ') })),
              ...lookups.fieldOptions.filter((f) => f.id !== 'priority'),
            ]}
          />
          <Input
            aria-label="New value"
            value={trigger.to === undefined || trigger.to === null ? '' : String(trigger.to)}
            onChange={(e) => onChange({ ...trigger, to: e.target.value || undefined })}
            placeholder="To this value (optional)"
            className="h-8 w-40"
          />
        </>
      ) : null}
      {meta.params.includes('user_id') ? (
        <Select
          aria-label="Person"
          value={trigger.user_id ?? ''}
          onChange={(v) => onChange({ ...trigger, user_id: v || null })}
          placeholder="Anyone"
          options={lookups.peopleOptions}
        />
      ) : null}
    </div>
  );
}

function ConditionRow({
  condition,
  onChange,
  onRemove,
  lookups,
}: {
  condition: RuleCondition;
  onChange: (c: RuleCondition) => void;
  onRemove: () => void;
  lookups: ReturnType<typeof useRuleLookups>;
}) {
  const op = OPS.find((o) => o.op === condition.op) ?? OPS[0]!;
  const fieldOptions = [
    ...CONDITION_FIELDS.map((f) => ({ id: f, label: f.replace('_', ' ') })),
    ...lookups.fieldOptions.filter((f) => f.id !== 'priority'),
  ];
  return (
    <div className={rowClass}>
      <Select
        aria-label="Condition field"
        value={condition.field}
        onChange={(field) => onChange({ field, op: condition.op, value: '' })}
        options={fieldOptions}
      />
      <Select
        aria-label="Condition operator"
        value={condition.op}
        onChange={(op) =>
          onChange({
            ...condition,
            op,
            value: op === 'empty' || op === 'not_empty' ? undefined : condition.value,
          })
        }
        options={OPS.map((o) => ({ id: o.op, label: o.label }))}
      />
      {op.needsValue ? (
        condition.field === 'assignee' ? (
          <Select
            aria-label="Condition value"
            value={typeof condition.value === 'string' ? condition.value : ''}
            onChange={(v) => onChange({ ...condition, value: v })}
            placeholder="Choose…"
            options={lookups.peopleOptions}
          />
        ) : condition.field === 'tag' ? (
          <Select
            aria-label="Condition value"
            value={typeof condition.value === 'string' ? condition.value : ''}
            onChange={(v) => onChange({ ...condition, value: v })}
            placeholder="Choose…"
            options={lookups.tagOptions}
          />
        ) : (
          <Input
            aria-label="Condition value"
            value={
              Array.isArray(condition.value)
                ? condition.value.join(', ')
                : condition.value === undefined || condition.value === null
                  ? ''
                  : String(condition.value)
            }
            onChange={(e) =>
              onChange({
                ...condition,
                value:
                  condition.op === 'in' ? e.target.value.split(',').map((v) => v.trim()) : e.target.value,
              })
            }
            placeholder={condition.op === 'in' ? 'a, b, c' : 'Value'}
            className="h-8 w-32"
          />
        )
      ) : null}
      <IconButton icon={X} label="Remove condition" size="icon-sm" className="ml-auto" onClick={onRemove} />
    </div>
  );
}

function ActionRow({
  projectId,
  action,
  onChange,
  onRemove,
  lookups,
}: {
  projectId: string;
  action: RuleAction;
  onChange: (a: RuleAction) => void;
  onRemove: () => void;
  lookups: ReturnType<typeof useRuleLookups>;
}) {
  const meta = ACTIONS.find((a) => a.type === action.type) ?? ACTIONS[0]!;
  // `field_id` is shared with set_field; an AI step only shows it for the kind that needs one.
  const needsField = (a: RuleAction) =>
    a.type !== 'ai_step' || AI_STEP_KINDS.find((k) => k.kind === a.kind)?.needsField === true;
  return (
    <div className={rowClass}>
      <Select
        aria-label="Action"
        value={action.type}
        onChange={(type) => onChange(defaultAction(type))}
        options={ACTIONS.map((a) => ({ id: a.type, label: a.label }))}
      />
      {meta.params.includes('user_id') ? (
        <Select
          aria-label="Person"
          value={action.user_id ?? ''}
          onChange={(v) => onChange({ ...action, user_id: v || null })}
          placeholder={action.type === 'assign' ? 'Unassign' : 'Choose…'}
          options={lookups.peopleOptions}
        />
      ) : null}
      {meta.params.includes('text') ? (
        <Input
          aria-label="Text"
          value={action.text ?? ''}
          onChange={(e) => onChange({ ...action, text: e.target.value })}
          placeholder="Text"
          className="h-8 min-w-48 flex-1"
        />
      ) : null}
      {meta.params.includes('section_id') ? (
        <SectionPicker
          projectId={projectId}
          value={action.section_id ?? ''}
          onChange={(v) => onChange({ ...action, section_id: v || null })}
        />
      ) : null}
      {action.type === 'ai_step' ? (
        <Select
          aria-label="AI step"
          value={action.kind ?? ''}
          onChange={(kind) => onChange({ type: 'ai_step', kind })}
          options={AI_STEP_KINDS.map((k) => ({ id: k.kind, label: k.label }))}
        />
      ) : null}
      {meta.params.includes('field_id') && needsField(action) ? (
        <Select
          aria-label="Field"
          value={action.field_id ?? ''}
          onChange={(v) => onChange({ ...action, field_id: v || null })}
          options={lookups.fieldOptions}
        />
      ) : null}
      {meta.params.includes('value') ? (
        <Input
          aria-label="Value"
          value={action.value === undefined || action.value === null ? '' : String(action.value)}
          onChange={(e) => onChange({ ...action, value: e.target.value })}
          placeholder="Value"
          className="h-8 w-32"
        />
      ) : null}
      {meta.params.includes('project_id') ? (
        <Select
          aria-label="Project"
          value={action.project_id ?? ''}
          onChange={(v) => onChange({ ...action, project_id: v || null, section_id: null })}
          placeholder="Choose a project…"
          options={lookups.otherProjectOptions}
        />
      ) : null}
      {action.type === 'add_to_project' && action.project_id ? (
        <SectionPicker
          projectId={action.project_id}
          value={action.section_id ?? ''}
          onChange={(v) => onChange({ ...action, section_id: v || null })}
          placeholder="Default section"
        />
      ) : null}
      {meta.params.includes('tag_id') ? (
        <Select
          aria-label="Tag"
          value={action.tag_id ?? ''}
          onChange={(v) => onChange({ ...action, tag_id: v || null })}
          placeholder="Choose a tag…"
          options={lookups.tagOptions}
        />
      ) : null}
      {meta.params.includes('titles') ? (
        <Input
          aria-label="Subtask titles"
          value={(action.titles ?? []).join(', ')}
          onChange={(e) => onChange({ ...action, titles: e.target.value.split(',').map((t) => t.trim()) })}
          placeholder="Title one, title two"
          className="h-8 min-w-48 flex-1"
        />
      ) : null}
      {meta.params.includes('days') ? (
        <Input
          aria-label="Days from now"
          type="number"
          value={action.days ?? 0}
          onChange={(e) => onChange({ ...action, days: Number(e.target.value) })}
          className="h-8 w-20"
        />
      ) : null}
      <IconButton icon={X} label="Remove action" size="icon-sm" className="ml-auto" onClick={onRemove} />
    </div>
  );
}

/** A rule's trigger → conditions → actions, with a readable sentence preview. Used for a new
 * rule, for editing one (S4.1.3), and for a draft Mo compiled from a sentence (S4.1.4) — a draft
 * is an ordinary new rule here: editable, and saved through the same create call, keeping the
 * prompt it came from. */
export function RuleBuilder({
  projectId,
  initial,
  draft,
  onSave,
  onCancel,
  saving,
}: {
  projectId: string;
  initial?: RuleOut;
  draft?: RuleSpec;
  onSave: (spec: RuleSpec) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const prefill = initial ?? draft;
  const [name, setName] = useState(prefill?.name ?? '');
  const [trigger, setTrigger] = useState<RuleTrigger>(prefill?.trigger ?? defaultTrigger('task.added'));
  const [conditions, setConditions] = useState<RuleCondition[]>(prefill?.conditions ?? []);
  const [actions, setActions] = useState<RuleAction[]>(prefill?.actions ?? [defaultAction('mark_complete')]);
  const lookups = useRuleLookups(projectId);

  const sentence = describeRule(trigger, conditions, actions, lookups.lookups);
  const canSave = name.trim().length > 0 && actions.length > 0 && actions.every(actionComplete);

  return (
    <div className="flex flex-col gap-3 p-4">
      <Input
        aria-label="Rule name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Rule name"
        // eslint-disable-next-line jsx-a11y/no-autofocus -- user just asked to add/edit a rule
        autoFocus
      />
      <TriggerEditor projectId={projectId} trigger={trigger} onChange={setTrigger} lookups={lookups} />

      <div className="flex flex-col gap-1.5">
        <span className="section-label">Conditions (optional)</span>
        {conditions.map((c, i) => (
          <ConditionRow
            key={i}
            condition={c}
            lookups={lookups}
            onChange={(v) => setConditions((prev) => prev.map((p, j) => (j === i ? v : p)))}
            onRemove={() => setConditions((prev) => prev.filter((_, j) => j !== i))}
          />
        ))}
        <Button
          size="sm"
          variant="ghost"
          className="justify-start"
          onClick={() => setConditions((prev) => [...prev, defaultCondition()])}
        >
          <Icon icon={Plus} /> Add condition
        </Button>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="section-label">Then</span>
        {actions.map((a, i) => (
          <ActionRow
            key={i}
            projectId={projectId}
            action={a}
            lookups={lookups}
            onChange={(v) => setActions((prev) => prev.map((p, j) => (j === i ? v : p)))}
            onRemove={() => setActions((prev) => prev.filter((_, j) => j !== i))}
          />
        ))}
        <Button
          size="sm"
          variant="ghost"
          className="justify-start"
          onClick={() => setActions((prev) => [...prev, defaultAction('assign')])}
        >
          <Icon icon={Plus} /> Add action
        </Button>
      </div>

      <p className="rounded-md bg-surface-2 px-3 py-2 text-sm text-ink-2">{sentence}</p>

      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="sm"
          disabled={!canSave}
          loading={saving}
          onClick={() =>
            onSave({
              name: name.trim(),
              enabled: prefill?.enabled ?? true,
              trigger,
              conditions,
              actions,
              ...(draft?.created_from_prompt ? { created_from_prompt: draft.created_from_prompt } : {}),
            })
          }
        >
          {initial ? 'Save rule' : 'Create rule'}
        </Button>
      </div>
    </div>
  );
}
